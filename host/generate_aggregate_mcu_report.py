# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        generate_aggregate_mcu_report.py
# Description:  Aggregate Cortex-M hotspots, PMU totals and backtrace views
#
# $Date:        9 October 2026
# $Revision:    V.1.0.4
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Merge Cortex-M capture reports and optionally render Brendan Gregg flame graphs."""

# Architecture: presentation after aggregate_profiler_captures.py has checked
# capture configuration and combined the decoded tables. No firmware, ELF or
# raw buffer is read here; symbolization and unwinding decisions are upstream.
#
#   <run>/captures.csv              <run>/summary.json
#          |                              |
#          v                              | expected ELF hash + PC sample total
#   each capture/cortex_m_report/         |
#     summary.json ----------------------+--> completion/identity checks
#     stacks.folded --> recovered chains |
#     samples.csv ----> rejected chains' PCs
#                                        |
#   <run>/cortex_m_functions.csv ---------+--> all-sample hotspots
#                                        |
#                                        v
#   <run>/mcu_report/
#     functions.csv + hotspots.svg + summary.json
#     stacks_recovered.folded --> flamegraph_recovered.svg  (optional)
#     stacks.folded ----------> flamegraph.svg             (optional)
#     function_reconciliation.csv                          (optional)
#
# The 2 stack views answer different questions:
#
#   Recovered view: root;caller;sampled_function  N
#   All-PC view:    recovered chains, plus
#                  [PC only: caller unavailable];sampled_function  M
#
# The synthetic PC-only root preserves samples whose callers cannot be trusted.
# It is a display category, not a real caller. Each sample contributes to exactly
# 1 leaf; inclusive widths of ancestor frames must not be added together.
# Root-filtered samples use a different category, "selected root unavailable";
# absence of the requested root does not itself make their callers unreliable.
#
# Denominators and scope:
#   * Hotspot percentages use all PC samples, not just the displayed top 20.
#   * Recovered flamegraph widths use included stacks; partial chains may remain.
#   * PMU totals cover each capture's initialization-to-stop interval, including
#     unsampled execution. They are not counts attributable to these functions.
# Captures contribute by sample count, not by an average of their percentages.
# Debugger pauses add no samples; this script does not reconstruct a timeline.
#
# Trust and I/O boundaries:
#   Matching summary hashes identify the reported ELF, not deployed firmware.
#   Input reports must remain together and unchanged after aggregation; these
#   checks do not rehash their source buffers or repeat all upstream validation.
#   Counters grow with distinct stacks/functions; captures are read sequentially.
#   All output is staged before replacing the owned mcu_report directory.
#   Validation/rendering failures preserve the previous report. Publication uses
#   2 renames with rollback on errors, not a crash-atomic directory exchange.

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import mkdtemp

from combine_perfetto_captures import capture_rows

# Keep uncertain callers visually separate from recovered application roots.
PC_ONLY = "[PC only: caller unavailable]"
ROOT_MISSING = "[PC only: selected root unavailable]"


def folded_rows(path):
    """Read decoder output: semicolon-separated frames followed by a hit count."""
    for line in path.read_text().splitlines():
        if line:
            # Function names may contain spaces; only the final space separates
            # the count. The decoder already escapes stack delimiters in names.
            stack, count = line.rsplit(" ", 1)
            yield stack, int(count)


def write_folded(path, counts):
    """Write deterministic input for the external FlameGraph renderer."""
    path.write_text("".join(f"{stack} {count}\n" for stack, count in sorted(counts.items())))


def leaf_counts(stacks):
    """Map decoder-specific leaf labels to the hotspot report's function names."""
    result = Counter()
    for stack, count in stacks.items():
        # Count the sampled leaf once, regardless of caller depth or recursion.
        # Address suffixes disambiguate equal names in the graph; reconciliation
        # intentionally collapses them to the function-name totals below.
        name = stack.split(";")[-1]
        if name.startswith("[unknown@"):
            name = "<unknown>"
        name = re.sub(r" \[0x[0-9a-fA-F]{8}\]$", "", name)
        result[name] += count
    return result


