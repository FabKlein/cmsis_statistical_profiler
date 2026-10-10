# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_report_index.py
# Description:  Offline report navigation and Perfetto launcher checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Offline report index links only real artifacts and checks capture totals."""

import csv
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import generate_report_index as report_index


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "href" in attributes:
            self.targets.append(attributes["href"])
        if tag == "object" and "data" in attributes:
            self.targets.append(attributes["data"])


class ReportIndexTests(unittest.TestCase):
    def test_prefers_cpu_npu_trace_for_link_and_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("combined.perfetto.json", "cortex_m_combined.perfetto.json"):
                (root / name).write_text("{}")
            page = report_index.render(
                root, {"captures": 0}, [], "Board", "Application"
            )
            self.assertIn("Combined Cortex-M and Ethos-U Perfetto timeline", page)
            self.assertIn("fetch('combined.perfetto.json')", page)
            self.assertNotIn("cortex_m_combined.perfetto.json", page)

    def test_optional_artifacts_and_relative_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "summary.json").write_text(
                json.dumps({"captures": 2, "sample_hz": 2000, "cpu_samples": 11})
            )
            with (root / "captures.csv").open("w", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=(
                        "capture",
                        "capture_dir",
                        "cpu_samples",
                        "ethosu_ticks",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "capture": 0,
                        "capture_dir": "capture_00",
                        "cpu_samples": 5,
                        "ethosu_ticks": 5,
                    }
                )
                writer.writerow(
                    {
                        "capture": 1,
                        "capture_dir": "capture_01",
                        "cpu_samples": 6,
                        "ethosu_ticks": 6,
                    }
                )
            for relative in (
                "REPORT.md",
                "mcu_report/hotspots.svg",
                "mcu_folded.svg",
                "joint_folded.svg",
                "ethosu_operator_hotspots.svg",
                "ethosu_operator_hotspots_top30.svg",
                "ethosu_operator_timing.csv",
                "mcu_report/instruction_hotspots.txt",
                "cortex_m_combined.perfetto.json",
                "capture_00/cortex_m_report/samples.perfetto.json",
                "capture_01/ethosu_report/summary.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            summary = json.loads((root / "summary.json").read_text())
            captures = report_index.read_capture_rows(root)
            page = report_index.render(
                root, summary, captures, "Board <E7>", "Traffic & test"
            )
            self.assertIn("Board &lt;E7&gt;", page)
            self.assertIn("Traffic &amp; test", page)
            self.assertIn("2000 Hz", page)
            self.assertIn("Instruction and source hotspots", page)
            self.assertIn("MCU activity folded by inference", page)
            self.assertIn("Combined MCU and Ethos-U folded profile", page)
            self.assertIn("Operator median phase after inference start", page)
            self.assertIn("Perfetto", page)
            self.assertIn("cortex_m_combined.perfetto.json", page)
            self.assertIn('id="open-perfetto" href="https://ui.perfetto.dev"', page)
            self.assertIn("target.postMessage('PING', origin)", page)
            self.assertIn("downloadable: true", page)
            self.assertNotIn("capture_00/cortex_m_report/samples.perfetto.json", page)
            self.assertNotIn("capture_01/ethosu_report/summary.json", page)
            self.assertIn("Operator hotspots, interactive", page)
            self.assertIn('class="operator-preview"', page)
            self.assertIn('data="ethosu_operator_hotspots_top30.svg"', page)
            self.assertIn(
                'href="ethosu_operator_hotspots.svg">open interactive chart', page
            )
            self.assertNotIn("All-PC flamegraph", page)
            links = Links()
            links.feed(page)
            local = [
                target
                for target in links.targets
                if not target.startswith(("#", "https://", "http://"))
            ]
            self.assertTrue(local)
            for target in local:
                self.assertTrue((root / unquote(target)).is_file(), target)

    def test_inconsistent_capture_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / "captures.csv").open("w", newline="") as output:
                writer = csv.DictWriter(
                    output, fieldnames=("capture", "capture_dir", "cpu_samples")
                )
                writer.writeheader()
                writer.writerow(
                    {"capture": 0, "capture_dir": "capture_00", "cpu_samples": 5}
                )
            captures = report_index.read_capture_rows(root)
            with self.assertRaisesRegex(ValueError, "capture count differs"):
                report_index.render(
                    root, {"captures": 2, "cpu_samples": 5}, captures, "board", "app"
                )

    def test_perfetto_control_omitted_without_combined_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            page = report_index.render(Path(folder), {}, [], "board", "app")
            self.assertNotIn('id="open-perfetto"', page)
            self.assertNotIn("Cortex-M non-idle PC share", page)

    def test_platform_details_and_freertos_idle_function(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "platform.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "soc": "Example SoC",
                        "cpu": {
                            "name": "Cortex-M55",
                            "role": "HP",
                            "frequency_hz": 400_000_000,
                            "idle_functions": ["prvIdleTask"],
                        },
                        "ethosu": {"name": "Ethos-U55", "frequency_hz": 200_000_000},
                        "clock_basis": "Configured nominal values",
                    }
                )
            )
            with (root / "cortex_m_samples.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=("pc", "function"))
                writer.writeheader()
                writer.writerows(
                    [
                        {"pc": "0x1000", "function": "prvIdleTask"},
                        {"pc": "0x1002", "function": "prvIdleTask"},
                        {"pc": "0x2000", "function": "work"},
                        {"pc": "0x2002", "function": "work"},
                    ]
                )
            page = report_index.render(root, {"cpu_samples": 4}, [], "board", "app")
            self.assertIn("Cortex-M55 (HP)", page)
            self.assertIn("400 MHz", page)
            self.assertIn("200 MHz", page)
            self.assertIn("50.00%", page)
            self.assertIn("Configured nominal values", page)
            self.assertIn("platform.json", page)

    def test_bare_metal_idle_pc_range_and_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            platform = {
                "schema_version": 1,
                "cpu": {"idle_pc_ranges": [{"start": "0x1000", "end": "0x1004"}]},
            }
            (root / "platform.json").write_text(json.dumps(platform))
            with (root / "samples.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=("pc", "function"))
                writer.writeheader()
                writer.writerows(
                    [
                        {"pc": "0x1000", "function": "main"},
                        {"pc": "0x1002", "function": "main"},
                        {"pc": "0x1004", "function": "main"},
                        {"pc": "0x2000", "function": "main"},
                    ]
                )
            page = report_index.render(
                root, {"header": {"count": 4}}, [], "board", "app"
            )
            self.assertIn("50.00%", page)
            platform["cpu"]["frequency_hz"] = True
            (root / "platform.json").write_text(json.dumps(platform))
            with self.assertRaisesRegex(ValueError, "frequency_hz"):
                report_index.render(root, {}, [], "board", "app")
            del platform["cpu"]["frequency_hz"]
            platform["cpu"]["idle_pc_ranges"][0]["start"] = True
            (root / "platform.json").write_text(json.dumps(platform))
            with self.assertRaisesRegex(ValueError, "PC range addresses"):
                report_index.render(root, {}, [], "board", "app")


if __name__ == "__main__":
    unittest.main()
