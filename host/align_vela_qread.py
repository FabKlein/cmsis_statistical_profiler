# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        align_vela_qread.py
# Description:  Match command listings and report sampled operator positions
#
# $Date:        6 October 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Check supplied Vela artifacts and annotate QREAD; capture provenance is caller supplied."""

import argparse
import bisect
import csv
import hashlib
import json
import re
import struct
from pathlib import Path

from build_vela_qread_map import build_map


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def command_stream(listing):
    words = []
    kicks = {}
    base = None
    for line in listing.splitlines():
        match = re.match(
            r"^0x([0-9a-fA-F]+):\s+([0-9a-fA-F]{8})(?:\s+([0-9a-fA-F]{8}))?\s+(NPU_\w+)", line
        )
        if not match:
            continue
        address = int(match.group(1), 16)
        if base is None:
            base = address
        offset = address - base
        if offset != len(words) * 4:
            raise ValueError(f"noncontiguous command listing at {address:#x}")
        words.append(int(match.group(2), 16))
        if match.group(3):
            words.append(int(match.group(3), 16))
        op = match.group(4)
        if op in {"NPU_OP_CONV", "NPU_OP_DEPTHWISE", "NPU_OP_POOL", "NPU_OP_ELEMENTWISE"}:
            kicks[offset] = op.removeprefix("NPU_OP_")
    if not words:
        raise ValueError("no NPU commands in listing")
    return base, struct.pack(f"<{len(words)}I", *words), kicks


