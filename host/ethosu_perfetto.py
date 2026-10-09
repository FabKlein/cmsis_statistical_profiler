# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        ethosu_perfetto.py
# Description:  Align decoded Ethos-U snapshots to a Cortex-M capture timeline
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Build Ethos-U Perfetto events using the CPU profiler's timestamp epoch.

CPU and NPU records originate in the same sampling interrupt. Header clocks
must match, and overlapping ticks must have identical raw timestamps. Shared
ticks verify alignment; the NPU start timestamp is not independently zeroed.

Compressed idle rows retain only their final snapshot. Export 1 instant with
its represented tick count, not an invented duration or repeated PMU values.
PMU rates describe the preceding retained-snapshot interval, including idle.
Keep those measurements in snapshot details. The counter tracks are an
idle-clamped display: Perfetto holds counter values forward, so explicitly
write zero at the first sampled idle tick rather than its compressed endpoint.
This does not claim that arbitrary PMU events stop counting while idle.
"""

import csv
import json

from analyze_profiler_buffer import timestamp_delta
from ethosu_pmu_events import DRIVER_VERSION, describe_events

MASK = 0xFFFFFFFF


def unsigned(value):
    """Require a decoded 32-bit integer before applying modular arithmetic."""
    number = int(value)
    if not 0 <= number <= MASK:
        raise ValueError("Ethos-U timestamp, tick or counter outside uint32 range")
    return number


def trace_events(directory, cpu_header, cpu_samples):
    """Return events, validated summary and counter configuration for 1 capture."""
    summary = json.loads((directory / "summary.json").read_text())
    with (directory / "samples.csv").open(newline="") as source:
        records = list(csv.DictReader(source))
    if any(
        summary.get(key) != expected
        for key, expected in (("complete", 1), ("active", 0), ("validation_passed", 1))
    ):
        raise ValueError("Ethos-U capture is not finalized and validated")
    if len(records) != summary["count"]:
        raise ValueError("Ethos-U record count differs from summary")
    if any(summary[key] != cpu_header[key] for key in ("sample_hz", "timestamp_hz")):
        raise ValueError("CPU/Ethos-U sample clocks differ")
    count = summary["pmu_count"]
    if (
        not 0 <= count <= 4
        or summary["pmu_status"] not in (0, 1, 2)
        or (summary["pmu_status"] == 1) != bool(count)
    ):
        raise ValueError("Invalid Ethos-U PMU configuration")
    event_ids = tuple(summary[f"pmu_event{i}"] for i in range(count))
    selected = describe_events(summary["device_type"], event_ids)
    configuration = (summary["device_type"], summary["pmu_status"], event_ids)

    def elapsed(timestamp, tick, start_timestamp=None, start_tick=None):
        return timestamp_delta(
            unsigned(timestamp),
            unsigned(tick),
            cpu_header["start_timestamp"] if start_timestamp is None else start_timestamp,
            cpu_header["start_tick"] if start_tick is None else start_tick,
            cpu_header["timestamp_hz"],
            cpu_header["timer_period"],
            cpu_header["timer_hz"],
        )

    cpu_stop = elapsed(cpu_header["stop_timestamp"], cpu_header["stop_tick"])
    npu_start = elapsed(summary["start_timestamp"], summary["start_tick"])
    npu_stop = elapsed(summary["stop_timestamp"], summary["stop_tick"])
    if not 0 <= npu_start <= npu_stop <= cpu_stop:
        raise ValueError("Ethos-U capture lies outside the Cortex-M capture window")
    stop_tick = (unsigned(summary["stop_tick"]) - cpu_header["start_tick"]) & MASK
    previous_tick = (unsigned(summary["start_tick"]) - cpu_header["start_tick"]) & MASK

    cpu_by_tick = {}
    for row in cpu_samples:
        tick = unsigned(row["tick"])
        if tick in cpu_by_tick:
            raise ValueError("Duplicate Cortex-M sample tick")
        cpu_by_tick[tick] = row
    streams = {int(stream["stream_id"]): stream for stream in summary["streams"]}
    if len(streams) != summary["stream_count"]:
        raise ValueError("Ethos-U stream table count differs")
    events = [
        {
            "ph": "M",
            "pid": 2,
            "name": "process_name",
            "args": {"name": "Ethos-U statistical capture"},
        },
        {
            "ph": "M",
            "pid": 2,
            "tid": 1,
            "name": "thread_name",
            "args": {"name": "NPU snapshots (compressed idle)"},
        },
    ]
    previous = None
    matched = running_ticks = idle_ticks = unknown = invalid_qread = 0

    def display_counters(time_us, rates):
        for slot, event in enumerate(selected):
            events.append(
                {
                    "ph": "C",
                    "pid": 2,
                    "ts": time_us,
                    "cat": "ethosu.pmu.idle_clamped_rate",
                    "name": f"PMU {slot}: {event['label']} (events/s, idle-clamped)",
                    "args": {"events_per_second": rates[slot]},
                }
            )

    # Do not carry a previous capture's last displayed rate into this window.
    display_counters(npu_start * 1e6 / cpu_header["timestamp_hz"], [0] * count)
    for index, row in enumerate(records):
        tick, timestamp = unsigned(row["tick"]), unsigned(row["timestamp"])
        relative_tick = (tick - cpu_header["start_tick"]) & MASK
        represented = int(row["sample_count"])
        running, idle = int(row["running"]), int(row["idle_count"])
        stream_id = int(row["stream_id"])
        if running not in (0, 1) or running != (unsigned(row["status"]) & 1):
            raise ValueError("Ethos-U running flag disagrees with STATUS")
        if (
            represented <= 0
            or represented != (1 if running else idle)
            or (running and idle)
            or (not running and stream_id)
        ):
            raise ValueError("Invalid Ethos-U compressed sample count/state")
        if relative_tick - previous_tick != represented or relative_tick > stop_tick:
            raise ValueError("Ethos-U represented ticks are not contiguous or exceed capture stop")
        ticks = elapsed(timestamp, tick)
        if ticks < npu_start or ticks > npu_stop or (previous and ticks <= previous[0]):
            raise ValueError("Ethos-U sample timing is outside its capture or non-increasing")
        cpu = cpu_by_tick.get(tick)
        if cpu is not None:
            if (
                unsigned(cpu["timestamp"]) != timestamp
                or abs(float(cpu["time_us"]) - ticks * 1e6 / cpu_header["timestamp_hz"]) > 0.01
            ):
                raise ValueError("CPU/Ethos-U timestamps differ at a shared tick")
            matched += 1
        qread = None if row["qread"] == "" else unsigned(row["qread"])
        if stream_id and stream_id not in streams:
            raise ValueError("Unknown Ethos-U stream descriptor")
        if qread is not None and (
            not running
            or qread % 4
            or (stream_id and qread > int(streams[stream_id]["stream_bytes"]))
        ):
            raise ValueError("Invalid Ethos-U QREAD position")
        running_ticks += running
        idle_ticks += idle
        unknown += int(running and not stream_id)
        invalid_qread += int(running and qread is None)
        time_us = ticks * 1e6 / cpu_header["timestamp_hz"]
        counters = [unsigned(row[f"pmu{i}"]) for i in range(count)]
        args = {
            "record": index,
            "tick": tick,
            "timestamp": timestamp,
            "running": running,
            "status": row["status"],
            "sample_count": represented,
            "idle_count": idle,
            "stream_id": stream_id,
            "qread_bytes": qread,
        }
        label = (
            f"Running: stream {stream_id or 'unknown'}, QREAD {hex(qread) if qread is not None else 'unavailable'}"
            if running
            else f"Idle: {idle} sampled ticks (last snapshot)"
        )
        events.append(
            {
                "ph": "I",
                "s": "t",
                "pid": 2,
                "tid": 1,
                "ts": time_us,
                "cat": "ethosu.sample",
                "name": label,
                "args": args,
            }
        )
        if previous:
            interval = elapsed(timestamp, tick, previous[1], previous[2])
            if interval != ticks - previous[0]:
                raise ValueError("Ethos-U interval timing disagrees with capture epoch")
            rates = [
                (
                    ((counters[slot] - previous[3][slot]) & MASK)
                    * cpu_header["timestamp_hz"]
                    / interval
                )
                for slot in range(count)
            ]
            # Preserve the measured interval even when its display is clamped.
            # Slot keys also distinguish repeated selections of the same event.
            args["pmu_interval_us"] = interval * 1e6 / cpu_header["timestamp_hz"]
            for slot, rate in enumerate(rates):
                args[f"pmu{slot}_measured_events_per_second"] = rate
            if running:
                display_counters(time_us, rates)

        if not running and count:
            first_tick = (tick - idle + 1) & MASK
            first_cpu = cpu_by_tick.get(first_tick)
            if idle == 1:
                first_ticks, source = ticks, "NPU snapshot"
            elif first_cpu is not None:
                first_ticks = elapsed(first_cpu["timestamp"], first_tick)
                source = "CPU timestamp at first idle tick"
                if (
                    abs(
                        float(first_cpu["time_us"]) - first_ticks * 1e6 / cpu_header["timestamp_hz"]
                    )
                    > 0.01
                ):
                    raise ValueError("CPU idle-start timestamp disagrees with capture epoch")
            else:
                # Compression discards this timestamp. A rejected/missing CPU
                # sample leaves only a nominal-period estimate, labelled below.
                first_ticks = ticks - (idle - 1) * (
                    cpu_header["timestamp_hz"] * cpu_header["timer_period"] / cpu_header["timer_hz"]
                )
                first_ticks = max(previous[0] if previous else npu_start, first_ticks)
                source = "estimated from timer period (CPU tick unavailable)"
            if not (previous[0] if previous else npu_start) <= first_ticks <= ticks:
                raise ValueError("Ethos-U idle-start timing is outside its retained interval")
            first_us = first_ticks * 1e6 / cpu_header["timestamp_hz"]
            args.update(idle_display_start_us=first_us, idle_display_start_source=source)
            display_counters(first_us, [0] * count)
            # Do not plot the idle interval's average at its final timestamp:
            # doing so would restore a nonzero step before the next active tick.
        previous = (ticks, timestamp, tick, counters)
        previous_tick = relative_tick

    # End the plotted window explicitly, including captures ending while busy.
    display_counters(npu_stop * 1e6 / cpu_header["timestamp_hz"], [0] * count)
    if records and not matched:
        raise ValueError("No shared CPU/Ethos-U sample ticks to verify clock alignment")
    for key, actual in (
        ("total_samples", running_ticks + idle_ticks),
        ("running_samples", running_ticks),
        ("idle_samples", idle_ticks),
        ("unknown_stream_samples", unknown),
        ("invalid_qread", invalid_qread),
    ):
        if summary[key] != actual:
            raise ValueError(f"Ethos-U {key} differs from decoded records")
    events.append(
        {
            "ph": "I",
            "s": "t",
            "pid": 2,
            "tid": 1,
            "ts": npu_start * 1e6 / cpu_header["timestamp_hz"],
            "cat": "profiler.metadata",
            "name": "Ethos-U capture information",
            "args": {
                "device_type": summary["device_type"],
                "records": len(records),
                "represented_ticks": running_ticks + idle_ticks,
                "full": summary["full"],
                "pmu_status": summary["pmu_status"],
                "pmu_events": json.dumps(selected),
                "pmu_catalog_driver_version": DRIVER_VERSION,
                "streams": json.dumps(summary["streams"]),
                "matched_cpu_ticks": matched,
                "limitations": "Instant snapshots, not inference/operator durations. PMU tracks are idle-clamped displays, not measured idle rates; capture boundaries also display zero. Snapshot details preserve measured preceding-interval rates. Idle starts use the first idle tick's CPU timestamp, or a labelled nominal-period estimate if unavailable; actual transitions occur between samples. Fewer than 2^32 PMU increments per interval required. No intervals cross captures.",
            },
        }
    )
    return events, summary, configuration
