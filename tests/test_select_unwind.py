# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_select_unwind.py
# Description:  AC6 selective unwind retention regression tests
#
# $Date:        26 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'host/select_profiler_unwind.py'
spec = importlib.util.spec_from_file_location('select_unwind', SCRIPT)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)

HEADER = 'Base Addr    Size         Type   Attr      Idx    E Section Name        Object\n'
# Sanitized AC6 6.24 example supplied by an integrator; no object paths needed.
ROWS = '''0x10000000   0x000002c2   Code   RO         5362    .text.arm_avg_pool_f16  libcmsis-nn.a(arm_avg_pool_f16.o)
0x100002c2   0x00000002   PAD
0x100028a8   0x000003ee   Code   RO         4858    .text.arm_nn_mat_mult_nt_n_packed_f16  libcmsis-nn.a(arm_nn_mat_mult_nt_n_packed_f16.o)
0x34180918   0x0000001c   Code   RO         5734    .text               c_wu.l(hvalid.o)
0x34182d5c   0x000000e4   Code   RO           15    .text.$Sub$$arm_nn_mat_mult_nt_n_packed_f16  dtcm_dma_kernels.o
0x341a95bc   0x00000ee4   Code   RO         1261    .text.app_main      runner.o
0x341bc020   0x00000138   Code   RO          146    .text.dtcm_dma_poll_completion  dtcm_dma_port.o
0x341c024c   0x0000024c   Code   RO          221    .text.preprocess_rgb565  preprocess.o
'''


def row(name, entry='', kind='Code', size='20'):
    return f'    0x10000000 0x{size} {kind} RO 42 {entry} {name} library.a(object.o)\n'


class SelectUnwindTests(unittest.TestCase):
    def test_supplied_map_rows(self):
        sections, warnings = selector.select_sections(HEADER + ROWS)
        names = ['.text', '.text.$Sub$$arm_nn_mat_mult_nt_n_packed_f16', '.text.app_main',
                 '.text.arm_avg_pool_f16', '.text.arm_nn_mat_mult_nt_n_packed_f16',
                 '.text.dtcm_dma_poll_completion', '.text.preprocess_rgb565']
        self.assertEqual(sections, ['.ARM.exidx' + name for name in names])
        self.assertTrue(any('Bare .text' in warning for warning in warnings))

    def test_marked_entries_dedup_and_noncode(self):
        source = HEADER + row('.text.live', '*') + row('.text.live') + row('.text.data', kind='Data')
        source += row('.text.empty', size='0') + row('.sram_text') + row('.textual')
        sections, warnings = selector.select_sections(source)
        self.assertEqual(sections, ['.ARM.exidx.text.live'])
        self.assertTrue(any('omitted' in warning for warning in warnings))
        sections, _ = selector.select_sections(source, ['.sram_text'])
        self.assertEqual(sections, ['.ARM.exidx.sram_text', '.ARM.exidx.text.live'])

    def test_section_table_scope(self):
        source = 'Removing unused input sections\n' + row('.text.removed')
        source += HEADER + row('.text.live') + '\nImage component sizes\n' + row('.text.not_a_section')
        source += HEADER + row('.text.other', '*')
        self.assertEqual(selector.select_sections(source)[0], ['.ARM.exidx.text.live', '.ARM.exidx.text.other'])

    def test_rejects_empty_malformed_and_unsafe_names(self):
        for text in ['', ROWS, HEADER, HEADER + row('.data'),
                     HEADER + '0x1000 0x10 Code RO invalid .text.foo foo.o\n',
                     HEADER + row('.text.*'), HEADER + row('.text.bad")'), HEADER + row('.text.bad\\x')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                selector.select_sections(text)

    def test_cli_literal_dollar_and_failure_preserves_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'firmware.map', Path(tmp) / 'keep.rsp'
            source.write_text(HEADER + ROWS)
            command = [sys.executable, str(SCRIPT), str(source), str(output)]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = output.read_bytes()
            self.assertIn(b'--keep="*(.ARM.exidx.text.$Sub$$arm_nn_mat_mult_nt_n_packed_f16)"\n', original)
            self.assertEqual(len(original.splitlines()), 7)
            source.write_text('unrecognized map')
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Abort the second link', result.stderr)
            self.assertEqual(output.read_bytes(), original)
            result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(source)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_text(), 'unrecognized map')
