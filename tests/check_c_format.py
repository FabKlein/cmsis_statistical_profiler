# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Check profiler-owned C/H files using the pinned clang-format 22.1.0."""

import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formatter", default="clang-format")
    args = parser.parse_args()
    version = subprocess.check_output([args.formatter, "--version"], text=True)
    if "version 22.1.0" not in version:
        parser.error("use clang-format 22.1.0")
    files = sorted(path for directory in ("mcu", "adapters", "integrations")
                   for path in (ROOT / directory).rglob("*") if path.suffix in (".c", ".h"))
    subprocess.run([args.formatter, "--dry-run", "--Werror", *map(str, files)], check=True)


if __name__ == "__main__":
    main()
