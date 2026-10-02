# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        select_profiler_unwind.py
# Description:  Infer selective EHABI retention from an AC6 first-pass map
#
# $Date:        2 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Generate an armlink --via response file from retained Code RO map rows.

Names are inferred, not verified against ELF input objects. Always check the final ELF.
"""

import argparse
from pathlib import Path
import re
import sys
import tempfile

# Parse only retained section tables. Discarded-section reports can mention
# the same names and must not cause dead code to be retained by the second link.
HEADER = re.compile(
    r"^\s*Base Addr\s+Size\s+Type\s+Attr\s+Idx\s+(?:E\s+)?Section Name\s+Object\s*$"
)
ADDRESS = re.compile(r"^\s*0[xX][0-9a-fA-F]+\s+0[xX][0-9a-fA-F]+\s+")
CODE = re.compile(
    r"^\s*0[xX][0-9a-fA-F]+\s+0[xX](?P<size>[0-9a-fA-F]+)\s+"
    r"Code\s+RO\s+\d+\s+(?:(?P<entry>\S)\s+)?(?P<section>\S+)\s+(?P<object>\S.*)$"
)


def validate_section(name):
    # Do not let input names become response-file syntax or wildcard selectors.
    if not name or any(c.isspace() or c in '*?[]()"\\' or ord(c) < 32 for c in name):
        raise ValueError(
            f"Cannot safely represent section name {name!r} in an armlink retention rule"
        )


def select_sections(text, extra_sections=()):
    """Read section tables, excluding discarded lists and other map reports."""
    for name in extra_sections:
        validate_section(name)
    selected, omitted = set(), set()
    active = found_header = False
    for number, line in enumerate(text.splitlines(), 1):
        if HEADER.fullmatch(line):
            active = found_header = True
            continue
        if not line.strip():
            continue
        if not active:
            continue
        # A non-row ends this table; another recognized header can reopen it.
        if not ADDRESS.match(line):
            active = False
            continue
        if not re.search(r"\bCode\s+RO\b", line):
            continue  # PAD, Data, Zero and other non-code rows.
        match = CODE.fullmatch(line)
        if not match:
            raise ValueError(
                f"Unrecognized Code RO row at line {number}; inspect the AC6 map format"
            )
        if int(match["size"], 16) == 0:
            continue
        name = match["section"]
        if name == ".text" or name.startswith(".text.") or name in extra_sections:
            validate_section(name)
            # AC6 commonly derives EXIDX names from the input code section.
            # This naming inference cannot establish whether metadata really exists.
            selected.add(".ARM.exidx" + name)
        else:
            omitted.add(name)
    if not found_header:
        raise ValueError("No AC6 section-table header found; supply the first-link --map output")
    if not selected:
        raise ValueError(
            "No selected executable input sections found; check the map or use --code-section NAME"
        )
    warnings = [
        "EXIDX names are inferred, not verified in input objects. Object wildcard * may retain matching sections from multiple objects."
    ]
    if ".ARM.exidx.text" in selected:
        warnings.append(
            "Bare .text inferred as .ARM.exidx.text; some objects use a different name or have no table, producing an unmatched-rule linker warning."
        )
    if omitted:
        names = ", ".join(sorted(omitted)[:8])
        warnings.append(
            f"{len(omitted)} other Code RO section names omitted ({names}); use --code-section NAME for required custom sections after checking their EXIDX names."
        )
    # Sorting and deduplication keep generated build inputs stable across runs.
    return sorted(selected), warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "map", type=Path, help="Fresh AC6 first-pass map, with no blanket EXIDX retention"
    )
    parser.add_argument(
        "output", type=Path, help="Generated response file, consumed directly by armlink --via"
    )
    parser.add_argument(
        "--code-section",
        action="append",
        default=[],
        metavar="NAME",
        help="Also infer .ARM.exidxNAME for this exact custom code section; repeatable",
    )
    args = parser.parse_args()
    temporary = None
    try:
        if args.map.resolve() == args.output.resolve():
            raise ValueError("Map input and response output must be different files")
        sections, warnings = select_sections(args.map.read_text(), args.code_section)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Publish complete deterministic output, preserving any previous file on failure.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=args.output.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write("".join(f'--keep="*({section})"\n' for section in sections))
        temporary.replace(args.output)
        temporary = None
    except (OSError, ValueError) as error:
        parser.exit(
            1, f"Error: {error}\nAbort the second link; do not reuse an earlier response file.\n"
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    for warning in warnings:
        print("WARNING: " + warning, file=sys.stderr)
    print(f"Selected {len(sections)} inferred EXIDX section names: {args.output}")


if __name__ == "__main__":
    main()