def align(pte_path, debug_dir, histogram_path, output_dir):
    pte = pte_path.read_bytes()
    base, stream, kicks = command_stream((debug_dir / "cmdstream_listing.txt").read_text())
    end = base + len(stream)
    if pte[base:end] != stream:
        mismatch = next((i for i, (a, b) in enumerate(zip(pte[base:end], stream)) if a != b), None)
        raise ValueError(f"Vela command stream differs from PTE at stream byte {mismatch}")

    ops = read_csv(debug_dir / "qread_ops.csv")
    if not ops:
        raise ValueError("operator map is empty")
    starts = [int(row["kick_offset"], 16) for row in ops]
    ends = [int(row["next_kick_offset"], 16) for row in ops]
    if starts != sorted(starts) or any(a != b for a, b in zip(ends[:-1], starts[1:])):
        raise ValueError("operator map has gaps, overlaps, or unsorted boundaries")
    if ends[-1] > len(stream):
        raise ValueError("operator map extends beyond the command stream")
    if set(starts) != set(kicks):
        raise ValueError("operator map does not contain exactly the listing's compute kicks")
    for row, start in zip(ops, starts):
        if row["npu_op"] != kicks[start]:
            raise ValueError(f"operator kind differs at {start:#x}")
    # Rebuild the canonical rows from the supplied database, not just its kick
    # offsets: a stale map can have matching boundaries but different labels.
    columns, expected = build_map(
        debug_dir / "out_debug.xml", debug_dir / "cmdstream_listing.txt", base
    )
    if len(ops) != len(expected):
        raise ValueError("operator map row count differs from the supplied Vela database")
    for index, (row, reference) in enumerate(zip(ops, expected)):
        if set(row) != set(columns):
            raise ValueError(f"operator map row {index}: columns differ from the generated map")
        for field in columns:
            actual = (
                int(row[field], 16) if field in ("kick_offset", "next_kick_offset") else row[field]
            )
            wanted = (
                int(reference[field], 16)
                if field in ("kick_offset", "next_kick_offset")
                else str(reference[field])
            )
            if actual != wanted:
                raise ValueError(
                    f"operator map row {index}: {field} differs from the supplied Vela artifacts"
                )

    histogram = read_csv(histogram_path)
    counts = [0] * len(ops)
    unmatched = []
    total = 0
    stream_ids = set()
    for row in histogram:
        qread = int(row["qread_bytes"])
        samples = int(row["samples"])
        if samples < 0:
            raise ValueError("histogram sample counts must be nonnegative")
        stream_ids.add(row["stream_id"])
        total += samples
        index = bisect.bisect_right(starts, qread) - 1
        if index < 0 or qread >= ends[index]:
            unmatched.append(
                {
                    "stream_id": row["stream_id"],
                    "qread_bytes": qread,
                    "qread_hex": f"0x{qread:06X}",
                    "samples": samples,
                }
            )
        else:
            counts[index] += samples
    if len(stream_ids) != 1:
        raise ValueError(f"expected one stream ID in histogram, got {sorted(stream_ids)}")
    summary_path = histogram_path.parent / "summary.json"
    # Histogram rows exclude unknown streams and invalid QREAD. Their sum
    # cannot supply the denominator for a percentage of all running samples.
    if not summary_path.is_file():
        raise ValueError(
            "aggregate summary.json is required beside the histogram for running totals"
        )
    summary = json.loads(summary_path.read_text())
    running_samples = summary.get("ethosu_running_ticks")
    if type(running_samples) is not int or running_samples < 0:
        raise ValueError("aggregate summary must contain nonnegative integer ethosu_running_ticks")
    if total > running_samples:
        raise ValueError("histogram sample total exceeds aggregate running ticks")
    descriptors = summary.get("stream_identity", [])
    if (
        len(descriptors) != 1
        or str(descriptors[0]["stream_id"]) not in stream_ids
        or int(descriptors[0]["stream_bytes"]) != len(stream)
    ):
        raise ValueError("histogram stream descriptor does not match the Vela command stream")

    # These hashes identify supplied files, not firmware/model identity on the
    # device. No stream hash is embedded in the capture for comparison.
    input_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in {
            "listing": debug_dir / "cmdstream_listing.txt",
            "debug_database": debug_dir / "out_debug.xml",
            "operator_map": debug_dir / "qread_ops.csv",
            "histogram": histogram_path,
            "aggregate_summary": summary_path,
        }.items()
    }
    input_hashes["pte"] = hashlib.sha256(pte).hexdigest()

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "ethosu_operator_samples.csv").open("w", newline="") as target:
        columns = list(ops[0]) + ["samples", "percent_of_running_samples"]
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for row, count in zip(ops, counts):
            writer.writerow(
                {
                    **row,
                    "samples": count,
                    "percent_of_running_samples": round(100 * count / running_samples, 2)
                    if running_samples
                    else 0,
                }
            )
    with (output_dir / "ethosu_unmatched_qread.csv").open("w", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=["stream_id", "qread_bytes", "qread_hex", "samples"]
        )
        writer.writeheader()
        writer.writerows(unmatched)
    result = {
        "pte": str(pte_path),
        "pte_sha256": hashlib.sha256(pte).hexdigest(),
        "command_stream_file_offset": base,
        "command_stream_bytes": len(stream),
        "command_stream_sha256": hashlib.sha256(stream).hexdigest(),
        "listing_matches_pte": True,
        "map_matches_supplied_debug_database": True,
        "capture_pte_identity_verified": False,
        "input_sha256": input_hashes,
        "provenance_note": (
            "The supplied listing matches the supplied PTE. The caller supplies the "
            "capture-to-PTE association and the database-to-model-build association; "
            "matching offsets, lengths and file hashes do not prove those associations."
        ),
        "debug_queue_operations": len(ops),
        "histogram_stream_ids": sorted(stream_ids),
        "running_samples": running_samples,
        "histogram_samples": total,
        "excluded_samples": running_samples - total,
        "assigned_samples": sum(counts),
        "unmatched_samples": sum(row["samples"] for row in unmatched),
        "operators_with_samples": sum(bool(count) for count in counts),
    }
    (output_dir / "vela_alignment.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pte", required=True, type=Path)
    parser.add_argument("--debug-dir", required=True, type=Path)
    parser.add_argument("--histogram", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = align(args.pte, args.debug_dir, args.histogram, args.output_dir)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"alignment failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
