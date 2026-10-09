# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_ethosu_operator_reports.py
# Description:  Capture report regression checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Regression checks for PTE unwrapping and portable operator charts."""

import csv
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import plot_ethosu_operators as operators
import unwrap_ethosu_pte as unwrap


class EthosuOperatorReportTests(unittest.TestCase):
    def test_timing_skips_unknown_stream_and_missing_qread(self):
        self.test_median_offset_uses_complete_inference_ticks(excluded=True)

    def test_median_offset_uses_complete_inference_ticks(self, excluded=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "summary.json").write_text(
                json.dumps(
                    {
                        "sample_hz": 1000,
                        "captures": 1,
                        "ethosu_running_ticks": 8 if excluded else 6,
                        "all_validation_passed": True,
                    }
                )
            )
            (root / "folded_summary.json").write_text(
                json.dumps({"sample_hz": 1000, "captures": 1, "complete_inferences": 1})
            )
            with (root / "ethosu_inference_windows.csv").open(
                "w", newline=""
            ) as target:
                writer = csv.DictWriter(
                    target, fieldnames=("capture", "start_tick", "last_running_tick")
                )
                writer.writeheader()
                writer.writerow(
                    {"capture": 0, "start_tick": 10, "last_running_tick": 13}
                )
            with (root / "ethosu_samples.csv").open("w", newline="") as target:
                writer = csv.DictWriter(
                    target,
                    fieldnames=(
                        "capture",
                        "tick",
                        "running",
                        "stream_id",
                        "sample_count",
                        "qread",
                    ),
                )
                writer.writeheader()
                for tick, qread in (
                    (2, 16),
                    (10, 16),
                    (11, 16),
                    (12, 16),
                    (13, 32),
                    (20, 32),
                ):
                    writer.writerow(
                        {
                            "capture": 0,
                            "tick": tick,
                            "running": 1,
                            "stream_id": 1,
                            "sample_count": 1,
                            "qread": qread,
                        }
                    )
                if excluded:
                    writer.writerow(
                        {
                            "capture": 0,
                            "tick": 21,
                            "running": 1,
                            "stream_id": 0,
                            "sample_count": 1,
                            "qread": 16,
                        }
                    )
                    writer.writerow(
                        {
                            "capture": 0,
                            "tick": 22,
                            "running": 1,
                            "stream_id": 1,
                            "sample_count": 1,
                            "qread": "",
                        }
                    )
            rows = [
                {
                    "op": 0,
                    "kick_offset": "0x0010",
                    "next_kick_offset": "0x0020",
                    "name": "first",
                    "tosa_op": "Conv2D",
                    "samples": 4,
                },
                {
                    "op": 1,
                    "kick_offset": "0x0020",
                    "next_kick_offset": "0x0030",
                    "name": "second",
                    "tosa_op": "Concat",
                    "samples": 2,
                },
            ]
            alignment = {
                "histogram_stream_ids": ["1"],
                "running_samples": 8 if excluded else 6,
            }
            timing = operators.add_sampled_offsets(rows, alignment, root)
            self.assertEqual(timing[0]["timed_samples"], 3)
            self.assertEqual(timing[0]["median_offset_ms"], 1.0)
            self.assertEqual(timing[1]["timed_samples"], 1)
            self.assertEqual(timing[1]["median_offset_ms"], 3.0)
            for row in rows:
                row.update(
                    {
                        "percent": 100 * row["samples"] / 6,
                        "npu_op": "CONV",
                        "vela_op": row["tosa_op"],
                        "ifm_hwc": "1x1x1",
                        "ifm2_hwc": "",
                        "ofm_hwc": "1x1x1",
                        "est_cycles": 7,
                        "macs": 8,
                        "sram_ac": 9,
                        "flash_ac": 10,
                    }
                )
            operators.draw(rows, 6, root / "timed.svg")
            chart = (root / "timed.svg").read_text()
            self.assertIn("Median +ms", chart)
            self.assertIn("+1.0", chart)
            self.assertIn("Vela est. cycles", chart)
            self.assertIn("more samples improve confidence, not tick resolution", chart)

    def test_cop1_stream_length_and_offset(self):
        commands = struct.pack("<III", 0x00000130, 0x00000002, 0xFFFF0000)
        driver = b"COP1" + struct.pack("<IIIIII", 0x00000001, 0, 0, 5, 5, (3 << 16) | 2)
        pte = b"prefix!!" + driver + commands + b"suffix"
        found = unwrap.streams_in_pte(pte)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0], (8, 8 + len(driver), commands))
        self.assertEqual(unwrap.streams_in_pte(pte[:-12]), [])

    def test_chart_uses_running_share_and_qread_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            samples = root / "ethosu_operator_samples.csv"
            fields = (
                "op",
                "kick_offset",
                "next_kick_offset",
                "npu_op",
                "vela_op",
                "tosa_op",
                "name",
                "ifm_hwc",
                "ifm2_hwc",
                "ofm_hwc",
                "est_cycles",
                "macs",
                "sram_ac",
                "flash_ac",
                "samples",
                "percent_of_running_samples",
            )
            with samples.open("w", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fields)
                writer.writeheader()
                for op, kick, label, count in (
                    (0, "0x0010", "Conv2D", 2),
                    (1, "0x0020", "Custom<&>", 5),
                ):
                    writer.writerow(
                        {
                            "op": op,
                            "kick_offset": kick,
                            "next_kick_offset": "0x0030",
                            "npu_op": "CONV",
                            "vela_op": label,
                            "tosa_op": label,
                            "name": label,
                            "ifm_hwc": "1x1x1",
                            "ifm2_hwc": "",
                            "ofm_hwc": "1x1x1",
                            "est_cycles": 7,
                            "macs": 8,
                            "sram_ac": 9,
                            "flash_ac": 10,
                            "samples": count,
                            "percent_of_running_samples": count,
                        }
                    )
            alignment = root / "vela_alignment.json"
            alignment.write_text(
                json.dumps(
                    {
                        "listing_matches_pte": True,
                        "running_samples": 100,
                        "assigned_samples": 7,
                        "debug_queue_operations": 2,
                    }
                )
            )
            output = root / "charts"
            command = [
                sys.executable,
                str(ROOT / "host" / "plot_ethosu_operators.py"),
                "--samples",
                str(samples),
                "--alignment",
                str(alignment),
                "--output-dir",
                str(output),
                "--top",
                "1",
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            ranked = ElementTree.parse(output / "ethosu_operator_hotspots.svg")
            ordered = ElementTree.parse(
                output / "ethosu_operator_hotspots_chronological.svg"
            )
            ns = {"s": "http://www.w3.org/2000/svg"}
            self.assertEqual(
                ranked.findall(".//s:g[@class='row']", ns)[0].attrib["data-op"], "1"
            )
            self.assertEqual(
                ordered.findall(".//s:g[@class='row']", ns)[0].attrib["data-op"], "0"
            )
            self.assertTrue((output / "ethosu_operator_hotspots_top1.svg").exists())
            self.assertIn(
                "Custom&lt;&amp;&gt;",
                (output / "ethosu_operator_hotspots.svg").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
