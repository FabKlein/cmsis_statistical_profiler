# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        analyze_samples.py
# Description:  Decode SRAM captures and report sampled functions using ELF symbols
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""CMSIS statistical profiler: offline SRAM PC sampling report (21 September 2026)."""

import argparse
from bisect import bisect_right
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import struct


MAGIC = 0x46504353
FORMAT_VERSION = 1
HEADER = struct.Struct("<34I")
REJECTION_NAMES = ("invalid_exc_return", "unsupported_frame", "stack_bounds", "invalid_xpsr")
RECORD = struct.Struct("<6I")
PMU_STATES = {0: "disabled", 1: "unavailable", 2: "active", 3: "busy", 4: "unsupported", 5: "access_denied"}
PMU_EVENTS = {0x0000: "sw-incr", 0x0003: "l1d-cache-refill", 0x0024: "stall-backend"}
HEADER_NAMES = (
    "magic version record_size buffer_bytes capacity count rejected active timestamp_hz "
    "timer_period start_timestamp start_tick stop_timestamp stop_tick full complete "
    "iterations validation_passed sample_hz timer_hz"
).split()
MODULUS = 1 << 32


def checked_slice(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError("Truncated ELF table/string data")
    return data[offset:offset + size]


def elf_functions(data):
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Expected an unstripped little-endian ELF32 AXF")
    if struct.unpack_from("<HH", data, 16) != (2, 40):
        raise ValueError("Expected an Arm executable ELF")
    section_offset = struct.unpack_from("<I", data, 32)[0]
    section_size, section_count = struct.unpack_from("<HH", data, 46)
    if section_size != 40 or not section_count:
        raise ValueError("Missing or unsupported ELF section table")
    sections = [struct.unpack("<10I", checked_slice(data, section_offset + index * 40, 40))
                for index in range(section_count)]
    functions = []
    for section in sections:
        if section[1] != 2:
            continue
        if section[9] != 16 or section[5] % 16 or section[6] >= section_count:
            raise ValueError("Invalid ELF symbol table")
        strings_section = sections[section[6]]
        strings = checked_slice(data, strings_section[4], strings_section[5])
        symbols = checked_slice(data, section[4], section[5])
        for name_offset, address, size, info, unused, section_index in struct.iter_unpack("<IIIBBH", symbols):
            if info & 15 != 2 or size == 0 or not 0 < section_index < section_count:
                continue
            if not sections[section_index][2] & 4:
                continue
            end = strings.find(b"\0", name_offset)
            if end < 0 or name_offset >= len(strings):
                raise ValueError("Invalid ELF symbol name")
            name = strings[name_offset:end].decode("utf-8", errors="replace")
            functions.append((address & ~1, size, name))
    if not functions:
        raise ValueError("No sized function symbols; supply the original unstripped AXF")
    return sorted(set(functions))


def read_capture(data):
    if len(data) < HEADER.size:
        raise ValueError("Truncated capture header")
    fields = HEADER.unpack_from(data)
    header = dict(zip(HEADER_NAMES, fields[:20]))
    if header["magic"] != MAGIC or header["version"] != FORMAT_VERSION:
        raise ValueError("Unsupported capture format; rebuild firmware and use its matching decoder")
    reasons = dict(zip(REJECTION_NAMES, fields[20:24]))
    if sum(reasons.values()) & 0xFFFFFFFF != header["rejected"]:
        raise ValueError("Rejection total and reason counters disagree")
    header["rejected_reasons"] = reasons
    state, count, event0, event1, bits, start0, start1, stop0, stop1, flags = fields[24:]
    if state not in PMU_STATES or flags & ~7 or max(event0, event1) > 0xFFFF:
        raise ValueError("Invalid PMU metadata")
    if (state == 2 and (count != 2 or bits != 32)) or (state != 2 and (count or bits or start0 or start1 or stop0 or stop1 or flags)):
        raise ValueError("Inconsistent PMU availability metadata")
    if state == 0 and (event0 or event1):
        raise ValueError("Disabled PMU must have zero event metadata")
    record = struct.Struct("<" + "I" * (6 + count))
    if header["record_size"] != record.size:
        raise ValueError("Record size disagrees with PMU count")
    header["pmu"] = dict(status=PMU_STATES[state], count=count, events=[event0, event1],
                         counter_bits=bits, start=[start0, start1], stop=[stop0, stop1], flags=flags,
                         scope="init_to_stop_all_execution")
    if header["active"] or header["complete"] != 1:
        raise ValueError("Capture not stopped/completed; dump after sampling_profiler_stop")
    if not 0 <= header["count"] <= header["capacity"] or not header["capacity"]:
        raise ValueError("Invalid record count or capacity")
    if (header["buffer_bytes"] % 4 or
            header["capacity"] != (header["buffer_bytes"] - HEADER.size) // record.size):
        raise ValueError("Invalid buffer dimensions")
    if len(data) != header["buffer_bytes"]:
        raise ValueError("Dump size differs from header; dump the entire statistical_samples object")
    if not header["timestamp_hz"]:
        raise ValueError("Invalid timestamp frequency")
    rate, period, hz = header["sample_hz"], header["timer_period"], header["timer_hz"]
    if not 0 < rate <= hz or period < 2:
        raise ValueError("Invalid sampling frequency or timer period")
    if period != (hz + rate // 2) // rate:
        raise ValueError("Sampling frequency and timer period disagree")
    if period * header["timestamp_hz"] // hz >= 0x40000000:
        raise ValueError("Timer period too long for unambiguous timestamps")
    samples = list(record.iter_unpack(data[HEADER.size:HEADER.size + header["count"] * record.size]))
    for sample in samples:
        timestamp, tick, pc, lr, xpsr, exception_return = sample[:6]
        if not xpsr & (1 << 24) or xpsr & 0x1FF or (
                exception_return & 0xFFFFFF80 != 0xFFFFFF80 or exception_return & 0x6B not in (0x69, 0x28)):
            raise ValueError("Unexpected exception frame in capture")
    return header, samples


def timestamp_delta(timestamp, tick, previous_timestamp, previous_tick, timestamp_hz, timer_period, timer_hz):
    tick_delta = (tick - previous_tick) & 0xFFFFFFFF
    if tick_delta >= 0x80000000:
        raise ValueError("Non-monotonic sampling timestamps")
    # Integer rational arithmetic retains precision across independent clocks and wraps.
    numerator = timer_period * timestamp_hz
    expected = tick_delta * numerator // timer_hz
    tolerance = (2 * numerator + timer_hz - 1) // timer_hz
    delta = (timestamp - previous_timestamp) & 0xFFFFFFFF
    delta += max(0, (expected - delta + MODULUS // 2) // MODULUS) * MODULUS
    if abs(delta - expected) > tolerance:
        raise ValueError("Timestamp/sampling timers disagree; capture may have been paused or clocks changed")
    return delta


def analyze_timing(header, samples):
    """Check intervals and cumulative drift, including the final stopped epoch."""
    previous_timestamp, previous_tick = header["start_timestamp"], header["start_tick"]
    elapsed = ticks = 0
    times = []
    numerator = header["timer_period"] * header["timestamp_hz"]
    tolerance = (2 * numerator + header["timer_hz"] - 1) // header["timer_hz"]
    # Checking every prefix prevents an early drift from being hidden by later recovery.
    epochs = [(sample[0], sample[1]) for sample in samples]
    epochs.append((header["stop_timestamp"], header["stop_tick"]))
    for index, (timestamp, tick) in enumerate(epochs):
        location = f"sample {index}" if index < len(samples) else "capture stop"
        try:
            elapsed += timestamp_delta(timestamp, tick, previous_timestamp, previous_tick,
                                       header["timestamp_hz"], header["timer_period"], header["timer_hz"])
            ticks += (tick - previous_tick) & 0xFFFFFFFF
            expected = ticks * numerator // header["timer_hz"]
            if abs(elapsed - expected) > tolerance:
                raise ValueError(f"Cumulative clock disagreement: timestamp={elapsed} ticks, "
                                 f"expected={expected}, tolerance={tolerance}")
        except ValueError as error:
            return [None] * len(samples), {"timing_valid": False, "timing_diagnostic": f"{location}: {error}"}
        times.append(elapsed)
        previous_timestamp, previous_tick = timestamp, tick
    return times[:-1], {"timing_valid": True, "timing_diagnostic": None}


def nominal_sample_hz(header):
    return header["timer_hz"] / header["timer_period"]


def analyze(header, samples, functions):
    addresses = [entry[0] for entry in functions]
    hits = Counter()
    timeline = []
    elapsed_times, timing = analyze_timing(header, samples)
    unknown = 0
    pmu = header["pmu"]
    pmu_previous = pmu["start"][:]
    pmu_valid = pmu["status"] == "active" and not pmu["flags"]
    for index, sample in enumerate(samples):
        timestamp, tick, pc, lr, xpsr, exception_return = sample[:6]
        elapsed = elapsed_times[index]
        address = pc & ~1
        symbol_index = bisect_right(addresses, address) - 1
        match = None
        while symbol_index >= 0:
            start, size, name = functions[symbol_index]
            if start <= address < start + size:
                match = start, name
                break
            symbol_index -= 1
        if match is None:
            match = 0, "<unknown>"
            unknown += 1
        hits[match] += 1
        timeline.append({"sample": index, "timestamp": timestamp, "timestamp_ticks_since_start": elapsed,
                         "time_us": elapsed * 1e6 / header["timestamp_hz"] if elapsed is not None else None, "tick": tick,
                         "pc": f"0x{pc:08x}", "lr": f"0x{lr:08x}", "xpsr": f"0x{xpsr:08x}",
                         "exception_return": f"0x{exception_return:08x}", "function": match[1]})
        if pmu["status"] != "disabled":
            for event in range(2):
                raw = sample[6 + event] if pmu["count"] else 0
                timeline[-1][f"pmu{event}_raw"] = raw if pmu["status"] == "active" else None
                timeline[-1][f"pmu{event}_interval_delta"] = ((raw - pmu_previous[event]) & 0xFFFFFFFF) if pmu_valid else None
                pmu_previous[event] = raw
    rows = [{"address": f"0x{address:08x}", "function": name, "hits": count,
             "percent": 100 * count / len(samples)}
            for (address, name), count in hits.most_common()]
    return rows, timeline, unknown, timing


def pmu_statistics(header):
    pmu = header["pmu"]
    if pmu["status"] == "disabled":
        return []
    rows = []
    for index, event in enumerate(pmu["events"]):
        valid = pmu["status"] == "active" and pmu["flags"] == 0
        status = pmu["status"] if pmu["status"] != "active" else ("invalid_overflow_or_read" if pmu["flags"] else "ok")
        rows.append(dict(event=PMU_EVENTS.get(event, f"event-0x{event:04x}"), event_id=f"0x{event:04x}",
                         count=((pmu["stop"][index] - pmu["start"][index]) & 0xFFFFFFFF) if valid else None,
                         status=status, scope=pmu["scope"]))
    return rows


def write_csv(path, rows, empty_fields):
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else empty_fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True, help="Exact unstripped AXF used for this capture")
    parser.add_argument("--output", type=Path, default=Path("sampling-report"))
    parser.add_argument("--top", type=int, default=0, help="Console function limit; 0 prints every sampled function (default)")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be nonnegative")
    try:
        capture = args.samples.read_bytes()
        elf = args.elf.read_bytes()
        header, samples = read_capture(capture)
        rows, timeline, unknown, timing = analyze(header, samples, elf_functions(elf))
        pmu_rows = pmu_statistics(header)
        args.output.mkdir(parents=True, exist_ok=True)
        write_csv(args.output / "functions.csv", rows, ["address", "function", "hits", "percent"])
        write_csv(args.output / "samples.csv", timeline,
                  ["sample", "timestamp", "timestamp_ticks_since_start",
                   "time_us", "tick", "pc", "lr", "xpsr", "exception_return", "function"] +
                  (["pmu0_raw", "pmu0_interval_delta", "pmu1_raw", "pmu1_interval_delta"] if header["pmu"]["status"] != "disabled" else []))
        if pmu_rows:
            write_csv(args.output / "events.csv", pmu_rows, [])
        else:
            (args.output / "events.csv").unlink(missing_ok=True)
        summary = {"header": header, "unknown_samples": unknown, **timing,
                   "nominal_sample_hz": nominal_sample_hz(header),
                   "requested_sample_hz": header["sample_hz"],
                   "pmu_events": pmu_rows,
                   "tick_units": "sampling_interrupts",
                   "elf_sha256": hashlib.sha256(elf).hexdigest(),
                   "capture_sha256": hashlib.sha256(capture).hexdigest(),
                   "notes": "Exclusive PC-hit percentages, not call counts or exact cycle shares. "
                            "Fixed-period sampling can alias. LR is not a reconstructed call stack. "
                            "Caller must supply the matching AXF; its identity is not embedded in the capture."}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"{len(samples)} samples, {header['rejected']} rejected, {unknown} unresolved")
    print("Rejection reasons: " + ", ".join(f"{name}={count}" for name, count in header["rejected_reasons"].items()))
    print(f"Sampling rate: {nominal_sample_hz(header):.12g} Hz (requested {header['sample_hz']} Hz)")
    if not timing["timing_valid"]:
        print("WARNING: timing invalid; derived time fields omitted. " + timing["timing_diagnostic"])
    if pmu_rows:
        print("PMU event counts (init to stop; all execution, including ISR/gated-off time):")
        for event in pmu_rows:
            value = f"{event['count']:,}" if event["count"] is not None else f"<{event['status']}>"
            print(f"  {value:>20}  {event['event']}")
        print("PMU intervals are not attributed to the sampled function.")
    print("  Overhead  Samples  Symbol (PC hits)")
    for row in rows[:args.top] if args.top else rows:
        print(f"{row['percent']:9.2f}% {row['hits']:8d}  {row['function']}")
    if header["rejected"] or unknown or not header["validation_passed"]:
        print("WARNING: inspect rejected/unresolved samples and workload validation before interpreting results")
    print(f"Reports: {args.output}")


if __name__ == "__main__":
    main()
