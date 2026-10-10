# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Native Himax start/failure tests with vendor API doubles, not SDK validation."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HimaxTimerTests(unittest.TestCase):
    def test_start_failure_cleanup_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("WE2_core.h", "hx_drv_timer.h"):
                (root / name).write_text('#include "fake_himax_timer.h"\n')
            for rate in (125, 333, 1000):
                with self.subTest(rate=rate):
                    binary = root / "test"
                    flags = ["-DTEST_INVALID_RATE"] if rate == 333 else []
                    subprocess.run(
                        [
                            "cc",
                            "-std=c11",
                            "-O2",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-fsanitize=undefined",
                            "-Imcu",
                            "-Itests/fakes",
                            "-I" + tmp,
                            '-DPROFILER_DEVICE_HEADER="fake_himax_timer.h"',
                            "-DPROFILER_STACK_BASE=0x20000000U",
                            "-DPROFILER_STACK_BYTES=4096U",
                            f"-DPROFILER_SAMPLE_HZ={rate}U",
                            *flags,
                            "tests/test_himax_timer.c",
                            "-o",
                            str(binary),
                        ],
                        cwd=ROOT,
                        check=True,
                    )
                    subprocess.run([str(binary)], check=True)
