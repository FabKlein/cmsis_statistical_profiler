# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_timing.py
# Description:  Capture-wide timing validation and degraded report tests
#
# $Date:        22 September 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Validate timing independently of PC attribution and PMU reporting."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from test_profiler import analyzer


def capture(timestamps, start_timestamp=0, start_tick=0, timestamp_hz=1000000):
    header = dict(start_timestamp=start_timestamp, start_tick=start_tick,
                  stop_timestamp=timestamps[-1] & 0xFFFFFFFF,
                  stop_tick=(start_tick + len(timestamps)) & 0xFFFFFFFF,
                  timestamp_hz=timestamp_hz, timer_period=1000, timer_hz=1000000,
                  pmu=dict(status="active", count=2, flags=0, events=[3, 36],
                           start=[0, 0], stop=[len(timestamps), 2 * len(timestamps)],
                           scope="init_to_stop_all_execution"))
    samples = [(value & 0xFFFFFFFF, (start_tick + i) & 0xFFFFFFFF, 0x10001004,
                0x10002001, 1 << 24, 0xFFFFFFF9, i, 2 * i)
               for i, value in enumerate(timestamps, 1)]
    return header, samples


class TimingTests(unittest.TestCase):
    def test_frozen_wrong_rate_and_mid_capture_drift(self):
        cases = [[0] * 12, [500 * i for i in range(1, 13)],
                 [1000 * i for i in range(1, 7)] + [6000 + 500 * i for i in range(1, 7)]]
        for timestamps in cases:
            with self.subTest(timestamps=timestamps):
                h, samples = capture(timestamps)
                rows, timeline, unknown, timing = analyzer.analyze(h, samples, [(0x10001000, 32, "workload")])
                self.assertFalse(timing["timing_valid"])
                self.assertIn("clock disagreement", timing["timing_diagnostic"])
                self.assertEqual((rows[0]["hits"], unknown), (12, 0))
                self.assertTrue(all(row["time_us"] is None and row["timestamp_ticks_since_start"] is None
                                    for row in timeline))
                self.assertEqual([row["timestamp"] for row in timeline], timestamps)
                self.assertEqual(timeline[-1]["pmu1_interval_delta"], 2)
                self.assertEqual(analyzer.pmu_statistics(h)[0]["count"], 12)

    def test_wraps_and_coarse_counter_remain_valid(self):
        h, samples = capture([0xFFFFFFF0 + 1000 * i for i in range(1, 13)],
                             start_timestamp=0xFFFFFFF0, start_tick=0xFFFFFFFE)
        times, timing = analyzer.analyze_timing(h, samples)
        self.assertTrue(timing["timing_valid"])
        self.assertEqual(times[-1], 12000)
        h, samples = capture([i // 2 for i in range(1, 13)], timestamp_hz=500)
        self.assertTrue(analyzer.analyze_timing(h, samples)[1]["timing_valid"])
        # A gated gap spanning multiple timestamp wraps is reconstructed from timer ticks.
        h, samples = capture([10000000000])
        samples[0] = (samples[0][0], 10000000) + samples[0][2:]
        h["stop_tick"] = 10000000
        times, timing = analyzer.analyze_timing(h, samples)
        self.assertTrue(timing["timing_valid"])
        self.assertEqual(times, [10000000000])

    def test_stop_epoch_is_checked_even_without_samples(self):
        h, samples = capture([1000 * i for i in range(1, 13)])
        h["stop_tick"] += 10  # Frozen counter during the final gated-off interval.
        for records in [samples, []]:
            _, timing = analyzer.analyze_timing(h, records)
            self.assertFalse(timing["timing_valid"])
            self.assertIn("capture stop", timing["timing_diagnostic"])

    def test_drift_cannot_cancel_out_later(self):
        h, samples = capture([500 * i for i in range(1, 7)] + [3000 + 1500 * i for i in range(1, 7)])
        self.assertEqual(h["stop_timestamp"], 12000)
        self.assertFalse(analyzer.analyze_timing(h, samples)[1]["timing_valid"])

    def test_cli_preserves_pc_reports_and_blanks_time(self):
        count = 12
        fields = [analyzer.MAGIC, analyzer.FORMAT_VERSION, 24, analyzer.HEADER.size + 24 * count,
                  24 * count, count, 0, 0, 1000000, 1000, 0, 0, 0, count, 0, 1, 1, 1, 1000, 1000000] + [0] * 22
        records = b"".join(analyzer.RECORD.pack(0, i, 0x10001004, 0x10002001, 1 << 24, 0xFFFFFFF9)
                           for i in range(1, count + 1))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "capture.bin").write_bytes(analyzer.HEADER.pack(*fields) + records)
            (root / "app.elf").write_bytes(b"ELF fixture")
            output = root / "report"
            argv = ["analyze_profiler_buffer.py", "--samples", str(root / "capture.bin"),
                    "--elf", str(root / "app.elf"), "--output", str(output)]
            console = io.StringIO()
            with patch("sys.argv", argv), patch.object(analyzer, "elf_functions", return_value=[(0x10001000, 32, "workload")]), redirect_stdout(console):
                analyzer.main()
            summary = json.loads((output / "summary.json").read_text())
            self.assertIs(summary["timing_valid"], False)
            self.assertTrue(summary["timing_diagnostic"])
            self.assertIn("WARNING: timing invalid", console.getvalue())
            with (output / "samples.csv").open() as source:
                rows = list(csv.DictReader(source))
            self.assertTrue(all(row["time_us"] == row["timestamp_ticks_since_start"] == "" for row in rows))
            self.assertTrue(all(row["timestamp"] == "0" and row["function"] == "workload" for row in rows))
            self.assertTrue((output / "functions.csv").exists())


if __name__ == "__main__":
    unittest.main()
