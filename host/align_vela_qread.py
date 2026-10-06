#!/usr/bin/env python3
"""Verify a Vela debug package against a PTE and annotate a QREAD histogram."""

import argparse
import bisect
import csv
import hashlib
import io
import json
import re
import struct
from pathlib import Path


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


def queue_offsets(xml):
    match = re.search(r'<table name="queue">\s*<!\[CDATA\[(.*?)\]\]>', xml, re.S)
    if not match:
        raise ValueError("Vela debug database has no queue table")
    return sorted(int(row["offset"]) for row in csv.DictReader(io.StringIO(match.group(1).strip())))


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
    if starts != queue_offsets((debug_dir / "out_debug.xml").read_text()):
        raise ValueError("operator map offsets differ from Vela debug queue offsets")

    histogram = read_csv(histogram_path)
    counts = [0] * len(ops)
    unmatched = []
    total = 0
    stream_ids = set()
    for row in histogram:
        qread = int(row["qread_bytes"])
        samples = int(row["samples"])
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
    if summary_path.exists():
        descriptors = json.loads(summary_path.read_text()).get("stream_identity", [])
        if (
            len(descriptors) != 1
            or str(descriptors[0]["stream_id"]) not in stream_ids
            or int(descriptors[0]["stream_bytes"]) != len(stream)
        ):
            raise ValueError("histogram stream descriptor does not match the Vela command stream")

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
                    "percent_of_running_samples": round(100 * count / total, 2) if total else 0,
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
        "command_stream_exact_match": True,
        "debug_queue_operations": len(ops),
        "histogram_stream_ids": sorted(stream_ids),
        "running_samples": total,
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
