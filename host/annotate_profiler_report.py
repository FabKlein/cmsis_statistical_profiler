# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        annotate_profiler_report.py
# Description:  Annotate instruction groups with sampled PC hit percentages
#
# $Date:        5 October 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Show disassembly of sampled functions with hit counts per instruction group.

Read an existing decoded report and its exact ELF. Grouping improves readability
of sparse samples; it does not measure individual instruction costs or remove
periodic-sampling bias. No PMU counts are attributed to instructions.
"""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from analyze_profiler_buffer import elf_functions


def find_objdump(explicit=None):
    """Prefer an explicit executable, otherwise probe supported tools on PATH."""
    candidates = [explicit] if explicit else ["arm-none-eabi-objdump", "llvm-objdump"]
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise ValueError(
        "objdump not found; install arm-none-eabi-objdump or llvm-objdump, "
        "or supply --objdump /path/to/objdump"
    )


def find_addr2line(explicit=None):
    """Find a source-line resolver only when snippets are requested."""
    candidates = [explicit] if explicit else ["arm-none-eabi-addr2line", "llvm-addr2line"]
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise ValueError("addr2line not found; install GNU Arm/LLVM tools or supply --addr2line PATH")


def source_locations(tool, elf, instructions):
    """Resolve a function's instructions in 1 process, rather than per group or PC."""
    result = subprocess.run(
        [tool, "-e", str(elf.resolve())],
        input="".join(f"0x{address:x}\n" for address, _ in instructions),
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode:
        raise ValueError(f"addr2line failed: {result.stderr.strip()}")
    rows = result.stdout.splitlines()
    if len(rows) != len(instructions):
        raise ValueError("Unexpected addr2line output; expected 1 location per instruction")
    locations = {}
    for (address, _), row in zip(instructions, rows):
        # GNU can append a discriminator, LLVM may include a column. Neither
        # changes which source line is shown. Unknown mappings stay absent.
        match = re.match(r"^(.*?):(\d+)(?::\d+)?(?: \(discriminator \d+\))?$", row)
        if match and match[1] != "??" and int(match[2]) > 0:
            locations[address] = (match[1], int(match[2]))
    return locations


def source_snippet(group, locations, cache, source_maps):
    """Show distinct mapped lines, without implying a contiguous source range."""
    mapped = list(dict.fromkeys(locations[pc] for pc, _ in group if pc in locations))
    if not mapped:
        return ["; Source: no line information for this group (debug information may be absent)."]
    lines = []
    for filename, number in mapped:
        # Prefix replacement supports sources moved since compilation. Never
        # guess by basename: unrelated source files can share the same name.
        local = filename
        for old, new in source_maps:
            if filename == old or filename.startswith(old.rstrip("/") + "/"):
                local = new.rstrip("/") + filename[len(old.rstrip("/")) :]
                break
        if local not in cache:
            try:
                cache[local] = (
                    Path(local).read_text(encoding="utf-8", errors="replace").splitlines()
                )
            except OSError:
                cache[local] = None
        contents = cache[local]
        if contents is None:
            text = "[source file unavailable]"
        elif number > len(contents):
            text = "[line unavailable; check source version]"
        else:
            text = contents[number - 1].strip()
        lines.append(f"; {filename}:{number}: {text}")
    return lines


def read_report(directory, elf):
    """Verify report identity and assign PCs to the same symbol ranges as the decoder."""
    data = elf.read_bytes()
    summary = json.loads((directory / "summary.json").read_text())
    if summary.get("elf_sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError("ELF hash differs from summary.json; supply the exact decoded executable")
    functions = elf_functions(data)
    starts = [start for start, _, _ in functions]

    # Use the decoder's displayed names, including its C++ demangling choices.
    # Addresses remain the identity so repeated names do not merge functions.
    with (directory / "functions.csv").open(newline="") as source:
        names = {int(row["address"], 16): row["function"] for row in csv.DictReader(source)}
    hits = defaultdict(Counter)
    total = unknown = 0
    with (directory / "samples.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            if int(row["sample"]) != total:
                raise ValueError("Missing or out-of-order sample in samples.csv")
            pc = int(row["pc"], 16)
            if not 0 <= pc <= 0xFFFFFFFF:
                raise ValueError("Sample PC is outside the 32-bit address space")
            pc &= ~1
            total += 1
            index = bisect_right(starts, pc) - 1
            while index >= 0:
                start, size, _ = functions[index]
                if start <= pc < start + size:
                    hits[index][pc] += 1
                    break
                index -= 1
            else:
                unknown += 1
    if total != summary["header"]["count"]:
        raise ValueError("Sample count differs from summary.json")
    return functions, names, hits, total, unknown


def parse_disassembly(text, start, size):
    """Read GNU/LLVM instruction lines, ignoring labels and embedded-data directives."""
    instructions = []
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+(.+?)\s*$", line)
        if not match:
            continue
        address, assembly = int(match[1], 16), match[2]
        if not start <= address < start + size:
            continue
        # Data directives and undecoded words are not instructions. Hits there
        # remain explicitly unassigned instead of leaking into a nearby group.
        if assembly.startswith((".", "<", "(bad)")):
            continue
        if instructions and address <= instructions[-1][0]:
            raise ValueError("Overlapping or unordered disassembly addresses")
        instructions.append((address, " ".join(assembly.split())))
    if not instructions:
        raise ValueError(f"No decoded instructions at 0x{start:08x}; check objdump target support")
    return instructions


def disassemble(tool, elf, start, size):
    """Disassemble 1 selected function; never spawn a process per sample or instruction."""
    result = subprocess.run(
        [
            tool,
            "-d",
            "--no-show-raw-insn",
            f"--start-address={start}",
            f"--stop-address={start + size}",
            str(elf.resolve()),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode:
        raise ValueError(f"objdump failed: {result.stderr.strip() or result.stdout.strip()}")
    return parse_disassembly(result.stdout, start, size)


def render_function(
    name,
    start,
    instructions,
    hits,
    total,
    group_size,
    show_zero_hit_groups=False,
    locations=None,
    source_cache=None,
    source_maps=(),
):
    """Put counts on group headings so no single instruction inherits the group's hits."""
    if source_cache is None:
        source_cache = {}
    count = sum(hits.values())
    share = 100 * count / total if total else 0
    lines = [f"{name} @ 0x{start:08x}: {count} samples, {share:.2f}% of capture"]
    instruction_addresses = {address for address, _ in instructions}
    unassigned = sum(value for pc, value in hits.items() if pc not in instruction_addresses)
    if unassigned:
        lines.append(
            f"WARNING: {unassigned} hits do not match decoded instruction starts; not grouped."
        )

    # Count instructions, not bytes: Thumb code mixes 16-bit and 32-bit encodings.
    # Exact address matching avoids silently rounding corrupt PCs into a group.
    # Filter after grouping: hiding cold groups must not shift hot group boundaries.
    omitted = 0
    for offset in range(0, len(instructions), group_size):
        group = instructions[offset : offset + group_size]
        group_hits = sum(hits.get(address, 0) for address, _ in group)
        if not group_hits and not show_zero_hit_groups:
            omitted += 1
            continue
        if omitted:
            lines.append(f"... {omitted} zero-hit group(s) omitted ...")
            omitted = 0
        percent = 100 * group_hits / count if count else 0
        lines.append(
            f"------- {group_hits} hits | {percent:.2f}% of function | "
            f"{len(group)} instructions -------"
        )
        if locations is not None:
            lines.extend(source_snippet(group, locations, source_cache, source_maps))
        lines.extend(f"{address:08x}    {assembly}" for address, assembly in group)
    if omitted:
        lines.append(f"... {omitted} zero-hit group(s) omitted ...")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--elf", type=Path, required=True, help="Exact ELF used to decode the report"
    )
    parser.add_argument("--objdump", help="Executable path/name; default: probe GNU Arm then LLVM")
    parser.add_argument(
        "--group-instructions",
        type=int,
        default=8,
        help="Instructions per group (default: 8; 1 for per-instruction hits)",
    )
    parser.add_argument(
        "--show-zero-hit-groups",
        action="store_true",
        help="Include groups with no sampled PC hits (hidden by default)",
    )
    parser.add_argument(
        "--source", action="store_true", help="Show available source lines for each displayed group"
    )
    parser.add_argument(
        "--addr2line", help="Source resolver path/name; default: probe GNU Arm then LLVM"
    )
    parser.add_argument(
        "--source-map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="Replace a debug source-path prefix with a local prefix; repeatable",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--top",
        type=int,
        default=5,
        help="Hottest functions (default: 5; 0 for all sampled functions)",
    )
    selection.add_argument(
        "--function", help="Exact displayed/ELF function name or hexadecimal start address"
    )
    parser.add_argument(
        "--output", type=Path, help="Write plain text to this file instead of stdout"
    )
    args = parser.parse_args()
    if args.group_instructions < 1 or args.top < 0:
        parser.error("--group-instructions must be positive and --top must be nonnegative")
    source_maps = []
    for mapping in args.source_map:
        old, separator, new = mapping.partition("=")
        if not separator or not old or not new:
            parser.error("--source-map requires nonempty OLD=NEW prefixes")
        source_maps.append((old, new))
    if (args.addr2line or source_maps) and not args.source:
        parser.error("--addr2line and --source-map require --source")
    try:
        tool = find_objdump(args.objdump)
        source_tool = find_addr2line(args.addr2line) if args.source else None
        source_cache = {}
        functions, names, hits, total, unknown = read_report(args.report, args.elf)
        selected = sorted(hits, key=lambda i: (-sum(hits[i].values()), functions[i]))
        if args.function:
            selected = [
                i
                for i, (start, _, name) in enumerate(functions)
                if args.function in (name, names.get(start), f"0x{start:08x}", hex(start))
            ]
            if not selected:
                raise ValueError(
                    "Function not found; use its exact name or hexadecimal start address"
                )
        elif args.top:
            selected = selected[: args.top]
        sections = [
            f"PC sample hits; {total} samples, {unknown} outside ELF function ranges.",
            f"Groups contain up to {args.group_instructions} consecutive instructions, starting at each function entry.\n"
            "Percentages are within each function; groups are not branch-delimited basic blocks.\n"
            "Sampling latency and periodic aliasing can bias hits; these are not instruction costs.",
        ]
        if args.source:
            sections.append(
                "Source lines come from compiler debug mappings; optimized code may reorder or inline them.\n"
                "Use sources matching this ELF; local source contents are not verified."
            )
        for index in selected:
            start, size, name = functions[index]
            instructions = disassemble(tool, args.elf, start, size)
            locations = (
                source_locations(source_tool, args.elf, instructions) if source_tool else None
            )
            sections.append(
                render_function(
                    names.get(start, name),
                    start,
                    instructions,
                    hits[index],
                    total,
                    args.group_instructions,
                    args.show_zero_hit_groups,
                    locations,
                    source_cache,
                    source_maps,
                )
            )
        if not selected:
            sections.append("No sampled functions to annotate.")
        report = "\n\n".join(sections) + "\n"
        if args.output:
            args.output.write_text(report)
        else:
            print(report, end="")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
