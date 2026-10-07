# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Fold Ethos-U running ticks and optional PMU events over complete periods."""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from combine_perfetto_captures import capture_rows

KNOWN_EVENTS = {
    5: ("npu_active", "NPU active"),
    6: ("mac_active", "MAC active"),
    13: ("ib_stall", "MAC input-buffer stall"),
    41: ("axi_read_request_stall", "AXI0 read-request stall"),
}


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def running_groups(records):
    groups = []
    current = []
    for index, record in enumerate(records):
        if int(record["running"]):
            tick = int(record["tick"])
            if current and tick != int(records[current[-1]]["tick"]) + 1:
                raise ValueError("running Ethos-U group has missing sample ticks")
            current.append(index)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def fold(root):
    aggregate = json.loads((root / "summary.json").read_text())
    captures = capture_rows(root)
    if aggregate.get("captures") != len(captures) or not aggregate.get("all_validation_passed"):
        raise ValueError("aggregate captures are incomplete or unvalidated")
    sample_hz = int(aggregate["sample_hz"])
    if sample_hz <= 0:
        raise ValueError("invalid sample rate")
    event_ids = None
    timestamp_hz = None
    windows = []
    pmu_windows = []
    phase_running = defaultdict(list)
    phase_qreads = defaultdict(list)
    phase_pmu = defaultdict(list)
    period_ticks = []
    running_intervals = 0

    for capture_index, item in enumerate(captures):
        directory = root / item["capture_dir"] / "ethosu_report"
        summary = json.loads((directory / "summary.json").read_text())
        records = read_csv(directory / "samples.csv")
        if any(
            summary.get(key) != value
            for key, value in (("active", 0), ("complete", 1), ("validation_passed", 1))
        ):
            raise ValueError(f"capture {capture_index}: Ethos-U trace is not finalized and valid")
        if len(records) != summary["count"] or summary["sample_hz"] != sample_hz:
            raise ValueError(f"capture {capture_index}: record count or sample rate differs")
        if sum(int(row["sample_count"]) for row in records) != summary["total_samples"]:
            raise ValueError(f"capture {capture_index}: compressed tick count differs")
        count = int(summary["pmu_count"])
        active = summary["pmu_status"] == 1
        if active != (count > 0):
            raise ValueError(f"capture {capture_index}: invalid Ethos-U PMU metadata")
        events = tuple(int(summary[f"pmu_event{i}"]) for i in range(count))
        if event_ids is None:
            event_ids = events
            timestamp_hz = int(summary["timestamp_hz"])
        elif events != event_ids or int(summary["timestamp_hz"]) != timestamp_hz:
            raise ValueError(f"capture {capture_index}: PMU events or timestamp clock changed")
        groups = running_groups(records)
        running_intervals += len(groups)
        # The first and last groups can touch a capture edge. Each retained
        # group needs an idle record before it and a following running start.
        for group_index in range(1, len(groups) - 1):
            group = groups[group_index]
            first, last = group[0], group[-1]
            next_first = groups[group_index + 1][0]
            if first == 0 or last + 1 >= next_first:
                raise ValueError(f"capture {capture_index}: missing idle record around inference")
            start_tick = int(records[first]["tick"])
            last_tick = int(records[last]["tick"])
            next_tick = int(records[next_first]["tick"])
            period = next_tick - start_tick
            if period <= 0 or last_tick >= next_tick:
                raise ValueError(f"capture {capture_index}: invalid inference period")
            period_ticks.append(period)
            window = {
                "capture": item["capture_dir"],
                "inference": group_index,
                "start_tick": start_tick,
                "last_running_tick": last_tick,
                "next_start_tick": next_tick,
                "period_ticks": period,
                "start_qread_bytes": int(records[first]["qread"]),
                "running_samples": len(group),
            }
            windows.append(window)
            per_phase = [[0] * count for _ in range(period)]
            for index in range(first, next_first):
                record = records[index]
                running = int(record["running"])
                phase = int(record["tick"]) - start_tick if running else last_tick - start_tick + 1
                if not 0 <= phase < period:
                    raise ValueError(f"capture {capture_index}: sample outside inference period")
                if running:
                    if int(record["sample_count"]) != 1:
                        raise ValueError(f"capture {capture_index}: compressed running sample")
                    phase_qreads[phase].append(int(record["qread"]))
                if count:
                    previous = records[index - 1]
                    for event_index in range(count):
                        delta = (
                            int(record[f"pmu{event_index}"]) - int(previous[f"pmu{event_index}"])
                        ) & 0xFFFFFFFF
                        per_phase[phase][event_index] += delta
            for phase in range(period):
                phase_running[phase].append(int(phase <= last_tick - start_tick))
                if count:
                    phase_pmu[phase].append(per_phase[phase])
            if count:
                totals = [sum(values[index] for values in per_phase) for index in range(count)]
                pmu_window = {
                    **window,
                    **{f"pmu{i}_cycles": total for i, total in enumerate(totals)},
                }
                for event_index, code in enumerate(events):
                    pmu_window[
                        f"{KNOWN_EVENTS.get(code, (f'pmu{event_index}_event_{code:04x}', ''))[0]}_cycles"
                    ] = totals[event_index]
                active_index = events.index(5) if 5 in events else None
                if active_index is not None:
                    for event_id, key in (
                        (6, "mac_pct_active"),
                        (13, "ib_pct_active"),
                        (41, "axi_pct_active"),
                    ):
                        if event_id in events:
                            pmu_window[key] = (
                                100 * totals[events.index(event_id)] / totals[active_index]
                                if totals[active_index]
                                else ""
                            )
                pmu_windows.append(pmu_window)

    if not windows:
        raise ValueError("no complete Ethos-U inference periods")
    names = [
        KNOWN_EVENTS.get(code, (f"pmu{i}_event_{code:04x}", f"PMU {i} event 0x{code:04X}"))
        for i, code in enumerate(event_ids)
    ]
    phases = []
    pmu_phases = []
    for phase in sorted(phase_running):
        running = phase_running[phase]
        row = {
            "phase_ms": phase * 1000 / sample_hz,
            "inference_count": len(running),
            "running_samples": sum(running),
            "running_percent": 100 * sum(running) / len(running),
            "median_qread_bytes": statistics.median(phase_qreads[phase])
            if phase_qreads[phase]
            else "",
        }
        phases.append(row)
        if event_ids:
            pmu_row = dict(row)
            for index, (key, _) in enumerate(names):
                values = [record[index] for record in phase_pmu[phase]]
                pmu_row[f"{key}_mean_cycles"] = statistics.mean(values)
                pmu_row[f"{key}_ci95_cycles"] = (
                    1.96 * statistics.stdev(values) / math.sqrt(len(values))
                    if len(values) > 1
                    else 0
                )
            pmu_phases.append(pmu_row)
    summary = {
        "captures": len(captures),
        "running_intervals": running_intervals,
        "complete_inferences": len(windows),
        "partial_intervals_excluded": running_intervals - len(windows),
        "sample_hz": sample_hz,
        "timestamp_hz": timestamp_hz,
        "pmu_count": len(event_ids),
        "pmu_events": [
            {"event_id": code, "key": key, "label": label}
            for code, (key, label) in zip(event_ids, names)
        ],
        "median_start_period_ms": statistics.median(period_ticks) * 1000 / sample_hz,
        "start_period_ms_p05": percentile(period_ticks, 5) * 1000 / sample_hz,
        "start_period_ms_p95": percentile(period_ticks, 95) * 1000 / sample_hz,
        "start_qread_bytes": sorted({row["start_qread_bytes"] for row in windows}),
    }
    event_index_by_id = {code: i for i, code in enumerate(event_ids)}
    if 5 in event_index_by_id:
        i = event_index_by_id[5]
        summary["mean_npu_active_ms_per_inference"] = (
            statistics.mean(row[f"pmu{i}_cycles"] for row in pmu_windows) * 1000 / timestamp_hz
        )
    if 6 in event_index_by_id:
        i = event_index_by_id[6]
        summary["mean_mac_active_cycles_per_inference"] = statistics.mean(
            row[f"pmu{i}_cycles"] for row in pmu_windows
        )
    if 5 in event_index_by_id:
        active_total = sum(row[f"pmu{event_index_by_id[5]}_cycles"] for row in pmu_windows)
        if active_total:
            for event_id, field in (
                (6, "mac_pct_active"),
                (13, "ib_pct_active"),
                (41, "axi_pct_active"),
            ):
                if event_id in event_index_by_id:
                    summary[field] = (
                        100
                        * sum(
                            row[f"pmu{event_index_by_id[event_id]}_cycles"] for row in pmu_windows
                        )
                        / active_total
                    )
    return summary, windows, phases, pmu_windows, pmu_phases


