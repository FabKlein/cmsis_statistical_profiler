# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Wrong-image rejection and generated configuration guards work before capture."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import test_integration_tools as fixtures
from test_profiler import analyzer
from generate_profiler_build_config import generate

ROOT = Path(__file__).resolve().parents[1]


class FirmwareIdentityTests(unittest.TestCase):
    def test_exact_image_mismatch_and_unavailable_identity(self):
        first, second = bytes(range(16)), bytes(range(1, 17))
        for identity, expected in ((first, "matched"), (None, "unavailable")):
            data = fixtures.elf(identity=identity)
            analyzer.elf_functions(data)
            header = {"firmware_id": identity.hex() if identity else None}
            self.assertEqual(analyzer.validate_firmware_identity(header, data)["status"], expected)
        for wrong in (second, None):
            with self.assertRaisesRegex(ValueError, "identity differs"):
                analyzer.validate_firmware_identity({"firmware_id": first.hex()}, fixtures.elf(identity=wrong))
        with self.assertRaisesRegex(ValueError, "read-only"):
            analyzer.elf_firmware_identity(fixtures.elf(identity=first, writable_identity=True))

    def test_fresh_build_tokens_and_per_file_override_rejection(self):
        self.assertNotEqual(generate(), generate())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "build_config.h").write_text(generate(2, 1, 16))
            for lto in (False, True):
                for override in (None, "-DPROFILER_PMU_COUNT=4", "-DPROFILER_STACK_UNWIND=0", "-DPROFILER_UNWIND_MAX_DEPTH=8"):
                    with self.subTest(lto=lto, override=override):
                        command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Imcu", "-Itests/fakes", "-I" + folder,
                                   '-DPROFILER_DEVICE_HEADER="fake_device.h"',
                                   '-DPROFILER_BUILD_CONFIG_HEADER="build_config.h"',
                                   "-DPROFILER_PRECISE_STACK_BOUNDS=1", "-DPROFILER_STACK_BASE=0x20000000U", "-DPROFILER_STACK_BYTES=4096U"]
                        if override:
                            command.append(override)
                        if lto:
                            command.append("-flto")
                        result = subprocess.run([*command, "-c", "mcu/sampling_profiler.c", "-o", str(root / "capture.o")],
                                                cwd=ROOT, capture_output=True, text=True)
                        self.assertEqual(result.returncode == 0, override is None, result.stderr)
                        if override:
                            self.assertIn("shared build configuration", result.stderr)
