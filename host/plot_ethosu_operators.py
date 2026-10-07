# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Render aligned Ethos-U operator samples as ranked and QREAD-ordered SVGs."""

import argparse
import bisect
import csv
import json
import math
import statistics
from collections import Counter
from html import escape
from itertools import pairwise
from pathlib import Path

COLORS = {
    "Conv2D": "#2563EB",
    "DepthwiseConv2D": "#7C3AED",
    "Concat": "#0F766E",
    "Add": "#D97706",
    "Resize": "#DC2626",
    "MaxPool": "#0891B2",
    "Table": "#64748B",
}


def label(value, limit):
    return value if len(value) <= limit else value[: limit - 1] + "…"


def text_at(x, y, value, *, css="", anchor="start"):
    return f'<text x="{x}" y="{y}" class="{css}" text-anchor="{anchor}">{escape(str(value))}</text>'


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def add_sampled_offsets(rows, alignment, run_dir):
    """Use capture-local ticks, never elapsed time across debugger pauses."""
    aggregate = json.loads((run_dir / "summary.json").read_text())
    folded = json.loads((run_dir / "folded_summary.json").read_text())
    sample_hz = int(aggregate["sample_hz"])
    if (
        sample_hz <= 0
        or folded["sample_hz"] != sample_hz
        or folded["captures"] != aggregate["captures"]
        or not aggregate["all_validation_passed"]
        or aggregate["ethosu_running_ticks"] != alignment["running_samples"]
    ):
        raise ValueError("timing run does not match the validated QREAD alignment")
    window_path = run_dir / "ethosu_inference_windows.csv"
    if not window_path.is_file():
        window_path = run_dir / "inference_pmu.csv"
    windows = read_csv(window_path)
    if len(windows) != folded["complete_inferences"] or not windows:
        raise ValueError("complete inference windows differ from fold summary")
    by_capture = {}
    for window in windows:
        capture = int(window["capture"].removeprefix("capture_"))
        start, last = int(window["start_tick"]), int(window["last_running_tick"])
        if start > last or capture < 0 or capture >= aggregate["captures"]:
            raise ValueError("invalid inference window")
        by_capture.setdefault(capture, []).append((start, last))
    starts_by_capture = {}
    for capture, periods in by_capture.items():
        periods.sort()
        if any(left[1] >= right[0] for left, right in pairwise(periods)):
            raise ValueError(f"capture {capture}: overlapping inference windows")
        starts_by_capture[capture] = [start for start, _ in periods]

    ordered = sorted(rows, key=lambda row: int(row["kick_offset"], 16))
    starts = [int(row["kick_offset"], 16) for row in ordered]
    ends = [int(row["next_kick_offset"], 16) for row in ordered]
    if any(start >= end for start, end in zip(starts, ends)) or any(
        left != right for left, right in zip(ends, starts[1:])
    ):
        raise ValueError("operator QREAD ranges have gaps or overlaps")
    stream_ids = set(map(str, alignment["histogram_stream_ids"]))
    counts = Counter()
    offsets = {row["op"]: [] for row in rows}
    running = 0
    for sample in read_csv(run_dir / "ethosu_samples.csv"):
        if not int(sample["running"]):
            continue
        if sample["stream_id"] not in stream_ids or int(sample["sample_count"]) != 1:
            raise ValueError("running sample has an unexpected stream or weight")
        running += 1
        qread = int(sample["qread"])
        index = bisect.bisect_right(starts, qread) - 1
        if index < 0 or qread >= ends[index]:
            continue
        op = ordered[index]["op"]
        counts[op] += 1
        capture, tick = int(sample["capture"]), int(sample["tick"])
        periods = by_capture.get(capture, [])
        starts_for_capture = starts_by_capture.get(capture, [])
        period_index = bisect.bisect_right(starts_for_capture, tick) - 1
        if period_index >= 0 and tick <= periods[period_index][1]:
            offsets[op].append(tick - periods[period_index][0])
    if running != alignment["running_samples"] or any(
        counts[row["op"]] != row["samples"] for row in rows
    ):
        raise ValueError("raw running QREAD samples differ from operator histogram")
    timing = []
    for row in rows:
        values = offsets[row["op"]]
        row["_sample_interval_ms"] = 1000 / sample_hz
        row["timed_samples"] = len(values)
        row["median_offset_ms"] = statistics.median(values) * 1000 / sample_hz if values else None
        row["p10_offset_ms"] = percentile(values, 10) * 1000 / sample_hz if values else None
        row["p90_offset_ms"] = percentile(values, 90) * 1000 / sample_hz if values else None
        timing.append(
            {
                key: row[key]
                for key in (
                    "op",
                    "kick_offset",
                    "name",
                    "tosa_op",
                    "timed_samples",
                    "median_offset_ms",
                    "p10_offset_ms",
                    "p90_offset_ms",
                )
            }
        )
    return timing


