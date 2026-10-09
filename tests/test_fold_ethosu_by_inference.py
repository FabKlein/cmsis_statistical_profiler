# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_fold_ethosu_by_inference.py
# Description:  Capture report regression checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.3
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Ethos-U inference folding works with and without PMU counters."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import fold_ethosu_by_inference as ethos_fold
import plot_ethosu_operators as operators


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class EthosFoldTests(unittest.TestCase):
    def make_run(self, root, events=(), device=55):
        (root / "summary.json").write_text(
            json.dumps(
                {"captures": 1, "sample_hz": 1000, "all_validation_passed": True}
            )
        )
        write_csv(root / "captures.csv", [{"capture": 0, "capture_dir": "capture_00"}])
        report = root / "capture_00/ethosu_report"
        report.mkdir(parents=True)
        running = {2, 3, 6, 7, 10, 11, 14, 15}
        rows = [
            {
                "tick": tick,
                "timestamp": tick * 1000,
                "running": int(tick in running),
                "stream_id": int(tick in running),
                "sample_count": 1,
                "qread": tick * 4 if tick in running else 0,
                **{f"pmu{i}": tick * (i + 10) for i in range(len(events))},
            }
            for tick in range(1, 17)
        ]
        write_csv(report / "samples.csv", rows)
        (report / "summary.json").write_text(
            json.dumps(
                {
                    "device_type": device,
                    "active": 0,
                    "complete": 1,
                    "validation_passed": 1,
                    "count": len(rows),
                    "total_samples": len(rows),
                    "sample_hz": 1000,
                    "timestamp_hz": 1_000_000,
                    "pmu_count": len(events),
                    "pmu_status": 1 if events else 0,
                    **{f"pmu_event{i}": event for i, event in enumerate(events)},
                }
            )
        )

    def test_device_specific_events_and_explicit_npu_clock(self):
        for device, events in ((55, (5, 6, 13, 41)), (65, (5, 6)), (85, (4, 5, 10))):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.make_run(root, events, device)
                summary, *_ = ethos_fold.fold(root)
                self.assertEqual(summary["pmu_events"][0]["key"], "npu_active")
                self.assertEqual(summary["pmu_events"][1]["key"], "mac_active")
                self.assertEqual(summary["mean_npu_active_cycles_per_inference"], 40)
                self.assertNotIn("mean_npu_active_ms_per_inference", summary)
                self.assertEqual(summary["mac_pct_active"], 110)
                summary, *_ = ethos_fold.fold(root, npu_clock_hz=2_000_000)
                self.assertEqual(summary["mean_npu_active_ms_per_inference"], 0.02)

    def test_u85_mac_only_does_not_become_npu_active(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, (5,), 85)
            summary, *_ = ethos_fold.fold(root)
            self.assertEqual(summary["pmu_events"][0]["key"], "mac_active")
            self.assertNotIn("mean_npu_active_cycles_per_inference", summary)

    def test_missing_qread_and_unknown_stream_keep_activity_and_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, (5,))
            before = ethos_fold.fold(root)
            path = root / "capture_00/ethosu_report/samples.csv"
            with path.open() as source:
                rows = list(csv.DictReader(source))
            rows[5]["qread"] = ""
            rows[9]["stream_id"] = "0"
            write_csv(path, rows)
            after = ethos_fold.fold(root)
            self.assertEqual(
                after[0]["complete_inferences"], before[0]["complete_inferences"]
            )
            self.assertEqual(after[0]["mean_npu_active_cycles_per_inference"], 40)
            self.assertEqual(after[2][0]["running_percent"], 100)
            self.assertEqual(after[2][0]["median_qread_bytes"], "")
            self.assertEqual(after[0]["start_qread_bytes"], [])

    def test_invalid_npu_clock(self):
        for value in (0, -1, float("nan"), float("inf")):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "frequency"),
            ):
                ethos_fold.fold(Path("."), npu_clock_hz=value)

    def test_without_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary, windows, phases, pmu_windows, pmu_phases = ethos_fold.fold(root)
            self.assertEqual(summary["complete_inferences"], 2)
            self.assertEqual(summary["pmu_events"], [])
            self.assertEqual([row["start_tick"] for row in windows], [6, 10])
            self.assertEqual(phases[0]["running_percent"], 100)
            self.assertEqual(phases[2]["running_percent"], 0)
            self.assertEqual((pmu_windows, pmu_phases), ([], []))

    def test_one_arbitrary_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, (99,))
            summary, _, _, windows, phases = ethos_fold.fold(root)
            self.assertEqual(summary["pmu_events"][0]["key"], "pmu0_event_0063")
            self.assertEqual(windows[0]["pmu0_cycles"], 40)
            self.assertEqual(phases[0]["pmu0_event_0063_mean_cycles"], 10)

    def test_known_non_demo_and_repeated_events(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, (38, 5, 5, 170), 85)
            summary, _, _, windows, phases = ethos_fold.fold(root)
            events = summary["pmu_events"]
            self.assertTrue(all(event["known"] for event in events))
            self.assertEqual(events[3]["key"], "ext1_wr_stall_limit")
            self.assertEqual(events[3]["hardware_event"], 0x29F)
            self.assertEqual(events[1]["key"], "mac_active_pmu1")
            self.assertEqual(events[2]["key"], "mac_active_pmu2")
            self.assertEqual(windows[0]["mac_active_pmu1_cycles"], 44)
            self.assertEqual(windows[0]["mac_active_pmu2_cycles"], 48)
            self.assertEqual(phases[0]["mac_active_pmu1_mean_cycles"], 11)
            self.assertEqual(phases[0]["mac_active_pmu2_mean_cycles"], 12)
            self.assertEqual(summary["mean_mac_active_cycles_per_inference"], 44)
            self.assertNotIn("mac_pct_active", summary)

    def test_numeric_capture_index_joins_operator_timing_outside_capture_directory(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            # No capture_N naming convention, and reports live in a sibling.
            (root / "capture_00").rename(root / "workload-a")
            output = root / "results"
            output.mkdir()
            summary = json.loads((root / "summary.json").read_text())
            summary["ethosu_running_ticks"] = 8
            (output / "summary.json").write_text(json.dumps(summary))
            write_csv(
                output / "captures.csv",
                [{"capture": 0, "capture_dir": "../workload-a"}],
            )
            folded, windows, *_ = ethos_fold.fold(output)
            self.assertEqual([window["capture"] for window in windows], [0, 0])
            (output / "folded_summary.json").write_text(json.dumps(folded))
            write_csv(output / "ethosu_inference_windows.csv", windows)
            with (root / "workload-a/ethosu_report/samples.csv").open() as stream:
                samples = [{"capture": 0, **row} for row in csv.DictReader(stream)]
            write_csv(output / "ethosu_samples.csv", samples)
            rows = [
                {
                    "op": 0,
                    "kick_offset": "0x0",
                    "next_kick_offset": "0x50",
                    "samples": 8,
                    "name": "test convolution",
                    "tosa_op": "Conv2D",
                }
            ]
            timing = operators.add_sampled_offsets(
                rows, {"histogram_stream_ids": ["1"], "running_samples": 8}, output
            )
            self.assertEqual(timing[0]["timed_samples"], 4)
            self.assertEqual(timing[0]["median_offset_ms"], 0.5)


if __name__ == "__main__":
    unittest.main()
