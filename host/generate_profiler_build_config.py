# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Generate a fresh firmware build token and optional shared profiler ABI settings."""

import argparse
import secrets
import struct
from pathlib import Path


def generate(pmu_count=None, unwind=None, depth=None):
    # A fresh per-build token avoids self-referential ELF hashing. It is an image
    # association check, not authentication; preserve the exact generated header.
    words = struct.unpack("<4I", secrets.token_bytes(16))
    lines = [
        "/* Generated before this firmware build; preserve with the ELF. */",
        "#ifndef PROFILER_GENERATED_BUILD_CONFIG_H",
        "#define PROFILER_GENERATED_BUILD_CONFIG_H",
        "#define PROFILER_FIRMWARE_ID {" + ", ".join(f"0x{word:08X}U" for word in words) + "}",
    ]
    for option, value in (
        ("PMU_COUNT", pmu_count),
        ("STACK_UNWIND", unwind),
        ("UNWIND_MAX_DEPTH", depth),
    ):
        if value is not None:
            lines.extend(
                [
                    f"#ifndef PROFILER_{option}",
                    f"#define PROFILER_{option} {value}",
                    "#endif",
                    f"#define PROFILER_EXPECTED_{option} {value}",
                ]
            )
    return "\n".join([*lines, "#endif", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pmu-count", type=int, choices=range(5))
    parser.add_argument("--unwind", type=int, choices=(0, 1))
    parser.add_argument("--unwind-depth", type=int, choices=range(1, 256))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate(args.pmu_count, args.unwind, args.unwind_depth))


if __name__ == "__main__":
    main()