def render_flamegraph(flamegraph, folded, output, title, subtitle):
    """Render one SVG, preserving the previous SVG if the subprocess fails."""
    if not flamegraph.is_file():
        raise FileNotFoundError(
            f"Missing {flamegraph}; provide Brendan Gregg's flamegraph.pl with --flamegraph"
        )
    # Argument lists preserve literal titles/paths without shell expansion.
    # Hash-based colors are stable across graphs; counts are samples, not time.
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
    # Stage beside the destination so replace stays on the same filesystem.
    # This protects this SVG only, not the entire report directory.
    temporary = output.with_suffix(".svg.tmp")
    try:
        with temporary.open("w") as stream:
            subprocess.run(command, check=True, stdout=stream)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def hotspots(path, functions, total):
    """Draw a simple PC-hit bar chart; the flame graphs use flamegraph.pl."""
    # The upstream table is sorted by decreasing hits. Scale bar lengths to the
    # hottest function, while labels/tooltips retain the all-sample denominator.
    top = functions[:20]
    width, height = 1100, 80 + len(top) * 28
    # Reserve separate space for names and bars; 28 px rows leave a small gap.
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


def renderer_provenance(flamegraph):
    """Identify the actual script; a tracked Git revision is optional context."""
    flamegraph = flamegraph.resolve()
    digest = hashlib.sha256(flamegraph.read_bytes()).hexdigest()
    revision = None
    try:
        # A script copied into an unrelated checkout must not inherit its HEAD.
        subprocess.run(
            [
                "git",
                "-C",
                str(flamegraph.parent),
                "ls-files",
                "--error-unmatch",
                "--",
                flamegraph.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        revision = subprocess.check_output(
            ["git", "-C", str(flamegraph.parent), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return {"flamegraph_sha256": digest, "flamegraph_revision": revision}


def generate(root, flamegraph=None):
    """Build privately, then replace the owned mcu_report directory on success.

    Capture paths are relative to the manifest, including sibling directories.
    Input captures must remain unchanged during generation. This function owns
    the entire output directory; supplemental files belong outside mcu_report.
    """
    output = root / "mcu_report"
    temporary = Path(mkdtemp(prefix=".mcu-report-", dir=root))
    previous = temporary / "previous"
    retain_backup = False
    try:
        staging = temporary / "report"
        staging.mkdir()
        result = build_report(root, staging, flamegraph)
        if output.exists():
            output.replace(previous)
        try:
            staging.replace(output)
        except BaseException:
            if previous.exists():
                try:
                    previous.replace(output)
                except BaseException as error:
                    # Cleanup must never delete the only remaining good report.
                    # Keep the recovery directory and identify it in the CLI error.
                    retain_backup = True
                    raise OSError(
                        f"Report publication and rollback failed; previous report preserved at {previous.resolve()}"
                    ) from error
            raise
    finally:
        if not retain_backup:
            shutil.rmtree(temporary)
    return result


def build_report(root, output, flamegraph):
    """Validate inputs and write a complete report into a fresh staging directory.

    Backtrace inputs must be present for every capture or none. The external
    Perl renderer is needed for nonempty graphs; no Git checkout is required.
    """
    captures = [root / row["capture_dir"] for row in capture_rows(root)]
    aggregate = json.loads((root / "summary.json").read_text())
    if len(captures) != aggregate["captures"]:
        raise ValueError("Capture manifest length differs from aggregate summary")
    # Keep recovered chains and untrusted-callers' PC samples separate until
    # the inclusion counts agree with the decoder summaries.
    recovered = Counter()
    pc_only = Counter()
    root_missing = Counter()
    sample_totals = Counter()
    unwind = Counter()
    pmu = Counter()
    pmu_statuses = {}
    pmu_metadata = {}
    elfs = set()
    stack_enabled = None
    stack_root = None
    for capture in captures:
        report = capture / "cortex_m_report"
        summary = json.loads((report / "summary.json").read_text())
        header = summary["header"]
        # This report deliberately requires validated captures with no rejected
        # exception frames. Validity here is stricter than simply being stopped.
        if not (
            header["complete"] == header["validation_passed"] == 1
            and header["active"] == header["rejected"] == 0
            and summary["timing_valid"]
        ):
            raise ValueError(f"Invalid Cortex-M capture: {capture}")
        elfs.add(summary["elf_sha256"])
        # Both artifacts are needed. A folded file alone may be stale, and a
        # summary alone cannot supply the actual recovered chains.
        # The decoder always emits this key, using null when unwinding is off.
        has_stacks = summary.get("flamegraph") is not None
        if has_stacks != (report / "stacks.folded").is_file():
            raise ValueError(f"Incomplete backtrace report: {capture}")
        if stack_enabled is None:
            stack_enabled = has_stacks
        elif stack_enabled != has_stacks:
            raise ValueError("Backtrace availability differs between captures")
        # Sum valid per-capture totals, never cumulative snapshots from different
        # captures. Unknown/unavailable/invalid counts stay out of the sum.
        # Counter slots are independent even when they count the same event.
        # Each slot contributes at most 1 observation per capture.
        for index, event in enumerate(summary.get("pmu_events", [])):
            name, status, count = event["event"], event["status"], event["count"]
            key = f"pmu{index}"
            metadata = {"counter": index, "event": name, "event_id": event.get("event_id")}
            if key in pmu_metadata and pmu_metadata[key] != metadata:
                raise ValueError(f"PMU selection differs between captures for {key}")
            pmu_metadata[key] = metadata
            if status == "ok" and (type(count) is not int or count < 0):
                raise ValueError(f"Invalid PMU count for {name}: {count}")
            pmu_statuses.setdefault(key, Counter())[status] += 1
            if status == "ok":
                pmu[key] += count
        if has_stacks:
            graph = summary["flamegraph"]
            if not sample_totals:
                stack_root = graph.get("root")
            elif stack_root != graph.get("root"):
                raise ValueError("Selected stack root differs between captures")
            if graph["total_samples"] != header["count"]:
                raise ValueError(f"Backtrace total differs from capture sample count: {capture}")
            # Preserve exclusion counts so the included-stack denominator remains
            # visible alongside the all-PC view. "Partial" is included, not an
            # extra population to add to total_samples.
            for key in (
                "total_samples",
                "included_samples",
                "excluded_unreliable",
                "excluded_root_missing",
                "partial_samples",
            ):
                sample_totals[key] += graph[key]
            unwind.update(summary["unwind_status_counts"])
            # The decoder emits each folded chain once with its combined count.
            recovered.update(dict(folded_rows(report / "stacks.folded")))
            with (report / "samples.csv").open(newline="") as stream:
                for sample in csv.DictReader(stream):
                    if sample["flamegraph_status"] == "included":
                        continue
                    disposition = sample["flamegraph_status"]
                    if disposition not in ("unreliable", "root_missing"):
                        raise ValueError(
                            f"Unexpected stack disposition: {sample['flamegraph_status']}"
                        )
                    # Retain the sampled function, but never attach an uncertain
                    # chain to real callers to make the graph look more complete.
                    function = sample["function"] or "<unresolved PC>"
                    if ";" in function:
                        raise ValueError(f"Function name cannot be folded: {function}")
                    category = ROOT_MISSING if disposition == "root_missing" else PC_ONLY
                    counts = root_missing if disposition == "root_missing" else pc_only
                    counts[f"{category};{function}"] += 1
    if len(elfs) != 1 or elfs != {aggregate["elf_sha256"]}:
        raise ValueError("Captures were not decoded with one matching firmware image")
    # Reuse upstream PC counts rather than deriving hotspots from the narrower
    # set of recovered stacks. The aggregate sample total is an independent check.
    shutil.copyfile(root / "cortex_m_functions.csv", output / "functions.csv")
    with (output / "functions.csv").open(newline="") as stream:
        functions = [(row["function"], int(row["hits"])) for row in csv.DictReader(stream)]
    total_samples = sum(count for _, count in functions)
    if total_samples != aggregate["cpu_samples"]:
        raise ValueError("Function hits do not match CPU sample count")
    if total_samples:
        hotspots(output / "hotspots.svg", functions, total_samples)
    else:
        (output / "hotspots.svg").unlink(missing_ok=True)
    result = {
        "captures": len(captures),
        "elf_sha256": next(iter(elfs)),
        "cpu_samples": total_samples,
        # A partial sum must not masquerade as a total across all captures.
        "pmu_event_totals": {
            name: pmu[name] if statuses["ok"] == len(captures) else None
            for name, statuses in pmu_statuses.items()
        },
        # Preserve a useful partial sum with explicit coverage even when a full
        # total cannot be reported. A missing observation is never a zero count.
        "pmu_event_details": {
            name: {
                **pmu_metadata[name],
                "valid_count": pmu[name] if statuses["ok"] else None,
                "valid_captures": statuses["ok"],
                "invalid_or_missing_captures": len(captures) - statuses["ok"],
                "status_counts": dict(statuses),
            }
            for name, statuses in pmu_statuses.items()
        },
        "backtraces_available": bool(stack_enabled),
    }
    if not stack_enabled:
        # Publishing a fresh directory also removes earlier backtrace artifacts.
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    # Reconcile populations before combining the two stack views. These checks
    # catch missing/extra rows even if an external renderer would accept them.
    if sum(recovered.values()) != sample_totals["included_samples"]:
        raise ValueError("Recovered stack count does not match decoder inclusion count")
    if sum(pc_only.values()) != sample_totals["excluded_unreliable"]:
        raise ValueError("PC-only count does not match decoder exclusion count")
    if sum(root_missing.values()) != sample_totals["excluded_root_missing"]:
        raise ValueError("Root-missing count does not match decoder exclusion count")

    pc_only.update(root_missing)
    all_pc = recovered + pc_only
    if (
        sum(all_pc.values()) != sample_totals["total_samples"]
        or sum(all_pc.values()) != total_samples
    ):
        raise ValueError("All-PC stacks do not account for all samples")
    if flamegraph is None and all_pc:
        raise ValueError("backtraces are present; pass --flamegraph /path/to/flamegraph.pl")
    all_folded = output / "stacks.folded"
    recovered_folded = output / "stacks_recovered.folded"
    write_folded(all_folded, all_pc)
    write_folded(recovered_folded, recovered)
    provenance = renderer_provenance(flamegraph) if all_pc else {}
    # Empty input is not a meaningful FlameGraph and some renderer versions
    # reject it. Keep empty folded tables, but omit the corresponding SVG.
    if all_pc:
        render_flamegraph(
            flamegraph,
            all_folded,
            output / "flamegraph.svg",
            "Cortex-M flame graph: all PC samples",
            f"{sample_totals['total_samples']:,} samples; PC-only categories omit unavailable callers or roots",
        )
    if recovered:
        render_flamegraph(
            flamegraph,
            recovered_folded,
            output / "flamegraph_recovered.svg",
            "Cortex-M flame graph: recovered stacks",
            f"{sample_totals['included_samples']:,} of {sample_totals['total_samples']:,} samples; partial caller chains",
        )

    # Equal global totals are insufficient: samples assigned to the wrong leaf
    # would still sum correctly. Compare every function's PC count as well.
    # Function addresses remain in functions.csv; this comparison groups names.
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
    result.update(
        {
            "flamegraph_renderer": "Brendan Gregg FlameGraph/flamegraph.pl" if all_pc else None,
            **provenance,
            "stack_root": stack_root,
            "flamegraph": dict(sample_totals),
            "unwind_status_counts": dict(unwind),
            "distinct_recovered_stacks": len(recovered),
            "all_pc_flamegraph_samples": sum(all_pc.values()),
            "pc_only_samples": sum(pc_only.values()),
            "root_missing_samples": sum(root_missing.values()),
            # This is specifically RTX's named idle thread, not generic CPU idle
            # classification for FreeRTOS or application-defined idle routines.
            "pc_only_idle_samples": pc_only_counts["osRtxIdleThread"],
            "functions_reconciled": len(hotspot_counts),
        }
    )
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    """Expose the report builder and turn expected input/tool failures into CLI errors."""
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
