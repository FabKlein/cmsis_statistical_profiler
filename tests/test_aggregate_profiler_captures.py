# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_aggregate_profiler_captures.py
# Description:  Aggregate configuration, empty captures and histogram regressions
#
# $Date:        6 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from test_ethosu_trace import MODULE as DECODER
from test_ethosu_trace import trace

SCRIPT = Path(__file__).resolve().parents[1] / "host/aggregate_profiler_captures.py"
SPEC = importlib.util.spec_from_file_location("aggregate_profiler_captures", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def capture(path, samples, extra_histogram_hits=0, cpu_empty=False):
    cpu = path / "cortex_m_report"
    npu = path / "ethosu_report"
    cpu.mkdir(parents=True)
    npu.mkdir()
    header = {
        "sample_hz": 2000,
        "pmu": {
            "count": 1,
            "requested": 1,
            "events": [3],
            "status": "active",
            "counter_bits": 32,
            "scope": "init_to_stop_all_execution",
            "start": [0],
            "stop": [10],
            "flags": 0,
        },
        "timestamp_hz": 400000000,
        "timer_hz": 100000000,
        "timer_period": 50000,
        "version": 2,
        "features": 1,
        "unwind_max_depth": 0,
        "buffer_bytes": 256,
        "record_base_bytes": 28,
        "complete": 1,
        "active": 0,
        "count": 0 if cpu_empty else 1,
        "rejected": 0,
        "full": 0,
        "validation_passed": 1,
        "iterations": 1,
    }
    (cpu / "summary.json").write_text(
        json.dumps(
            {
                "header": header,
                "elf_sha256": "same-test-elf",
                "unknown_samples": 0,
                "timing_valid": True,
            }
        )
    )
    MODULE.write_csv(
        cpu / "samples.csv",
        ["pc", "pmu0_raw"],
        [] if cpu_empty else [{"pc": "0x1000", "pmu0_raw": 10}],
    )
    MODULE.write_csv(
        cpu / "functions.csv",
        ["address", "function", "hits"],
        [] if cpu_empty else [{"address": "0x1000", "function": "worker", "hits": 1}],
    )

    # Feed the aggregator actual decoder output, including blank QREAD sentinels.
    summary, records = DECODER.decode(
        trace(samples=samples, streams=None if samples else [], pmu_count=1)
    )
    (npu / "summary.json").write_text(json.dumps(summary))
    MODULE.write_csv(
        npu / "samples.csv",
        [
            "timestamp",
            "tick",
            "status",
            "running",
            "stream_id",
            "idle_count",
            "sample_count",
            "qread",
            "pmu0",
        ],
        records,
    )
    MODULE.write_csv(
        npu / "streams.csv",
        ["stream_id", "command_address", "stream_bytes"],
        summary["streams"],
    )
    histogram = DECODER.qread_histogram(records)
    if extra_histogram_hits:
        histogram[0]["samples"] += extra_histogram_hits
    MODULE.write_csv(
        npu / "qread_histogram.csv",
        [
            "stream_id",
            "qread_bytes",
            "samples",
            "percent_of_running_samples",
            "percent_of_all_samples",
        ],
        histogram,
    )
    return path


class AggregateTests(unittest.TestCase):
    def test_rejects_incompatible_metadata_before_output(self):
        cases = [
            ("cpu", ("pmu", "events"), [4]),
            ("cpu", ("pmu", "requested"), 2),
            ("cpu", ("pmu", "status"), "unavailable"),
            ("cpu", ("pmu", "counter_bits"), 16),
            ("cpu", ("pmu", "scope"), "different"),
            ("cpu", ("timestamp_hz",), 200000000),
            ("cpu", ("timer_hz",), 80000000),
            ("cpu", ("timer_period",), 40000),
            ("cpu", ("version",), 3),
            ("cpu", ("features",), 3),
            ("cpu", ("unwind_max_depth",), 16),
            ("npu", ("pmu_event0",), 4),
            ("npu", ("pmu_status",), 2),
            ("npu", ("device_type",), 85),
            ("npu", ("timestamp_hz",), 200000000),
            ("npu", ("version",), 2),
        ]
        for processor, keys, value in cases:
            with (
                self.subTest(processor=processor, keys=keys),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                paths = [capture(root / str(i), [(1, 1, 1, 16, 1)]) for i in range(2)]
                report = "cortex_m_report" if processor == "cpu" else "ethosu_report"
                path = paths[1] / report / "summary.json"
                summary = json.loads(path.read_text())
                field = summary["header"] if processor == "cpu" else summary
                for key in keys[:-1]:
                    field = field[key]
                field[keys[-1]] = value
                path.write_text(json.dumps(summary))
                with self.assertRaisesRegex(ValueError, "configuration differs"):
                    MODULE.aggregate(paths, root / "output")
                self.assertFalse((root / "output").exists())

    def test_counter_values_can_differ_between_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [capture(root / str(i), [(1, 1, 1, 16, 1)]) for i in range(2)]
            path = paths[1] / "cortex_m_report/summary.json"
            summary = json.loads(path.read_text())
            summary["header"]["pmu"].update(start=[50], stop=[100], flags=1)
            path.write_text(json.dumps(summary))
            result = MODULE.aggregate(paths, root / "output")
            self.assertEqual(result["capture_configuration"]["cpu_pmu"]["events"], [3])

    def test_empty_cpu_npu_or_both_keep_csv_headers(self):
        for cpu_empty, npu_empty in ((True, False), (False, True), (True, True)):
            with (
                self.subTest(cpu_empty=cpu_empty, npu_empty=npu_empty),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                path = capture(
                    root / "capture",
                    [] if npu_empty else [(1, 1, 1, 16, 1)],
                    cpu_empty=cpu_empty,
                )
                result = MODULE.aggregate([path], root / "output")
                self.assertEqual(result["cpu_samples"], 0 if cpu_empty else 1)
                self.assertEqual(result["ethosu_records"], 0 if npu_empty else 1)
                for filename in ("cortex_m_samples.csv", "ethosu_samples.csv"):
                    self.assertTrue(
                        (root / "output" / filename).read_text().startswith("capture,")
                    )
                if npu_empty:
                    self.assertEqual(result["ethosu_running_percent"], 0.0)
                    self.assertEqual(result["stream_identity"], [])

    def test_empty_and_nonempty_captures_in_either_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = capture(root / "empty", [], cpu_empty=True)
            full = capture(root / "full", [(1, 1, 1, 16, 1)])
            for i, paths in enumerate(([empty, full], [full, empty])):
                result = MODULE.aggregate(paths, root / f"output{i}")
                self.assertEqual(result["captures"], 2)
                self.assertEqual(result["cpu_samples"], 1)
                self.assertEqual(result["ethosu_ticks"], 1)
                self.assertEqual(len(result["stream_identity"]), 1)

    def test_mismatched_csv_schema_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [capture(root / str(i), [], cpu_empty=True) for i in range(2)]
            (paths[1] / "cortex_m_report/samples.csv").write_text("pc,unexpected\n")
            with self.assertRaisesRegex(ValueError, "sample columns differ"):
                MODULE.aggregate(paths, root / "output")
            self.assertFalse((root / "output").exists())

    def test_unknown_qread_is_excluded_from_hotspots_but_keeps_running_time(self):
        # Unknown valid/invalid QREAD, known valid/invalid QREAD, compressed idle.
        samples = [
            (1, 1, 1, 16, 0),
            (2, 2, 1, DECODER.NO_QREAD, 0),
            (3, 3, 1, 32, 1),
            (4, 4, 1, DECODER.NO_QREAD, 1),
            (8, 8, 0, DECODER.NO_QREAD, 4),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [capture(root / str(i), samples) for i in range(2)]
            result = MODULE.aggregate(paths, root / "output")
            self.assertEqual(result["ethosu_ticks"], 16)
            self.assertEqual(result["ethosu_running_ticks"], 8)
            self.assertEqual(result["ethosu_unknown_stream_samples"], 4)
            self.assertEqual(result["ethosu_running_percent"], 50.0)
            rows = MODULE.read_csv(root / "output/ethosu_qread_histogram.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(int(rows[0]["samples"]), 2)
            self.assertEqual(float(rows[0]["percent_of_running_samples"]), 25.0)

    def test_only_unknown_streams_allow_empty_histogram(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = capture(root / "capture", [(1, 1, 1, 16, 0)])
            result = MODULE.aggregate([path], root / "output")
            self.assertEqual(result["ethosu_running_percent"], 100.0)
            self.assertEqual(
                MODULE.read_csv(root / "output/ethosu_qread_histogram.csv"), []
            )

    def test_incorrect_histogram_count_still_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = capture(root / "capture", [(1, 1, 1, 16, 1)], extra_histogram_hits=1)
            with self.assertRaisesRegex(ValueError, "histogram totals"):
                MODULE.aggregate([path], root / "output")
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
