# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""End-to-end fold regressions for actual clocks, overlap and cumulative rollover."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import test_fold_mcu_by_ethosu as fixtures
from test_fold_mcu_by_ethosu import write_csv
import fold_mcu_by_ethosu as mcu
import fold_ethosu_by_inference as npu
from capture_time import CaptureClock, normalize


class CaptureTimeTests(unittest.TestCase):
    def make_run(self, root):
        fixtures.McuFoldTests().make_run(root)
        report = root / "capture_00/ethosu_report"
        summary = json.loads((report / "summary.json").read_text())
        summary.update(device_type=55, pmu_count=0, pmu_status=0)
        (report / "summary.json").write_text(json.dumps(summary))
        with (report / "samples.csv").open() as source:
            rows = list(csv.DictReader(source))
        for row in rows:
            row.update(stream_id=int(row["running"]), qread=4 if int(row["running"]) else "")
        write_csv(report / "samples.csv", rows[0], rows)

    def change(self, root, clock=None, origin=0, compressed=False, delayed=False):
        for processor in ("cortex_m_report", "ethosu_report"):
            directory = root / "capture_00" / processor
            summary = json.loads((directory / "summary.json").read_text())
            header = summary["header"] if processor == "cortex_m_report" else summary
            with (directory / "samples.csv").open() as source:
                rows = list(csv.DictReader(source))
            if clock:
                header.update(sample_hz=4, timer_hz=10, timer_period=3)
                header["stop_timestamp"] = 23 * 300000
                for row in rows:
                    row["timestamp"] = int(row["tick"]) * 300000
                    if "time_us" in row:
                        row["time_us"] = row["timestamp"]
            if delayed and processor == "ethosu_report":
                rows = rows[1:-1]
                header.update(start_tick=1, start_timestamp=1000, stop_tick=22, stop_timestamp=22000)
            if compressed and processor == "ethosu_report":
                compact = []
                for row in rows:
                    if compact and not int(row["running"]) and not int(compact[-1]["running"]):
                        row["sample_count"] = int(compact.pop()["sample_count"]) + 1
                    compact.append(row)
                rows = compact
            header["start_tick"] = (header["start_tick"] + origin) & 0xffffffff
            header["stop_tick"] = (header["stop_tick"] + origin) & 0xffffffff
            for row in rows:
                row["tick"] = (int(row["tick"]) + origin) & 0xffffffff
            header["count"] = len(rows)
            if processor == "ethosu_report":
                header["total_samples"] = sum(int(row["sample_count"]) for row in rows)
            (directory / "summary.json").write_text(json.dumps(summary))
            write_csv(directory / "samples.csv", rows[0], rows)
        if clock:
            path = root / "summary.json"
            aggregate = json.loads(path.read_text())
            aggregate["sample_hz"] = 4
            path.write_text(json.dumps(aggregate))

    def test_actual_clock_and_both_folds_agree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            self.change(root, clock=True, origin=0xfffffff7, compressed=True)
            cpu, _, phases, _ = mcu.fold(root, post_ms=1800)
            ethos, _, npu_phases, *_ = npu.fold(root)
            self.assertEqual(cpu["eligible_periods"], ethos["eligible_periods"])
            self.assertEqual(cpu["median_period_ms"], 1800)
            self.assertEqual(ethos["median_start_period_ms"], 1800)
            self.assertEqual([r["phase_ms"] for r in phases], [r["phase_ms"] for r in npu_phases])
            self.assertEqual(phases[4]["phase_ms"], 1200)
            self.assertEqual(cpu["actual_sample_hz"], 10 / 3)

    def test_rollover_in_running_idle_and_between_starts(self):
        for origin in (0xfffffff7, 0xfffffff4, 0xfffffffa):
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.make_run(root)
                before = mcu.fold(root)
                self.change(root, origin=origin, compressed=True)
                after = mcu.fold(root)
                self.assertEqual(before[0]["eligible_periods"], after[0]["eligible_periods"])
                self.assertEqual(before[2], after[2])
                self.assertEqual(npu.fold(root)[0]["eligible_periods"], after[0]["eligible_periods"])

    def test_fractional_millisecond_phase_keys_match_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            for processor in ("cortex_m_report", "ethosu_report"):
                directory = root / "capture_00" / processor
                summary = json.loads((directory / "summary.json").read_text())
                header = summary["header"] if processor == "cortex_m_report" else summary
                header.update(sample_hz=3333, timer_hz=10000, timer_period=3,
                              stop_timestamp=23 * 300)
                with (directory / "samples.csv").open() as source:
                    rows = list(csv.DictReader(source))
                for row in rows:
                    row["timestamp"] = int(row["tick"]) * 300
                (directory / "summary.json").write_text(json.dumps(summary))
                write_csv(directory / "samples.csv", rows[0], rows)
            path = root / "summary.json"
            aggregate = json.loads(path.read_text())
            aggregate["sample_hz"] = 3333
            path.write_text(json.dumps(aggregate))
            cpu_phases = mcu.fold(root)[2]
            npu_phases = npu.fold(root)[2]
            self.assertEqual([r["phase_ms"] for r in cpu_phases],
                             [r["phase_ms"] for r in npu_phases])
            self.assertEqual(cpu_phases[3]["phase_ms"], 0.9)

    def test_paired_folds_reject_different_firmware_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            path = root / "capture_00/ethosu_report/summary.json"
            summary = json.loads(path.read_text())
            summary["firmware_id"] = "0123456789abcdef" * 2
            path.write_text(json.dumps(summary))
            for fold in (mcu.fold, npu.fold):
                with self.subTest(fold=fold), self.assertRaisesRegex(ValueError, "firmware identity"):
                    fold(root)

    def test_documented_sequential_start_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_run(root)
            self.change(root, delayed=True, origin=0xfffffffe)
            cpu = mcu.fold(root)[0]
            ethos = npu.fold(root)[0]
            self.assertEqual(cpu["complete_inferences"], 2)
            self.assertEqual(cpu["eligible_periods"], ethos["eligible_periods"])

    def test_nonzero_cpu_validation_is_accepted(self):
        for validation in (1, 2, 0x80000000):
            with self.subTest(validation=validation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.make_run(root)
                path = root / "capture_00/cortex_m_report/summary.json"
                data = json.loads(path.read_text())
                data["header"]["validation_passed"] = validation
                path.write_text(json.dumps(data))
                self.assertEqual(mcu.fold(root)[0]["complete_inferences"], 2)

    def test_missing_backward_and_ambiguous_ticks_fail(self):
        header = dict(timestamp_hz=1000, timer_hz=1000, timer_period=10,
                      start_tick=0, stop_tick=10, start_timestamp=0, stop_timestamp=100)
        for ticks in ((1, 1), (2, 1), (1, 3), (0x80000000,)):
            with self.subTest(ticks=ticks), self.assertRaises(ValueError):
                normalize(header, [dict(tick=t, timestamp=t * 10, sample_count=1) for t in ticks], compressed=True)

    def test_exact_and_rounded_clock_conversion(self):
        self.assertEqual(CaptureClock(1000000, 10, 3).milliseconds(4), 1200)
        self.assertEqual(CaptureClock(1000000, 1000000, 1000).milliseconds(4), 4)


if __name__ == "__main__":
    unittest.main()
