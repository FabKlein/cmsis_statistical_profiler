# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Fold Cortex-M PC and PMU samples around Ethos-U running-burst starts."""

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from combine_perfetto_captures import capture_rows
from visualize_profiler_report import event_rates, read_report


def read_ethosu_report(directory):
    summary = json.loads((directory / "summary.json").read_text())
    with (directory / "samples.csv").open(newline="") as source:
        records = list(csv.DictReader(source))
    if (
        summary.get("active") != 0
        or summary.get("complete") != 1
        or not summary.get("validation_passed")
    ):
        raise ValueError(f"{directory}: Ethos-U capture is incomplete or invalid")
    if len(records) != summary["count"]:
        raise ValueError(f"{directory}: record count differs from summary")
    return summary, records


def running_groups(records):
    groups = []
    current = []
    for record in records:
        if int(record["running"]):
            tick = int(record["tick"])
            if current and tick != int(current[-1]["tick"]) + 1:
                raise ValueError("running Ethos-U group has missing sample ticks")
            current.append(record)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def mean_ci(values):
    if not values:
        return "", ""
    mean = statistics.mean(values)
    ci = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0
    return mean, ci


def fold(root, pre_ms=0.0, post_ms=40.0, idle_function="osRtxIdleThread", highlight_function=None):
    aggregate = json.loads((root / "summary.json").read_text())
    captures = capture_rows(root)
    if aggregate.get("captures") != len(captures) or not aggregate.get("all_validation_passed"):
        raise ValueError("aggregate captures are incomplete or unvalidated")
    rate = int(aggregate["sample_hz"])
    pre_ticks = round(pre_ms * rate / 1000)
    post_ticks = round(post_ms * rate / 1000)
    if pre_ticks < 0 or post_ticks < 1:
        raise ValueError("invalid phase window")

    phase_functions = defaultdict(Counter)
    phase_pmu = defaultdict(lambda: defaultdict(list))
    phase_expected = Counter()
    phase_npu_running = Counter()
    inference_rows = []
    excluded_edges = 0
    event_names = None
    period_ticks = []
    matched_cpu_ticks = 0
    highlighted_run_counts = Counter()
    highlighted_two_run_gaps = []

    for capture_index, item in enumerate(captures):
        directory = root / item["capture_dir"]
        cpu_summary, cpu = read_report(directory / "cortex_m_report")
        ethos_summary, ethos = read_ethosu_report(directory / "ethosu_report")
        cpu_header = cpu_summary["header"]
        if (cpu_header["sample_hz"], cpu_header["timestamp_hz"]) != (
            ethos_summary["sample_hz"],
            ethos_summary["timestamp_hz"],
        ) or cpu_header["sample_hz"] != rate:
            raise ValueError(f"capture {capture_index}: CPU/Ethos-U sample clocks differ")
        if (
            cpu_header["start_tick"] != ethos_summary["start_tick"]
            or abs(cpu_header["stop_tick"] - ethos_summary["stop_tick"]) > 1
        ):
            raise ValueError(f"capture {capture_index}: CPU/Ethos-U tick ranges differ")
        if not cpu_summary["timing_valid"] or cpu_header.get("validation_passed") != 1:
            raise ValueError(f"capture {capture_index}: CPU timing or validation failed")
        pmu = cpu_header.get("pmu", {})
        events = cpu_summary.get("pmu_events", [])
        pmu_active = pmu.get("status") == "active" and pmu.get("count", 0) > 0
        if pmu_active:
            if pmu.get("flags", 0) or len(events) != pmu["count"]:
                raise ValueError(f"capture {capture_index}: CPU PMU metadata is invalid")
            if any(event.get("status") != "ok" for event in events):
                raise ValueError(f"capture {capture_index}: CPU PMU event is invalid")
            # Validate decoded interval deltas against raw counter values.
            event_rates(cpu_summary, cpu)
        names = tuple(event["event"] for event in events) if pmu_active else ()
        if event_names is None:
            event_names = names
        elif names != event_names:
            raise ValueError(f"capture {capture_index}: CPU PMU configuration changed")

        cpu_by_tick = {int(row["tick"]): (index, row) for index, row in enumerate(cpu)}
        if len(cpu_by_tick) != len(cpu):
            raise ValueError(f"capture {capture_index}: duplicate CPU tick")
        for record in ethos:
            if not int(record["running"]):
                continue
            pair = cpu_by_tick.get(int(record["tick"]))
            if pair:
                if pair[1]["timestamp"] != record["timestamp"]:
                    raise ValueError(f"capture {capture_index}: CPU/Ethos-U timestamp mismatch")
                matched_cpu_ticks += 1

        groups = running_groups(ethos)
        running_ticks = {int(record["tick"]) for record in ethos if int(record["running"])}
        excluded_edges += min(len(groups), 2)
        # Match the Ethos-U PMU fold: both capture-edge running groups are excluded.
        for group_index in range(1, len(groups) - 1):
            first_tick = int(groups[group_index][0]["tick"])
            next_tick = int(groups[group_index + 1][0]["tick"])
            period = next_tick - first_tick
            if period <= 0:
                raise ValueError(f"capture {capture_index}: non-increasing inference starts")
            period_ticks.append(period)
            if highlight_function:
                runs = []
                run_start = None
                for tick in range(first_tick, next_tick + 1):
                    pair = cpu_by_tick.get(tick)
                    matches = (
                        tick < next_tick and pair and pair[1]["function"] == highlight_function
                    )
                    if matches and run_start is None:
                        run_start = tick
                    elif not matches and run_start is not None:
                        runs.append((run_start, tick))
                        run_start = None
                highlighted_run_counts[len(runs)] += 1
                if len(runs) == 2:
                    highlighted_two_run_gaps.append(runs[1][0] - runs[0][1])
            start = first_tick - pre_ticks
            end = min(first_tick + post_ticks, next_tick)
            if start <= cpu_header["start_tick"] or end > cpu_header["stop_tick"] + 1:
                raise ValueError(f"capture {capture_index}: phase window crosses capture edge")
            observed = idle = 0
            for tick in range(start, end):
                phase = tick - first_tick
                phase_expected[phase] += 1
                phase_npu_running[phase] += tick in running_ticks
                pair = cpu_by_tick.get(tick)
                if pair is None:
                    continue
                index, row = pair
                observed += 1
                function = row["function"]
                idle += function == idle_function
                phase_functions[phase][function] += 1
                if index and int(cpu[index - 1]["tick"]) == tick - 1:
                    for event_index, name in enumerate(event_names):
                        phase_pmu[phase][name].append(int(row[f"pmu{event_index}_interval_delta"]))
            inference_rows.append(
                {
                    "capture": capture_index,
                    "inference": group_index,
                    "start_tick": first_tick,
                    "next_start_tick": next_tick,
                    "period_ticks": period,
                    "cpu_samples_in_window": observed,
                    "idle_samples_in_window": idle,
                }
            )
    if not inference_rows:
        raise ValueError("no complete inference periods")
    phases = []
    function_rows = []
    for phase in sorted(phase_expected):
        functions = phase_functions[phase]
        observed = sum(functions.values())
        row = {
            "phase_ms": phase * 1000 / rate,
            "inferences_eligible": phase_expected[phase],
            "ethosu_running_samples": phase_npu_running[phase],
            "ethosu_running_percent": 100 * phase_npu_running[phase] / phase_expected[phase],
            "cpu_samples": observed,
            "idle_samples": functions[idle_function],
            "idle_percent": 100 * functions[idle_function] / observed if observed else "",
            "non_idle_percent": 100 * (observed - functions[idle_function]) / observed
            if observed
            else "",
        }
        for name in event_names:
            values = phase_pmu[phase][name]
            row[f"{name}_intervals"] = len(values)
            row[f"{name}_mean"], row[f"{name}_ci95"] = mean_ci(values)
        phases.append(row)
        for function, count in sorted(functions.items(), key=lambda item: (-item[1], item[0])):
            function_rows.append(
                {
                    "phase_ms": row["phase_ms"],
                    "function": function,
                    "samples": count,
                    "percent_of_cpu_samples": 100 * count / observed,
                }
            )
    summary = {
        "captures": len(captures),
        "complete_inferences": len(inference_rows),
        "edge_groups_excluded": excluded_edges,
        "matched_running_cpu_ticks": matched_cpu_ticks,
        "sample_hz": rate,
        "pre_ms": pre_ms,
        "post_ms": post_ms,
        "idle_function": idle_function,
        "idle_function_observed": any(row["idle_samples_in_window"] for row in inference_rows),
        "median_period_ms": statistics.median(period_ticks) * 1000 / rate,
        "min_period_ms": min(period_ticks) * 1000 / rate,
        "max_period_ms": max(period_ticks) * 1000 / rate,
        "cpu_pmu_events": event_names,
        "cpu_phase_observations": sum(row["cpu_samples_in_window"] for row in inference_rows),
        "pre_context_may_repeat_samples": pre_ticks > 0,
        "idle_phase_observations": sum(row["idle_samples_in_window"] for row in inference_rows),
        "missing_cpu_phase_samples": sum(phase_expected.values())
        - sum(row["cpu_samples"] for row in phases),
    }
    if highlight_function:
        summary["highlight_function"] = highlight_function
        summary["highlight_sampled_runs_per_period"] = dict(sorted(highlighted_run_counts.items()))
        summary["highlight_two_run_median_gap_ms"] = (
            statistics.median(highlighted_two_run_gaps) * 1000 / rate
            if highlighted_two_run_gaps
            else None
        )
    return summary, inference_rows, phases, function_rows


