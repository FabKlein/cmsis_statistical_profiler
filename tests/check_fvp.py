# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        check_fvp.py
# Description:  Check FVP capture reports against explicit pass/fail criteria
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Validate decoded FVP reports against the committed acceptance reference."""
import argparse
import csv
import json
from pathlib import Path


def check_report(report, reference):
    """Return concise failures; malformed or missing report files raise an exception."""
    summary = json.loads((report / "summary.json").read_text())
    tables = {}
    for name in ("functions", "samples", "events"):
        with (report / (name + ".csv")).open(newline="") as source:
            tables[name] = list(csv.DictReader(source))
    failures = []

    def require(condition, message):
        if not condition:
            failures.append(message)

    def match(actual, expected, path="summary"):
        for key, value in expected.items():
            current = actual.get(key)
            if isinstance(value, dict):
                require(isinstance(current, dict), f"{path}.{key}: missing object")
                if isinstance(current, dict):
                    match(current, value, f"{path}.{key}")
            else:
                require(current == value, f"{path}.{key}: expected {value!r}, got {current!r}")

    match(summary, reference["expected"])
    h = summary["header"]
    count = h["count"]
    low, high = reference["sample_count_range"]
    require(low <= count <= high, f"sample count {count} outside {low}..{high}")
    ticks = (h["stop_tick"] - h["start_tick"]) & 0xFFFFFFFF
    low, high = reference["capture_tick_range"]
    require(low <= ticks <= high, f"capture ticks {ticks} outside {low}..{high}")
    require(h["start_tick"] >= reference["minimum_start_tick"], "missing evidence of a second capture")
    require(h["iterations"] > 0, "workload did not run")
    samples, functions, events = tables["samples"], tables["functions"], tables["events"]
    require(len(samples) == count, "sample CSV row count differs from header")
    require(sum(int(row["hits"]) for row in functions) == count, "function hits differ from sample count")
    workload = reference["workload_function"]
    hits = sum(int(row["hits"]) for row in functions if row["function"] == workload)
    percent = 100 * hits / count if count else 0
    require(percent >= reference["minimum_workload_percent"], f"{workload} share too low: {percent:.2f}%")
    require(any(int(row["exception_return"], 16) == int(reference["required_exception_return"], 16)
                for row in samples), "no extended PSP frame captured")
    pmu = h["pmu"]
    expected_count = reference["expected"]["header"]["pmu"]["count"]
    require(len(events) == expected_count and len(summary["pmu_events"]) == expected_count,
            f"expected {expected_count} PMU event results")
    for index, event_id in enumerate(reference["expected"]["header"]["pmu"]["events"]):
        if index >= len(events) or index >= len(summary["pmu_events"]):
            continue
        event, item = events[index], summary["pmu_events"][index]
        total = (pmu["stop"][index] - pmu["start"][index]) & 0xFFFFFFFF
        require(event["event_id"] == f"0x{event_id:04x}" and item["event_id"] == event["event_id"],
                f"PMU {index}: wrong event ID")
        require(event["status"] == item["status"] == "ok", f"PMU {index}: invalid result")
        require(event["count"] == str(total) and item["count"] == total, f"PMU {index}: inconsistent total")
        previous = pmu["start"][index]
        for row in samples:
            raw = int(row[f"pmu{index}_raw"])
            delta = int(row[f"pmu{index}_interval_delta"])
            require(delta == (raw - previous) & 0xFFFFFFFF, f"PMU {index}: inconsistent interval")
            previous = raw
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path(__file__).with_name("fvp_reference.json"))
    args = parser.parse_args()
    try:
        failures = check_report(args.report, json.loads(args.reference.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures = [str(error)]
    for failure in failures:
        print("FAIL:", failure)
    if failures:
        raise SystemExit(1)
    print("PASS: FVP capture matches the acceptance reference")


if __name__ == "__main__":
    main()
