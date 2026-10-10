# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""CPU folding uses shared ticks and excludes the two capture-edge NPU runs."""

import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import fold_mcu_by_ethosu as mcu_fold
import generate_report_index as report_index


def write_csv(path, fields, rows):
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class McuFoldTests(unittest.TestCase):
    def make_run(self, root, with_pmu=True, deltas=(10,)):
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
                        "complete": 1,
                        "active": 0,
                        "pmu": {
                            "status": "active" if with_pmu else "disabled",
                            "count": len(deltas) if with_pmu else 0,
                            "flags": 0,
                        },
                    },
                    "pmu_events": (
                        [
                            {
                                "event": "cpu-cycles",
                                "event_id": "0x0011",
                                "status": "ok",
                            }
                            for _ in deltas
                        ]
                        if with_pmu
                        else []
                    ),
                }
            )
        )
        (ethos / "summary.json").write_text(
            json.dumps(
                {
                    "count": 23,
                    "total_samples": 23,
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
            for slot in range(len(deltas)):
                fields.extend((f"pmu{slot}_raw", f"pmu{slot}_interval_delta"))
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
                        {
                            field: value
                            for slot, delta in enumerate(deltas)
                            for field, value in (
                                (f"pmu{slot}_raw", tick * delta),
                                (f"pmu{slot}_interval_delta", delta),
                            )
                        }
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
            ("timestamp", "tick", "running", "sample_count"),
            [
                {
                    "timestamp": tick * 1000,
                    "tick": tick,
                    "running": int(tick in running),
                    "sample_count": 1,
                }
                for tick in range(1, 24)
            ],
        )

    def test_fold_aligns_shared_ticks_and_cpu_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary, windows, phases, functions = mcu_fold.fold(
                root,
                pre_ms=1,
                post_ms=5,
                idle_function="osRtxIdleThread",
                highlight_function="work",
            )
            by_phase = {row["phase_ms"]: row for row in phases}
            self.assertEqual(summary["complete_inferences"], 2)
            self.assertEqual(summary["edge_groups_excluded"], 2)
            self.assertEqual(summary["matched_running_cpu_ticks"], 12)
            self.assertEqual([row["start_tick"] for row in windows], [8, 14])
            self.assertEqual(by_phase[3.0]["idle_percent"], 100)
            self.assertEqual(by_phase[0.0]["pmu0_mean"], 10)
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
            summary, windows, phases, _ = mcu_fold.fold(
                root, pre_ms=1, post_ms=5, idle_function="osRtxIdleThread"
            )
            self.assertEqual(summary["complete_inferences"], 2)
            self.assertEqual(summary["cpu_pmu_events"], [])
            self.assertTrue(summary["idle_observed"])
            self.assertNotIn("pmu0_mean", phases[0])
            self.assertEqual(len(windows), 2)

    def test_repeated_event_slots_remain_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, deltas=(10, 30))
            summary, _, phases, _ = mcu_fold.fold(root, post_ms=5)
            self.assertEqual(
                [event["slot"] for event in summary["cpu_pmu_events"]], [0, 1]
            )
            self.assertEqual(
                [event["event"] for event in summary["cpu_pmu_events"]],
                ["cpu-cycles"] * 2,
            )
            for row in phases:
                self.assertEqual((row["pmu0_mean"], row["pmu1_mean"]), (10, 30))
                self.assertEqual((row["pmu0_intervals"], row["pmu1_intervals"]), (2, 2))
                self.assertEqual((row["pmu0_ci95"], row["pmu1_ci95"]), (0, 0))

    def test_pmu_configuration_uses_ids_even_when_labels_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root, deltas=(10, 30))
            shutil.copytree(root / "capture_00", root / "capture_01")
            path = root / "summary.json"
            aggregate = json.loads(path.read_text())
            aggregate["captures"] = 2
            path.write_text(json.dumps(aggregate))
            write_csv(
                root / "captures.csv",
                ("capture", "capture_dir"),
                [
                    {"capture": slot, "capture_dir": f"capture_0{slot}"}
                    for slot in (0, 1)
                ],
            )
            path = root / "capture_01/cortex_m_report/summary.json"
            summary = json.loads(path.read_text())
            summary["pmu_events"][1]["event_id"] = "0x0012"
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "PMU configuration changed"):
                mcu_fold.fold(root)

    def test_missing_cpu_samples_do_not_become_zero_pmu_measurements(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            cpu = root / "capture_00/cortex_m_report"
            with (cpu / "samples.csv").open(newline="") as source:
                rows = [
                    row
                    for row in csv.DictReader(source)
                    if int(row["tick"]) not in (8, 14)
                ]
            for index, row in enumerate(rows):
                row["sample"] = index
                row["pmu0_interval_delta"] = (
                    10 * (int(row["tick"]) - int(rows[index - 1]["tick"]))
                    if index
                    else 10
                )
            write_csv(cpu / "samples.csv", rows[0], rows)
            summary = json.loads((cpu / "summary.json").read_text())
            summary["header"]["count"] = len(rows)
            (cpu / "summary.json").write_text(json.dumps(summary))
            summary, _, phases, _ = mcu_fold.fold(root, post_ms=5)
            self.assertEqual(summary["missing_cpu_phase_samples"], 2)
            for row in phases[:2]:
                self.assertEqual(row["pmu0_intervals"], 0)
                self.assertEqual((row["pmu0_mean"], row["pmu0_ci95"]), ("", ""))

    def test_idle_estimates_require_explicit_classification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary, windows, phases, _ = mcu_fold.fold(root, post_ms=5)
            self.assertIsNone(summary["idle_classification"])
            self.assertNotIn("non_idle_percent", phases[0])
            self.assertNotIn("idle_samples_in_window", windows[0])

    def test_platform_names_and_ranges_match_index_classification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            platform = {
                "schema_version": 1,
                "cpu": {
                    "idle_functions": ["osRtxIdleThread"],
                    "idle_pc_ranges": [{"start": "0x10", "end": "0x12"}],
                },
            }
            (root / "platform.json").write_text(json.dumps(platform))
            summary, _, phases, functions = mcu_fold.fold(root, post_ms=5)
            self.assertEqual(summary["idle_phase_observations"], 10)
            self.assertTrue(all(row["non_idle_percent"] == 0 for row in phases))
            self.assertTrue(any(row["function"] == "work" for row in functions))
            # The same PC range classifies work symbols as idle in the index.
            self.assertEqual(
                report_index.sampled_cpu_non_idle(
                    root / "capture_00/cortex_m_report", {}, platform
                ),
                0,
            )

    def test_both_folds_reject_unfinalized_and_bad_compression(self):
        import fold_ethosu_by_inference as ethos_fold

        for kind in ("unfinalized", "compression"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.make_run(root)
                path = root / "capture_00/ethosu_report/summary.json"
                summary = json.loads(path.read_text())
                summary["complete" if kind == "unfinalized" else "total_samples"] = 0
                path.write_text(json.dumps(summary))
                for fold in (mcu_fold.fold, ethos_fold.fold):
                    with self.assertRaisesRegex(
                        ValueError, "finalized|compressed tick"
                    ):
                        fold(root)


if __name__ == "__main__":
    unittest.main()
