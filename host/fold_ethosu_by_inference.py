# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        fold_ethosu_by_inference.py
# Description:  Fold sampled NPU activity and PMU intervals over repeated periods
#
# $Date:        9 October 2026
# $Revision:    V.1.0.4
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Fold Ethos-U running ticks and optional PMU events over complete periods."""

# Architecture: align repeated sampled bursts at phase 0, then summarize each
# phase across periods. This is statistical folding, not a driver invocation log.
#
#   <run>/summary.json + captures.csv
#               |
#               v
#   each capture's ethosu_report/{summary.json,samples.csv}
#               |
#               +-- validate completion, record weights, device and PMU setup
#               +-- running_groups(): find bursts separated by sampled idle
#               +-- keep interior start-to-next-start periods
#               |     -> windows + optional per-period PMU totals
#               +-- move each period's first running tick to phase 0
#               |     -> phase activity, QREAD medians and optional PMU statistics
#               v
#   CSV/JSON results                  SVG/PNG views
#   ethosu_inference_windows.csv      ethosu_activity_folded.*
#   ethosu_folded.csv                 ethosu_pmu_folded.* (optional)
#   folded_summary.json
#   inference_pmu.csv / folded_pmu.csv (optional)
#
# Selection and alignment, separately within each capture:
#
#   idle | burst A | idle | burst B | idle | burst C | idle | burst D
#          exclude         [--- period B ---) [--- period C ---) exclude
#                          ^ phase 0          ^ phase 0
#
# The first and last bursts are conservatively excluded, even when they appear
# complete. The following burst supplies the end of each retained period.
# An "inference" in these outputs means an observed running burst. Back-to-back
# submissions without sampled idle merge into one burst; short bursts can be
# missed completely. This tool does not separate models by stream ID, so callers
# must select a workload whose periods are meaningful to compare.
#
# Three quantities have different meanings:
#   Activity: fraction of eligible periods still running at a given phase.
#   QREAD: median known-stream command position among running observations.
#   PMU: cumulative-counter differences over preceding sampling intervals,
#        including the idle part of a period. These are not per-operator counts.
#
# Idle compression retains only the final snapshot of an idle run. We know its
# represented ticks, but cannot reconstruct when PMU increments occurred inside
# it. Their accumulated delta is placed at the first idle phase; subsequent
# idle-phase zeros are a storage convention, not measurements of zero activity.
#
# fold() performs analysis without plotting dependencies or output writes.
# Plotters consume its results; main() writes artifacts and handles the CLI.
# Memory grows with retained periods, phase lengths and QREAD observations.

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from report_helpers import (
    mean_ci,
    percentile,
    read_aggregate,
    read_ethosu_report,
    running_groups,
    write_csv,
)
from ethosu_pmu_events import DRIVER_VERSION, SUPPORTED_DEVICES, describe_events

# Optional ratios select semantic event names from the shared catalog.
# They do not constrain the arbitrary event combinations accepted by the fold.
RATIOS = (
    ("mac_active", "mac_pct_active"),
    ("mac_stalled_by_ib", "ib_pct_active"),
    ("axi0_rd_tran_req_stalled", "axi_pct_active"),
)


def fold(root, npu_clock_hz=None):
    """Return summary, windows, activity phases, PMU windows and PMU phases.

    Captures are processed independently: debugger pauses and counter resets
    between captures never enter the phase axis or PMU subtraction.
    The optional NPU clock is caller supplied and must stay constant.
    """
    if npu_clock_hz is not None and (not math.isfinite(npu_clock_hz) or npu_clock_hz <= 0):
        raise ValueError("NPU clock frequency must be finite and positive")
    aggregate, captures = read_aggregate(root)
    sample_hz = int(aggregate["sample_hz"])
    event_ids = None
    timestamp_hz = None
    device_type = None
    event_metadata = []
    event_index_by_key = {}
    # Keep individual observations until reduction. Each phase can have a
    # different population because shorter periods end before longer ones.
    windows = []
    pmu_windows = []
    phase_running = defaultdict(list)
    phase_qreads = defaultdict(list)
    phase_pmu = defaultdict(list)
    period_ticks = []
    running_intervals = 0

    for capture_index, item in enumerate(captures):
        directory = root / item["capture_dir"] / "ethosu_report"
        summary, records = read_ethosu_report(directory)
        if summary["sample_hz"] != sample_hz:
            raise ValueError(f"capture {capture_index}: sample rate differs")
        # No-PMU captures still produce activity and QREAD folds. When PMU is
        # present, counter order, symbolic event IDs and device must agree.
        count = int(summary["pmu_count"])
        active = summary["pmu_status"] == 1
        if active != (count > 0):
            raise ValueError(f"capture {capture_index}: invalid Ethos-U PMU metadata")
        events = tuple(int(summary[f"pmu_event{i}"]) for i in range(count))
        device = int(summary["device_type"])
        if device not in SUPPORTED_DEVICES:
            raise ValueError(f"unsupported Ethos-U device type: {device}")
        if device_type is not None and device != device_type:
            raise ValueError("Ethos-U device type changed between captures")
        device_type = device
        event_metadata = describe_events(device, events)
        # Repeated selections keep separate output columns. Use the first
        # matching counter when deriving an optional semantic ratio.
        event_index_by_key = {}
        for i, event in enumerate(event_metadata):
            event_index_by_key.setdefault(event["semantic_key"], i)
        if event_ids is None:
            event_ids = events
            timestamp_hz = int(summary["timestamp_hz"])
        elif events != event_ids or int(summary["timestamp_hz"]) != timestamp_hz:
            raise ValueError(f"capture {capture_index}: PMU events or timestamp clock changed")
        groups = running_groups(records)
        running_intervals += len(groups)
        # At least 3 bursts are needed to retain 1 period. The preceding idle
        # snapshot also supplies the baseline for the first PMU delta.
        # Groups are selected by index, not by a claim that every edge group is
        # actually partial; partial_intervals_excluded counts these exclusions.
        for group_index in range(1, len(groups) - 1):
            group = groups[group_index]
            first, last = group[0], group[-1]
            next_first = groups[group_index + 1][0]
            if first == 0 or last + 1 >= next_first:
                raise ValueError(f"capture {capture_index}: missing idle record around inference")
            # Period = start of this burst to start of the next, including idle.
            # The next running sample is an endpoint, not part of this window.
            start_tick = int(records[first]["tick"])
            last_tick = int(records[last]["tick"])
            next_tick = int(records[next_first]["tick"])
            period = next_tick - start_tick
            if period <= 0 or last_tick >= next_tick:
                raise ValueError(f"capture {capture_index}: invalid inference period")
            period_ticks.append(period)
            window = {
                # Join other aggregate tables by manifest index, never by a
                # directory name or path that changes when the output moves.
                "capture": capture_index,
                "inference": group_index,
                "start_tick": start_tick,
                "last_running_tick": last_tick,
                "next_start_tick": next_tick,
                "period_ticks": period,
                "start_qread_bytes": int(records[first]["qread"])
                if int(records[first]["stream_id"]) and records[first]["qread"] != ""
                else "",
                "running_samples": len(group),
            }
            windows.append(window)
            # Example: running ticks 6,7; compressed idle ends at 9; next start 10.
            #
            #   phase                  0       1       2       3
            #   represented tick       6       7       8       9
            #   activity               1       1       0       0
            #   PMU delta endpoints  5->6    6->7    7->9       0
            #
            # This preserves interval totals, but idle PMU phase placement is
            # approximate. Multiple idle rows, e.g. split runs, share that bin.
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
                    # Unknown streams/invalid QREAD still contribute running time
                    # and PMU intervals, but cannot describe a command position.
                    if int(record["stream_id"]) and record["qread"] != "":
                        phase_qreads[phase].append(int(record["qread"]))
                if count:
                    # Modulo subtraction handles a 32-bit rollover, assuming
                    # fewer than 2^32 events between retained snapshots. Multiple
                    # wraps or external resets cannot be recovered here.
                    previous = records[index - 1]
                    for event_index in range(count):
                        delta = (
                            int(record[f"pmu{event_index}"]) - int(previous[f"pmu{event_index}"])
                        ) & 0xFFFFFFFF
                        per_phase[phase][event_index] += delta
            # Populate activity for every represented phase, including ticks
            # hidden by idle compression. Later phases of shorter periods are
            # absent, not treated as idle observations.
            for phase in range(period):
                phase_running[phase].append(int(phase <= last_tick - start_tick))
                if count:
                    phase_pmu[phase].append(per_phase[phase])
            if count:
                totals = [sum(values[index] for values in per_phase) for index in range(count)]
                # Generic *_cycles columns retain the existing output naming;
                # for arbitrary events their values are event counts, not cycles.
                pmu_window = {
                    **window,
                    **{f"pmu{i}_cycles": total for i, total in enumerate(totals)},
                }
                for event_index, event in enumerate(event_metadata):
                    pmu_window[f"{event['key']}_cycles"] = totals[event_index]
                active_index = event_index_by_key.get("npu_active")
                if active_index is not None:
                    for key, field in RATIOS:
                        if key in event_index_by_key:
                            pmu_window[field] = (
                                100 * totals[event_index_by_key[key]] / totals[active_index]
                                if totals[active_index]
                                else ""
                            )
                pmu_windows.append(pmu_window)

    if not windows:
        raise ValueError("no complete Ethos-U inference periods")
    names = [(event["key"], event["label"]) for event in event_metadata]
    phases = []
    pmu_phases = []
    # Reduce only the periods that reach each phase. QREAD has a narrower
    # population: known streams with valid positions while running.
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
                pmu_row[f"{key}_mean_cycles"], pmu_row[f"{key}_ci95_cycles"] = mean_ci(values)
            pmu_phases.append(pmu_row)
    summary = {
        "captures": len(captures),
        "running_intervals": running_intervals,
        "complete_inferences": len(windows),
        "partial_intervals_excluded": running_intervals - len(windows),
        "sample_hz": sample_hz,
        "timestamp_hz": timestamp_hz,
        "pmu_count": len(event_ids),
        "pmu_events": event_metadata,
        "pmu_catalog_driver_version": DRIVER_VERSION,
        "median_start_period_ms": statistics.median(period_ticks) * 1000 / sample_hz,
        "start_period_ms_p05": percentile(period_ticks, 5) * 1000 / sample_hz,
        "start_period_ms_p95": percentile(period_ticks, 95) * 1000 / sample_hz,
        "start_qread_bytes": sorted(
            {row["start_qread_bytes"] for row in windows if row["start_qread_bytes"] != ""}
        ),
    }
    summary["device_type"] = device_type
    summary["npu_clock_hz"] = npu_clock_hz
    # Timestamp frequency describes the CPU timebase, not the NPU cycle clock.
    # Only an explicitly supplied, constant NPU frequency permits this conversion.
    if "npu_active" in event_index_by_key:
        i = event_index_by_key["npu_active"]
        cycles = statistics.mean(row[f"pmu{i}_cycles"] for row in pmu_windows)
        summary["mean_npu_active_cycles_per_inference"] = cycles
        if npu_clock_hz is not None:
            summary["mean_npu_active_ms_per_inference"] = cycles * 1000 / npu_clock_hz
        active_total = sum(row[f"pmu{i}_cycles"] for row in pmu_windows)
        # Ratio of summed counts weights periods by their active cycles.
        # It intentionally differs from the mean of per-period percentages.
        if active_total:
            for key, field in RATIOS:
                if key in event_index_by_key:
                    index = event_index_by_key[key]
                    summary[field] = (
                        100 * sum(row[f"pmu{index}_cycles"] for row in pmu_windows) / active_total
                    )
    if "mac_active" in event_index_by_key:
        i = event_index_by_key["mac_active"]
        summary["mean_mac_active_cycles_per_inference"] = statistics.mean(
            row[f"pmu{i}_cycles"] for row in pmu_windows
        )
    return summary, windows, phases, pmu_windows, pmu_phases


def plot_activity(destination, summary, phases):
    """Render the share of eligible periods running at each sampled phase."""
    # Agg supports headless hosts; analysis remains usable without Matplotlib.
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
    """Plot event means and approximate confidence bands from the PMU fold."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    events = summary["pmu_events"]
    # Pair the familiar activity/stall series for a compact view. Other event
    # selections get 1 panel per event, without guessing equivalent semantics.
    known_four = [event["key"] for event in events] == [
        "npu_active",
        "mac_active",
        "mac_stalled_by_ib",
        "axi0_rd_tran_req_stalled",
    ]
    panels = 2 if known_four else len(events)
    fig, axes = plt.subplots(panels, 1, figsize=(11, 3.3 * panels + 1), sharex=True, squeeze=False)
    axes = axes[:, 0]
    x = [row["phase_ms"] for row in phases]
    colors = ("#245A91", "#138A70", "#D07A14", "#9B4089")
    for index, event in enumerate(events):
        axis = axes[index // 2] if known_four else axes[index]
        key = event["key"]
        # Divide by 1000 only for the "k events" display scale, not milliseconds.
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
    """Analyze first, then write tables and render the optional PMU charts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, help="defaults to run directory")
    parser.add_argument(
        "--npu-clock-hz",
        type=float,
        help="Constant NPU cycle clock; enables active-time conversion to ms",
    )
    args = parser.parse_args()
    root = args.run_dir.resolve()
    destination = (args.output_dir or root).resolve()
    try:
        # Invalid analysis inputs fail before output is created. Rendering is
        # later, so a plotting failure may still leave useful CSV/JSON artifacts.
        summary, windows, phases, pmu_windows, pmu_phases = fold(root, args.npu_clock_hz)
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
            # Avoid displaying stale PMU plots when reusing an output directory
            # for a capture configuration that no longer collects counters.
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
