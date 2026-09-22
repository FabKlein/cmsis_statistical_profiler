# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_profiler.py
# Description:  Native capture and Python decoder regression tests
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Run with python3 -B -m unittest discover -s tests -v (requires native cc)."""
import importlib.util
import itertools
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analyzer", ROOT / "host/analyze_samples.py")
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)


class ProfilerTests(unittest.TestCase):
    def test_native_capture_and_decoder(self):
        for cache, rate in itertools.product([0, 1], [1, 125, 333, 2500]):
            with self.subTest(cache=cache, rate=rate), tempfile.TemporaryDirectory() as tmp:
                binary = Path(tmp) / "test_capture"
                capture = Path(tmp) / "samples.bin"
                sources = ["tests/test_capture.c", "mcu/sampling_profiler.c",
                           "mcu/sampling_profiler_cortex_m.c"]
                defines = [f"-DPROFILER_SAMPLE_HZ={rate}"]
                subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                f"-D__DCACHE_PRESENT={cache}", "-Itests/fakes", "-Imcu", '-DPROFILER_USER_CONFIG="profiler_test_config.h"' ] + defines +
                               sources + ["-o", str(binary)], cwd=ROOT, check=True)
                subprocess.run([str(binary), str(capture)], check=True)
                header, samples = analyzer.read_capture(capture.read_bytes())
                self.assertEqual(header["count"], 3)
                self.assertEqual(header["version"], 1)
                self.assertEqual(header["record_size"], 24)
                self.assertEqual(len(samples[0]), 6)
                self.assertEqual(header["sample_hz"], rate)
                self.assertAlmostEqual(analyzer.nominal_sample_hz(header),
                                       header["timer_hz"] / header["timer_period"])
                rows, timeline, unknown, timing = analyzer.analyze(header, samples, [(0x10001000, 32, "workload")])
                self.assertEqual((rows[0]["hits"], unknown), (3, 0))
                self.assertEqual(len(timeline), 3)

    def test_architecture_and_custom_timestamp(self):
        for core, v8, fpu in [(0, False, 0), (1, False, 0), (3, False, 0), (4, False, 1),
                              (7, False, 1), (23, True, 0), (33, True, 1), (35, True, 1),
                              (52, True, 1), (55, True, 1), (85, True, 1)]:
            for secure in ([False, True] if v8 else [False]):
                with self.subTest(core=core, secure=secure), tempfile.TemporaryDirectory() as tmp:
                    binary, capture = Path(tmp) / "test", Path(tmp) / "capture.bin"
                    flags = [f"-D__CORTEX_M={core}", f"-D__FPU_PRESENT={fpu}",
                             "-D__DCACHE_PRESENT=0", "-DPROFILER_TIMESTAMP_CUSTOM=1",
                             "-DPROFILER_SAMPLE_HZ=333", "-DPROFILER_PRECISE_STACK_BOUNDS=1"]
                    if v8:
                        flags += ["-DTEST_V8"]
                    if not secure:
                        flags += ["-DTEST_NONSECURE"]
                    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                    "-Imcu", "-Itests/fakes", '-DPROFILER_USER_CONFIG="profiler_test_config.h"'] +
                                   flags + ["tests/test_architecture.c", "mcu/sampling_profiler.c",
                                            "mcu/sampling_profiler_cortex_m.c", "-o", str(binary)],
                                   cwd=ROOT, check=True)
                    subprocess.run([str(binary), str(capture)], check=True)
                    header, samples = analyzer.read_capture(capture.read_bytes())
                    self.assertEqual(header["timestamp_hz"], 1000000)
                    reasons = header["rejected_reasons"]
                    self.assertEqual(reasons, dict(invalid_exc_return=1,
                        unsupported_frame=3 if fpu else 4, stack_bounds=0, invalid_xpsr=0))
                    self.assertNotIn("clock_hz", header)
                    rows, timeline, unknown, timing = analyzer.analyze(header, samples, [(0x10001000, 32, "workload")])
                    self.assertEqual((rows[0]["hits"], unknown), (3, 0))
                    self.assertEqual(timeline[0]["timestamp_ticks_since_start"], 15015)
                    self.assertEqual(timeline[0]["time_us"], 15015)

    def test_pmu_capture(self):
        for count in range(5):
            for available in [False, True]:
                with self.subTest(count=count, available=available), tempfile.TemporaryDirectory() as tmp:
                    binary, capture = Path(tmp) / "test", Path(tmp) / "capture.bin"
                    flags = ["-DTEST_PMU"] if available else []
                    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-Imcu", "-Itests/fakes", f"-DPROFILER_PMU_COUNT={count}",
                        '-DPROFILER_USER_CONFIG="profiler_test_config.h"'] + flags +
                        ["tests/test_pmu.c", "mcu/sampling_profiler.c", "mcu/sampling_profiler_pmu.c",
                         "-o", str(binary)], cwd=ROOT, check=True)
                    subprocess.run([str(binary), str(capture)], check=True)
                    data = capture.read_bytes()
                    header, samples = analyzer.read_capture(data)
                    active = bool(count and available)
                    stride = 24 + (4 * count if active else 0)
                    capacity = (236 + 12 * count - analyzer.HEADER.size) // stride
                    self.assertEqual(header["pmu"]["status"], "disabled" if not count else "active" if available else "unavailable")
                    self.assertEqual(header["pmu"]["requested"], count)
                    self.assertEqual(header["record_size"], stride)
                    self.assertEqual(header["capacity"], capacity)
                    self.assertEqual(len(samples[0]), stride // 4)
                    events = analyzer.pmu_statistics(header)
                    self.assertEqual(len(events), count)
                    rows, timeline, unknown, timing = analyzer.analyze(header, samples, [(0x10001000, 32, "workload")])
                    self.assertEqual((rows[0]["hits"], unknown), (capacity, 0))
                    self.assertNotIn("pmu0", rows[0])
                    for event in range(count):
                        self.assertEqual(events[event]["count"], (event + 1) * 0x10000 + 3 * (5 + 2 * event) if active else None)
                        self.assertEqual(timeline[1][f"pmu{event}_interval_delta"], 5 + 2 * event if active else None)
                    with self.assertRaises(ValueError):
                        analyzer.read_capture(data[:120])
                    if active:
                        for flag in [1 << event for event in range(count)] + [16]:
                            flagged = bytearray(data)
                            analyzer.struct.pack_into("<I", flagged, 160, flag)
                            invalid, records = analyzer.read_capture(flagged)
                            self.assertTrue(all(event["count"] is None for event in analyzer.pmu_statistics(invalid)))
                            _, invalid_timeline, _, _ = analyzer.analyze(invalid, records, [])
                            self.assertIsNone(invalid_timeline[0]["pmu0_interval_delta"])
                    for offset, value in [(100, 5), (104, 5), (160, 32), (124, 16)]:
                        malformed = bytearray(data)
                        analyzer.struct.pack_into("<I", malformed, offset, value)
                        with self.subTest(offset=offset), self.assertRaises(ValueError):
                            analyzer.read_capture(malformed)

    def test_pmu_event_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            for count, event, valid in [(4, "0", True), (4, "0xFFFF", True), (4, "0x10000", False),
                                        (4, "-1", False), (4, "0x001E", False), (1, "0x10000", True)]:
                with self.subTest(count=count, event=event):
                    result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-Imcu", "-Itests/fakes", f"-DPROFILER_PMU_COUNT={count}",
                        f"-DPROFILER_PMU_EVENT3={event}", '-DPROFILER_USER_CONFIG="profiler_test_config.h"',
                        "-c", "mcu/sampling_profiler_pmu.c", "-o", str(Path(tmp) / "pmu.o")],
                        cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_dtcm_size_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "test_dtcm"
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-Itests/fakes", "-Imcu", '-DPROFILER_USER_CONFIG="profiler_dtcm_config.h"',
                            "tests/test_dtcm.c", "mcu/sampling_profiler.c", "mcu/sampling_profiler_cortex_m.c",
                            "-o", str(binary)], cwd=ROOT, check=True)
            subprocess.run([str(binary)], check=True)

    def test_shared_configuration(self):
        device = ['-DPROFILER_DEVICE_HEADER="fake_device.h"']
        defaults = ["-DPROFILER_DEFAULT_STACK_BASE=0x30000000U", "-DPROFILER_DEFAULT_STACK_BYTES=4096U"]
        explicit = ["-DPROFILER_STACK_BASE=0x20000000U", "-DPROFILER_STACK_BYTES=8192U"]
        cases = [(device + defaults, True), (device + defaults + explicit, True),
                 (device + defaults + ['-DPROFILER_STACK_REGIONS={{0x20000000U,8192U}}'], True),
                 (device, False), (defaults, False),
                 (device + defaults[:1], False),
                 (device + defaults + explicit[:1], False),
                 (device + explicit + ['-DPROFILER_STACK_REGIONS={{0U,4096U}}'], False)]
        for flags, valid in cases:
            with self.subTest(flags=flags):
                result = subprocess.run(["cc", "-std=c11", "-fsyntax-only", "-x", "c", "-Imcu"] + flags + ["-"],
                                        input='#include "sampling_profiler.h"\n', text=True,
                                        capture_output=True, cwd=ROOT)
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_timestamp_and_tick_wrap(self):
        self.assertEqual(analyzer.timestamp_delta(705032704, 50000, 0, 0,
                         100000000, 1000, 1000000), 5000000000)
        self.assertEqual(analyzer.timestamp_delta(200000, 1, 0, 0xFFFFFFFF,
                         100000000, 1000, 1000000), 200000)
        with self.assertRaises(ValueError):
            analyzer.timestamp_delta(100000, 200, 0, 0, 100000000, 1000, 1000000)
        with self.assertRaises(ValueError):
            analyzer.timestamp_delta(0, 0x80000000, 0, 0, 100000000, 1000, 1000000)

    def test_invalid_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "test_capture"
            common = ["cc", "-std=c11", "-O2", "-Itests/fakes", "-Imcu", '-DPROFILER_USER_CONFIG="profiler_test_config.h"' ]
            for rate in [37000000, 100000000, 100000001]:
                subprocess.run(common + [f"-DPROFILER_SAMPLE_HZ={rate}", "-DTEST_INVALID_RATE",
                               "tests/test_capture.c", "mcu/sampling_profiler.c", "mcu/sampling_profiler_cortex_m.c",
                               "-o", str(binary)], cwd=ROOT, check=True)
                subprocess.run([str(binary), "unused"], check=True)
            for define in ["-DPROFILER_SAMPLE_HZ=0", "-DPROFILER_PMU_COUNT=-1", "-DPROFILER_PMU_COUNT=5"]:
                result = subprocess.run(common + [define, "-c", "mcu/sampling_profiler.c",
                                        "-o", str(Path(tmp) / "invalid.o")], cwd=ROOT, capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    @staticmethod
    def capture_fields():
        return [analyzer.MAGIC, analyzer.FORMAT_VERSION, 24, analyzer.HEADER.size + 24, 1, 1, 0, 0,
                1000000, 1000, 0, 0, 1000, 1, 1, 1, 1, 1, 1000, 1000000] + [0] * 21

    def test_independent_timer_clock(self):
        fields = self.capture_fields()
        fields[8], fields[9], fields[18], fields[19] = 100000000, 111111, 333, 37000000
        timestamp = 111111 * 100000000 // 37000000
        fields[12] = timestamp  # Stop must follow the sample in the same clock domain.
        record = analyzer.RECORD.pack(timestamp, 1, 0x10001004, 0x10002001, 1 << 24, 0xFFFFFFF9)
        header, samples = analyzer.read_capture(analyzer.HEADER.pack(*fields) + record)
        self.assertAlmostEqual(analyzer.nominal_sample_hz(header), 333.000333000333)
        rows, timeline, unknown, timing = analyzer.analyze(header, samples, [(0x10001000, 32, "workload")])
        self.assertEqual((rows[0]["hits"], unknown), (1, 0))
        self.assertEqual(timeline[0]["timestamp_ticks_since_start"], timestamp)
        expected = 20000 * 111111 * 100000000 // 37000000
        self.assertEqual(analyzer.timestamp_delta(expected & 0xFFFFFFFF, 20000, 0, 0,
                                                 100000000, 111111, 37000000), expected)
        for index, value in [(9, 0), (9, 111112), (18, 0), (18, 37000001), (19, 0), (19, 40000000)]:
            changed = fields[:]
            changed[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                analyzer.read_capture(analyzer.HEADER.pack(*changed) + record)

    def test_diagnostics_and_empty_capture(self):
        fields = self.capture_fields()
        fields[6], fields[20:24] = 10, [1, 2, 3, 4]
        record = analyzer.RECORD.pack(1000, 1, 0x10001004, 0x10002001, 1 << 24, 0xFFFFFFB8)
        data = analyzer.HEADER.pack(*fields) + record
        header, _ = analyzer.read_capture(data)
        self.assertEqual(sum(header["rejected_reasons"].values()), 10)
        self.assertEqual(header["pmu"]["status"], "disabled")
        self.assertEqual(analyzer.pmu_statistics(header), [])
        fields[5] = 0
        header, samples = analyzer.read_capture(analyzer.HEADER.pack(*fields) + bytes(24))
        self.assertEqual(analyzer.analyze(header, samples, [])[:3], ([], [], 0))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "empty.csv"
            analyzer.write_csv(output, [], ["sample", "time_us"])
            self.assertEqual(output.read_text(), "sample,time_us\n")
        fields[23] = 5
        with self.assertRaises(ValueError):
            analyzer.read_capture(analyzer.HEADER.pack(*fields) + record)

    def test_format_rejections(self):
        fields = self.capture_fields()
        record = analyzer.RECORD.pack(1000, 1, 0x10001004, 0x10002001, 1 << 24, 0xFFFFFFF9)
        valid = analyzer.HEADER.pack(*fields) + record
        self.assertEqual(analyzer.read_capture(valid)[0]["count"], 1)
        for index, value in [(0, 0), (1, 99), (2, 32), (3, 159), (4, 0), (5, 2),
                             (7, 1), (8, 0), (9, 0), (15, 0), (18, 0), (24, 99),
                             (26, 3), (33, 8)]:
            changed = fields[:]
            changed[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                analyzer.read_capture(analyzer.HEADER.pack(*changed) + record)
        for invalid in [valid[:120], valid[:-1], valid + b"x"]:
            with self.assertRaises(ValueError):
                analyzer.read_capture(invalid)
        for index, value in [(4, 0), (4, (1 << 24) | 15), (5, 0xFFFFFFF1)]:
            words = list(analyzer.RECORD.unpack(record))
            words[index] = value
            with self.subTest(record_index=index), self.assertRaises(ValueError):
                analyzer.read_capture(analyzer.HEADER.pack(*fields) + analyzer.RECORD.pack(*words))


if __name__ == "__main__":
    unittest.main()
