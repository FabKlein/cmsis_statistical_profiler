# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_alif.py
# Description:  Test independent Alif UTIMER channels and configuration checks
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Native Alif register tests; real SDK builds verify vector mappings separately."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AlifTimerTests(unittest.TestCase):
    def test_channels_and_configuration(self):
        flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Imcu", "-Itests/fakes",
                 "-Iadapters/alif_e8", '-DPROFILER_DEVICE_HEADER="fake_alif_timer.h"',
                 "-DPROFILER_STACK_BASE=0x20000000U", "-DPROFILER_STACK_BYTES=4096U",
                 "-DPROFILER_TIMER_CLOCK_HZ=100000000U"]
        cases = [(["-DRTSS_HP"], True), (["-DRTSS_HE"], True)]
        cases += [(["-DRTSS_HP", f"-DPROFILER_ALIF_UTIMER_CHANNEL={channel}U"], True)
                  for channel in range(12)]
        cases += [(["-DRTSS_HP", "-DRTSS_HE"], False), ([], False),
                  (["-DPROFILER_ALIF_UTIMER_CHANNEL=12"], False),
                  (["-DPROFILER_ALIF_UTIMER_CHANNEL=-1"], False)]
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "test"
            for defines, valid in cases:
                with self.subTest(defines=defines):
                    built = subprocess.run(flags + defines + ["tests/test_alif_timer.c", "-o", str(binary)],
                                           cwd=ROOT, text=True, capture_output=True)
                    self.assertEqual(built.returncode == 0, valid, built.stderr)
                    if valid:
                        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
