# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        analyze_ethosu_trace.py
# Description:  Validate and export Ethos-U statistical captures
#
# $Date:        5 October 2026
# $Revision:    V.1.0.5
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Validate and export a separate Ethos-U EUTR v1 statistical trace."""

import argparse
import csv
import json
import struct
from collections import Counter
from pathlib import Path

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
    "stream_count",
    "streams_seen",
    "invalid_qread",
    "start_timestamp",
    "start_tick",
    "stop_timestamp",
    "stop_tick",
    "iterations",
    "validation_passed",
    "device_type",
    "stream_capacity",
    "unknown_stream_samples",
    "unregistered_streams",
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
    # Only stop() finalizes and flushes the allocation. An active dump can
    # contain a record whose fields and publication count were read at different times.
    for flag in ("active", "full", "complete", "validation_passed"):
        if header[flag] not in (0, 1):
            raise ValueError(f"invalid boolean capture flag: {flag}")
    if header["active"] or not header["complete"]:
        raise ValueError("capture not stopped/completed; dump after trace_ethosu_stop")
    if not header["sample_hz"] or not header["timestamp_hz"]:
        raise ValueError("sample and timestamp frequencies must be nonzero")
    if len(data) % 32:
        raise ValueError(
            "buffer allocation must match firmware's minimum size and 32-byte alignment"
        )
    if any(words[len(HEADER_FIELDS) :]):
        raise ValueError("reserved EUTR v1 header words must be zero")
    stream_capacity = header["stream_capacity"]
    stream_count = header["stream_count"]
    if not 1 <= stream_capacity <= 64 or stream_count > stream_capacity:
        raise ValueError("invalid stream table dimensions")
    if stream_count + header["unregistered_streams"] > header["streams_seen"]:
        raise ValueError("stream discovery counts exceed submission count")
    record_offset = HEADER_BYTES + 8 * stream_capacity
    if record_offset > len(data):
        raise ValueError("truncated stream table")
    streams = []
    identities = set()
    for i in range(stream_capacity):
        address, size = struct.unpack_from("<II", data, HEADER_BYTES + i * 8)
        if i >= stream_count:
            if address or size:
                raise ValueError("unused stream descriptors must be zero")
            continue
        if address % 4 or not size or size % 4 or address + size > 1 << 32:
            raise ValueError("invalid stream address or length")
        if (address, size) in identities:
            raise ValueError("duplicate stream descriptor")
        identities.add((address, size))
        streams.append(
            {"stream_id": i + 1, "command_address": f"0x{address:08x}", "stream_bytes": size}
        )

    pmu_count = header["pmu_count"]
    record_bytes = header["record_bytes"]
    if pmu_count > 4 or record_bytes != (5 + pmu_count) * 4:
        raise ValueError("invalid PMU count or record width")
    # The adapter publishes counters only after acquiring the PMU. Disabled or
    # busy PMUs contribute no event words; unused event identifiers stay zero.
    pmu_status = header["pmu_status"]
    if pmu_status not in (0, 1, 2) or (pmu_status == 1) != (pmu_count > 0):
        raise ValueError("PMU status and counter count disagree")
    if any(header[f"pmu_event{i}"] for i in range(pmu_count, 4)):
        raise ValueError("unused PMU event identifiers must be zero")
    capacity = (len(data) - record_offset) // record_bytes
    if capacity < 1:
        raise ValueError("allocation cannot hold a record")
    if header["count"] > capacity:
        raise ValueError("record count exceeds buffer capacity")
    if header["full"] and header["count"] != capacity:
        raise ValueError("full flag disagrees with record count")
    records = []
    invalid_qread = unknown_stream_samples = 0
    for index in range(header["count"]):
        values = struct.unpack_from(
            f"<{5 + pmu_count}I", data, record_offset + index * record_bytes
        )
        record = dict(zip(("timestamp", "tick", "status", "qread", "stream_id"), values[:5]))
        record["running"] = int(bool(record["status"] & 1))
        stream_id = record["stream_id"]
        if stream_id > stream_count or (not record["running"] and stream_id):
            raise ValueError(f"record {index}: invalid stream ID")
        unknown_stream_samples += int(record["running"] and not stream_id)
        if record["qread"] == NO_QREAD:
            invalid_qread += record["running"]
            record["qread"] = ""
        else:
            if not record["running"] or record["qread"] % 4:
                raise ValueError(f"record {index}: QREAD must be aligned and the NPU running")
            if stream_id and record["qread"] > streams[stream_id - 1]["stream_bytes"]:
                raise ValueError(f"record {index}: QREAD exceeds its stream length")
        for counter, value in enumerate(values[5:]):
            record[f"pmu{counter}"] = value
        records.append(record)
    if invalid_qread != header["invalid_qread"]:
        raise ValueError("invalid_qread counter disagrees with running records missing QREAD")
    if unknown_stream_samples != header["unknown_stream_samples"]:
        raise ValueError("unknown_stream_samples counter disagrees with records")
    summary = {key: header[key] for key in HEADER_FIELDS if key != "magic"}
    summary["format"] = "EUTR"
    summary["streams"] = streams
    summary["running_samples"] = sum(record["running"] for record in records)
    summary["qread_samples"] = sum(record["qread"] != "" for record in records)
    summary["running_percent"] = (
        round(100 * summary["running_samples"] / len(records), 2) if records else 0.0
    )
    return summary, records


def qread_histogram(records):
    """Rank (stream ID, QREAD) pairs; never merge anonymous streams into hotspots."""
    counts = Counter(
        (record["stream_id"], record["qread"])
        for record in records
        if record["running"] and record["stream_id"] and record["qread"] != ""
    )
    running_samples = sum(record["running"] for record in records)
    return [
        {
            "stream_id": stream_id,
            "qread_bytes": offset,
            "samples": count,
            "percent_of_running_samples": round(100 * count / running_samples, 2),
            "percent_of_all_samples": round(100 * count / len(records), 2),
        }
        for (stream_id, offset), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True, help="full EUTR buffer dump")
    parser.add_argument("--output", type=Path, required=True, help="output directory")
    args = parser.parse_args()
    # Validate everything before creating output files, so a rejected dump
    # cannot publish plausible-looking partial reports.
    try:
        summary, records = decode(args.samples.read_bytes())
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"Error: {error}\n")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    fields = ["timestamp", "tick", "status", "running", "stream_id", "qread"] + [
        f"pmu{i}" for i in range(summary["pmu_count"])
    ]
    with (args.output / "samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    with (args.output / "streams.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("stream_id", "command_address", "stream_bytes"))
        writer.writeheader()
        writer.writerows(summary["streams"])
    histogram = qread_histogram(records)
    with (args.output / "qread_histogram.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "stream_id",
                "qread_bytes",
                "samples",
                "percent_of_running_samples",
                "percent_of_all_samples",
            ),
        )
        writer.writeheader()
        writer.writerows(histogram)
    print(f"{summary['count']} samples, {summary['running_percent']}% NPU running")
    print(f"{len(histogram)} stream/QREAD pairs; hottest offsets (% of running samples):")
    if summary["unknown_stream_samples"]:
        print(
            f"WARNING: {summary['unknown_stream_samples']} running samples have unknown stream IDs; excluded from histogram"
        )
    for row in histogram[:10]:
        print(
            f"  stream {row['stream_id']:3d}  {row['qread_bytes']:8d} B  {row['samples']:6d}  {row['percent_of_running_samples']:6.2f}%"
        )


if __name__ == "__main__":
    main()
