"""Merge Cortex-M capture reports and optionally render Brendan Gregg flame graphs."""

import argparse
import csv
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

PC_ONLY = "[PC only: caller unavailable]"


def folded_rows(path):
    for line in path.read_text().splitlines():
        if line:
            stack, count = line.rsplit(" ", 1)
            yield stack, int(count)


def write_folded(path, counts):
    path.write_text("".join(f"{stack} {count}\n" for stack, count in sorted(counts.items())))


def leaf_counts(stacks):
    """Map decoder-specific leaf labels to the hotspot report's function names."""
    result = Counter()
    for stack, count in stacks.items():
        name = stack.split(";")[-1]
        if name.startswith("[unknown@"):
            name = "<unknown>"
        name = re.sub(r" \[0x[0-9a-fA-F]{8}\]$", "", name)
        result[name] += count
    return result


def render_flamegraph(flamegraph, folded, output, title, subtitle):
    if not flamegraph.is_file():
        raise FileNotFoundError(
            f"Missing {flamegraph}; provide Brendan Gregg's flamegraph.pl with --flamegraph"
        )
    command = [
        "perl",
        str(flamegraph),
        "--width",
        "1600",
        "--height",
        "22",
        "--minwidth",
        "0",
        "--hash",
        "--countname",
        "samples",
        "--title",
        title,
        "--subtitle",
        subtitle,
        str(folded),
    ]
    temporary = output.with_suffix(".svg.tmp")
    try:
        with temporary.open("w") as stream:
            subprocess.run(command, check=True, stdout=stream)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def hotspots(path, functions, total):
    """Draw a simple PC-hit bar chart; the flame graphs use flamegraph.pl."""
    top = functions[:20]
    width, height = 1100, 80 + len(top) * 28
    label_width, bar_width = 340, 640
    maximum = top[0][1]
    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
        ),
        "<style>text{font:13px Arial,sans-serif;fill:#20252b}.title{font:bold 21px Arial,sans-serif}</style>",
        f'<rect width="{width}" height="{height}" fill="white"/>',
        '<text class="title" x="16" y="31">Cortex-M sampled PC hotspots</text>',
    ]
    for index, (name, count) in enumerate(top):
        y = 55 + index * 28
        bar = bar_width * count / maximum
        # Names are already symbolized in the validated capture report. Escape
        # XML metacharacters before embedding C++ template names in SVG text.
        from html import escape

        lines.append(
            f"<g><title>{escape(name)}: {count:,} / {total:,} PC samples "
            f'({count / total:.2%})</title><text x="16" y="{y + 17}">'
            f"{escape(name[:43] + ('…' if len(name) > 43 else ''))}</text>"
            f'<rect x="{label_width}" y="{y}" width="{bar:.1f}" height="22" '
            f'fill="#356b9c"/><text x="{label_width + bar + 8:.1f}" y="{y + 17}">'
            f"{count / total:.2%}</text></g>"
        )
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n")


