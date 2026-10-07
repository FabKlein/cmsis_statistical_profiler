# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

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


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class EthosFoldTests(unittest.TestCase):
    def make_run(self, root, events=()):
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


if __name__ == "__main__":
    unittest.main()
