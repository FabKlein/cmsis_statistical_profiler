#!/usr/bin/env python3
"""Validate and export a separate Ethos-U EUTR v1 statistical trace."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import struct


MAGIC = 0x52545545
HEADER_WORDS = 32
HEADER_BYTES = HEADER_WORDS * 4
NO_QREAD = 0xFFFFFFFF
HEADER_FIELDS = (
    "magic",
    "version",
    "header_bytes",
    "record_bytes",
    "buffer_bytes",
    "count",
    "active",
    "full",
    "complete",
    "sample_hz",
    "timestamp_hz",
    "pmu_count",
    "pmu_status",
    "pmu_event0",
    "pmu_event1",
    "pmu_event2",
    "pmu_event3",
    "stream_bytes",
    "streams_seen",
    "invalid_qread",
    "start_timestamp",
    "start_tick",
    "stop_timestamp",
    "stop_tick",
    "iterations",
    "validation_passed",
    "device_type",
)


def decode(data):
    if len(data) < HEADER_BYTES or len(data) % 4:
        raise ValueError("trace must contain a complete 128-byte, word-aligned header")
    words = struct.unpack_from("<32I", data)
    header = dict(zip(HEADER_FIELDS, words))
    if header["magic"] != MAGIC or header["version"] != 1:
        raise ValueError("not an Ethos-U EUTR v1 trace")
    if header["header_bytes"] != HEADER_BYTES or header["buffer_bytes"] != len(data):
        raise ValueError("trace header or buffer length does not match the dump")
    if header["device_type"] not in (55, 65, 85):
        raise ValueError("unknown Ethos-U device type")
    pmu_count = header["pmu_count"]
    record_bytes = header["record_bytes"]
    if pmu_count > 4 or record_bytes != (4 + pmu_count) * 4:
        raise ValueError("invalid PMU count or record width")
    if header["count"] > (len(data) - HEADER_BYTES) // record_bytes:
        raise ValueError("record count exceeds buffer capacity")
    records = []
    for index in range(header["count"]):
        values = struct.unpack_from(f"<{4 + pmu_count}I", data, HEADER_BYTES + index * record_bytes)
        record = dict(zip(("timestamp", "tick", "status", "qread"), values[:4]))
        record["running"] = int(bool(record["status"] & 1))
        if record["qread"] == NO_QREAD:
            record["qread"] = ""
        for counter, value in enumerate(values[4:]):
            record[f"pmu{counter}"] = value
        records.append(record)
    summary = {key: header[key] for key in HEADER_FIELDS if key != "magic"}
    summary["format"] = "EUTR"
    summary["running_samples"] = sum(record["running"] for record in records)
    summary["qread_samples"] = sum(record["qread"] != "" for record in records)
    summary["running_percent"] = (
        round(100 * summary["running_samples"] / len(records), 2) if records else 0.0
    )
    return summary, records


def qread_histogram(records):
    """Count valid running samples by QREAD byte offset, hottest first."""
    counts = Counter(
        record["qread"] for record in records if record["running"] and record["qread"] != ""
    )
    running_samples = sum(record["running"] for record in records)
    return [
        {
            "qread_bytes": offset,
            "samples": count,
            "percent_of_running_samples": round(100 * count / running_samples, 2),
            "percent_of_all_samples": round(100 * count / len(records), 2),
        }
        for offset, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True, help="full EUTR buffer dump")
    parser.add_argument("--output", type=Path, required=True, help="output directory")
    args = parser.parse_args()
    summary, records = decode(args.samples.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    fields = ["timestamp", "tick", "status", "running", "qread"] + [
        f"pmu{i}" for i in range(summary["pmu_count"])
    ]
    with (args.output / "samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    histogram = qread_histogram(records)
    with (args.output / "qread_histogram.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "qread_bytes",
                "samples",
                "percent_of_running_samples",
                "percent_of_all_samples",
            ),
        )
        writer.writeheader()
        writer.writerows(histogram)
    print(f"{summary['count']} samples, {summary['running_percent']}% NPU running")
    print(f"{len(histogram)} QREAD offsets; hottest offsets (% of running samples):")
    for row in histogram[:10]:
        print(
            f"  {row['qread_bytes']:8d} B  {row['samples']:6d}  {row['percent_of_running_samples']:6.2f}%"
        )


if __name__ == "__main__":
    main()