def generate(root, flamegraph=None):
    output = root / "mcu_report"
    captures_table = root / "captures.csv"
    with captures_table.open(newline="") as stream:
        capture_rows = list(csv.DictReader(stream))
    captures = [root / row["capture_dir"] for row in capture_rows]
    if not captures:
        raise ValueError("No captures in captures.csv")
    output.mkdir(exist_ok=True)
    recovered = Counter()
    pc_only = Counter()
    sample_totals = Counter()
    unwind = Counter()
    pmu = Counter()
    elfs = set()
    stack_enabled = None
    for capture in captures:
        report = capture / "cortex_m_report"
        summary = json.loads((report / "summary.json").read_text())
        header = summary["header"]
        if not (
            header["complete"] == header["validation_passed"] == 1
            and header["active"] == header["rejected"] == 0
            and summary["timing_valid"]
        ):
            raise ValueError(f"Invalid Cortex-M capture: {capture}")
        elfs.add(summary["elf_sha256"])
        has_stacks = (report / "stacks.folded").is_file() and "flamegraph" in summary
        if stack_enabled is None:
            stack_enabled = has_stacks
        elif stack_enabled != has_stacks:
            raise ValueError("Backtrace availability differs between captures")
        pmu.update({event["event"]: event["count"] for event in summary.get("pmu_events", [])})
        if has_stacks:
            graph = summary["flamegraph"]
            for key in (
                "total_samples",
                "included_samples",
                "excluded_unreliable",
                "excluded_root_missing",
                "partial_samples",
            ):
                sample_totals[key] += graph[key]
            unwind.update(summary["unwind_status_counts"])
            recovered.update(dict(folded_rows(report / "stacks.folded")))
            with (report / "samples.csv").open(newline="") as stream:
                for sample in csv.DictReader(stream):
                    if sample["flamegraph_status"] == "included":
                        continue
                    if sample["flamegraph_status"] != "unreliable":
                        raise ValueError(
                            f"Unexpected stack disposition: {sample['flamegraph_status']}"
                        )
                    function = sample["function"] or "<unresolved PC>"
                    if ";" in function:
                        raise ValueError(f"Function name cannot be folded: {function}")
                    pc_only[f"{PC_ONLY};{function}"] += 1
    if len(elfs) != 1 or elfs != {json.loads((root / "summary.json").read_text())["elf_sha256"]}:
        raise ValueError("Captures were not decoded with one matching firmware image")
    shutil.copyfile(root / "cortex_m_functions.csv", output / "functions.csv")
    with (output / "functions.csv").open(newline="") as stream:
        functions = [(row["function"], int(row["hits"])) for row in csv.DictReader(stream)]
    total_samples = sum(count for _, count in functions)
    if total_samples != json.loads((root / "summary.json").read_text())["cpu_samples"]:
        raise ValueError("Function hits do not match CPU sample count")
    if total_samples:
        hotspots(output / "hotspots.svg", functions, total_samples)
    else:
        (output / "hotspots.svg").unlink(missing_ok=True)
    result = {
        "captures": len(captures),
        "elf_sha256": next(iter(elfs)),
        "cpu_samples": total_samples,
        "pmu_event_totals": dict(pmu),
        "backtraces_available": bool(stack_enabled),
    }
    if not stack_enabled:
        for name in (
            "stacks.folded",
            "stacks_recovered.folded",
            "flamegraph.svg",
            "flamegraph_recovered.svg",
            "function_reconciliation.csv",
        ):
            (output / name).unlink(missing_ok=True)
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    if sum(recovered.values()) != sample_totals["included_samples"]:
        raise ValueError("Recovered stack count does not match decoder inclusion count")
    if sum(pc_only.values()) != sample_totals["excluded_unreliable"]:
        raise ValueError("PC-only count does not match decoder exclusion count")

    all_pc = recovered + pc_only
    if sum(all_pc.values()) != sample_totals["total_samples"]:
        raise ValueError("All-PC stacks do not account for all samples")
    if flamegraph is None:
        raise ValueError("backtraces are present; pass --flamegraph /path/to/flamegraph.pl")
    all_folded = output / "stacks.folded"
    recovered_folded = output / "stacks_recovered.folded"
    write_folded(all_folded, all_pc)
    write_folded(recovered_folded, recovered)
    render_flamegraph(
        flamegraph,
        all_folded,
        output / "flamegraph.svg",
        "Cortex-M flame graph: all PC samples",
        f"{sample_totals['total_samples']:,} samples; PC-only frames have no trusted caller",
    )
    render_flamegraph(
        flamegraph,
        recovered_folded,
        output / "flamegraph_recovered.svg",
        "Cortex-M flame graph: recovered stacks",
        f"{sample_totals['included_samples']:,} of {sample_totals['total_samples']:,} samples; partial caller chains",
    )

    hotspot_counts = Counter()
    for name, count in functions:
        hotspot_counts[name] += count
    recovered_counts = leaf_counts(recovered)
    pc_only_counts = leaf_counts(pc_only)
    if hotspot_counts != recovered_counts + pc_only_counts:
        raise ValueError("Flamegraph leaf counts do not match function hotspots")
    with (output / "function_reconciliation.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "function",
                "hotspot_pc_samples",
                "flamegraph_pc_samples",
                "recovered_stack_samples",
                "pc_only_samples",
                "percent_of_all_pc_samples",
            )
        )
        for name, count in sorted(hotspot_counts.items(), key=lambda item: (-item[1], item[0])):
            writer.writerow(
                (
                    name,
                    count,
                    recovered_counts[name] + pc_only_counts[name],
                    recovered_counts[name],
                    pc_only_counts[name],
                    round(100 * count / sample_totals["total_samples"], 2),
                )
            )
    revision = subprocess.check_output(
        ["git", "-C", str(flamegraph.parent), "rev-parse", "HEAD"], text=True
    ).strip()
    result.update(
        {
            "flamegraph_renderer": "Brendan Gregg FlameGraph/flamegraph.pl",
            "flamegraph_revision": revision,
            "flamegraph": dict(sample_totals),
            "unwind_status_counts": dict(unwind),
            "distinct_recovered_stacks": len(recovered),
            "all_pc_flamegraph_samples": sum(all_pc.values()),
            "pc_only_samples": sum(pc_only.values()),
            "pc_only_idle_samples": pc_only_counts["osRtxIdleThread"],
            "functions_reconciled": len(hotspot_counts),
        }
    )
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--flamegraph", type=Path, help="Brendan Gregg FlameGraph/flamegraph.pl")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(generate(args.run_dir, args.flamegraph), indent=2))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Aggregate MCU report failed: {error}\n")


if __name__ == "__main__":
    main()
