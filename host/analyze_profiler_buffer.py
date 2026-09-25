# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        analyze_profiler_buffer.py
# Description:  Decode SRAM captures and report sampled functions using ELF symbols
#
# $Date:        25 September 2026
# $Revision:    V.1.0.2
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
import shutil
import subprocess
import sys


MAGIC = 0x46504353
FORMAT_VERSION = 2
HEADER = struct.Struct("<44I")
REJECTION_NAMES = ("invalid_exc_return", "unsupported_frame", "stack_bounds", "invalid_xpsr")
RECORD = struct.Struct("<6I")
PMU_STATES = {0: "disabled", 1: "unavailable", 2: "active", 3: "busy", 4: "unsupported", 5: "access_denied"}
PMU_EVENTS = {0x0000: "sw-incr", 0x0003: "l1d-cache-refill", 0x0024: "stall-backend", 0x0008: "instructions-retired", 0x0011: "cpu-cycles"}
HEADER_NAMES = (
    "magic version record_base_bytes buffer_bytes bytes_used count rejected active timestamp_hz "
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


def demangle_functions(functions, tool=None):
    """Demangle unique C++ symbols in 1 subprocess, preserving addresses and sizes."""
    names = sorted({name for _, _, name in functions if name.startswith("_Z") and not any(c.isspace() for c in name)})
    if not names:
        return functions
    executable = tool or next((path for name in ("arm-none-eabi-c++filt", "llvm-cxxfilt", "c++filt")
                               if (path := shutil.which(name))), None)
    if not executable:
        print("WARNING: C++ names remain mangled; install c++filt or specify --cxxfilt PATH.", file=sys.stderr)
        return functions
    try:
        result = subprocess.run([executable], input="\n".join(names) + "\n", text=True,
                                capture_output=True, check=True, timeout=30)
        decoded = result.stdout.splitlines()
        if len(decoded) != len(names) or not all(decoded):
            raise ValueError("unexpected demangler output")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"WARNING: C++ demangling failed ({error}); retaining original names.", file=sys.stderr)
        return functions
    mapping = dict(zip(names, decoded))
    return [(address, size, mapping.get(name, name)) for address, size, name in functions]


