# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_unwind.py
# Description:  EHABI backtraces and folded-stack regression tests
#
# $Date:        25 September 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from test_profiler import analyzer

ROOT = Path(__file__).resolve().parents[1]


class UnwindTests(unittest.TestCase):
    def test_native_compact_unwinder(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "test"
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-pie", "-no-pie",
                            "-fsanitize=undefined", "-Imcu", "-Itests/fakes", "-DPROFILER_STACK_UNWIND=1",
                            "-DPROFILER_PRECISE_STACK_BOUNDS=1", '-DPROFILER_USER_CONFIG="profiler_test_config.h"',
                            "tests/test_unwind.c", "mcu/sampling_profiler_unwind.c", "-o", str(binary)], cwd=ROOT, check=True)
            subprocess.run([str(binary)], check=True)

    def test_firmware_storage_with_every_pmu_count(self):
        for count in range(5):
            for available in [True, False]:
                with self.subTest(count=count, available=available), tempfile.TemporaryDirectory() as tmp:
                    binary, capture = Path(tmp) / "test", Path(tmp) / "capture.bin"
                    flags = [] if available else ["-DTEST_UNAVAILABLE"]
                    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Imcu", "-Itests/fakes",
                        "-DPROFILER_STACK_UNWIND=1", "-DPROFILER_PRECISE_STACK_BOUNDS=1", f"-DPROFILER_PMU_COUNT={count}",
                        '-DPROFILER_USER_CONFIG="profiler_test_config.h"', "tests/test_unwind_store.c", "mcu/sampling_profiler.c",
                        "-o", str(binary)] + flags, cwd=ROOT, check=True)
                    subprocess.run([str(binary), str(capture)], check=True)
                    h, samples = analyzer.read_capture(capture.read_bytes())
                    active = count if available else 0
                    self.assertEqual(h["record_base_bytes"], 28 + 4 * active)
                    self.assertEqual(h["unwind_max_depth"], 16)
                    self.assertEqual(samples[0][6:6 + active], tuple(range(100, 100 + active)))
                    folded, _, _ = analyzer.analyze_backtraces(h, samples,
                        [(0x1000, 16, "leaf"), (0x2000, 16, "caller")], [(0x1000, 0x1100)])
                    self.assertEqual(folded, {"caller;leaf": 1})

    def test_variable_storage_limits_and_full_buffer(self):
        for maximum in (1, 4, 16, 32):
            for pmu in (0, 4):
                with self.subTest(maximum=maximum, pmu=pmu), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / "config.h").write_text('#include "profiler_test_config.h"\n'
                        '#undef PROFILER_SAMPLE_BUFFER_BYTES\n#define PROFILER_SAMPLE_BUFFER_BYTES 512U\n')
                    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Imcu", "-Itests/fakes",
                        "-I" + tmp, '-DPROFILER_USER_CONFIG="config.h"', "-DPROFILER_STACK_UNWIND=1",
                        "-DPROFILER_PRECISE_STACK_BOUNDS=1", "-DTEST_MIXED", f"-DPROFILER_UNWIND_MAX_DEPTH={maximum}",
                        f"-DPROFILER_PMU_COUNT={pmu}", "tests/test_unwind_store.c", "mcu/sampling_profiler.c",
                        "-o", str(root / "test")], cwd=ROOT, check=True)
                    subprocess.run([str(root / "test"), str(root / "capture.bin")], check=True)
                    h, samples = analyzer.read_capture((root / "capture.bin").read_bytes())
                    self.assertEqual(h["unwind_max_depth"], maximum)
                    self.assertEqual(h["full"], 1)
                    self.assertEqual(h["bytes_used"], sum(len(sample) * 4 for sample in samples))
                    self.assertEqual(samples[1][6 + pmu], 0)
                    self.assertEqual(samples[2][6 + pmu], maximum)
                    self.assertLess(h["bytes_used"], len(samples) * (h["record_base_bytes"] + 4 * maximum))

    def test_variable_capture_truncation(self):
        original = self.capture(0, 2, [0x2005, 0x3005])
        for offset, value in [(4 * 4, 32), (4 * 4, 40), (5 * 4, 0), (5 * 4, 2),
                              (41 * 4, 1), (analyzer.HEADER.size + 24, 17)]:
            data = bytearray(original)
            analyzer.struct.pack_into("<I", data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                analyzer.read_capture(data)

    def test_interrupted_registers_and_task_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.h").write_text('#include <stdint.h>\nextern uint32_t unwind_stacks[128];\n'
                '#define PROFILER_DEVICE_HEADER "fake_device.h"\n#define PROFILER_SAMPLE_BUFFER_BYTES 512\n'
                '#define PROFILER_STACK_REGIONS {{(uintptr_t)unwind_stacks,sizeof(unwind_stacks)}}\n')
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-pie", "-no-pie",
                "-fsanitize=undefined", "-Imcu", "-Itests/fakes", "-I" + tmp, '-DPROFILER_USER_CONFIG="config.h"',
                "-DPROFILER_STACK_UNWIND=1", "-DPROFILER_PRECISE_STACK_BOUNDS=1", "-DPROFILER_TIMESTAMP_CUSTOM=1",
                "-D__DCACHE_PRESENT=0", "tests/test_unwind_entry.c", "mcu/sampling_profiler.c",
                "mcu/sampling_profiler_cortex_m.c", "-o", str(root / "test")], cwd=ROOT, check=True)
            subprocess.run([str(root / "test")], check=True)

    @staticmethod
    def capture(pmu, metadata, callers):
        callers = callers[:metadata & 255]
        stride = 28 + 4 * pmu + 4 * len(callers)
        fields = [analyzer.MAGIC, analyzer.FORMAT_VERSION, 28 + 4 * pmu, analyzer.HEADER.size + stride,
                  stride, 1, 0, 0, 1000000, 1000, 0, 0, 1000, 1, 1, 1, 1, 1, 1000, 1000000] + [0] * 22 + [analyzer.HEADER.size, 0]
        if pmu:
            fields[24:27] = [2, pmu, pmu]
            fields[27:27 + pmu] = [3, 36, 8, 17][:pmu]
            fields[31] = 32
        fields[41] = 16
        fields[43] = (1 if pmu else 0) | 2
        record = [1000, 1, 0x1004, 0x2001, 1 << 24, 0xFFFFFFFD] + [0] * pmu + [metadata] + callers
        return analyzer.HEADER.pack(*fields) + analyzer.struct.pack("<" + "I" * len(record), *record)

    def test_record_stride_and_folded_order(self):
        functions = [(0x1000, 16, "leaf"), (0x2000, 16, "parent"), (0x3000, 16, "root")]
        for pmu in range(5):
            with self.subTest(pmu=pmu):
                header, samples = analyzer.read_capture(self.capture(pmu, 2, [0x2005, 0x3005] + [0] * 14))
                self.assertEqual(header["record_base_bytes"], 28 + 4 * pmu)
                folded, details, counts = analyzer.analyze_backtraces(header, samples, functions, [(0x1000, 0x3000)])
                self.assertEqual(folded, {"root;parent;leaf": 1})
                self.assertEqual(counts, {"complete": 1})
                self.assertEqual(details[0]["unwind_status"], "complete")
                self.assertEqual(analyzer.analyze(header, samples, functions)[0][0]["hits"], 1)

    def test_partial_and_invalid_traces_keep_pc(self):
        functions = [(0x1000, 16, "leaf"), (0x2000, 16, "parent")]
        cases = [(1 | (1 << 8), [0x2005] + [0] * 15, "no_table", "parent;leaf"),
                 (1, [0x9999] + [0] * 15, "invalid_trace", None),
                 (1, [0x2004] + [0] * 15, "invalid_trace", None),
                 (1 | (7 << 8), [0x2005] + [0] * 15, "invalid_trace", None),
                 (1 | (6 << 8), [0x2005] + [0] * 15, "invalid_trace", None)]
        for metadata, callers, status, stack in cases:
            with self.subTest(metadata=metadata, callers=callers):
                header, samples = analyzer.read_capture(self.capture(0, metadata, callers))
                folded, _, counts = analyzer.analyze_backtraces(header, samples, functions, [(0x1000, 0x1100)])
                self.assertEqual(folded, {stack: 1} if stack else {})
                self.assertEqual(counts, {status: 1})
                self.assertEqual(analyzer.analyze(header, samples, functions)[0][0]["function"], "leaf")

    def test_recursion_return_boundary_and_delimiters(self):
        header, samples = analyzer.read_capture(self.capture(0, 16 | (6 << 8), [0x2011] * 16))
        folded, _, _ = analyzer.analyze_backtraces(header, samples,
            [(0x1000, 16, "leaf"), (0x2000, 16, "recursive;name\n")], [(0x1000, 0x1010)])
        self.assertEqual(folded, {"recursive:name ;" * 16 + "leaf": 1})

    def test_function_entry_preserves_pc_and_raw_callers(self):
        functions = [(0x1000, 16, "leaf"), (0x2000, 16, "parent")]
        raw = [0x2005] + [0] * 15
        for pmu in range(5):
            for pc in (0x1000, 0x1001, 0x1002):
                with self.subTest(pmu=pmu, pc=pc):
                    header, samples = analyzer.read_capture(self.capture(pmu, 1, raw))
                    sample = list(samples[0])
                    sample[2] = pc
                    folded, details, counts = analyzer.analyze_backtraces(
                        header, [sample], functions, [(0x1000, 0x2000)])
                    entry = (pc & ~1) == 0x1000
                    status = "function_entry" if entry else "complete"
                    stack = None if entry else "parent;leaf"
                    self.assertEqual(folded, {stack: 1} if stack else {})
                    self.assertEqual(counts, {status: 1})
                    self.assertEqual(details[0]["unwind_status"], status)
                    self.assertEqual(json.loads(details[0]["callers_raw"]), [f"0x{x:08x}" for x in raw[:1]])
                    self.assertEqual(analyzer.analyze(header, [sample], functions)[0][0]["hits"], 1)

    def test_lr_only_entry_metadata_and_caller_agreement(self):
        # An allocated exidx at 0x3000, with a merged finish range [0x1000,0x2000).
        data = bytearray(108)
        analyzer.struct.pack_into("<I", data, 32, 52)
        analyzer.struct.pack_into("<HH", data, 46, 40, 1)
        analyzer.struct.pack_into("<10I", data, 52, 0, 0x70000001, 2, 0x3000, 92, 16, 0, 0, 4, 8)
        analyzer.struct.pack_into("<4I", data, 92, (-0x2000) & 0x7fffffff, 0x80B0B0B0,
                                  (-0x1008) & 0x7fffffff, 0x808408B0)
        functions = [(0x1000, 16, "leaf"), (0x1100, 16, "merged"), (0x2000, 16, "parent")]
        safe = analyzer.lr_only_entries(data, functions)
        self.assertEqual(safe, {0x1000, 0x1100})
        header, samples = analyzer.read_capture(self.capture(0, 1, [0x2005] + [0] * 15))
        sample = list(samples[0])
        sample[2] = 0x1000
        sample[3] = 0x2005
        folded, _, _ = analyzer.analyze_backtraces(header, [sample], functions, [(0x1000, 0x2000)], safe)
        self.assertEqual(folded, {"parent;leaf": 1})
        sample[3] = 0x2009
        folded, _, counts = analyzer.analyze_backtraces(header, [sample], functions, [(0x1000, 0x2000)], safe)
        self.assertEqual(counts, {"function_entry": 1})
        analyzer.struct.pack_into("<I", data, 96, 1)  # CANTUNWIND never qualifies.
        self.assertEqual(analyzer.lr_only_entries(data, functions), set())

    def test_stack_root_and_exclusion_accounting(self):
        functions = [(0x1000, 16, "leaf"), (0x2000, 16, "parent"), (0x3000, 16, "root")]
        header, samples = analyzer.read_capture(self.capture(0, 2 | (1 << 8), [0x2005, 0x3005] + [0] * 14))
        folded, details, _ = analyzer.analyze_backtraces(header, samples, functions, [(0x1000, 0x3000)], stack_root="parent")
        self.assertEqual(folded, {"parent;leaf": 1})
        self.assertEqual(json.loads(details[0]["callchain"]), ["root", "parent", "leaf"])
        summary = analyzer.flamegraph_summary(details, "parent")
        self.assertEqual(summary["included_samples"], 1)
        self.assertEqual(summary["partial_samples"], 1)
        folded, details, _ = analyzer.analyze_backtraces(header, samples, functions, [(0x1000, 0x3000)], stack_root="missing")
        self.assertEqual(folded, {})
        self.assertEqual(analyzer.flamegraph_summary(details)["excluded_root_missing"], 1)
        entry = list(samples[0]); entry[2] = 0x1000
        folded, details, _ = analyzer.analyze_backtraces(header, [entry], functions, [(0x1000, 0x3000)], stack_root="missing")
        self.assertEqual(analyzer.flamegraph_summary(details)["excluded_unreliable"], 1)
        self.assertEqual(analyzer.flamegraph_summary(details)["excluded_root_missing"], 0)

    def test_bad_format_and_stride(self):
        original = self.capture(0, 0, [0] * 16)
        for offset, value in [(41 * 4, 256), (2 * 4, 24)]:
            data = bytearray(original)
            analyzer.struct.pack_into("<I", data, offset, value)
            with self.assertRaises(ValueError):
                analyzer.read_capture(data)
