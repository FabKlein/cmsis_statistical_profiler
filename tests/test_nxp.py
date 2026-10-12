# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Clock-aware RT685 adapter regression; SDK and silicon validation are separate."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NxpTimerTests(unittest.TestCase):
    def test_bad_clock_restart_and_owned_register_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for header in ("fsl_clock.h", "fsl_reset.h"):
                (root / header).write_text('#include "fake_nxp_timer.h"\n')
            binary = root / "test"
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=undefined", "-Imcu", "-Itests/fakes", "-I" + folder,
                            '-DPROFILER_DEVICE_HEADER="fake_nxp_timer.h"',
                            "-DPROFILER_STACK_BASE=0x20000000U", "-DPROFILER_STACK_BYTES=4096U",
                            "tests/test_nxp_timer.c", "-o", str(binary)], cwd=ROOT, check=True)
            subprocess.run([str(binary)], check=True)
