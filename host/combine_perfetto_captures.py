# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Combine decoded Cortex-M capture windows into one pause-free Perfetto trace."""

import argparse
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from visualize_profiler_report import event_rates, read_report, write_perfetto


def capture_rows(root):
    with (root / "captures.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError("captures.csv has no capture windows")
    for index, row in enumerate(rows):
        if int(row["capture"]) != index:
            raise ValueError("captures.csv must list consecutive captures from zero")
        directory = Path(row["capture_dir"])
        if directory.is_absolute() or ".." in directory.parts:
            raise ValueError(f"unsafe capture directory: {directory}")
    return rows


def duration_us(header):
    frequency = int(header["timestamp_hz"])
    if frequency <= 0:
        raise ValueError("timestamp_hz must be positive")
    # The device timestamp is 32-bit; a window can straddle counter rollover.
    ticks = (int(header["stop_timestamp"]) - int(header["start_timestamp"])) & 0xFFFFFFFF
    return ticks * 1_000_000 / frequency


def boundary(index, position, timestamp, duration):
    return {
        "ph": "I",
        "s": "g",
        "pid": 1,
        "ts": timestamp,
        "cat": "capture.boundary",
        "name": f"Capture {index:02d} {position}",
        "args": {"capture": index, "position": position, "duration_us": duration},
    }


def combine(root, destination):
    aggregate = json.loads((root / "summary.json").read_text())
    rows = capture_rows(root)
    if aggregate.get("captures") != len(rows):
        raise ValueError("aggregate capture count differs from captures.csv")
    if aggregate.get("all_validation_passed") is not True:
        raise ValueError("aggregate capture validation did not pass")
    events = []
    offset_us = 0.0
    sample_total = 0
    with TemporaryDirectory() as temporary:
        scratch = Path(temporary) / "window.json"
        for index, row in enumerate(rows):
            report = root / row["capture_dir"] / "cortex_m_report"
            summary, samples = read_report(report)
            header = summary["header"]
            if summary.get("elf_sha256") != aggregate.get("elf_sha256"):
                raise ValueError(f"capture {index}: ELF hash differs from aggregate")
            if int(header["sample_hz"]) != int(aggregate["sample_hz"]):
                raise ValueError(f"capture {index}: sample rate differs from aggregate")
            if any(
                header.get(field) != value
                for field, value in (("complete", 1), ("active", 0), ("validation_passed", 1))
            ):
                raise ValueError(f"capture {index}: buffer was not finalized and validated")
            if len(samples) != int(row["cpu_samples"]):
                raise ValueError(f"capture {index}: sample count differs from captures.csv")
            duration = duration_us(header)
            if duration < samples[-1]["time_us"]:
                raise ValueError(f"capture {index}: last sample exceeds capture stop")
            rates, warnings = event_rates(summary, samples)
            write_perfetto(scratch, summary, samples, rates, warnings)
            window_events = json.loads(scratch.read_text())["traceEvents"]
            if index == 0:
                events.extend(event for event in window_events if event["ph"] == "M")
                events.append(
                    {
                        "ph": "I",
                        "s": "g",
                        "pid": 1,
                        "ts": 0,
                        "cat": "profiler.metadata",
                        "name": "Combined capture timeline",
                        "args": {
                            "captures": len(rows),
                            "time_basis": "concatenated active capture durations; debugger pauses omitted",
                            "pmu_boundary": "no PMU rate calculated between capture windows",
                        },
                    }
                )
            events.append(boundary(index, "start", offset_us, duration))
            for event in window_events:
                if event["ph"] == "M":
                    continue
                event["ts"] += offset_us
                event.setdefault("args", {})["capture"] = index
                events.append(event)
            offset_us += duration
            events.append(boundary(index, "end", offset_us, duration))
            sample_total += len(samples)
    if sample_total != aggregate.get("cpu_samples"):
        raise ValueError("combined sample count differs from aggregate summary")
    destination.write_text(
        json.dumps({"traceEvents": events}, separators=(",", ":"), allow_nan=False) + "\n"
    )
    return len(rows), sample_total, offset_us


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    destination = root / "cortex_m_combined.perfetto.json"
    try:
        captures, samples, duration = combine(root, destination)
        print(
            f"{destination}: {captures} captures, {samples} CPU samples, {duration / 1_000_000:.3f} s active time"
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"combined Perfetto trace failed: {error}\n")


if __name__ == "__main__":
    main()