def read_capture(data):
    if len(data) < 8:
        raise ValueError("Truncated capture signature")
    magic, version = struct.unpack_from("<II", data)
    if magic != MAGIC:
        raise ValueError("Not an SCPF capture")
    if version != FORMAT_VERSION:
        raise ValueError(f"Capture format {version} is unsupported; this decoder supports {FORMAT_VERSION}. "
                         "Use the decoder shipped with that firmware or rebuild and recapture.")
    if len(data) < HEADER.size:
        raise ValueError("Truncated capture header")
    fields = HEADER.unpack_from(data)
    header = dict(zip(HEADER_NAMES, fields[:20]))
    header.update(header_bytes=fields[42], features=fields[43])
    if fields[42] != HEADER.size or fields[43] != (int(fields[25] != 0) | (2 if fields[41] else 0)):
        raise ValueError("Header length or feature flags disagree with capture format")
    reasons = dict(zip(REJECTION_NAMES, fields[20:24]))
    if sum(reasons.values()) & 0xFFFFFFFF != header["rejected"]:
        raise ValueError("Rejection total and reason counters disagree")
    header["rejected_reasons"] = reasons
    state, count, requested = fields[24:27]
    events, bits, start, stop, flags = list(fields[27:31]), fields[31], list(fields[32:36]), list(fields[36:40]), fields[40]
    if state not in PMU_STATES or not 0 <= requested <= 4 or flags & ~31 or max(events) > 0xFFFF:
        raise ValueError("Invalid PMU metadata")
    if (state == 2 and (not requested or count != requested or bits != 32 or flags & ~((1 << count) - 1 | 16))) or (
            state != 2 and (count or bits or any(start) or any(stop) or flags)):
        raise ValueError("Inconsistent PMU availability metadata")
    if (state == 0) != (requested == 0) or any(events[requested:]) or any(start[count:]) or any(stop[count:]):
        raise ValueError("Invalid unused PMU metadata")
    if 0x001E in events[:requested]:
        raise ValueError("CHAIN is reserved for counter pairing")
    unwind_max_depth = fields[41]
    if unwind_max_depth > 255:
        raise ValueError("Invalid maximum unwind depth")
    header["unwind_max_depth"] = unwind_max_depth
    base = 24 + 4 * count + (4 if unwind_max_depth else 0)
    if header["record_base_bytes"] != base:
        raise ValueError("Record base size disagrees with PMU/backtrace metadata")
    header["pmu"] = dict(status=PMU_STATES[state], count=count, requested=requested, events=events[:requested],
                         counter_bits=bits, start=start[:requested], stop=stop[:requested], flags=flags,
                         scope="init_to_stop_all_execution")
    if header["active"] or header["complete"] != 1:
        raise ValueError("Capture not stopped/completed; dump after sampling_profiler_stop")
    used = header["bytes_used"]
    if (header["buffer_bytes"] % 4 or header["buffer_bytes"] < HEADER.size + base or used % 4 or
            used > header["buffer_bytes"] - HEADER.size or header["count"] > used // base):
        raise ValueError("Invalid buffer dimensions/count")
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
    samples = []
    cursor, end = HEADER.size, HEADER.size + used
    for _ in range(header["count"]):
        if end - cursor < base:
            raise ValueError("Truncated record base")
        depth = struct.unpack_from("<I", data, cursor + base - 4)[0] & 255 if unwind_max_depth else 0
        if depth > unwind_max_depth:
            raise ValueError("Record depth exceeds capture maximum")
        size = base + 4 * depth
        if size > end - cursor:
            raise ValueError("Truncated caller array")
        samples.append(struct.unpack_from("<" + "I" * (size // 4), data, cursor))
        cursor += size
    if cursor != end:
        raise ValueError("Record count disagrees with bytes_used")
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
            for event in range(len(pmu["events"])):
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


UNWIND_STATES = {0: "complete", 1: "no_table", 2: "unsupported", 3: "stack_bounds",
                 4: "invalid_pc", 5: "no_progress", 6: "depth_limit"}


def executable_ranges(data):
    """Read executable section ranges from the ELF already validated by elf_functions."""
    offset = struct.unpack_from("<I", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 46)
    ranges = []
    for index in range(count):
        section = struct.unpack("<10I", checked_slice(data, offset + index * size, 40))
        if section[2] & 6 == 6 and section[5]:
            ranges.append((section[3], section[5]))
    return ranges


def lr_only_entries(data, functions):
    """Find function entries covered by the exact inline EHABI finish recipe.

    This recipe reads live LR without touching SP or saved registers, so it is
    valid before the first instruction too. Other encodings stay conservative.
    """
    offset = struct.unpack_from("<I", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 46)
    safe = set()
    code = executable_ranges(data)
    def region(address):
        return next((i for i, (base, size) in enumerate(code) if base <= address < base + size), None)
    for index in range(count):
        section = struct.unpack("<10I", checked_slice(data, offset + index * size, 40))
        if section[1] != 0x70000001 or not section[2] & 2:  # SHT_ARM_EXIDX, allocated
            continue
        if section[5] % 8:
            return set()
        entries = []
        for n, (relative, recipe) in enumerate(struct.iter_unpack(
                "<II", checked_slice(data, section[4], section[5]))):
            if relative & 0x80000000:
                return set()
            delta = relative - (0x80000000 if relative & 0x40000000 else 0)
            address = (section[3] + 8 * n + delta) & 0xffffffff
            if address & 1 or (entries and address <= entries[-1][0]):
                return set()
            entries.append((address, recipe))
        starts = [address for address, _ in entries]
        for address, _, _ in functions:
            entry = bisect_right(starts, address) - 1
            if entry >= 0 and entries[entry][1] == 0x80B0B0B0 and region(entries[entry][0]) == region(address):
                safe.add(address)
    return safe


def analyze_backtraces(header, samples, functions, code_ranges, lr_entries=(), stack_root=None):
    """Validate optional caller chains; never discard the underlying PC sample."""
    addresses = [item[0] for item in functions]
    folded, statuses = Counter(), Counter()
    details = []
    names = Counter(name for _, _, name in functions)
    function_entries = set(addresses)

    def label(pc):
        index = bisect_right(addresses, pc) - 1
        while index >= 0:
            start, size, name = functions[index]
            if start <= pc < start + size:
                # Folded format uses semicolons and newlines as delimiters.
                name = name.replace(";", ":").replace("\n", " ").replace("\r", " ")
                return f"{name} [0x{start:08x}]" if names[functions[index][2]] > 1 else name
            index -= 1
        return f"[unknown@0x{pc:08x}]"

    def executable(pc):
        return any(base <= pc and pc - base < size for base, size in code_ranges)

    offset = 6 + header["pmu"]["count"]
    for sample in samples:
        metadata = sample[offset]
        depth, status = metadata & 255, metadata >> 8
        raw = sample[offset + 1:]
        valid = (depth <= header["unwind_max_depth"] and status in UNWIND_STATES and
                 (status != 6 or depth == header["unwind_max_depth"]) and len(raw) == depth)
        pc = sample[2] & ~1
        valid = valid and executable(pc)
        callers = []
        if valid:
            for address in raw[:depth]:
                call_site = (address & ~1) - 2
                if not address & 1 or call_site < 0 or not executable(call_site):
                    valid = False
                    break
                callers.append(label(call_site))
        state = UNWIND_STATES[status] if valid else "invalid_trace"
        # EHABI assumes the prologue has executed. At the exact entry PC,
        # applying its recipe can pop the caller's frame and skip a function.
        safe_entry = pc in lr_entries and depth > 0 and raw[0] == sample[3]
        at_entry = valid and pc in function_entries and not safe_entry
        if at_entry:
            state = "function_entry"
        chain = list(reversed(callers)) + [label(pc)] if valid and not at_entry else [label(pc)]
        disposition = "unreliable" if not valid or at_entry else "included"
        displayed = chain
        if disposition == "included" and stack_root is not None:
            if stack_root in chain:
                displayed = chain[chain.index(stack_root):]  # Outermost occurrence for recursion.
            else:
                disposition = "root_missing"
        if disposition == "included":
            folded[";".join(displayed)] += 1
        statuses[state] += 1
        details.append(dict(unwind_status=state, callers_raw=json.dumps([f"0x{x:08x}" for x in raw]),
                            callchain=json.dumps(chain), flamegraph_status=disposition))
    return folded, details, dict(statuses)


def flamegraph_summary(details, root=None):
    counts = Counter(item["flamegraph_status"] for item in details)
    included = counts["included"]
    partial = sum(item["flamegraph_status"] == "included" and item["unwind_status"] != "complete"
                  for item in details)
    text = f"{included} of {len(details)} samples shown"
    if counts["unreliable"]:
        text += f"; {counts['unreliable']} excluded because their call stacks could not be trusted"
    if counts["root_missing"]:
        text += f"; {counts['root_missing']} excluded because the selected root was not captured"
    if partial:
        text += ". Some stacks are partial (unwinding stopped early)."
    return dict(root=root, total_samples=len(details), included_samples=included,
                excluded_unreliable=counts["unreliable"], excluded_root_missing=counts["root_missing"],
                partial_samples=partial,
                root_reached_percent=(100 * included / len(details) if details and root else None),
                recovered_caller_depth_counts=dict(sorted(Counter(len(json.loads(item["callers_raw"])) for item in details).items())),
                subtitle=text)


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
    parser.add_argument("--cxxfilt", help="C++ demangler executable; auto-detected from PATH by default")
    parser.add_argument("--stack-root", help="Flamegraph base: exact displayed function name; omit chains without it")
    parser.add_argument("--no-demangle", action="store_true", help="Keep original ELF symbol names")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be nonnegative")
    try:
        capture = args.samples.read_bytes()
        elf = args.elf.read_bytes()
        header, samples = read_capture(capture)
        functions = elf_functions(elf)
        if not args.no_demangle:
            functions = demangle_functions(functions, args.cxxfilt)
        rows, timeline, unknown, timing = analyze(header, samples, functions)
        pmu_rows = pmu_statistics(header)
        folded, stack_statuses = Counter(), {}
        stack_summary = None
        if args.stack_root is not None and (not args.stack_root.strip() or not header["unwind_max_depth"]):
            raise ValueError("--stack-root requires a nonempty name and a capture with backtraces")
        if header["unwind_max_depth"]:
            folded, stack_details, stack_statuses = analyze_backtraces(
                header, samples, functions, executable_ranges(elf), lr_only_entries(elf, functions), args.stack_root)
            stack_summary = flamegraph_summary(stack_details, args.stack_root)
            for row, detail in zip(timeline, stack_details):
                row.update(detail)
        args.output.mkdir(parents=True, exist_ok=True)
        if header["unwind_max_depth"]:
            (args.output / "stacks.folded").write_text("".join(f"{stack} {count}\n" for stack, count in sorted(folded.items())))
            (args.output / "stacks.note.txt").write_text(stack_summary["subtitle"] + "\n")
        else:
            (args.output / "stacks.folded").unlink(missing_ok=True)
            (args.output / "stacks.note.txt").unlink(missing_ok=True)
        write_csv(args.output / "functions.csv", rows, ["address", "function", "hits", "percent"])
        write_csv(args.output / "samples.csv", timeline,
                  ["sample", "timestamp", "timestamp_ticks_since_start",
                   "time_us", "tick", "pc", "lr", "xpsr", "exception_return", "function"] +
                  [f"pmu{i}_{field}" for i in range(len(header["pmu"]["events"])) for field in ("raw", "interval_delta")] +
                  (["unwind_status", "callers_raw", "callchain", "flamegraph_status"] if header["unwind_max_depth"] else []))
        if pmu_rows:
            write_csv(args.output / "events.csv", pmu_rows, [])
        else:
            (args.output / "events.csv").unlink(missing_ok=True)
        summary = {"header": header, "unknown_samples": unknown, **timing,
                   "nominal_sample_hz": nominal_sample_hz(header),
                   "requested_sample_hz": header["sample_hz"],
                   "pmu_events": pmu_rows,
                   "unwind_status_counts": stack_statuses,
                   "flamegraph": stack_summary,
                   "storage": {"record_bytes": header["bytes_used"],
                               "average_record_bytes": header["bytes_used"] / len(samples) if samples else None,
                               "payload_occupancy_percent": 100 * header["bytes_used"] / (header["buffer_bytes"] - HEADER.size),
                               "maximum_record_bytes": header["record_base_bytes"] + 4 * header["unwind_max_depth"],
                               "buffer_exhausted": bool(header["full"]),
                               "capture_finalized": bool(header["complete"])},
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
    if header["unwind_max_depth"]:
        print("Backtraces (best effort): " + ", ".join(f"{key}={value}" for key, value in stack_statuses.items()))
        print("Flamegraph: " + stack_summary["subtitle"])
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
