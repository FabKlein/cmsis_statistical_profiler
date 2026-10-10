# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        combine_perfetto_captures.py
# Description:  Combine capture-local timelines without debugger pause time
#
# $Date:        9 October 2026
# $Revision:    V.1.0.4
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Combine Cortex-M captures, optionally with aligned Ethos-U snapshots, for Perfetto."""

# Architecture
# ============
# This tool consumes decoded reports; it does not concatenate raw MCU buffers.
# The aggregator establishes capture order and shared metadata. Each original
# report remains the source for its samples, elapsed times and PMU observations.
#
#   <run>/summary.json + captures.csv
#                      |
#                      v
#   for each capture's cortex_m_report/
#     summary.json + samples.csv
#                      |
#                      +-- read_report(): validate decoded sample timing
#                      +-- duration_us(): recover the full start-to-stop duration
#                      +-- event_rates(): calculate PMU rates within this capture
#                      +-- write_perfetto(): reuse the standard event encoding
#                      |
#                      v
#   shift local event timestamps by preceding capture durations
#     + mark each capture start/end
#     + keep shared track metadata once
#                      |
#                      v
#   cortex_m_combined.perfetto.json
#   or combined.perfetto.json with --include-ethosu
#
# Optional ethosu_report/{summary.json,samples.csv} supplies a separate NPU
# process: STATUS/QREAD instants and PMU interval rates. Shared sampling ticks
# and timestamps verify alignment; both processors use the Cortex-M epoch.
# Idle runs remain compressed observations, not inferred execution spans.
#
# Timeline convention (example):
#
#   Target:    [capture 0: 2 s] ... debugger pause ... [capture 1: 3 s]
#   Report:    0--------------2-----------------------5 seconds
#              capture 0      capture 1
#
# The joined axis is a synthetic sequence of capture windows, not wall-clock
# time or evidence of uninterrupted execution. Initialization-to-first-sample
# and last-sample-to-stop time remain inside each window. Capture duration
# includes idle/gated time between its recorded start and stop; "active capture"
# does not mean CPU busy time.
#
# Counter values and epochs may restart between captures. PMU deltas are computed
# separately before joining; never subtract the last counter of one capture from
# the first of the next. No event samples are invented to bridge that boundary.
#
# Current design favors reuse and auditability over streaming: temporary JSON
# adapts the existing writer, and all joined events remain in memory until the
# final consistency check passes. Very large runs therefore need memory
# proportional to their total event count.

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from analyze_profiler_buffer import timestamp_delta
from ethosu_perfetto import trace_events as ethosu_trace_events
from visualize_profiler_report import event_rates, read_report, write_perfetto
from report_helpers import capture_rows


def duration_us(header):
    """Recover start-to-stop microseconds using the decoder's clock model."""
    frequency = int(header["timestamp_hz"])
    if frequency <= 0:
        raise ValueError("timestamp_hz must be positive")
    # A 32-bit timestamp repeats after about 10.74 s at 400 MHz. Subtracting
    # stop-start modulo 2^32 alone would turn a 12 s window into about 1.26 s.
    # Sampling ticks and timer period estimate elapsed time and select the wrap
    # count. The shared helper also rejects inconsistent clock observations.
    ticks = timestamp_delta(
        int(header["stop_timestamp"]),
        int(header["stop_tick"]),
        int(header["start_timestamp"]),
        int(header["start_tick"]),
        frequency,
        int(header["timer_period"]),
        int(header["timer_hz"]),
    )
    return ticks * 1_000_000 / frequency


def boundary(index, position, timestamp, duration):
    """Create a global instant marker, not a measured execution-duration event."""
    # Chrome/Perfetto JSON uses microseconds for ts. ph=I is an instant event;
    # s=g makes the boundary visible independently of any sampled thread track.
    return {
        "ph": "I",
        "s": "g",
        "pid": 1,
        "ts": timestamp,
        "cat": "capture.boundary",
        "name": f"Capture {index:02d} {position}",
        "args": {"capture": index, "position": position, "duration_us": duration},
    }