def plot_activity(destination, summary, phases):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [row["phase_ms"] for row in phases]
    y = [row["running_percent"] for row in phases]
    fig, axis = plt.subplots(figsize=(11, 3.6))
    axis.plot(x, y, color="#245A91", linewidth=1.8)
    axis.set(
        xlabel="Time from first running sample (ms)", ylabel="Running periods (%)", ylim=(0, 105)
    )
    axis.grid(color="#D7DEE5", linewidth=0.7)
    fig.suptitle(
        f"Ethos-U running share across {summary['complete_inferences']} periods", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(destination / "ethosu_activity_folded.svg")
    fig.savefig(destination / "ethosu_activity_folded.png", dpi=150)
    plt.close(fig)


def plot_pmu(destination, summary, phases):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    events = summary["pmu_events"]
    known_four = [event["event_id"] for event in events] == [5, 6, 13, 41]
    panels = 2 if known_four else len(events)
    fig, axes = plt.subplots(panels, 1, figsize=(11, 3.3 * panels + 1), sharex=True, squeeze=False)
    axes = axes[:, 0]
    x = [row["phase_ms"] for row in phases]
    colors = ("#245A91", "#138A70", "#D07A14", "#9B4089")
    for index, event in enumerate(events):
        axis = axes[index // 2] if known_four else axes[index]
        key = event["key"]
        mean = [row[f"{key}_mean_cycles"] / 1000 for row in phases]
        ci = [row[f"{key}_ci95_cycles"] / 1000 for row in phases]
        color = colors[index]
        axis.plot(x, mean, color=color, linewidth=1.7, label=event["label"])
        axis.fill_between(
            x,
            [max(0, a - b) for a, b in zip(mean, ci)],
            [a + b for a, b in zip(mean, ci)],
            color=color,
            alpha=0.13,
        )
    for axis in axes:
        axis.set_ylabel("Events / sample (k)")
        axis.grid(axis="y", color="#D7DEE5", linewidth=0.7)
        axis.legend(loc="upper right")
    axes[-1].set_xlabel("Time from first running sample (ms)")
    fig.suptitle(
        f"Ethos-U PMU folded over {summary['complete_inferences']} complete periods",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(destination / "ethosu_pmu_folded.svg")
    fig.savefig(destination / "ethosu_pmu_folded.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, help="defaults to run directory")
    args = parser.parse_args()
    root = args.run_dir.resolve()
    destination = (args.output_dir or root).resolve()
    try:
        summary, windows, phases, pmu_windows, pmu_phases = fold(root)
        destination.mkdir(parents=True, exist_ok=True)
        write_csv(destination / "ethosu_inference_windows.csv", windows)
        write_csv(destination / "ethosu_folded.csv", phases)
        (destination / "folded_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        plot_activity(destination, summary, phases)
        if pmu_windows:
            write_csv(destination / "inference_pmu.csv", pmu_windows)
            write_csv(destination / "folded_pmu.csv", pmu_phases)
            plot_pmu(destination, summary, pmu_phases)
        else:
            for name in (
                "inference_pmu.csv",
                "folded_pmu.csv",
                "ethosu_pmu_folded.svg",
                "ethosu_pmu_folded.png",
            ):
                (destination / name).unlink(missing_ok=True)
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"Ethos-U fold failed: {error}\n")


if __name__ == "__main__":
    main()
