# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_rtos_fvp.py
# Description:  CMSIS-RTX capture acceptance regression tests
#
# $Date:        24 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import csv
import json
from pathlib import Path
import tempfile
import unittest

from run_rtos_fvp import check_report


class RtosFvpChecks(unittest.TestCase):
    def fixture(self, root):
        summary = {"timing_valid": True, "header": {"complete": 1, "active": 0,
            "validation_passed": 1, "iterations": 4, "rejected": 0, "unwind_max_depth": 16,
            "record_base_bytes": 28, "count": 666}}
        (root / "summary.json").write_text(json.dumps(summary))
        rows = []
        folded = []
        for suffix in ("", "1"):
            chain = ["worker" + suffix, "run_once" + suffix] + ["function" + c + suffix for c in "ABCDE"]
            rows += [{"function": "functionE" + suffix, "callchain": json.dumps(chain),
                      "exception_return": "0xfffffffd"}] * 333
            folded.append(";".join(chain) + " 333")
        self.write_rows(root, rows)
        (root / "stacks.folded").write_text("\n".join(folded))
        return summary, rows

    @staticmethod
    def write_rows(root, rows):
        with (root / "samples.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_both_threads_and_corrupt_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, rows = self.fixture(root)
            self.assertEqual(check_report(root), [])
            summary["timing_valid"] = False
            (root / "summary.json").write_text(json.dumps(summary))
            self.assertIn("invalid timestamp timing", check_report(root))
            summary, rows = self.fixture(root)
            # All rows are valid independently, but combining threads is unsafe.
            rows[0] = dict(rows[0], callchain=json.dumps(["functionA", "functionB1"]))
            self.write_rows(root, rows)
            self.assertIn("caller chain crosses thread workloads", check_report(root))
            summary, rows = self.fixture(root)
            rows[0] = dict(rows[0], exception_return="0xfffffff9")
            self.write_rows(root, rows)
            self.assertIn("sample did not use a thread PSP", check_report(root))
            self.fixture(root)
            (root / "stacks.folded").write_text("functionE 1\n")
            self.assertIn("folded stacks lost samples", check_report(root))