def draw(rows, running_samples, destination, limit=None, mode="ranked", interactive=False):
    if mode not in ("ranked", "qread"):
        raise ValueError(f"Unknown sort mode: {mode}")
    ordered = (
        sorted(rows, key=lambda row: (int(row["kick_offset"], 16), row["op"]))
        if mode == "qread"
        else rows
    )
    selected = ordered[:limit] if limit else ordered
    max_percent = max(row["percent"] for row in rows)
    axis_max = max(2, math.ceil(max_percent / 2) * 2)
    timed = any("median_offset_ms" in row for row in rows)
    sample_interval_ms = rows[0].get("_sample_interval_ms") if timed else None
    width, bar_x, bar_width = (1950 if timed else 1750), 700, 500
    show_controls = limit is None
    shift = 35 if show_controls else 0
    counts = Counter(row["tosa_op"] for row in rows)
    colors = {
        op: COLORS.get(op, f"hsl({(index * 137) % 360} 65% 42%)")
        for index, op in enumerate(sorted(counts))
    }
    legend_rows = math.ceil(len(counts) / 4)
    start_y, row_height = max(224 + shift, 174 + shift + 24 * (legend_rows - 1)), 27
    height = start_y + row_height * len(selected) + 34
    plot_bottom = start_y + row_height * len(selected)

    svg = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
        ),
        (
            "<style>text{font:13px Arial,sans-serif;fill:#26323D}"
            ".title{font:bold 24px Arial,sans-serif}.subtitle{font:14px Arial,sans-serif;fill:#526171}"
            ".header{font:bold 12px Arial,sans-serif;fill:#415466}"
            ".axis{font:12px Arial,sans-serif;fill:#607080}.value{font-weight:bold}"
            "g.row:hover .hitarea{fill:#EAF2FB;fill-opacity:.55}"
            ".sort-button{cursor:pointer}.sort-button rect{fill:#F3F6FA;stroke:#64748B}"
            ".sort-button text{font-weight:bold}.sort-button.active rect{fill:#245A91;stroke:#245A91}"
            ".sort-button.active text{fill:white}</style>"
        ),
        f'<rect width="{width}" height="{height}" fill="white"/>',
        text_at(20, 35, "Ethos-U operator hotspots", css="title"),
        text_at(
            20,
            61,
            f"{len(selected)} of {len(rows)} Vela queue operations; "
            + (
                "use the buttons to sort by sample share or QREAD address"
                if show_controls
                else "ranked by sampled QREAD share"
            )
            + f"; denominator = {running_samples:,} running ticks",
            css="subtitle",
        ),
        text_at(
            20,
            82,
            f"Bar = sampled QREAD share (0–{axis_max}% axis). "
            "Vela est. cycles/MACs are static estimates, not live PMU counts."
            + (
                f" Median +ms uses {sample_interval_ms:g} ms ticks; more samples improve confidence, not tick resolution."
                if sample_interval_ms
                else ""
            ),
            css="subtitle",
        ),
    ]

    if show_controls:
        for key, caption, x, href in (
            ("ranked", "Top sampled", 20, "ethosu_operator_hotspots.svg"),
            ("qread", "QREAD order", 190, "ethosu_operator_hotspots_chronological.svg"),
        ):
            active = " active" if key == mode else ""
            svg.append(
                f'<a xlink:href="{href}"><g id="button_{key}" '
                f'class="sort-button{active}"><title>Sort by '
                f"{('descending sample share' if key == 'ranked' else 'ascending QREAD kick offset')}"
                f'</title><rect x="{x}" y="94" width="160" height="27" rx="5"/>'
                f'<text x="{x + 80}" y="112" text-anchor="middle">{caption}</text>'
                f"</g></a>"
            )
        svg.append(
            f'<text id="sort_indicator" x="390" y="112" class="subtitle">'
            f"{('Sorted by sample share (descending)' if mode == 'ranked' else 'Sorted by kick QREAD (ascending)')}"
            f"</text>"
        )

    for index, (op, count) in enumerate(counts.items()):
        column = index % 4
        line = index // 4
        x, y = 20 + 420 * column, 108 + shift + 24 * line
        svg.append(
            f'<rect x="{x}" y="{y - 12}" width="13" height="13" fill="{colors[op]}" rx="2"/>'
        )
        svg.append(text_at(x + 20, y, f"{op} ({count})"))

    for rank in range(1, len(selected) + 1):
        y = start_y + (rank - 1) * row_height
        if rank % 2:
            svg.append(
                f'<rect x="12" y="{y}" width="{width - 24}" height="{row_height}" fill="#F7F9FC"/>'
            )

    header_y = start_y - 46
    headers = [
        (20, "Row", "start"),
        (68, "Op #", "start"),
        (125, "Kick QREAD", "start"),
        (240, "TOSA type", "start"),
        (420, "Vela output name", "start"),
        (bar_x, "QREAD sample share", "start"),
        (1270, "Share", "end"),
        (1380, "Samples", "end"),
    ]
    if timed:
        headers.append((1515, "Median +ms", "end"))
    headers.extend(
        [
            (1690 if timed else 1510, "Vela est. cycles", "end"),
            (1900 if timed else 1710, "Vela est. MACs", "end"),
        ]
    )
    for x, name, anchor in headers:
        svg.append(text_at(x, header_y, name, css="header", anchor=anchor))
    svg.append(
        f'<line x1="20" y1="{start_y - 34}" x2="{width - 20}" y2="{start_y - 34}" stroke="#B8C3CE"/>'
    )

    for index in range(axis_max // 2 + 1):
        pct = index * 2
        x = bar_x + bar_width * pct / axis_max
        svg.append(
            f'<line x1="{x:.2f}" y1="{start_y - 28}" x2="{x:.2f}" y2="{plot_bottom}" '
            f'stroke="#DEE6EE"/>'
        )
        svg.append(text_at(f"{x:.2f}", start_y - 15, f"{pct}%", css="axis", anchor="middle"))

    for rank, row in enumerate(selected, 1):
        y = start_y + (rank - 1) * row_height
        pct = row["percent"]
        bar = bar_width * pct / axis_max
        color = colors[row["tosa_op"]]
        tooltip = "\n".join(
            (
                f"Stream operator {row['op']}: {row['tosa_op']} / {row['vela_op']} / NPU {row['npu_op']}",
                f"Output: {row['name']}",
                f"Input: {row['ifm_hwc']}; second input: {row['ifm2_hwc'] or 'none'}; output: {row['ofm_hwc']}",
                f"QREAD interval: {row['kick_offset']} to {row['next_kick_offset']}",
                f"Samples: {row['samples']:,} / {running_samples:,} running ticks ({pct:.2f}%)",
                f"Vela static estimate: {row['est_cycles']:,} cycles, {row['macs']:,} MACs; not measured PMU counts",
                f"SRAM accesses: {row['sram_ac']:,}; flash accesses: {row['flash_ac']:,}",
            )
        )
        if timed:
            tooltip += (
                f"\nMedian sampled offset: +{row['median_offset_ms']:.1f} ms "
                f"(10–90%: +{row['p10_offset_ms']:.1f}–{row['p90_offset_ms']:.1f} ms; "
                f"{row['timed_samples']:,} samples from complete periods)"
                if row["timed_samples"]
                else "\nMedian sampled offset: unavailable (no samples in complete periods)"
            )
        svg.append(
            f'<g class="row" data-origin="{rank}" '
            f'data-qread="{int(row["kick_offset"], 16)}" '
            f'data-percent="{pct}" data-op="{row["op"]}">'
        )
        svg.append(f"<title>{escape(tooltip)}</title>")
        svg.append(
            f'<rect class="hitarea" x="12" y="{y}" width="{width - 24}" '
            f'height="{row_height}" fill="transparent"/>'
        )
        svg.append(
            f'<rect x="{bar_x:.2f}" y="{y + 4}" width="{bar:.2f}" height="19" '
            f'fill="{color}" rx="2"/>'
        )
        svg.append(f'<rect x="240" y="{y + 8}" width="10" height="10" fill="{color}" rx="1"/>')
        baseline = y + 18
        svg.append(f'<text class="row-position" x="20" y="{baseline}">{rank}</text>')
        cells = [
            (68, row["op"], "start", ""),
            (125, row["kick_offset"], "start", ""),
            (255, row["tosa_op"], "start", ""),
            (420, label(row["name"], 38), "start", ""),
            (1270, f"{pct:.2f}%", "end", "value"),
            (1380, f"{row['samples']:,}", "end", ""),
        ]
        if timed:
            cells.append(
                (
                    1515,
                    f"+{row['median_offset_ms']:.1f}" if row["timed_samples"] else "—",
                    "end",
                    "",
                )
            )
        cells.extend(
            [
                (1690 if timed else 1510, f"{row['est_cycles']:,}", "end", ""),
                (1900 if timed else 1710, f"{row['macs']:,}", "end", ""),
            ]
        )
        for x, value, anchor, css in cells:
            svg.append(text_at(x, baseline, value, css=css, anchor=anchor))
        svg.append("</g>")

    svg.append(
        text_at(
            20,
            height - 12,
            "QREAD position is approximate operator attribution; register setup and DMA may fall inside a kick interval."
            + (
                " Median +ms is sampled QREAD phase, not an exact operator boundary."
                if timed
                else ""
            ),
            css="subtitle",
        )
    )
    if interactive:
        svg.append("""<script type="text/ecmascript"><![CDATA[
function setSort(mode) {
  const rows = Array.from(document.querySelectorAll("g.row"));
  rows.sort((left, right) => {
    if (mode === "qread") {
      return Number(left.getAttribute("data-qread")) - Number(right.getAttribute("data-qread")) ||
             Number(left.getAttribute("data-op")) - Number(right.getAttribute("data-op"));
    }
    return Number(right.getAttribute("data-percent")) - Number(left.getAttribute("data-percent")) ||
           Number(left.getAttribute("data-op")) - Number(right.getAttribute("data-op"));
  });
  rows.forEach((row, index) => {
    const shift = (index + 1 - Number(row.getAttribute("data-origin"))) * 27;
    row.setAttribute("transform", "translate(0 " + shift + ")");
    row.querySelector(".row-position").textContent = String(index + 1);
  });
  document.getElementById("button_ranked").setAttribute("class", "sort-button" + (mode === "ranked" ? " active" : ""));
  document.getElementById("button_qread").setAttribute("class", "sort-button" + (mode === "qread" ? " active" : ""));
  document.getElementById("sort_indicator").textContent =
    mode === "qread" ? "Sorted by kick QREAD (ascending)" : "Sorted by sample share (descending)";
}
for (const mode of ["ranked", "qread"]) {
  document.getElementById("button_" + mode).addEventListener("click", (event) => {
    event.preventDefault();
    setSort(mode);
  });
}
]]></script>""")
    svg.append("</svg>")
    destination.write_text("\n".join(svg) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path, help="ethosu_operator_samples.csv")
    parser.add_argument(
        "--alignment", required=True, type=Path, help="matching vela_alignment.json"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--timing-run-dir",
        type=Path,
        help="validated run with ethosu_samples.csv, inference_pmu.csv and fold summary",
    )
    parser.add_argument(
        "--top", type=int, default=30, help="rows in the compact chart (default: 30)"
    )
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    alignment = json.loads(args.alignment.read_text())
    if alignment.get("command_stream_exact_match") is not True:
        parser.error("Vela command stream has not been verified against the PTE")
    running = int(alignment["running_samples"])
    if running <= 0:
        parser.error("alignment has no running samples")
    with args.samples.open(newline="") as source:
        raw = list(csv.DictReader(source))
    if not raw:
        parser.error("operator sample table is empty")
    if len(raw) != alignment["debug_queue_operations"]:
        raise SystemExit("Queue operation count changed")
    rows = []
    for source in raw:
        row = dict(source)
        for field in ("op", "samples", "est_cycles", "macs", "sram_ac", "flash_ac"):
            row[field] = int(row[field])
        row["percent"] = float(row["percent_of_running_samples"])
        if abs(row["percent"] - 100 * row["samples"] / running) > 0.006:
            raise SystemExit(f"Percent does not match sample count at op {row['op']}")
        rows.append(row)
    if sum(row["samples"] for row in rows) != alignment["assigned_samples"]:
        raise SystemExit("Assigned sample count changed")
    timing = None
    if args.timing_run_dir:
        try:
            timing = add_sampled_offsets(rows, alignment, args.timing_run_dir)
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.exit(1, f"operator timing failed: {error}\n")
    rows.sort(key=lambda row: (-row["percent"], row["op"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if timing is not None:
        with (args.output_dir / "ethosu_operator_timing.csv").open("w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(timing[0]))
            writer.writeheader()
            writer.writerows(timing)
    draw(rows, running, args.output_dir / "ethosu_operator_hotspots.svg", interactive=True)
    draw(
        rows, running, args.output_dir / "ethosu_operator_hotspots_chronological.svg", mode="qread"
    )
    draw(
        rows,
        running,
        args.output_dir / f"ethosu_operator_hotspots_top{args.top}.svg",
        limit=args.top,
    )
    print(
        f"Rendered {len(rows)} operators; top share {rows[0]['percent']:.2f}%; "
        f"{alignment['assigned_samples']} assigned running samples"
    )


if __name__ == "__main__":
    main()