def combine(root, destination, include_ethosu=False):
    """Join validated windows and return capture count, sample count and duration."""
    aggregate = json.loads((root / "summary.json").read_text())
    rows = capture_rows(root)
    if aggregate.get("captures") != len(rows):
        raise ValueError("aggregate capture count differs from captures.csv")
    if aggregate.get("all_validation_passed") is not True:
        raise ValueError("aggregate capture validation did not pass")
    # offset_us is the sum of preceding full window durations. Never derive it
    # from the last PC sample: doing so would erase each window's unsampled tail.
    events = []
    offset_us = 0.0
    sample_total = 0
    npu_records = npu_ticks = 0
    npu_configuration = None
    # Reuse write_perfetto() rather than duplicating its PC/PMU event schema.
    # The scratch file is overwritten per window and removed on failure too.
    with TemporaryDirectory() as temporary:
        scratch = Path(temporary) / "window.json"
        for index, row in enumerate(rows):
            report = root / row["capture_dir"] / "cortex_m_report"
            # Validate every source report as well as the aggregate. Files may
            # have been replaced since aggregation; ELF hashes bind symbolization
            # to the supplied executable, not to verified device firmware identity.
            summary, samples = read_report(report)
            header = summary["header"]
            if summary.get("elf_sha256") != aggregate.get("elf_sha256"):
                raise ValueError(f"capture {index}: ELF hash differs from aggregate")
            if int(header["sample_hz"]) != int(aggregate["sample_hz"]):
                raise ValueError(f"capture {index}: sample rate differs from aggregate")
            if any(
                header.get(field) != value
                for field, value in (("complete", 1), ("active", 0), ("validation_passed", 1))
            ):
                raise ValueError(f"capture {index}: buffer was not finalized and validated")
            if len(samples) != int(row["cpu_samples"]):
                raise ValueError(f"capture {index}: sample count differs from captures.csv")
            # read_report() requires nonempty, ordered samples with valid times.
            # The final sample must lie within the recovered start/stop window.
            duration = duration_us(header)
            if duration < samples[-1]["time_us"]:
                raise ValueError(f"capture {index}: last sample exceeds capture stop")
            # All PMU calculations stay capture-local. The standard writer omits
            # the first interval and preserves capture-specific warnings/metadata.
            rates, warnings = event_rates(summary, samples)
            write_perfetto(scratch, summary, samples, rates, warnings)
            window_events = json.loads(scratch.read_text())["traceEvents"]
            if include_ethosu:
                npu_events, npu_summary, configuration = ethosu_trace_events(
                    report.parent / "ethosu_report", header, samples
                )
                if npu_configuration is not None and configuration != npu_configuration:
                    raise ValueError("Ethos-U device or PMU configuration differs between captures")
                npu_configuration = configuration
                if npu_summary["total_samples"] != int(row["ethosu_ticks"]) or npu_summary[
                    "count"
                ] != int(row["ethosu_records"]):
                    raise ValueError(f"capture {index}: Ethos-U counts differ from captures.csv")
                window_events.extend(npu_events)
                npu_records += npu_summary["count"]
                npu_ticks += npu_summary["total_samples"]
            # ph=M records name shared process/thread tracks and have no sample
            # timestamp. Retain them once; other metadata is a timed event and
            # remains attached to its own capture.
            if index == 0:
                events.extend(event for event in window_events if event["ph"] == "M")
                events.append(
                    {
                        "ph": "I",
                        "s": "g",
                        "pid": 1,
                        "ts": 0,
                        "cat": "profiler.metadata",
                        "name": "Combined capture timeline",
                        "args": {
                            "captures": len(rows),
                            "time_basis": "concatenated active capture durations; debugger pauses omitted",
                            "pmu_boundary": "no PMU rate calculated between capture windows",
                            "processors": "Cortex-M and Ethos-U" if include_ethosu else "Cortex-M",
                        },
                    }
                )
            # At a join, the previous end and next start share a timestamp.
            # Explicit boundaries and capture IDs expose that discontinuity.
            events.append(boundary(index, "start", offset_us, duration))
            for event in window_events:
                if event["ph"] == "M":
                    continue
                # Shift only presentation time. Original sample indices, ticks,
                # symbol names and PMU rates retain their capture-local meanings.
                event["ts"] += offset_us
                # Counter args are numeric series: a capture ID there would
                # accidentally create an additional counter named "capture".
                if event["ph"] != "C":
                    event.setdefault("args", {})["capture"] = index
                events.append(event)
            offset_us += duration
            events.append(boundary(index, "end", offset_us, duration))
            sample_total += len(samples)
    # Keep the destination untouched on validation failure. This is a direct
    # final write, not an atomic replace; write/I/O failures can still interrupt it.
    if sample_total != aggregate.get("cpu_samples"):
        raise ValueError("combined sample count differs from aggregate summary")
    if include_ethosu and (
        npu_records != aggregate.get("ethosu_records") or npu_ticks != aggregate.get("ethosu_ticks")
    ):
        raise ValueError("combined Ethos-U counts differ from aggregate summary")
    destination.write_text(
        json.dumps({"traceEvents": events}, separators=(",", ":"), allow_nan=False) + "\n"
    )
    return len(rows), sample_total, offset_us


def main():
    """Resolve the run directory and expose the combiner as a small CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--include-ethosu",
        action="store_true",
        help="Include synchronized Ethos-U reports; requires both processors in every capture",
    )
    args = parser.parse_args()
    root = args.run_dir.resolve()
    destination = root / (
        "combined.perfetto.json" if args.include_ethosu else "cortex_m_combined.perfetto.json"
    )
    try:
        captures, samples, duration = combine(root, destination, args.include_ethosu)
        print(
            f"{destination}: {captures} captures, {samples} CPU samples, {duration / 1_000_000:.3f} s active time"
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"combined Perfetto trace failed: {error}\n")


if __name__ == "__main__":
    main()
