# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_rtos_fvp.py
# Description:  RTOS capture acceptance and Toolbox runner regression tests
#
# $Date:        27 September 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import contextlib
import io
import csv
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from run_rtos_fvp import check_report, main


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

    def test_freertos_root_and_empty_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            folded = root / "stacks.folded"
            folded.write_text("\n".join("worker_entry;" + line for line in folded.read_text().splitlines()))
            self.assertEqual(check_report(root, "worker_entry"), [])
            self.assertIn("incorrect flamegraph root", check_report(root, "osThreadEntry"))
            folded.write_text("")
            self.assertIn("no usable folded stacks", check_report(root, "worker_entry"))

    def test_failed_toolbox_build_cannot_reuse_previous_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("samples.bin", "profiler.elf", "result.json"):
                (root / name).write_text("stale")
            with patch("sys.argv", ["run_rtos_fvp.py", "--kernel", "freertos", "--output", tmp]), \
                 patch("run_rtos_fvp.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cbuild")) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "cbuild")
            self.assertIn("call_tree.FreeRTOS+Corstone300", command)
            self.assertFalse((root / "samples.bin").exists())
            self.assertFalse((root / "profiler.elf").exists())
            self.assertEqual(json.loads((root / "result.json").read_text())["status"], "fail")

    def test_excessive_exclusions_and_per_worker_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for counts in ((1, 1), (99, 333), (333, 99), (100, 100)):
                with self.subTest(counts=counts):
                    _, rows = self.fixture(root)
                    rows = [dict(row, flamegraph_status="included" if i % 333 < counts[i // 333]
                                 else "unreliable") for i, row in enumerate(rows)]
                    self.write_rows(root, rows)
                    lines = (root / "stacks.folded").read_text().splitlines()
                    (root / "stacks.folded").write_text("\n".join(
                        line.rsplit(" ", 1)[0] + " " + str(count) for line, count in zip(lines, counts)))
                    failures = check_report(root)
                    if counts == (100, 100):
                        self.assertEqual(failures, [])
                    else:
                        suffix = "1" if counts[1] < 100 and counts[0] >= 100 else ""
                        self.assertIn("too few plotted samples for worker" + suffix, failures)
                    self.assertNotIn("folded stacks lost samples", failures)

    def test_folded_caller_order_and_deep_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for old, new in (("functionB;", ""),
                             ("functionB;functionC", "functionC;functionB"),
                             ("functionB", "functionB1"),
                             ("functionB", "functionB;functionB"),
                             (";functionD;functionE", "")):
                with self.subTest(replacement=new):
                    self.fixture(root)
                    folded = root / "stacks.folded"
                    folded.write_text(folded.read_text().replace(old, new))
                    failures = check_report(root)
                    if old == ";functionD;functionE":
                        self.assertIn("missing plotted deep caller chain for worker", failures)
                        self.assertNotIn("invalid folded caller chain", failures)
                    else:
                        self.assertIn("invalid folded caller chain", failures)
                    self.assertNotIn("folded stacks lost samples", failures)
