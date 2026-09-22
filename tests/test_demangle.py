# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_demangle.py
# Description:  C++ symbol demangling regression tests
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import io
import csv
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from test_profiler import analyzer


class DemangleTests(unittest.TestCase):
    def test_batch_preserves_addresses_c_names_and_overloads(self):
        functions = [(0x1000, 16, "_ZN3Foo3runEi"), (0x2000, 32, "_ZN3Foo3runEf"),
                     (0x3000, 8, "arm_nn_kernel"), (0x4000, 16, "_ZN3Foo3runEi")]
        result = subprocess.CompletedProcess([], 0, "Foo::run(float)\nFoo::run(int)\n", "")
        with patch.object(analyzer.subprocess, "run", return_value=result) as run:
            decoded = analyzer.demangle_functions(functions, "/tools/c++filt")
        self.assertEqual(decoded, [(0x1000, 16, "Foo::run(int)"), (0x2000, 32, "Foo::run(float)"),
                                   (0x3000, 8, "arm_nn_kernel"), (0x4000, 16, "Foo::run(int)")])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["input"], "_ZN3Foo3runEf\n_ZN3Foo3runEi\n")
        self.assertEqual(run.call_args.args[0], ["/tools/c++filt"])

    def test_missing_failed_and_malformed_tools_preserve_names(self):
        functions = [(0x1000, 16, "_ZN3Foo3runEi")]
        with patch.object(analyzer.shutil, "which", return_value=None), redirect_stderr(io.StringIO()) as warning:
            self.assertEqual(analyzer.demangle_functions(functions), functions)
        self.assertIn("--cxxfilt", warning.getvalue())
        for failure in [OSError("missing"), subprocess.CalledProcessError(1, "c++filt"),
                        subprocess.TimeoutExpired("c++filt", 30)]:
            with self.subTest(failure=failure), patch.object(analyzer.subprocess, "run", side_effect=failure), redirect_stderr(io.StringIO()):
                self.assertEqual(analyzer.demangle_functions(functions, "c++filt"), functions)
        with patch.object(analyzer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), redirect_stderr(io.StringIO()):
            self.assertEqual(analyzer.demangle_functions(functions, "c++filt"), functions)
        with patch.object(analyzer.subprocess, "run") as run:
            plain = [(0x1000, 16, "run_once")]
            self.assertEqual(analyzer.demangle_functions(plain), plain)
            run.assert_not_called()

    @unittest.skipUnless(shutil.which("c++filt"), "c++filt is not installed")
    def test_real_demangler(self):
        self.assertEqual(analyzer.demangle_functions([(0x1000, 16, "_ZN3Foo3runEi")], "c++filt"),
                         [(0x1000, 16, "Foo::run(int)")])

    def test_cli_reports_and_opt_out(self):
        fields = [analyzer.MAGIC, analyzer.FORMAT_VERSION, 24, analyzer.HEADER.size + 24,
                  1, 1, 0, 0, 1000000, 1000, 0, 0, 1000, 1, 1, 1, 1, 1, 1000, 1000000] + [0] * 21
        data = analyzer.HEADER.pack(*fields) + analyzer.RECORD.pack(1000, 1, 0x1004, 0x2001, 1 << 24, 0xFFFFFFF9)
        for options, expected in [([], "Foo::run(int)"), (["--cxxfilt", "/custom/c++filt"], "Foo::run(int)"),
                                  (["--no-demangle"], "_ZN3Foo3runEi")]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "capture.bin").write_bytes(data)
                (root / "app.elf").write_bytes(b"ELF fixture")
                argv = ["analyze_profiler_buffer.py", "--samples", str(root / "capture.bin"),
                        "--elf", str(root / "app.elf"), "--output", str(root / "report")] + options
                with patch("sys.argv", argv), patch.object(analyzer, "elf_functions", return_value=[(0x1000, 16, "_ZN3Foo3runEi")]), patch.object(
                        analyzer.shutil, "which", return_value="/auto/c++filt"), patch.object(
                        analyzer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Foo::run(int)\n", "")) as run, redirect_stdout(io.StringIO()) as console:
                    analyzer.main()
                for name in ["functions", "samples"]:
                    with (root / "report" / (name + ".csv")).open() as stream:
                        self.assertEqual(next(csv.DictReader(stream))["function"], expected)
                self.assertIn(expected, console.getvalue())
                if "--no-demangle" in options:
                    run.assert_not_called()
                elif "--cxxfilt" in options:
                    self.assertEqual(run.call_args.args[0], ["/custom/c++filt"])
