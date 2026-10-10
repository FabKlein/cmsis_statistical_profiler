# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Shared decoded-report checks, folding statistics and explicit idle selection."""

import csv
import json
import math
import statistics

from pathlib import Path


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def capture_rows(root):
    """Return the ordered capture manifest, also used by the folding tools."""
    with (root / "captures.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError("captures.csv has no capture windows")
    # Use manifest order rather than a directory glob: capture indices are
    # referenced by merged CSVs, timing windows and event annotations.
    for index, row in enumerate(rows):
        if int(row["capture"]) != index:
            raise ValueError("captures.csv must list consecutive captures from zero")
        # The local manifest may point outside the aggregate output directory.
        # Parent components are required for sibling captures; absolute paths
        # remain disallowed so moving the whole directory tree preserves links.
        directory = Path(row["capture_dir"])
        if not row["capture_dir"].strip() or directory.is_absolute():
            raise ValueError(f"capture directory must be a nonempty relative path: {directory}")
    return rows


def read_aggregate(root):
    summary = json.loads((root / "summary.json").read_text())
    captures = capture_rows(root)
    if summary.get("captures") != len(captures) or not summary.get("all_validation_passed"):
        raise ValueError("aggregate captures are incomplete or unvalidated")
    if int(summary["sample_hz"]) <= 0:
        raise ValueError("invalid sample rate")
    return summary, captures


def require_finalized(header, label):
    if any(
        header.get(key) != value
        for key, value in (("active", 0), ("complete", 1), ("validation_passed", 1))
    ):
        raise ValueError(f"{label}: capture is not finalized and valid")


def read_ethosu_report(directory):
    summary = json.loads((directory / "summary.json").read_text())
    records = read_csv(directory / "samples.csv")
    require_finalized(summary, str(directory))
    if len(records) != summary["count"]:
        raise ValueError(f"{directory}: record count differs from summary")
    weights = [int(row["sample_count"]) for row in records]
    if any(weight < 1 for weight in weights) or sum(weights) != summary["total_samples"]:
        raise ValueError(f"{directory}: compressed tick count differs")
    if any(int(row["running"]) and weight != 1 for row, weight in zip(records, weights)):
        raise ValueError(f"{directory}: compressed running sample")
    return summary, records


def running_groups(records):
    """Return indices of bursts separated by idle; never fill missing running ticks."""
    groups, current = [], []
    for index, record in enumerate(records):
        if int(record["running"]):
            if current and int(record["tick"]) != int(records[current[-1]]["tick"]) + 1:
                raise ValueError("running Ethos-U group has missing sample ticks")
            current.append(index)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def mean_ci(values):
    """Mean and approximate normal 95% interval, not a bound on profiling error.

    Periods may be correlated. One observation has width zero; empty coverage
    stays blank rather than becoming a measured zero.
    """
    if not values:
        return "", ""
    ci = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0
    return statistics.mean(values), ci


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_address(value):
    if type(value) is int:
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError("PC range addresses must be integers or strings")


def idle_classification(platform, functions=None):
    """Select only caller-supplied names/ranges; an absent classification is None."""
    cpu = platform.get("cpu", {})
    names = cpu.get("idle_functions", []) if functions is None else functions
    if functions is not None and isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name.strip() for name in names
    ):
        raise ValueError("idle_functions must be a list of names")
    ranges = cpu.get("idle_pc_ranges", [])
    if not isinstance(ranges, list):
        raise TypeError("idle_pc_ranges must be a list")
    for item in ranges:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise ValueError("each idle PC range needs start and end")
        if not 0 <= parse_address(item["start"]) < parse_address(item["end"]):
            raise ValueError("idle PC ranges must have increasing nonnegative addresses")
    return {"idle_functions": names, "idle_pc_ranges": ranges} if names or ranges else None


def is_idle(row, classification):
    if row.get("function") in classification["idle_functions"]:
        return True
    ranges = classification["idle_pc_ranges"]
    return bool(ranges) and any(
        parse_address(item["start"]) <= parse_address(row["pc"]) < parse_address(item["end"])
        for item in ranges
    )


def read_platform(root):
    path = root / "platform.json"
    if not path.is_file():
        return {}
    platform = json.loads(path.read_text())
    if not isinstance(platform, dict):
        raise TypeError("platform.json must contain an object")
    if platform.get("schema_version") != 1:
        raise ValueError("unsupported platform.json schema_version")
    for key in ("soc", "clock_basis"):
        if key in platform and (not isinstance(platform[key], str) or not platform[key].strip()):
            raise ValueError(f"platform.json {key} must be nonempty text")
    for processor in ("cpu", "ethosu"):
        info = platform.get(processor, {})
        if not isinstance(info, dict):
            raise TypeError(f"platform.json {processor} must be an object")
        for key in ("name", "role"):
            if key in info and (not isinstance(info[key], str) or not info[key].strip()):
                raise ValueError(f"platform.json {processor}.{key} must be nonempty text")
        if "frequency_hz" in info:
            hz = info["frequency_hz"]
            if isinstance(hz, bool) or not isinstance(hz, int) or hz <= 0:
                raise ValueError(
                    f"platform.json {processor}.frequency_hz must be a positive integer"
                )
    idle_classification(platform)
    return platform