def write_csv(path, rows):
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(root, summary, phases, function_rows, highlight_function=None, highlight_label=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [row["phase_ms"] for row in phases]
    by_phase = defaultdict(dict)
    totals = Counter()
    for row in function_rows:
        by_phase[row["phase_ms"]][row["function"]] = row["samples"]
        if row["function"] != summary["idle_function"]:
            totals[row["function"]] += row["samples"]
    top = [name for name, _ in totals.most_common(5)]
    labels = [summary["idle_function"], *top, "Other active"]
    series = []
    for name in labels[:-1]:
        series.append(
            [
                100 * by_phase[phase].get(name, 0) / row["cpu_samples"] if row["cpu_samples"] else 0
                for phase, row in zip(x, phases)
            ]
        )
    series.append(
        [
            max(0, 100 - sum(values)) if row["cpu_samples"] else 0
            for values, row in zip(zip(*series), phases)
        ]
    )
    event_names = summary["cpu_pmu_events"]
    rows = 1 + math.ceil(len(event_names) / 2)
    fig, axes = plt.subplots(rows, 2, figsize=(14, 3.5 * rows), sharex=True, squeeze=False)
    mix = axes[0, 0]
    mix.stackplot(x, *series, labels=labels, alpha=0.88)
    mix.set(ylabel="CPU PC samples (%)", ylim=(0, 100), title="Function sampled at each phase")
    if highlight_function:
        # A bracket can show that separated PC segments belong to one inferred
        # operation span. The colored stack remains the actual sampled CPU PC.
        dominant = [
            phase
            for phase, row in zip(x, phases)
            if row["cpu_samples"]
            and by_phase[phase].get(highlight_function, 0) / row["cpu_samples"] >= 0.5
        ]
        if dominant:
            step_ms = 1000 / summary["sample_hz"]
            runs = [[dominant[0]]]
            for phase in dominant[1:]:
                if phase - runs[-1][-1] > step_ms * 1.5:
                    runs.append([])
                runs[-1].append(phase)
            for run in runs:
                mix.plot([run[0], run[-1]], [105, 105], color="#173c64", linewidth=4)
            for left, right in pairwise(runs):
                mix.plot(
                    [left[-1], right[0]], [105, 105], color="#173c64", linewidth=2, linestyle="--"
                )
            mix.text(
                (min(dominant) + max(dominant)) / 2,
                108,
                highlight_label or f"{highlight_function}: interrupted execution",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#173c64",
            )
            mix.set_ylim(0, 114)
    mix.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.01, 0.5))
    axes[0, 1].plot(x, [row["non_idle_percent"] for row in phases], color="#1d6d80")
    axes[0, 1].set(ylabel="Non-idle PC samples (%)", ylim=(0, 100), title="MCU non-idle share")
    colors = ("#245A91", "#D07A14", "#138A70", "#9B4089")
    for axis, name, color in zip(axes.flat[2:], event_names, colors):
        mean = [float(row[f"{name}_mean"] or 0) for row in phases]
        ci = [float(row[f"{name}_ci95"] or 0) for row in phases]
        axis.plot(x, mean, color=color, linewidth=1.6)
        axis.fill_between(
            x,
            [max(0, a - b) for a, b in zip(mean, ci)],
            [a + b for a, b in zip(mean, ci)],
            color=color,
            alpha=0.16,
        )
        axis.set(title=name, ylabel="Events / sample interval")
    for axis in list(axes.flat)[2 + len(event_names) :]:
        axis.set_visible(False)
    for axis in axes.flat:
        axis.axvline(0, color="#333333", linewidth=0.8, linestyle="--")
        axis.grid(axis="y", color="#dde3e8", linewidth=0.7)
        axis.set_axisbelow(True)
    for axis in axes[-1]:
        axis.set_xlabel("Time from first Ethos-U running sample (ms)")
    fig.suptitle(
        f"Cortex-M activity folded over {summary['complete_inferences']} Ethos-U periods "
        f"({summary['sample_hz']} Hz)",
        fontsize=15,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(root / "mcu_folded.svg")
    fig.savefig(root / "mcu_folded.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--pre-ms", type=float, default=0.0)
    parser.add_argument("--post-ms", type=float, default=40.0)
    parser.add_argument("--idle-function", default="osRtxIdleThread")
    parser.add_argument("--highlight-function", help="Show the sampled span of this function")
    parser.add_argument("--highlight-label", help="Caption for the highlighted function span")
    args = parser.parse_args()
    root = args.run_dir.resolve()
    try:
        summary, inferences, phases, functions = fold(
            root, args.pre_ms, args.post_ms, args.idle_function, args.highlight_function
        )
        if args.highlight_label:
            summary["highlight_label"] = args.highlight_label
        write_csv(root / "mcu_inference_windows.csv", inferences)
        write_csv(root / "mcu_folded.csv", phases)
        write_csv(root / "mcu_folded_functions.csv", functions)
        (root / "mcu_folded_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        plot(root, summary, phases, functions, args.highlight_function, args.highlight_label)
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"MCU fold failed: {error}\n")


if __name__ == "__main__":
    main()
