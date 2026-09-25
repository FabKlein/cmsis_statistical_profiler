# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_integration_tools.py
# Description:  Integration tooling regression tests
#
# $Date:        25 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from test_profiler import analyzer
import test_unwind

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import check_profiler_elf as preflight
from estimate_profiler_buffer import estimate


def elf(recipe=0x80b0b0b0, second_start=0x2000):
    """2 code allocations plus symbols/index; no compiler required for host tests."""
    data = bytearray(52)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHI', data, 16, 2, 40, 1)
    labels = b'\0.text\0.sram_text\0.ARM.exidx\0.strtab\0.symtab\0.shstrtab\0'
    strings = b'\0leaf\0parent\0statistical_samples\0profiler_unwind_tables\0profiler_stack_bounds\0'
    sections = [(0,) * 10]

    def section(name, kind, flags, address, blob, link=0, entsize=0):
        while len(data) % 4:
            data.append(0)
        sections.append((labels.index(name.encode()), kind, flags, address, len(data), len(blob), link, 0, 4, entsize))
        data.extend(blob)

    section('.text', 1, 6, 0x1000, bytes(32))
    section('.sram_text', 1, 6, 0x2000, bytes(32))
    entries = [(0x1000, recipe), (second_start, 0x80b0b0b0), (0x2020, 1)]
    index = b''.join(struct.pack('<II', (addr - (0x3000 + 8 * n)) & 0x7fffffff, value)
                     for n, (addr, value) in enumerate(entries))
    section('.ARM.exidx', 0x70000001, 2, 0x3000, index)
    section('.strtab', 3, 0, 0, strings)
    symbols = b''.join(struct.pack('<IIIBBH', strings.index(name.encode()), address | 1, 16, 2, 0, sec)
                       for name, address, sec in [('leaf', 0x1000, 1), ('parent', 0x2000, 2),
                         ('statistical_samples', 0x1010, 1), ('profiler_unwind_tables', 0x1010, 1), ('profiler_stack_bounds', 0x1010, 1)])
    section('.symtab', 2, 0, 0, symbols, 4, 16)
    section('.shstrtab', 3, 0, 0, labels)
    offset = len(data)
    data.extend(b''.join(struct.pack('<10I', *s) for s in sections))
    struct.pack_into('<I', data, 32, offset)
    struct.pack_into('<HHH', data, 46, 40, len(sections), 6)
    return bytes(data)


class IntegrationToolsTests(unittest.TestCase):
    def test_preflight_regions_and_missing_metadata(self):
        self.assertTrue(preflight.check(elf(), ['leaf', 'parent'], True)['ok'])
        self.assertFalse(preflight.check(elf(1), ['leaf'], True)['ok'])
        # A boundary sentinel cannot supply a recipe for the next allocation.
        self.assertFalse(preflight.check(elf(second_start=0x1020), ['parent'], True)['ok'])
        self.assertFalse(preflight.check(elf(second_start=0x1800), [], True)['ok'])
        self.assertFalse(preflight.check(elf(second_start=0x1000), [], True)['ok'])
        self.assertFalse(preflight.check(elf(recipe=0x100), [], True)['ok'])
        self.assertFalse(preflight.check(elf(), ['missing'], True)['ok'])
        with self.assertRaises(ValueError):
            preflight.check(elf()[:-8])

    def test_format_identity(self):
        capture = test_unwind.UnwindTests.capture(0, 1, [0x2005])
        for index, value in [(1, 1), (42, 168), (43, 0), (43, 0x82)]:
            data = bytearray(capture)
            struct.pack_into('<I', data, index * 4, value)
            with self.assertRaises(ValueError):
                analyzer.read_capture(data)
        with self.assertRaisesRegex(ValueError, 'rebuild and recapture'):
            analyzer.read_capture(struct.pack('<II', analyzer.MAGIC, 1))

    def test_budget_and_depth_metrics(self):
        result = estimate(1048576, 2000, 4, 16, 8)
        self.assertEqual(result['maximum']['record_bytes'], 108)
        self.assertLess(result['maximum']['seconds'], 6)
        self.assertGreater(result['minimum']['seconds'], result['expected']['seconds'])
        with self.assertRaises(ValueError):
            estimate(65536, 1000, 0, 4, 16)
        details = [dict(flamegraph_status='included', unwind_status='no_table', callers_raw='[1, 2]')]
        summary = analyzer.flamegraph_summary(details, 'parent')
        self.assertEqual(summary['root_reached_percent'], 100)
        self.assertEqual(summary['partial_samples'], 1)
        self.assertEqual(summary['recovered_caller_depth_counts'], {2: 1})

    def test_report_preserves_inputs_and_rejects_stale_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.elf').write_bytes(elf())
            capture = test_unwind.UnwindTests.capture(0, 1, [0x2005])
            (root / 'samples.bin').write_bytes(capture)
            command = [sys.executable, str(ROOT / 'host/create_profiler_report.py'), '--samples', str(root / 'samples.bin'),
                       '--elf', str(root / 'app.elf'), '--output', str(root / 'report'), '--stack-root', 'parent']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = root / 'report'
            self.assertEqual((report / 'inputs/samples.bin').read_bytes(), capture)
            self.assertTrue((report / 'samples.perfetto.json').is_file())
            self.assertIn('not embedded', json.loads((report / 'manifest.json').read_text())['provenance_note'])
            self.assertIn('stacks.folded', (report / 'index.html').read_text())
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
