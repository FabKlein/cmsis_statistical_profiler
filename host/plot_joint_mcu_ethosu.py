# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Plot synchronized MCU and Ethos-U inference folds on one phase axis."""

import argparse
import json
import math
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from report_helpers import read_csv, write_csv


def number(row, key):
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key} at phase {row['phase_ms']}")
    return value


def by_phase(rows, label):
    result = {}
    for row in rows:
        phase = number(row, "phase_ms")
        if phase in result:
            raise ValueError(f"duplicate {label} phase {phase}")
        result[phase] = row
    if not result:
        raise ValueError(f"empty {label} fold")
    return result


def combine(root):
    mcu_summary = json.loads((root / "mcu_folded_summary.json").read_text())
    ethos_summary = json.loads((root / "folded_summary.json").read_text())
    for key in ("captures", "complete_inferences", "sample_hz"):
        if mcu_summary[key] != ethos_summary[key]:
            raise ValueError(f"MCU/Ethos-U {key} differs")
    mcu = by_phase(read_csv(root / "mcu_folded.csv"), "MCU")
    activity_path = root / "ethosu_folded.csv"
    ethos = by_phase(
        read_csv(activity_path if activity_path.is_file() else root / "folded_pmu.csv"), "Ethos-U"
    )
    pmu_path = root / "folded_pmu.csv"
    pmu = by_phase(read_csv(pmu_path), "Ethos-U PMU") if pmu_path.is_file() else {}
    events = ethos_summary.get("pmu_events")
    if events is None:
        # Reports made before the generic fold did not record event metadata.
        legacy = ("npu_active", "mac_active", "ib_stall", "axi_read_request_stall")
        events = [{"key": key, "label": key.replace("_", " ")} for key in legacy] if pmu else []
    if bool(pmu) != bool(events):
        raise ValueError("Ethos-U PMU data and event metadata differ")
    if pmu and set(pmu) != set(ethos):
        raise ValueError("Ethos-U activity and PMU phases differ")
    if not set(mcu).issubset(ethos):
        raise ValueError("Ethos-U fold is missing MCU phases")
    rows = []
    for phase in sorted(mcu):
        cpu, npu = mcu[phase], ethos[phase]
        eligible = int(cpu["inferences_eligible"])
        if eligible != int(npu["inference_count"]) or eligible > mcu_summary["complete_inferences"]:
            raise ValueError(f"MCU/Ethos-U coverage differs at {phase} ms")
        observed = int(cpu["cpu_samples"])
        running = int(cpu["ethosu_running_samples"])
        if not (0 <= observed <= eligible and 0 <= running <= eligible):
            raise ValueError(f"invalid sample coverage at {phase} ms")
        row = {
            "phase_ms": phase,
            "inferences_eligible": eligible,
            "mcu_pc_samples": observed,
            "ethosu_running_samples": running,
            "ethosu_running_percent": 100 * running / eligible,
        }
        if "running_samples" in npu and running != int(npu["running_samples"]):
            raise ValueError(f"Ethos-U running coverage differs at {phase} ms")
        if mcu_summary["idle_classification"]:
            row["mcu_non_idle_percent"] = number(cpu, "non_idle_percent") if observed else ""
            if observed and not 0 <= row["mcu_non_idle_percent"] <= 100:
                raise ValueError(f"invalid MCU activity at {phase} ms")
        for event in mcu_summary["cpu_pmu_events"]:
            key = event["key"]
            for suffix in ("intervals", "mean", "ci95"):
                field = f"{key}_{suffix}"
                row[f"mcu_{field}"] = number(cpu, field) if cpu[field] != "" else ""
        for event in events:
            name = event["key"]
            row[f"ethosu_{name}_mean_cycles"] = number(pmu[phase], f"{name}_mean_cycles")
            row[f"ethosu_{name}_ci95_cycles"] = number(pmu[phase], f"{name}_ci95_cycles")
        rows.append(row)
    return {**mcu_summary, "ethosu_pmu_events": events}, rows, len(ethos) - len(mcu)


