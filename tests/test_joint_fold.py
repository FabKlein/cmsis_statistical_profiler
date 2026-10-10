# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Joint folds require matching inference coverage and shared phases."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import plot_joint_mcu_ethosu as joint


def write_csv(path, rows):
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class JointFoldTests(unittest.TestCase):
    def make_run(self, root):
        common = {"captures": 2, "complete_inferences": 4, "sample_hz": 2000}
        (root / "mcu_folded_summary.json").write_text(
            json.dumps(
                {
                    **common,
                    "idle_classification": {
                        "idle_functions": ["idle"],
                        "idle_pc_ranges": [],
                    },
                    "cpu_pmu_events": [
                        {"slot": 0, "key": "pmu0", "label": "PMU0 · cpu-cycles"}
                    ],
                }
            )
        )
        (root / "folded_summary.json").write_text(json.dumps(common))
        write_csv(
            root / "mcu_folded.csv",
            [
                {
                    "phase_ms": phase,
                    "inferences_eligible": 4,
                    "cpu_samples": 4,
                    "non_idle_percent": 75,
                    "ethosu_running_samples": running,
                    "pmu0_intervals": 4,
                    "pmu0_mean": 200,
                    "pmu0_ci95": 10,
                }
                for phase, running in ((0.0, 4), (0.5, 2))
            ],
        )
        write_csv(
            root / "folded_pmu.csv",
            [
                {
                    "phase_ms": phase,
                    "inference_count": 4,
                    "npu_active_mean_cycles": 100,
                    "npu_active_ci95_cycles": 10,
                    "mac_active_mean_cycles": 50,
                    "mac_active_ci95_cycles": 5,
                    "ib_stall_mean_cycles": 2,
                    "ib_stall_ci95_cycles": 1,
                    "axi_read_request_stall_mean_cycles": 5,
                    "axi_read_request_stall_ci95_cycles": 1,
                }
                for phase in (0.0, 0.5, 1.0)
            ],
        )

    def test_combines_matching_phases_and_running_share(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary, rows, omitted = joint.combine(root)
            self.assertEqual(summary["complete_inferences"], 4)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["ethosu_running_percent"], 50)
            self.assertEqual(rows[1]["mcu_pmu0_mean"], 200)
            self.assertEqual(omitted, 1)

    def test_repeated_cpu_event_slots_survive_joint_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            path = root / "mcu_folded_summary.json"
            summary = json.loads(path.read_text())
            summary["cpu_pmu_events"].append(
                {"slot": 1, "key": "pmu1", "label": "PMU1 · cpu-cycles"}
            )
            path.write_text(json.dumps(summary))
            rows = joint.read_csv(root / "mcu_folded.csv")
            for row in rows:
                row.update(pmu1_intervals=4, pmu1_mean=600, pmu1_ci95=30)
            write_csv(root / "mcu_folded.csv", rows)
            merged, combined, _ = joint.combine(root)
            self.assertEqual(len(merged["cpu_pmu_events"]), 2)
            self.assertEqual(
                (combined[0]["mcu_pmu0_mean"], combined[0]["mcu_pmu1_mean"]), (200, 600)
            )

    def test_joint_omits_unclassified_idle_estimate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            path = root / "mcu_folded_summary.json"
            summary = json.loads(path.read_text())
            summary["idle_classification"] = None
            path.write_text(json.dumps(summary))
            rows = joint.read_csv(root / "mcu_folded.csv")
            for row in rows:
                del row["non_idle_percent"]
            write_csv(root / "mcu_folded.csv", rows)
            _, combined, _ = joint.combine(root)
            self.assertNotIn("mcu_non_idle_percent", combined[0])

    def test_rejects_mismatched_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            rows = joint.read_csv(root / "folded_pmu.csv")
            rows[1]["inference_count"] = 3
            write_csv(root / "folded_pmu.csv", rows)
            with self.assertRaisesRegex(ValueError, "coverage differs"):
                joint.combine(root)

    def test_combines_without_either_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary = json.loads((root / "mcu_folded_summary.json").read_text())
            summary["cpu_pmu_events"] = []
            (root / "mcu_folded_summary.json").write_text(json.dumps(summary))
            rows = joint.read_csv(root / "mcu_folded.csv")
            for row in rows:
                del row["pmu0_intervals"]
                del row["pmu0_mean"]
                del row["pmu0_ci95"]
            write_csv(root / "mcu_folded.csv", rows)
            (root / "folded_pmu.csv").unlink()
            write_csv(
                root / "ethosu_folded.csv",
                [
                    {
                        "phase_ms": phase,
                        "inference_count": 4,
                        "running_samples": running,
                    }
                    for phase, running in ((0.0, 4), (0.5, 2), (1.0, 0))
                ],
            )
            merged_summary, combined, omitted = joint.combine(root)
            self.assertEqual(merged_summary["ethosu_pmu_events"], [])
            self.assertEqual(combined[1]["ethosu_running_percent"], 50)
            self.assertFalse(any("mean_cycles" in key for key in combined[0]))
            self.assertEqual(omitted, 1)

    def test_combines_single_ethosu_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            summary = json.loads((root / "folded_summary.json").read_text())
            summary["pmu_events"] = [{"key": "custom", "label": "Custom counter"}]
            (root / "folded_summary.json").write_text(json.dumps(summary))
            rows = joint.read_csv(root / "folded_pmu.csv")
            write_csv(
                root / "folded_pmu.csv",
                [
                    {
                        "phase_ms": row["phase_ms"],
                        "inference_count": 4,
                        "custom_mean_cycles": 20,
                        "custom_ci95_cycles": 2,
                    }
                    for row in rows
                ],
            )
            _, combined, _ = joint.combine(root)
            self.assertEqual(combined[0]["ethosu_custom_mean_cycles"], 20)


if __name__ == "__main__":
    unittest.main()
