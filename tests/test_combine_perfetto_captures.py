# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_combine_perfetto_captures.py
# Description:  Capture report regression checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""The combined trace omits debugger gaps and PMU intervals across windows."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import combine_perfetto_captures as merger


class CombinedPerfettoTests(unittest.TestCase):
    def make_run(self, root):
        (root / "summary.json").write_text(
            json.dumps(
                {
                    "captures": 2,
                    "all_validation_passed": True,
                    "elf_sha256": "test-elf",
                    "sample_hz": 1000,
                    "cpu_samples": 4,
                }
            )
        )
        with (root / "captures.csv").open("w", newline="") as output:
            writer = csv.DictWriter(
                output, fieldnames=("capture", "capture_dir", "cpu_samples")
            )
            writer.writeheader()
            for index in range(2):
                writer.writerow(
                    {
                        "capture": index,
                        "capture_dir": f"capture_{index:02d}",
                        "cpu_samples": 2,
                    }
                )
        for index in range(2):
            report = root / f"capture_{index:02d}" / "cortex_m_report"
            report.mkdir(parents=True)
            (report / "summary.json").write_text(
                json.dumps(
                    {
                        "timing_valid": True,
                        "elf_sha256": "test-elf",
                        "header": {
                            "count": 2,
                            "sample_hz": 1000,
                            "timestamp_hz": 1_000_000,
                            "start_tick": 0,
                            "stop_tick": 2,
                            "timer_hz": 1_000_000,
                            "timer_period": 1000,
                            "start_timestamp": 0xFFFFFF00 if index else 100,
                            "stop_timestamp": 0x000006D0 if index else 2100,
                            "complete": 1,
                            "active": 0,
                            "validation_passed": 1,
                            "full": 0,
                            "rejected": 0,
                            "pmu": {"status": "active", "flags": 0, "count": 1},
                        },
                        "pmu_events": [{"event": "cpu-cycles", "status": "ok"}],
                    }
                )
            )
            with (report / "samples.csv").open("w", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=(
                        "sample",
                        "time_us",
                        "pc",
                        "lr",
                        "function",
                        "pmu0_interval_delta",
                        "pmu0_raw",
                    ),
                )
                writer.writeheader()
                for sample, timestamp, raw in ((0, 500, 10), (1, 1500, 20)):
                    writer.writerow(
                        {
                            "sample": sample,
                            "time_us": timestamp,
                            "pc": "0x00000010",
                            "lr": "0x00000020",
                            "function": "work",
                            "pmu0_interval_delta": 10,
                            "pmu0_raw": raw,
                        }
                    )

    def test_duration_recovers_multiple_timestamp_wraps(self):
        for seconds in (12, 30):
            with self.subTest(seconds=seconds):
                header = dict(
                    timestamp_hz=400_000_000,
                    start_timestamp=123,
                    stop_timestamp=(123 + seconds * 400_000_000) & 0xFFFFFFFF,
                    start_tick=0xFFFFFF00,
                    stop_tick=(0xFFFFFF00 + seconds * 1000) & 0xFFFFFFFF,
                    timer_hz=100_000_000,
                    timer_period=100000,
                )
                self.assertEqual(merger.duration_us(header), seconds * 1_000_000)

    def test_long_capture_places_next_window_after_full_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            path = root / "capture_00/cortex_m_report/summary.json"
            summary = json.loads(path.read_text())
            summary["header"].update(
                timestamp_hz=400_000_000,
                start_timestamp=0,
                stop_timestamp=(12 * 400_000_000) & 0xFFFFFFFF,
                stop_tick=12000,
            )
            path.write_text(json.dumps(summary))
            target = root / "combined.json"
            _, _, duration = merger.combine(root, target)
            self.assertEqual(duration, 12_002_000)
            events = json.loads(target.read_text())["traceEvents"]
            starts = [
                event["ts"]
                for event in events
                if event.get("cat") == "capture.boundary"
                and event["args"]["position"] == "start"
            ]
            self.assertEqual(starts, [0, 12_000_000])

    def test_duration_rejects_inconsistent_clock_metadata(self):
        with self.assertRaises(ValueError):
            merger.duration_us(
                dict(
                    timestamp_hz=400_000_000,
                    start_timestamp=0,
                    stop_timestamp=1,
                    start_tick=0,
                    stop_tick=1000,
                    timer_hz=100_000_000,
                    timer_period=100000,
                )
            )

    def test_merges_active_time_with_boundaries_and_no_cross_window_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            target = root / "cortex_m_combined.perfetto.json"
            captures, samples, duration = merger.combine(root, target)
            events = json.loads(target.read_text())["traceEvents"]
            self.assertEqual((captures, samples, duration), (2, 4, 4000))
            self.assertEqual(
                [event["ts"] for event in events if event.get("cat") == "pc.sample"],
                [500, 1500, 2500, 3500],
            )
            self.assertEqual(
                len(
                    [
                        event
                        for event in events
                        if event.get("cat") == "pmu.interval_rate"
                    ]
                ),
                2,
            )
            self.assertEqual(
                [
                    event["ts"]
                    for event in events
                    if event.get("cat") == "capture.boundary"
                ],
                [0, 2000, 2000, 4000],
            )

    def test_rejects_missing_capture_samples_before_writing_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary_path = root / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["cpu_samples"] = 5
            summary_path.write_text(json.dumps(summary))
            target = root / "cortex_m_combined.perfetto.json"
            with self.assertRaisesRegex(ValueError, "combined sample count"):
                merger.combine(root, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
