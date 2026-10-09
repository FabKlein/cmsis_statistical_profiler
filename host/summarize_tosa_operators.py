# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Group exact-PTE-aligned Vela queue rows by TOSA operation type."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def summarize(root):
    alignment = json.loads((root / "vela_alignment.json").read_text())
    if not alignment["listing_matches_pte"]:
        raise ValueError("Vela debug package does not match the PTE command stream")
    with (root / "ethosu_operator_samples.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != alignment["debug_queue_operations"]:
        raise ValueError("queue row count changed")

    groups = defaultdict(
        lambda: {
            "operators": 0,
            "operators_with_samples": 0,
            "samples": 0,
            "est_cycles": 0,
            "macs": 0,
        }
    )
    for row in rows:
        group = groups[row["tosa_op"] or "<unspecified>"]
        group["operators"] += 1
        samples = int(row["samples"])
        group["operators_with_samples"] += bool(samples)
        group["samples"] += samples
        group["est_cycles"] += int(row["est_cycles"])
        group["macs"] += int(row["macs"])
    if sum(group["samples"] for group in groups.values()) != alignment["assigned_samples"]:
        raise ValueError("assigned sample count changed")
    running = alignment["running_samples"]
    if running <= 0:
        raise ValueError("no running Ethos-U samples")
    return [
        {
            "tosa_op": op,
            **group,
            "percent_of_running_samples": round(100 * group["samples"] / running, 2),
        }
        for op, group in sorted(groups.items(), key=lambda item: (-item[1]["samples"], item[0]))
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = summarize(args.run_dir)
        if not rows:
            raise ValueError("no TOSA operations")
        with (args.run_dir / "ethosu_tosa_op_summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=(
                    "tosa_op",
                    "operators",
                    "operators_with_samples",
                    "samples",
                    "percent_of_running_samples",
                    "est_cycles",
                    "macs",
                ),
            )
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} TOSA operation groups")
    except (OSError, ValueError, KeyError, IndexError) as error:
        parser.exit(1, f"TOSA summary failed: {error}\n")


if __name__ == "__main__":
    main()
