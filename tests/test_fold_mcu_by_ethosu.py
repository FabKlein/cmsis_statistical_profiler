# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""CPU folding uses shared ticks and excludes the two capture-edge NPU runs."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import fold_mcu_by_ethosu as mcu_fold


def write_csv(path, fields, rows):
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class McuFoldTests(unittest.TestCase):
    def make_run(self, root, with_pmu=True):
        (root / "summary.json").write_text(
            json.dumps(
                {
                    "captures": 1,
                    "sample_hz": 1000,
                    "all_validation_passed": True,
                }
            )
        )
        write_csv(
            root / "captures.csv",
            ("capture", "capture_dir"),
            [
                {"capture": 0, "capture_dir": "capture_00"},
            ],
        )
        cpu = root / "capture_00/cortex_m_report"
        ethos = root / "capture_00/ethosu_report"
        cpu.mkdir(parents=True)
        ethos.mkdir(parents=True)
        (cpu / "summary.json").write_text(
            json.dumps(
                {
                    "timing_valid": True,
                    "header": {
                        "count": 23,
                        "sample_hz": 1000,
                        "timestamp_hz": 1_000_000,
                        "start_tick": 0,
                        "stop_tick": 23,
                        "validation_passed": 1,
                        "pmu": {
                            "status": "active" if with_pmu else "disabled",
                            "count": 1 if with_pmu else 0,
                            "flags": 0,
                        },
                    },
                    "pmu_events": (
                        [{"event": "cpu-cycles", "status": "ok"}] if with_pmu else []
                    ),
                }
            )
        )
        (ethos / "summary.json").write_text(
            json.dumps(
                {
                    "count": 23,
                    "sample_hz": 1000,
                    "timestamp_hz": 1_000_000,
                    "start_tick": 0,
                    "stop_tick": 23,
                    "active": 0,
                    "complete": 1,
                    "validation_passed": 1,
                }
            )
        )
        fields = [
            "sample",
            "timestamp",
            "time_us",
            "tick",
            "pc",
            "lr",
            "function",
        ]
        if with_pmu:
            fields.extend(("pmu0_raw", "pmu0_interval_delta"))
        write_csv(
            cpu / "samples.csv",
            fields,
            [
                {
                    "sample": tick - 1,
                    "timestamp": tick * 1000,
                    "time_us": tick * 1000,
                    "tick": tick,
                    "pc": "0x00000010",
                    "lr": "0x00000020",
                    "function": "osRtxIdleThread" if tick in (11, 17) else "work",
                    **(
                        {"pmu0_raw": tick * 10, "pmu0_interval_delta": 10}
                        if with_pmu
                        else {}
                    ),
                }
                for tick in range(1, 24)
            ],
        )
        running = {2, 3, 4, 8, 9, 10, 14, 15, 16, 20, 21, 22}
        write_csv(
            ethos / "samples.csv",
            ("timestamp", "tick", "running"),
            [
                {
                    "timestamp": tick * 1000,
                    "tick": tick,
                    "running": int(tick in running),
                }
                for tick in range(1, 24)
            ],
        )

    def test_fold_aligns_shared_ticks_and_cpu_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary, windows, phases, functions = mcu_fold.fold(
                root, pre_ms=1, post_ms=5, highlight_function="work"
            )
            by_phase = {row["phase_ms"]: row for row in phases}
            self.assertEqual(summary["complete_inferences"], 2)
            self.assertEqual(summary["edge_groups_excluded"], 2)
            self.assertEqual(summary["matched_running_cpu_ticks"], 12)
            self.assertEqual([row["start_tick"] for row in windows], [8, 14])
            self.assertEqual(by_phase[3.0]["idle_percent"], 100)
            self.assertEqual(by_phase[0.0]["cpu-cycles_mean"], 10)
            self.assertEqual(by_phase[0.0]["ethosu_running_percent"], 100)
            self.assertEqual(by_phase[3.0]["ethosu_running_samples"], 0)
            self.assertEqual(by_phase[-1.0]["inferences_eligible"], 2)
            self.assertEqual(summary["missing_cpu_phase_samples"], 0)
            self.assertEqual(summary["highlight_sampled_runs_per_period"], {2: 2})
            self.assertEqual(summary["highlight_two_run_median_gap_ms"], 1.0)
            self.assertTrue(
                any(row["function"] == "osRtxIdleThread" for row in functions)
            )

    def test_rejects_mismatched_shared_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            path = root / "capture_00/ethosu_report/samples.csv"
            with path.open(newline="") as source:
                rows = list(csv.DictReader(source))
            rows[1]["timestamp"] = "9999"
            write_csv(path, rows[0], rows)
            with self.assertRaisesRegex(ValueError, "timestamp mismatch"):
                mcu_fold.fold(root, pre_ms=1, post_ms=5)

    def test_fold_without_cpu_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, with_pmu=False)
            summary, windows, phases, _ = mcu_fold.fold(root, pre_ms=1, post_ms=5)
            self.assertEqual(summary["complete_inferences"], 2)
            self.assertEqual(summary["cpu_pmu_events"], ())
            self.assertTrue(summary["idle_function_observed"])
            self.assertNotIn("cpu-cycles_mean", phases[0])
            self.assertEqual(len(windows), 2)


if __name__ == "__main__":
    unittest.main()
