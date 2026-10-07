# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Repeated capture aggregation accepts either processor and optional PMUs."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import aggregate_profiler_captures as aggregate
import generate_aggregate_mcu_report as mcu_report


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class AggregateVariantTests(unittest.TestCase):
    def make_capture(
        self, root, name, *, cpu=True, ethos=True, cpu_events=(), ethos_events=()
    ):
        capture = root / name
        capture.mkdir()
        if cpu:
            report = capture / "cortex_m_report"
            report.mkdir()
            (report / "summary.json").write_text(
                json.dumps(
                    {
                        "elf_sha256": "same-elf",
                        "unknown_samples": 0,
                        "timing_valid": True,
                        "header": {
                            "sample_hz": 1000,
                            "buffer_bytes": 128,
                            "record_base_bytes": 24,
                            "complete": 1,
                            "active": 0,
                            "count": 1,
                            "rejected": 0,
                            "full": 0,
                            "validation_passed": 1,
                            "iterations": 1,
                            "pmu": {
                                "count": len(cpu_events),
                                "events": list(cpu_events),
                            },
                        },
                    }
                )
            )
            write_csv(report / "samples.csv", [{"tick": 1, "pc": "0x10"}])
            write_csv(
                report / "functions.csv",
                [{"address": "0x10", "function": "work", "hits": 1}],
            )
        if ethos:
            report = capture / "ethosu_report"
            report.mkdir()
            (report / "summary.json").write_text(
                json.dumps(
                    {
                        "sample_hz": 1000,
                        "buffer_bytes": 128,
                        "record_bytes": 24,
                        "format": "EUTR",
                        "complete": 1,
                        "active": 0,
                        "count": 1,
                        "pmu_count": len(ethos_events),
                        **{
                            f"pmu_event{i}": event
                            for i, event in enumerate(ethos_events)
                        },
                        "total_samples": 1,
                        "running_samples": 1,
                        "idle_samples": 0,
                        "full": 0,
                        "validation_passed": 1,
                        "invalid_qread": 0,
                        "unknown_stream_samples": 0,
                        "unregistered_streams": 0,
                        "streams_seen": 1,
                        "qread_samples": 1,
                    }
                )
            )
            write_csv(
                report / "streams.csv",
                [
                    {
                        "stream_id": 1,
                        "command_address": "0x100",
                        "stream_bytes": 20,
                    }
                ],
            )
            write_csv(
                report / "samples.csv", [{"tick": 1, "sample_count": 1, "qread": 4}]
            )
            write_csv(
                report / "qread_histogram.csv",
                [
                    {
                        "stream_id": 1,
                        "qread_bytes": 4,
                        "samples": 1,
                    }
                ],
            )
        return capture

    def test_cpu_only_without_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = [
                self.make_capture(root, f"capture_{i:02d}", ethos=False)
                for i in range(2)
            ]
            result = aggregate.aggregate(captures, root)
            self.assertEqual(result["cpu_samples"], 2)
            self.assertNotIn("ethosu_ticks", result)
            self.assertFalse((root / "ethosu_samples.csv").exists())
            # The aggregate CPU chart is still useful without PMU or backtraces.
            report = mcu_report.generate(root)
            self.assertFalse(report["backtraces_available"])
            self.assertTrue((root / "mcu_report/hotspots.svg").exists())
            self.assertFalse((root / "mcu_report/flamegraph.svg").exists())

    def test_ethosu_only_without_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = [
                self.make_capture(root, f"capture_{i:02d}", cpu=False) for i in range(2)
            ]
            result = aggregate.aggregate(captures, root / "out")
            self.assertEqual(result["ethosu_ticks"], 2)
            self.assertNotIn("cpu_samples", result)
            self.assertFalse((root / "out/cortex_m_samples.csv").exists())

    def test_mixed_processors_and_pmu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = [
                self.make_capture(
                    root, f"capture_{i:02d}", cpu_events=(3,), ethos_events=(5, 6)
                )
                for i in range(2)
            ]
            result = aggregate.aggregate(captures, root / "out")
            self.assertEqual(
                (result["cpu_pmu_count"], result["ethosu_pmu_count"]), (1, 2)
            )

    def test_rejects_changed_event_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a = self.make_capture(root, "capture_00", ethos_events=(5,))
            b = self.make_capture(root, "capture_01", ethos_events=(6,))
            with self.assertRaisesRegex(ValueError, "PMU configuration differs"):
                aggregate.aggregate([a, b], root / "out")


if __name__ == "__main__":
    unittest.main()
