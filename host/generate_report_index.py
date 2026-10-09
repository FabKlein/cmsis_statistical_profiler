# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        generate_report_index.py
# Description:  Offline report navigation and combined Perfetto trace launcher
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Build an offline HTML index of available statistical profiling artifacts."""

import argparse
import csv
import html
import json
from pathlib import Path
from urllib.parse import quote

GROUPS = (
    (
        "overview",
        "Capture and provenance",
        (
            ("REPORT.md", "Human report"),
            ("summary.json", "Aggregate metadata"),
            ("captures.csv", "Capture validation table"),
            ("manifest.json", "Input and tool provenance"),
            ("platform.json", "Platform and idle classification metadata"),
            ("firmware.axf", "Exact firmware image"),
        ),
    ),
    (
        "mcu",
        "Cortex-M analysis",
        (
            ("mcu_report/REPORT.md", "MCU report"),
            ("combined.perfetto.json", "Combined Cortex-M and Ethos-U Perfetto timeline"),
            ("cortex_m_combined.perfetto.json", "Combined Cortex-M Perfetto timeline"),
            ("mcu_folded.svg", "MCU activity folded by inference"),
            ("mcu_folded.png", "MCU folded chart image"),
            ("mcu_folded.csv", "MCU phase samples and PMU"),
            ("mcu_folded_functions.csv", "MCU functions by inference phase"),
            ("mcu_inference_windows.csv", "MCU inference windows"),
            ("mcu_folded_summary.json", "MCU fold metadata"),
            ("mcu_report/hotspots.svg", "PC hotspot chart"),
            ("mcu_report/flamegraph.svg", "All-PC flamegraph"),
            ("mcu_report/flamegraph_recovered.svg", "Recovered-stack flamegraph"),
            ("mcu_report/instruction_hotspots.txt", "Instruction and source hotspots"),
            ("mcu_report/instruction_annotation.txt", "Per-instruction annotation"),
            ("mcu_report/functions.csv", "Function samples"),
            ("mcu_report/function_reconciliation.csv", "Hotspot and flamegraph reconciliation"),
            ("mcu_report/stacks.folded", "Folded stacks"),
            ("mcu_report/stacks_recovered.folded", "Recovered folded stacks"),
            ("mcu_report/summary.json", "MCU analysis metadata"),
            ("cortex_m_functions.csv", "Combined function samples"),
            ("cortex_m_samples.csv", "Combined PC samples"),
        ),
    ),
    (
        "ethosu",
        "Ethos-U analysis",
        (
            ("ethosu_operator_hotspots.svg", "Operator hotspots, interactive"),
            ("ethosu_operator_hotspots_chronological.svg", "Operators in QREAD order"),
            ("ethosu_operator_samples.csv", "Operator sample table"),
            ("ethosu_operator_timing.csv", "Operator median phase after inference start"),
            ("ethosu_command_stream.txt", "Unwrapped register command stream"),
            ("ethosu_qread_histogram.csv", "QREAD histogram"),
            ("ethosu_tosa_op_summary.csv", "TOSA operation summary"),
            ("ethosu_unmatched_qread.csv", "Unmatched QREAD positions"),
            ("vela_alignment.json", "PTE and Vela alignment"),
            ("ethosu_samples.csv", "Combined NPU samples"),
        ),
    ),
    (
        "pmu",
        "PMU and inference timing",
        (
            ("joint_folded.svg", "Combined MCU and Ethos-U folded profile"),
            ("joint_folded.png", "Combined folded profile image"),
            ("joint_folded.csv", "Combined folded phase table"),
            ("ethosu_pmu_timeline.svg", "Ethos-U PMU timeline"),
            ("ethosu_pmu_timeline.png", "Ethos-U PMU timeline image"),
            ("ethosu_pmu_zoom.svg", "Ethos-U PMU zoom"),
            ("ethosu_pmu_zoom.png", "Ethos-U PMU zoom image"),
            ("ethosu_pmu_folded.svg", "Folded Ethos-U PMU chart"),
            ("ethosu_pmu_folded.png", "Folded Ethos-U PMU image"),
            ("ethosu_activity_folded.svg", "Folded Ethos-U running activity"),
            ("ethosu_activity_folded.png", "Folded Ethos-U activity image"),
            ("ethosu_folded.csv", "Folded Ethos-U activity samples"),
            ("ethosu_inference_windows.csv", "Complete Ethos-U inference windows"),
            ("folded_pmu.csv", "Folded PMU samples"),
            ("inference_pmu.csv", "Per-inference PMU samples"),
            ("folded_summary.json", "Inference timing summary"),
        ),
    ),
)


def escape(value):
    return html.escape(str(value), quote=True)


def href(path):
    return escape(quote(path.as_posix(), safe="/"))


def link(path, label):
    return f'<a href="{href(path)}">{escape(label)}</a>'


def read_capture_rows(root):
    path = root / "captures.csv"
    if not path.is_file():
        return []
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def read_platform(root):
    path = root / "platform.json"
    if not path.is_file():
        return {}
    platform = json.loads(path.read_text())
    if not isinstance(platform, dict) or platform.get("schema_version") != 1:
        raise ValueError("platform.json requires schema_version 1 and a JSON object")
    for key in ("soc", "clock_basis"):
        if key in platform and (not isinstance(platform[key], str) or not platform[key].strip()):
            raise ValueError(f"platform.json {key} must be nonempty text")
    for component in ("cpu", "ethosu"):
        data = platform.get(component, {})
        if not isinstance(data, dict):
            raise TypeError(f"platform.json {component} must be an object")
        for key in ("name", "role"):
            if key in data and (not isinstance(data[key], str) or not data[key].strip()):
                raise ValueError(f"platform.json {component}.{key} must be nonempty text")
        frequency = data.get("frequency_hz")
        if frequency is not None and (type(frequency) is not int or frequency <= 0):
            raise ValueError(f"platform.json {component}.frequency_hz must be a positive integer")
    cpu = platform.get("cpu", {})
    idle_functions = cpu.get("idle_functions", [])
    if not isinstance(idle_functions, list) or any(
        not isinstance(name, str) or not name.strip() for name in idle_functions
    ):
        raise ValueError("platform.json cpu.idle_functions must be a list of names")
    ranges = cpu.get("idle_pc_ranges", [])
    if not isinstance(ranges, list):
        raise TypeError("platform.json cpu.idle_pc_ranges must be a list")
    for item in ranges:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise ValueError("idle PC ranges require start and exclusive end")
        start, end = parse_address(item["start"]), parse_address(item["end"])
        if start < 0 or end <= start:
            raise ValueError("idle PC ranges require 0 <= start < end")
    return platform


def parse_address(value):
    if type(value) is int:
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError("PC range addresses must be integers or numeric strings")


def sampled_cpu_non_idle(root, summary, platform):
    cpu = platform.get("cpu", {})
    idle_functions = set(cpu.get("idle_functions", []))
    idle_ranges = [
        (parse_address(item["start"]), parse_address(item["end"]))
        for item in cpu.get("idle_pc_ranges", [])
    ]
    if not idle_functions and not idle_ranges:
        return None
    path = root / "cortex_m_samples.csv"
    if not path.is_file():
        path = root / "samples.csv"
    if not path.is_file():
        return None
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source))
    expected = summary.get("cpu_samples", summary.get("header", {}).get("count"))
    if expected is not None and len(rows) != expected:
        raise ValueError("CPU sample count differs from summary.json")
    if not rows:
        return None
    idle = 0
    for row in rows:
        pc = parse_address(row["pc"]) if idle_ranges else None
        if row.get("function") in idle_functions or any(
            start <= pc < end for start, end in idle_ranges
        ):
            idle += 1
    return 100 * (len(rows) - idle) / len(rows)


def format_frequency(hz):
    return f"{hz / 1_000_000:g} MHz" if hz >= 1_000_000 else f"{hz:g} Hz"


def metadata(root, summary, captures, board, application):
    header = summary.get("header", {})
    count = summary.get("captures", len(captures) or 1)
    if captures and count != len(captures):
        raise ValueError("capture count differs between summary.json and captures.csv")
    if captures and "cpu_samples" in summary:
        total = sum(int(row["cpu_samples"]) for row in captures)
        if total != summary["cpu_samples"]:
            raise ValueError("CPU sample count differs between summary.json and captures.csv")
    platform = read_platform(root)
    cpu = platform.get("cpu", {})
    ethosu = platform.get("ethosu", {})
    non_idle = sampled_cpu_non_idle(root, summary, platform)
    facts = [
        ("Application", application),
        ("Board / target", board),
    ]
    if platform.get("soc"):
        facts.append(("SoC", platform["soc"]))
    if cpu.get("name"):
        role = f" ({cpu['role']})" if cpu.get("role") else ""
        facts.append(("Cortex-M core", cpu["name"] + role))
    if cpu.get("frequency_hz"):
        facts.append(("Cortex-M clock (nominal)", format_frequency(cpu["frequency_hz"])))
    if ethosu.get("name"):
        facts.append(("Ethos-U", ethosu["name"]))
    if ethosu.get("frequency_hz"):
        facts.append(("Ethos-U clock (nominal)", format_frequency(ethosu["frequency_hz"])))
    facts.extend(
        [
            ("Sampling rate", f"{summary.get('sample_hz', header.get('sample_hz', 'Unknown'))} Hz"),
            ("Captures", count),
            ("Cortex-M samples", summary.get("cpu_samples", header.get("count", "Not recorded"))),
        ]
    )
    if non_idle is not None:
        facts.append(("Cortex-M non-idle PC share", f"{non_idle:.2f}%"))
    facts.extend(
        [
            ("Ethos-U ticks", summary.get("ethosu_ticks", "Not recorded")),
            (
                "Ethos-U running",
                f"{summary['ethosu_running_percent']:.2f}%"
                if "ethosu_running_percent" in summary
                else "Not recorded",
            ),
            (
                "CPU PMU counters",
                summary.get("cpu_pmu_count", header.get("pmu", {}).get("count", "Not recorded")),
            ),
            ("Ethos-U PMU counters", summary.get("ethosu_pmu_count", "Not recorded")),
            (
                "Validated",
                summary.get(
                    "all_validation_passed", header.get("validation_passed", "Not recorded")
                ),
            ),
            ("ELF SHA-256", summary.get("elf_sha256", "Not recorded")),
        ]
    )
    return tuple(facts)


def combined_trace(root):
    """Prefer the CPU/NPU trace when both exports exist."""
    for name in ("combined.perfetto.json", "cortex_m_combined.perfetto.json"):
        if (root / name).is_file():
            return name
    return None


def artifact_section(root, identifier, title, entries):
    found = [(relative, label) for relative, label in entries if (root / relative).is_file()]
    if combined_trace(root) == "combined.perfetto.json":
        found = [
            (relative, label)
            for relative, label in found
            if relative != "cortex_m_combined.perfetto.json"
        ]
    if identifier == "ethosu":
        found.extend(
            (path.relative_to(root).as_posix(), "Operator hotspots, compact")
            for path in sorted(root.glob("ethosu_operator_hotspots_top*.svg"))
            if path.is_file()
        )
    if not found:
        return ""
    items = "".join(
        f"<li>{link(Path(relative), label)}<small>{escape(relative)}</small></li>"
        for relative, label in found
    )
    if identifier == "mcu" and combined_trace(root):
        items += (
            '<li><a id="open-perfetto" href="https://ui.perfetto.dev">'
            "Open combined trace in Perfetto ↗</a>"
            '<small id="perfetto-status">Loads the local trace when served on localhost. See REPORT.md for the command.</small></li>'
        )
    return f'<section id="{identifier}"><h2>{escape(title)}</h2><ul class="artifacts">{items}</ul></section>'


PERFETTO_SCRIPT = """<script>
(() => {
  const link = document.getElementById('open-perfetto');
  if (!link) return;
  const status = document.getElementById('perfetto-status');
  const origin = 'https://ui.perfetto.dev';
  link.addEventListener('click', async (event) => {
    event.preventDefault();
    if (location.protocol !== 'http:' && location.protocol !== 'https:') {
      status.textContent = 'Open this report through the localhost report server to load its trace automatically. See REPORT.md for the command.';
      return;
    }
    // Open synchronously in the click handler so popup blockers allow the tab.
    const target = window.open(origin, '_blank');
    if (!target) {
      status.textContent = 'Allow popups for this report, then try again.';
      return;
    }
    status.textContent = 'Loading the trace and waiting for Perfetto…';
    const ready = new Promise((resolve, reject) => {
      let ping;
      const timeout = setTimeout(() => {
        clearInterval(ping);
        window.removeEventListener('message', onMessage);
        reject(new Error('Perfetto did not respond within 60 seconds.'));
      }, 60000);
      function onMessage(message) {
        if (message.source !== target || message.origin !== origin || message.data !== 'PONG') return;
        clearInterval(ping);
        clearTimeout(timeout);
        window.removeEventListener('message', onMessage);
        resolve();
      }
      window.addEventListener('message', onMessage);
      ping = setInterval(() => target.postMessage('PING', origin), 200);
      target.postMessage('PING', origin);
    });
    try {
      const [response] = await Promise.all([
        fetch('cortex_m_combined.perfetto.json'), ready,
      ]);
      if (!response.ok) throw new Error(`Trace fetch failed: HTTP ${response.status}`);
      const buffer = await response.arrayBuffer();
      target.postMessage({perfetto: {
        buffer,
        title: document.title + ' · combined profiler trace',
        fileName: 'cortex_m_combined.perfetto.json',
        shareable: false,
        downloadable: true,
      }}, origin, [buffer]);
      status.textContent = 'Combined trace sent to Perfetto.';
    } catch (error) {
      status.textContent = `Could not open trace: ${error.message}`;
    }
  });
})();
</script>"""


def render(root, summary, captures, board, application):
    facts = metadata(root, summary, captures, board, application)
    platform = read_platform(root)
    cpu_activity_note = (
        "Cortex-M non-idle is the share of sampled PCs outside the idle functions or PC ranges "
        "listed in platform.json. It estimates where the CPU was interrupted, not cycle utilization."
        if sampled_cpu_non_idle(root, summary, platform) is not None
        else ""
    )
    clock_note = platform.get("clock_basis", "")
    detail_note = "".join(
        f'<p class="detail-note">{escape(note)}</p>'
        for note in (cpu_activity_note, clock_note)
        if note
    )
    cards = "".join(
        f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
        for label, value in facts
    )
    sections = [
        artifact_section(root, identifier, title, entries) for identifier, title, entries in GROUPS
    ]
    # Single-capture packages from create_profiler_report.py place these here.
    single = (
        ("dashboard.html", "Interactive MCU dashboard"),
        ("samples.perfetto.json", "Perfetto timeline"),
        ("hotspots.svg", "PC hotspots"),
        ("flamegraph.svg", "Flamegraph"),
        ("stacks.folded", "Folded stacks"),
        ("functions.csv", "Function samples"),
        ("samples.csv", "PC samples"),
    )
    sections.append(artifact_section(root, "single", "Single-capture views", single))
    navigation = "".join(
        f'<a href="#{identifier}">{escape(title)}</a>'
        for identifier, title, _ in GROUPS
        if f'id="{identifier}"' in "".join(sections)
    )
    if 'id="single"' in "".join(sections):
        navigation += '<a href="#single">Single-capture views</a>'
    preview = []
    for relative, caption in (
        ("joint_folded.svg", "Combined Cortex-M and Ethos-U activity by inference"),
        ("mcu_report/hotspots.svg", "Cortex-M PC hotspots"),
        ("mcu_folded.svg", "Cortex-M activity folded by inference"),
        ("ethosu_pmu_folded.svg", "Ethos-U PMU folded by inference"),
        ("ethosu_activity_folded.svg", "Ethos-U running activity folded by inference"),
    ):
        if (root / relative).is_file():
            preview.append(
                f"<figure><figcaption>{escape(caption)} · {link(Path(relative), 'open full size')}</figcaption>"
                f'<object type="image/svg+xml" data="{href(Path(relative))}">'
                f"{link(Path(relative), caption)}</object></figure>"
            )
    operator_full = Path("ethosu_operator_hotspots.svg")
    operator_compact = Path("ethosu_operator_hotspots_top30.svg")
    if (root / operator_full).is_file() or (root / operator_compact).is_file():
        snapshot = operator_compact if (root / operator_compact).is_file() else operator_full
        target = operator_full if (root / operator_full).is_file() else snapshot
        preview.insert(
            1 if preview else 0,
            '<figure class="operator-preview"><figcaption>Ethos-U operator hotspots · '
            f"{link(target, 'open interactive chart' if target == operator_full else 'open full size')}"
            '</figcaption><object type="image/svg+xml" '
            f'data="{href(snapshot)}">{link(target, "Open operator hotspots")}</object></figure>',
        )
    previews = (
        '<section id="preview"><h2>At a glance</h2><div class="previews">'
        + "".join(preview)
        + "</div></section>"
        if preview
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(application)} · Statistical profiling</title>
<style>
:root{{font:16px/1.48 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172334;background:#f5f7fa}}
*{{box-sizing:border-box}}body{{margin:0}}header{{background:#142943;color:white;padding:2rem max(1.5rem,calc((100vw - 1150px)/2))}}
header h1{{font-size:2rem;margin:.2rem 0}}header p{{margin:.2rem 0;color:#d5e5f5}}main{{max-width:1150px;margin:auto;padding:1.5rem}}
nav{{display:flex;flex-wrap:wrap;gap:.7rem;margin:0 0 1.5rem}}nav a{{background:#e5eef8;border-radius:99px;padding:.3rem .8rem}}
a{{color:#12559a;text-decoration:none}}a:hover{{text-decoration:underline}}section{{margin:1.5rem 0;padding:1.3rem;background:white;border:1px solid #dce3ec;border-radius:12px}}
h2{{margin:0 0 .8rem;font-size:1.25rem}}dl{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:.7rem;margin:0}}
.fact{{padding:.75rem;background:#f1f5fa;border-radius:8px;min-width:0}}dt{{font-size:.83rem;color:#52657a}}dd{{font-weight:650;margin:.2rem 0 0;overflow-wrap:anywhere}}
.detail-note{{margin:.8rem 0 0;color:#52657a;font-size:.9rem}}
.artifacts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:.6rem;list-style:none;padding:0;margin:0}}
.artifacts li{{padding:.7rem;border:1px solid #dce3ec;border-radius:8px;min-width:0}}small{{display:block;color:#68788a;overflow-wrap:anywhere;margin-top:.2rem}}
.previews{{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:1rem}}figure{{margin:0;min-width:0}}figcaption{{font-weight:650;margin-bottom:.4rem}}
object{{display:block;width:100%;height:380px;border:1px solid #e1e8ef;border-radius:8px}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}
.operator-preview{{grid-column:1/-1}}.operator-preview object{{height:min(70vh,700px)}}
th,td{{padding:.5rem .65rem;text-align:left;border-bottom:1px solid #dce3ec;white-space:nowrap}}th{{background:#f1f5fa}}
footer{{color:#52657a;margin:2rem 0}}@media(max-width:500px){{.previews{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>{escape(application)} · Statistical profiling</h1><p>{escape(board)}</p></header>
<main><nav>{navigation}</nav><section id="details"><h2>Capture details</h2><dl>{cards}</dl>{detail_note}</section>
{previews}{"".join(sections)}
<footer>Offline index generated from available files. PC and QREAD samples estimate activity; PMU event counts are not per-instruction costs.</footer>
</main>{PERFETTO_SCRIPT.replace("cortex_m_combined.perfetto.json", combined_trace(root)) if combined_trace(root) else ""}</body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--board", required=True, help="Board or simulator used for this capture")
    parser.add_argument("--application", help="Application name (default: run directory name)")
    args = parser.parse_args()
    try:
        root = args.run_dir.resolve()
        summary = json.loads((root / "summary.json").read_text())
        captures = read_capture_rows(root)
        page = render(root, summary, captures, args.board, args.application or root.name)
        destination = root / "index.html"
        destination.write_text(page)
        print(destination)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"report index failed: {error}\n")


if __name__ == "__main__":
    main()
