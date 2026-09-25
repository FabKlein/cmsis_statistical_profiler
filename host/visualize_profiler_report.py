# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        visualize_profiler_report.py
# Description:  Export decoded samples to offline HTML dashboards and Perfetto traces
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Export a decoded statistical capture to local Perfetto JSON and optional HTML."""

import argparse
from collections import Counter, defaultdict
import csv
import html
import json
import math
from pathlib import Path
import sys


LIMITATIONS = (
    "PC hits estimate exclusive time share, not calls or exact function cycles. "
    "Fixed-period sampling can alias. Points are observations, not execution spans. "
    "LR is not a reconstructed call stack. PMU rates cover the entire preceding "
    "sample interval, including interrupts and gated-off execution; they must not "
    "be attributed to the function sampled at the interval endpoint. "
    "The first PMU interval is omitted because its start epoch differs from the "
    "timestamp epoch. Final unsampled time is not plotted."
)


def read_report(directory):
    summary = json.loads((directory / "summary.json").read_text())
    if summary.get("timing_valid") is not True:
        raise ValueError(f"Invalid decoded timing: {summary.get('timing_diagnostic')}")
    with (directory / "samples.csv").open(newline="") as source:
        reader = csv.DictReader(source)
        required = {"sample", "time_us", "pc", "lr", "function"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"samples.csv must contain {sorted(required)}")
        samples = list(reader)
    if not samples or len(samples) != summary["header"]["count"]:
        raise ValueError("Empty capture or sample count differs from summary.json")
    previous_time = -1.0
    for index, sample in enumerate(samples):
        timestamp = float(sample["time_us"])
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp <= previous_time:
            raise ValueError(f"Invalid or non-increasing timestamp at sample {index}")
        if int(sample["sample"]) != index:
            raise ValueError(f"Missing or out-of-order sample {index}")
        for register in ("pc", "lr"):
            if not 0 <= int(sample[register], 16) <= 0xFFFFFFFF:
                raise ValueError(f"Invalid {register} at sample {index}")
        sample["time_us"] = timestamp
        sample["function"] = sample["function"] or "<unknown>"
        previous_time = timestamp
    return summary, samples


def event_rates(summary, samples):
    warnings = []
    header = summary["header"]
    for field, expected in (("complete", 1), ("active", 0), ("validation_passed", 1),
                            ("full", 0), ("rejected", 0)):
        if header.get(field) != expected:
            warnings.append(f"Capture {field}={header.get(field)} (expected {expected}).")
    if summary.get("unknown_samples"):
        warnings.append(f"Unresolved PCs: {summary['unknown_samples']}.")
    pmu = header.get("pmu", {})
    events = summary.get("pmu_events", [])
    if pmu.get("status") != "active" or pmu.get("flags", 0):
        warnings.append(f"PMU rates unavailable: status={pmu.get('status', 'missing')}, "
                        f"flags={pmu.get('flags', 0)}.")
        return [], warnings
    if len(events) != pmu.get("count") or not events:
        raise ValueError("PMU event metadata does not match header count")
    rates = []
    for index, event in enumerate(events):
        if event.get("status") != "ok":
            warnings.append(f"PMU {event['event']} omitted: {event.get('status')}.")
            continue
        values = []
        for previous, sample in zip(samples, samples[1:]):
            delta = int(sample[f"pmu{index}_interval_delta"])
            raw = int(sample[f"pmu{index}_raw"])
            previous_raw = int(previous[f"pmu{index}_raw"])
            if not 0 <= delta <= 0xFFFFFFFF or any(
                not 0 <= value <= 0xFFFFFFFF for value in (raw, previous_raw)
            ) or delta != (raw - previous_raw) & 0xFFFFFFFF:
                raise ValueError(f"Inconsistent PMU {index} at sample {sample['sample']}")
            elapsed_us = sample["time_us"] - previous["time_us"]
            rate = delta * 1e6 / elapsed_us
            if not math.isfinite(rate):
                raise ValueError("Non-finite PMU rate")
            values.append(rate)
        rates.append({"event": event, "values": values})
    return rates, warnings


def write_perfetto(destination, summary, samples, rates, warnings):
    events = [
        {"ph": "M", "pid": 1, "name": "process_name",
         "args": {"name": "MCU statistical capture"}},
        {"ph": "M", "pid": 1, "tid": 1, "name": "thread_name",
         "args": {"name": "Sampled PC (instant observations)"}},
        {"ph": "I", "s": "t", "pid": 1, "tid": 1, "ts": 0,
         "cat": "profiler.metadata", "name": "Capture information",
         "args": {"limitations": LIMITATIONS, "warnings": " ".join(warnings),
                  "elf_sha256": summary.get("elf_sha256", ""),
                  "capture_sha256": summary.get("capture_sha256", ""),
                  "sample_count": len(samples),
                  "pmu_totals": json.dumps(summary.get("pmu_events", []))}},
    ]
    for index, sample in enumerate(samples):
        events.append({"ph": "I", "s": "t", "pid": 1, "tid": 1,
                       "ts": sample["time_us"], "cat": "pc.sample",
                       "name": sample["function"],
                       "args": {"sample": index, "pc": sample["pc"],
                                "lr": sample["lr"], "tick": sample.get("tick", "")}})
        if index == 0:
            continue
        for series in rates:
            events.append({"ph": "C", "pid": 1, "ts": sample["time_us"],
                           "cat": "pmu.interval_rate",
                           "name": series["event"]["event"] + " (events/s, preceding interval)",
                           "args": {"events_per_second": series["values"][index - 1]}})
    destination.write_text(json.dumps({"traceEvents": events}, separators=(",", ":"),
                                     allow_nan=False) + "\n")


def write_html(destination, summary, samples, rates, warnings):
    import plotly.graph_objects as graph
    from plotly.subplots import make_subplots

    counts = Counter(sample["function"] for sample in samples)
    ranked = counts.most_common()
    top = ranked[:20][::-1]
    bars = graph.Figure(graph.Bar(
        x=[100 * count / len(samples) for name, count in top],
        y=[html.escape(name) for name, count in top], orientation="h",
        customdata=[count for name, count in top],
        hovertemplate="%{y}<br>%{customdata} hits (%{x:.2f}%)<extra></extra>"))
    bars.update_layout(title="Top 20 exclusive PC hotspots (whole capture)",
                       xaxis_title="Share of all samples (%)", height=620,
                       margin=dict(l=360), template="plotly_white")
    timeline = make_subplots(rows=1 + len(rates), cols=1, shared_xaxes=True,
                             vertical_spacing=0.08,
                             subplot_titles=["Sampled function - points, not durations"] + [
                                 series["event"]["event"] + " - preceding interval rate"
                                 for series in rates])
    grouped = defaultdict(list)
    for sample in samples:
        grouped[sample["function"]].append(sample)
    for rank, (name, count) in enumerate(ranked):
        group = grouped[name]
        timeline.add_trace(graph.Scattergl(
            x=[sample["time_us"] / 1e6 for sample in group],
            y=[rank] * len(group), mode="markers", name=html.escape(name),
            marker=dict(size=4),
            customdata=[[sample["sample"], sample["pc"], sample["lr"]] for sample in group],
            hovertemplate=(html.escape(name) + "<br>%{x:.6f} s<br>sample %{customdata[0]}"
                           "<br>PC %{customdata[1]}<br>LR %{customdata[2]}<extra></extra>")),
            row=1, col=1)
    timeline.update_yaxes(title_text="Function rank (table below)", autorange="reversed",
                          row=1, col=1)
    elapsed = [(sample["time_us"] - previous["time_us"]) for previous, sample
               in zip(samples, samples[1:])]
    for row, series in enumerate(rates, 2):
        timeline.add_trace(graph.Scattergl(
            x=[sample["time_us"] / 1e6 for sample in samples[1:]],
            y=series["values"], mode="lines", showlegend=False,
            customdata=elapsed,
            hovertemplate="%{x:.6f} s<br>%{y:,.1f} events/s<br>interval %{customdata:.3f} us<extra></extra>"),
            row=row, col=1)
        timeline.update_yaxes(title_text="Events/s", row=row, col=1)
    timeline.update_xaxes(title_text="Seconds since capture start", row=1 + len(rates), col=1)
    timeline.update_layout(height=420 + 220 * len(rates), template="plotly_white",
                           legend=dict(orientation="h", y=-0.2, maxheight=0.2),
                           margin=dict(b=180), hovermode="closest")
    config = {"responsive": True, "displaylogo": False, "scrollZoom": True}
    plots = bars.to_html(full_html=False, include_plotlyjs=True, config=config)
    plots += timeline.to_html(full_html=False, include_plotlyjs=False, config=config)
    table = "".join(f"<tr><td>{rank}</td><td>{html.escape(name)}</td><td>{count:,}</td>"
                    f"<td>{100 * count / len(samples):.3f}%</td></tr>"
                    for rank, (name, count) in enumerate(ranked))
    notices = "".join(f"<li>{html.escape(message)}</li>" for message in warnings)
    totals = "".join(f"<li>{html.escape(event['event'])}: "
                     f"{html.escape(str(event.get('count')))} ({html.escape(event['status'])})</li>"
                     for event in summary.get("pmu_events", []))
    destination.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="connect-src \'none\'; '
        'object-src \'none\'; base-uri \'none\'">'
        '<title>MCU statistical profile</title><style>'
        'body{font:16px system-ui;margin:2em;background:#fafafa;color:#172332}'
        'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px;'
        'border-bottom:1px solid #ddd}li{margin:8px 0}.warning{color:#9b3900}'
        '</style></head><body><h1>MCU statistical profile</h1>'
        f'<p>{len(samples):,} samples; {len(ranked)} functions; last sample '
        f'{samples[-1]["time_us"] / 1e6:.6f} s after start. '
        f'Output validation: {summary["header"].get("validation_passed", "unknown")}.</p>'
        f'<p>{html.escape(LIMITATIONS)}</p><ul class="warning">{notices}</ul>'
        '<p>Drag to zoom; double-click a plot to reset. Time axes are linked. '
        'Click a function legend to hide it, double-click to isolate it. '
        'Hotspot percentages and the table remain whole-capture statistics.</p>'
        f'{plots}<h2>All functions - exclusive PC hits</h2>'
        '<table><thead><tr><th>Rank</th><th>Function</th><th>Hits</th><th>Share</th>'
        f'</tr></thead><tbody>{table}</tbody></table>'
        '<h2>PMU totals (initialization through stop)</h2>'
        f'<ul>{totals}</ul><p>These totals also include unsampled boundaries.</p>'
        '<h2>Capture identity</h2><pre>'
        f'ELF SHA256: {html.escape(summary.get("elf_sha256", "unknown"))}\n'
        f'Capture SHA256: {html.escape(summary.get("capture_sha256", "unknown"))}'
        '</pre><p>Local, self-contained report; no CDN or upload required.</p></body></html>',
        encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True,
                        help="Directory containing decoded summary.json and samples.csv")
    parser.add_argument("--output", type=Path, help="Output directory (default: report directory)")
    parser.add_argument("--html", action="store_true", help="Also write offline Plotly dashboard")
    args = parser.parse_args()
    try:
        summary, samples = read_report(args.report)
        rates, warnings = event_rates(summary, samples)
        if args.html:
            try:
                import plotly
            except ImportError as error:
                requirements = Path(__file__).with_name("requirements-visualization.txt")
                raise ValueError(f"Install {requirements} for --html") from error
        output = args.output or args.report
        output.mkdir(parents=True, exist_ok=True)
        write_perfetto(output / "samples.perfetto.json", summary, samples, rates, warnings)
        if args.html:
            write_html(output / "dashboard.html", summary, samples, rates, warnings)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"error: {error}\n")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Exported {len(samples):,} PC samples and {len(rates)} PMU rate tracks to {output}")


if __name__ == "__main__":
    main()
