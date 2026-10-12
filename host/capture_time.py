# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Actual sampling clocks and checked capture-relative ticks shared by folds."""

from dataclasses import dataclass
from fractions import Fraction

from analyze_profiler_buffer import timestamp_delta
from report_helpers import require_finalized, running_groups

MASK = 0xFFFFFFFF
HALF = 0x80000000


@dataclass(frozen=True)
class CaptureClock:
    timestamp_hz: int
    timer_hz: int
    timer_period: int

    @classmethod
    def from_header(cls, header):
        values = tuple(int(header[key]) for key in ("timestamp_hz", "timer_hz", "timer_period"))
        if any(value <= 0 or value > MASK for value in values) or values[2] < 2:
            raise ValueError("invalid actual sampling clock")
        return cls(*values)

    @property
    def rate(self):
        return Fraction(self.timer_hz, self.timer_period)

    def milliseconds(self, ticks):
        return float(Fraction(str(ticks)) * self.timer_period * 1000 / self.timer_hz)

    def window_ticks(self, milliseconds):
        # Preserve nearest-tick rounding, with exact ratio arithmetic and ties to even.
        return round(Fraction(str(milliseconds)) * self.rate / 1000)

    def metadata(self):
        return {
            "timestamp_hz": self.timestamp_hz,
            "timer_hz": self.timer_hz,
            "timer_period": self.timer_period,
            "actual_sample_hz": float(self.rate),
        }


def relative_tick(raw, origin):
    raw = int(raw)
    if not 0 <= raw <= MASK:
        raise ValueError("tick is outside uint32 range")
    delta = (raw - origin) & MASK
    if delta >= HALF:
        raise ValueError("backward or ambiguous capture tick")
    return delta


def normalize(header, records, origin=None, compressed=False):
    """Keep raw ticks, but perform every subsequent operation in one forward epoch.

    Missing CPU observations are allowed. An NPU idle record represents a span
    ending at its retained snapshot, so its weight must account for that span.
    Capture windows must fit in the same unambiguous half-range as the decoder.
    """
    clock = CaptureClock.from_header(header)
    origin = int(header["start_tick"]) if origin is None else origin
    start = relative_tick(header["start_tick"], origin)
    stop = relative_tick(header["stop_tick"], origin)
    if stop < start:
        raise ValueError("non-increasing capture window")
    result = []
    previous = start
    previous_raw = int(header["start_tick"])
    previous_timestamp = int(header["start_timestamp"])
    for row in records:
        raw = int(row["tick"])
        tick = relative_tick(raw, origin)
        if not previous < tick <= stop:
            raise ValueError("duplicate, backward or out-of-window sample tick")
        weight = int(row["sample_count"]) if compressed else 1
        if compressed and (
            weight < 1 or tick - weight < start or (result and tick - previous != weight)
        ):
            raise ValueError("compressed NPU records have missing or inconsistent sample ticks")
        timestamp_delta(
            int(row["timestamp"]),
            raw,
            int(header["start_timestamp"]),
            int(header["start_tick"]),
            clock.timestamp_hz,
            clock.timer_period,
            clock.timer_hz,
        )
        timestamp_delta(
            int(row["timestamp"]),
            raw,
            previous_timestamp,
            previous_raw,
            clock.timestamp_hz,
            clock.timer_period,
            clock.timer_hz,
        )
        result.append({**row, "tick_raw": raw, "tick": tick})
        previous, previous_raw, previous_timestamp = tick, raw, int(row["timestamp"])
    timestamp_delta(
        int(header["stop_timestamp"]),
        int(header["stop_tick"]),
        previous_timestamp,
        previous_raw,
        clock.timestamp_hz,
        clock.timer_period,
        clock.timer_hz,
    )
    timestamp_delta(
        int(header["stop_timestamp"]),
        int(header["stop_tick"]),
        int(header["start_timestamp"]),
        int(header["start_tick"]),
        clock.timestamp_hz,
        clock.timer_period,
        clock.timer_hz,
    )
    return {
        **header,
        "start_tick_raw": int(header["start_tick"]),
        "stop_tick_raw": int(header["stop_tick"]),
        "start_tick": start,
        "stop_tick": stop,
    }, result


def synchronize(cpu_header, cpu, npu_header, npu):
    require_finalized(cpu_header, "CPU")
    if (
        CaptureClock.from_header(cpu_header) != CaptureClock.from_header(npu_header)
        or cpu_header["sample_hz"] != npu_header["sample_hz"]
    ):
        raise ValueError("CPU/Ethos-U sample clocks differ")
    if cpu_header.get("firmware_id") != npu_header.get("firmware_id"):
        raise ValueError("CPU/Ethos-U firmware identity differs")
    raw_cpu = {int(row["tick"]): row for row in cpu}
    for row in npu:
        if int(row["tick"]) in raw_cpu and int(row["timestamp"]) != int(
            raw_cpu[int(row["tick"])]["timestamp"]
        ):
            raise ValueError("CPU/Ethos-U timestamp mismatch")
    origin = int(cpu_header["start_tick"])
    ch, cpu = normalize(cpu_header, cpu, origin)
    nh, npu = normalize(npu_header, npu, origin, compressed=True)
    # Headers may have different epochs. Their correspondence still needs the
    # same validation as record intervals, followed by exact shared snapshots.
    clock = CaptureClock.from_header(ch)
    timestamp_delta(
        int(npu_header["start_timestamp"]),
        int(npu_header["start_tick"]),
        int(cpu_header["start_timestamp"]),
        origin,
        clock.timestamp_hz,
        clock.timer_period,
        clock.timer_hz,
    )
    by_tick = {row["tick"]: row for row in cpu}
    shared = 0
    for row in npu:
        if row["tick"] in by_tick:
            if int(row["timestamp"]) != int(by_tick[row["tick"]]["timestamp"]):
                raise ValueError("CPU/Ethos-U timestamp mismatch")
            shared += 1
    if not shared:
        raise ValueError("no shared CPU/Ethos-U timestamps to verify synchronization")
    return ch, cpu, nh, npu


def select_periods(npu_header, records, cpu_header=None, pre_ticks=0):
    """One conservative period selection for CPU and NPU, with a shared baseline."""
    groups = running_groups(records)
    lower = npu_header["start_tick"] + 1
    upper = npu_header["stop_tick"] + 1
    if records:
        lower = max(lower, records[0]["tick"] - int(records[0]["sample_count"]) + 1)
        upper = min(upper, records[-1]["tick"] + 1)
    if cpu_header is not None:
        lower = max(lower, cpu_header["start_tick"] + 1)
        upper = min(upper, cpu_header["stop_tick"] + 1)
    selected = []
    for index in range(1, len(groups) - 1):
        first, last = groups[index][0], groups[index][-1]
        following = groups[index + 1][0]
        if first == 0 or last + 1 >= following:
            raise ValueError("missing idle record around inference")
        start, end = records[first]["tick"], records[following]["tick"]
        if end <= start:
            raise ValueError("non-increasing inference starts")
        if start - pre_ticks < lower or records[first - 1]["tick"] < lower or end > upper:
            continue
        selected.append(index)
    return groups, selected