def plot(root, summary, rows, omitted_ethos_phases):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    x = [row["phase_ms"] for row in rows]
    functions = read_csv(root / "mcu_folded_functions.csv")
    by_phase = defaultdict(dict)
    totals = Counter()
    for record in functions:
        phase = number(record, "phase_ms")
        name = record["function"]
        count = int(record["samples"])
        if phase not in x or name in by_phase[phase] or count < 0:
            raise ValueError(f"invalid MCU function samples at {phase} ms")
        by_phase[phase][name] = count
        totals[name] += count
    for row in rows:
        if sum(by_phase[row["phase_ms"]].values()) != row["mcu_pc_samples"]:
            raise ValueError(f"MCU function samples differ at {row['phase_ms']} ms")

    cpu_events = summary.get("cpu_pmu_events", [])
    npu_events = summary.get("ethosu_pmu_events", [])
    npu_panels = math.ceil(len(npu_events) / 2)
    interval_ms = 1000 / summary["sample_hz"]
    fig, axes = plt.subplots(
        3 + len(cpu_events) + npu_panels,
        1,
        figsize=(15, 9 + 2.2 * (len(cpu_events) + npu_panels)),
        sharex=True,
    )
    fig.subplots_adjust(left=0.095, right=0.79, top=0.948, bottom=0.064, hspace=0.58)
    mix = axes[0]
    top = [name for name, _ in totals.most_common(5)]
    labels = [*top, "Other functions"]
    series = [
        [
            100 * by_phase[phase].get(name, 0) / row["mcu_pc_samples"]
            if row["mcu_pc_samples"]
            else 0
            for phase, row in zip(x, rows)
        ]
        for name in labels[:-1]
    ]
    series.append(
        [
            max(0, 100 - sum(values)) if row["mcu_pc_samples"] else 0
            for values, row in zip(zip(*series), rows)
        ]
    )
    mix.stackplot(x, *series, labels=labels, alpha=0.88)
    mix.set(
        ylabel="PC samples (%)", ylim=(0, 100), title="Cortex-M · function sampled at each phase"
    )
    mix.legend(fontsize=8, loc="center left", bbox_to_anchor=(1.01, 0.5))
    highlight = summary.get("highlight_function")
    if highlight:
        dominant = [
            phase
            for phase, row in zip(x, rows)
            if row["mcu_pc_samples"]
            and by_phase[phase].get(highlight, 0) / row["mcu_pc_samples"] >= 0.5
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
                    [left[-1], right[0]],
                    [105, 105],
                    color="#173c64",
                    linewidth=2,
                    linestyle="--",
                )
            mix.text(
                (min(dominant) + max(dominant)) / 2,
                108,
                summary.get("highlight_label") or f"{highlight}: interrupted sampled span",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#173c64",
            )
            mix.set_ylim(0, 114)

    if summary["idle_classification"]:
        axes[1].plot(
            x,
            [
                float(row["mcu_non_idle_percent"])
                if row["mcu_non_idle_percent"] != ""
                else float("nan")
                for row in rows
            ],
            color="#1d6d80",
        )
        axes[1].set(
            ylabel="PC samples (%)", ylim=(0, 100), title="Cortex-M · non-idle share (estimate)"
        )
    else:
        axes[1].set_visible(False)

    cpu_colors = ("#245A91", "#D07A14", "#138A70", "#9B4089")
    for index, (axis, event) in enumerate(zip(axes[2 : 2 + len(cpu_events)], cpu_events)):
        name = event["key"]
        color = cpu_colors[index % len(cpu_colors)]
        mean = [
            float(row[f"mcu_{name}_mean"]) if row[f"mcu_{name}_mean"] != "" else float("nan")
            for row in rows
        ]
        ci = [
            float(row[f"mcu_{name}_ci95"]) if row[f"mcu_{name}_ci95"] != "" else float("nan")
            for row in rows
        ]
        axis.plot(x, mean, color=color, linewidth=1.6)
        axis.fill_between(
            x,
            [max(0, a - b) for a, b in zip(mean, ci)],
            [a + b for a, b in zip(mean, ci)],
            color=color,
            alpha=0.16,
        )
        axis.set(title=f"Cortex-M · {event['label']}", ylabel=f"Events / {interval_ms:g} ms")

    npu_activity = axes[2 + len(cpu_events)]
    npu_activity.plot(x, [row["ethosu_running_percent"] for row in rows], color="#7C3AED")
    npu_activity.set(ylabel="Periods (%)", ylim=(0, 105), title="Ethos-U · running share")
    npu_colors = ("#245A91", "#138A70", "#D07A14", "#9B4089")
    for index, event in enumerate(npu_events):
        name, label = event["key"], event["label"]
        color = npu_colors[index % len(npu_colors)]
        axis = axes[3 + len(cpu_events) + index // 2]
        mean = [row[f"ethosu_{name}_mean_cycles"] / 1000 for row in rows]
        ci = [row[f"ethosu_{name}_ci95_cycles"] / 1000 for row in rows]
        axis.plot(x, mean, color=color, linewidth=1.7, label=label)
        axis.fill_between(
            x,
            [max(0, a - b) for a, b in zip(mean, ci)],
            [a + b for a, b in zip(mean, ci)],
            color=color,
            alpha=0.13,
        )
    for index, axis in enumerate(axes[3 + len(cpu_events) :]):
        axis.set(
            title=f"Ethos-U · PMU events {2 * index + 1}–{min(2 * index + 2, len(npu_events))}",
            ylabel=f"Events / {interval_ms:g} ms (k)",
        )
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 0.9), fontsize=8)
    for axis in axes:
        axis.set_xlim(min(0, min(x)), max(max(x) + interval_ms, summary.get("post_ms", 0)))
        axis.tick_params(axis="x", labelbottom=True, labelsize=8)
        axis.grid(axis="both", color="#dde3e8", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.axvline(0, color="#333333", linewidth=0.8, linestyle="--")
    axes[-1].set_xlabel("Time from first Ethos-U running sample (ms)")
    axes[-1].xaxis.set_major_locator(MaxNLocator(nbins=9, steps=(1, 2, 2.5, 5, 10)))
    fig.suptitle(
        f"Cortex-M and Ethos-U folded over {summary['complete_inferences']} periods "
        f"({summary['sample_hz']} Hz; {summary['captures']} captures)",
        fontsize=15,
        fontweight="bold",
    )
    note = "Aligned phase; Cortex-M PC distribution and Ethos-U running share. PMU shading shows 95% CI when counters exist."
    if omitted_ethos_phases:
        note += f" {omitted_ethos_phases} trailing Ethos-U phase(s) have no MCU counterpart."
    fig.text(0.095, 0.025, note, ha="left", fontsize=8)
    fig.savefig(root / "joint_folded.svg")
    fig.savefig(root / "joint_folded.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    try:
        summary, rows, omitted = combine(root)
        write_csv(root / "joint_folded.csv", rows)
        plot(root, summary, rows, omitted)
        print(f"Wrote {len(rows)} aligned phases from {summary['complete_inferences']} periods")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"Joint fold failed: {error}\n")


if __name__ == "__main__":
    main()
