# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_fvp.py
# Description:  Test FVP acceptance checks and stale-artifact failure handling
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Host-only tests for the CI pass/fail gate."""
import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import check_fvp
import run_fvp

REFERENCE = json.loads(Path(__file__).with_name("fvp_reference.json").read_text())


class FvpChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.report = Path(self.temp.name) / "report"
        self.report.mkdir()
        self.summary = copy.deepcopy(REFERENCE["expected"])
        self.summary["header"].update(count=84, start_tick=84, stop_tick=168, iterations=100)
        self.summary["header"]["pmu"].update(start=[0, 0], stop=[84, 168])
        self.events = [dict(event_id="0x0003", count=84, status="ok"),
                       dict(event_id="0x0024", count=168, status="ok")]
        self.summary["pmu_events"] = copy.deepcopy(self.events)
        self.samples = [dict(exception_return="0xffffffed", pmu0_raw=i, pmu0_interval_delta=1,
                             pmu1_raw=2 * i, pmu1_interval_delta=2) for i in range(1, 85)]
        self.functions = [dict(function="run_once", hits=84)]

    def write(self):
        (self.report / "summary.json").write_text(json.dumps(self.summary))
        for name, rows in [("events", self.events), ("samples", self.samples), ("functions", self.functions)]:
            with (self.report / (name + ".csv")).open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

    def check(self):
        self.write()
        return check_fvp.check_report(self.report, REFERENCE)

    def test_valid_nonzero_pmu_counts(self):
        self.assertEqual(self.check(), [])

    def test_bad_capture_metadata(self):
        original = copy.deepcopy(self.summary)
        for field, value in [("complete", 0), ("validation_passed", 0), ("count", 0),
                             ("rejected", 1), ("start_tick", 0), ("stop_tick", 999), ("iterations", 0)]:
            with self.subTest(field=field):
                self.summary = copy.deepcopy(original)
                self.summary["header"][field] = value
                self.assertTrue(self.check())
        for field, value in [("status", "unavailable"), ("count", 0), ("events", [0, 0]), ("flags", 1)]:
            with self.subTest(pmu=field):
                self.summary = copy.deepcopy(original)
                self.summary["header"]["pmu"][field] = value
                self.assertTrue(self.check())
        self.summary = copy.deepcopy(original)
        self.summary["unknown_samples"] = 1
        self.assertTrue(self.check())
        self.summary = copy.deepcopy(original)
        self.summary["timing_valid"] = False
        self.assertTrue(self.check())

    def test_bad_function_frame_and_pmu_csv(self):
        self.functions[0]["function"] = "other"
        self.assertTrue(self.check())
        self.functions[0]["function"] = "run_once"
        for row in self.samples:
            row["exception_return"] = "0xfffffff9"
        self.assertTrue(self.check())
        for row in self.samples:
            row["exception_return"] = "0xffffffed"
        self.samples[0]["pmu0_interval_delta"] = 123
        self.assertTrue(self.check())
        self.samples[0]["pmu0_interval_delta"] = 1
        self.events[0]["count"] = 0
        self.assertTrue(self.check())

    def test_missing_report_fails(self):
        self.write()
        (self.report / "events.csv").unlink()
        with self.assertRaises(OSError):
            check_fvp.check_report(self.report, REFERENCE)

    def test_failed_command_cannot_reuse_stale_capture(self):
        self.write()
        output = self.report.parent
        capture = output / "samples.bin"
        capture.write_bytes(b"stale capture")
        argv = ["run_fvp.py", "--cmsis", "/unused", "--bsp", "/unused", "--output", str(output)]
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()), patch(
                "run_fvp.subprocess.run", side_effect=subprocess.TimeoutExpired("armclang", 1)):
            self.assertEqual(run_fvp.main(), 1)
        self.assertFalse(capture.exists())
        self.assertFalse((self.report / "summary.json").exists())
        self.assertEqual(json.loads((output / "result.json").read_text())["status"], "fail")


if __name__ == "__main__":
    unittest.main()
