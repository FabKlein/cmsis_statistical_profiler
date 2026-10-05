# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_ethosu_trace.py
# Description:  Ethos-U capture decoder regression tests
#
# $Date:        5 October 2026
# $Revision:    V.1.0.3
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""EUTR decoder checks independent of board tooling."""

import contextlib
import io
import csv
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "host" / "analyze_ethosu_trace.py"
SPEC = importlib.util.spec_from_file_location("analyze_ethosu_trace", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def trace(device=55, pmu_count=0, count=None, samples=None, streams=None):
    if samples is None:
        samples = [(123, 10, 1, 16)]
    if streams is None:
        streams = [(0x1000, 64)]
    samples = [
        (*sample, int(bool(sample[2] & 1))) if len(sample) == 4 else sample
        for sample in samples
    ]
    payload = b"".join(
        struct.pack(f"<{5 + pmu_count}I", *sample, *range(pmu_count))
        for sample in samples
    )
    stream_capacity = 2
    offset = 128 + 8 * stream_capacity
    buffer_bytes = ((offset + max(36, len(payload)) + 31) // 32) * 32
    header = [0] * 32
    header[0:5] = [MODULE.MAGIC, 1, 128, 20 + 4 * pmu_count, buffer_bytes]
    header[5] = len(samples) if count is None else count
    header[8] = 1
    header[9:11] = [2000, 400000000]
    header[11] = pmu_count
    header[12] = 1 if pmu_count else 0
    header[17] = len(streams)
    header[18] = len(streams)
    header[19] = sum(
        bool(status & 1) and qread == MODULE.NO_QREAD
        for _, _, status, qread, _ in samples
    )
    header[26] = device
    header[27] = stream_capacity
    header[28] = sum(
        bool(status & 1) and not stream_id for _, _, status, _, stream_id in samples
    )
    descriptors = b"".join(struct.pack("<II", *stream) for stream in streams)
    descriptors += bytes((stream_capacity - len(streams)) * 8)
    return (
        struct.pack("<32I", *header)
        + descriptors
        + payload
        + bytes(buffer_bytes - offset - len(payload))
    )


def change_header(data, **fields):
    result = bytearray(data)
    for name, value in fields.items():
        struct.pack_into("<I", result, MODULE.HEADER_FIELDS.index(name) * 4, value)
    return bytes(result)


class EthosuTraceTest(unittest.TestCase):
    def test_variants_and_records(self):
        for device in (55, 65, 85):
            for pmu_count in range(5):
                summary, records = MODULE.decode(trace(device, pmu_count))
                self.assertEqual(summary["device_type"], device)
                self.assertEqual(summary["running_percent"], 100.0)
                self.assertEqual(records[0]["qread"], 16)
                self.assertEqual(
                    len([key for key in records[0] if key.startswith("pmu")]), pmu_count
                )

    def test_rejects_truncated_or_wrong_count(self):
        with self.assertRaises(ValueError):
            MODULE.decode(trace()[:-4])
        with self.assertRaises(ValueError):
            MODULE.decode(trace(count=10))

    def test_rejects_unfinished_flags_and_invalid_frequencies(self):
        for fields in (
            {"active": 1},
            {"complete": 0},
            {"active": 2},
            {"complete": 2},
            {"full": 2},
            {"validation_passed": 2},
            {"sample_hz": 0},
            {"timestamp_hz": 0},
            {"full": 1},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                MODULE.decode(change_header(trace(), **fields))
        # A stopped full buffer and failed workload validation are still valid data.
        data = trace(samples=[(n, n, 0, MODULE.NO_QREAD) for n in range(4)])
        summary, _ = MODULE.decode(change_header(data, full=1, validation_passed=0))
        self.assertEqual(summary["full"], 1)
        summary, records = MODULE.decode(trace(samples=[]))
        self.assertEqual(records, [])
        self.assertEqual(summary["running_percent"], 0)

    def test_pmu_status_and_unused_events(self):
        cases = [
            change_header(trace(), pmu_status=1),
            change_header(trace(), pmu_status=3),
            change_header(trace(), pmu_event0=1),
            change_header(trace(pmu_count=1), pmu_status=0),
            change_header(trace(pmu_count=1), pmu_status=2),
            change_header(trace(pmu_count=1), pmu_event1=1),
        ]
        for data in cases:
            with self.subTest(data=data[:68]), self.assertRaises(ValueError):
                MODULE.decode(data)
        summary, _ = MODULE.decode(change_header(trace(), pmu_status=2))
        self.assertEqual(summary["pmu_count"], 0)

    def test_qread_validation_and_stream_identity(self):
        for sample in [
            (1, 1, 1, 3, 1),
            (1, 1, 0, 16, 0),
            (1, 1, 1, 68, 1),
            (1, 1, 1, 16, 3),
            (1, 1, 0, MODULE.NO_QREAD, 1),
        ]:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                MODULE.decode(trace(samples=[sample]))
        # Bounds are associated with IDs, including earlier streams.
        MODULE.decode(
            trace(samples=[(1, 1, 1, 64, 1)], streams=[(0x1000, 64), (0x2000, 4)])
        )
        MODULE.decode(trace(samples=[(1, 1, 1, 80, 0)]))
        missing = trace(samples=[(1, 1, 1, MODULE.NO_QREAD, 1)])
        MODULE.decode(missing)
        with self.assertRaisesRegex(ValueError, "invalid_qread"):
            MODULE.decode(change_header(missing, invalid_qread=0))
        with self.assertRaisesRegex(ValueError, "unknown_stream_samples"):
            MODULE.decode(change_header(trace(), unknown_stream_samples=1))

    def test_stream_table_validation(self):
        for fields in (
            {"stream_capacity": 0},
            {"stream_capacity": 65},
            {"stream_count": 3},
            {"streams_seen": 0},
            {"unregistered_streams": 1},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                MODULE.decode(change_header(trace(), **fields))
        for streams in (
            [(0x1001, 64)],
            [(0x1000, 3)],
            [(0x1000, 0)],
            [(0xFFFFFFFC, 8)],
            [(0x1000, 64), (0x1000, 64)],
        ):
            with self.subTest(streams=streams), self.assertRaises(ValueError):
                MODULE.decode(trace(streams=streams))
        data = bytearray(trace())
        struct.pack_into("<I", data, 136, 1)
        with self.assertRaisesRegex(ValueError, "unused stream"):
            MODULE.decode(data)
        with self.assertRaisesRegex(ValueError, "EUTR v1"):
            MODULE.decode(change_header(trace(), version=2))

    def test_histogram_separates_streams_and_excludes_unknown(self):
        summary, records = MODULE.decode(
            trace(
                streams=[(0x1000, 64), (0x2000, 64)],
                samples=[
                    (1, 1, 1, 16, 1),
                    (2, 2, 1, 16, 2),
                    (3, 3, 1, 16, 1),
                    (4, 4, 1, 16, 0),
                ],
            )
        )
        histogram = MODULE.qread_histogram(records)
        self.assertEqual(
            [(r["stream_id"], r["qread_bytes"], r["samples"]) for r in histogram],
            [(1, 16, 2), (2, 16, 1)],
        )
        self.assertEqual(summary["unknown_stream_samples"], 1)
        self.assertEqual(len(summary["streams"]), 2)

    def test_rejects_reserved_words_and_misaligned_allocation(self):
        data = bytearray(trace())
        struct.pack_into("<I", data, 120, 1)
        with self.assertRaisesRegex(ValueError, "reserved"):
            MODULE.decode(data)
        data = trace() + bytes(4)
        with self.assertRaisesRegex(ValueError, "alignment"):
            MODULE.decode(change_header(data, buffer_bytes=len(data)))

    def test_cli_rejects_capture_before_writing_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump, output = root / "active.bin", root / "report"
            dump.write_bytes(change_header(trace(), active=1, complete=0))
            errors = io.StringIO()
            with (
                mock.patch(
                    "sys.argv",
                    [str(SCRIPT), "--samples", str(dump), "--output", str(output)],
                ),
                contextlib.redirect_stderr(errors),
            ):
                with self.assertRaises(SystemExit) as result:
                    MODULE.main()
            self.assertEqual(result.exception.code, 1)
            self.assertIn("capture not stopped/completed", errors.getvalue())
            self.assertFalse(output.exists())

    def test_qread_histogram_excludes_idle_and_missing_offsets(self):
        samples = [
            (10, 1, 1, 16),
            (20, 2, 0, MODULE.NO_QREAD),
            (30, 3, 1, 32),
            (40, 4, 1, 16),
            (50, 5, 1, MODULE.NO_QREAD),
            (60, 6, 1, 32),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "trace.bin"
            output = root / "report"
            dump.write_bytes(trace(samples=samples))
            with mock.patch(
                "sys.argv",
                [str(SCRIPT), "--samples", str(dump), "--output", str(output)],
            ):
                MODULE.main()
            with (output / "qread_histogram.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["qread_bytes"] for row in rows], ["16", "32"])
            self.assertEqual([row["samples"] for row in rows], ["2", "2"])
            self.assertEqual(
                [row["percent_of_running_samples"] for row in rows], ["40.0", "40.0"]
            )
            self.assertEqual(
                [row["percent_of_all_samples"] for row in rows], ["33.33", "33.33"]
            )


if __name__ == "__main__":
    unittest.main()
