"""EUTR decoder checks independent of board tooling."""

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


def trace(device=55, pmu_count=0, count=None, samples=None):
    if samples is None:
        samples = [(123, 10, 1, 16)]
    payload = b"".join(
        struct.pack(f"<{4 + pmu_count}I", *sample, *range(pmu_count)) for sample in samples
    )
    buffer_bytes = 128 + max(32, len(payload))
    header = [0] * 32
    header[0:5] = [MODULE.MAGIC, 1, 128, 16 + 4 * pmu_count, buffer_bytes]
    header[5] = len(samples) if count is None else count
    header[8] = 1
    header[9:11] = [2000, 400000000]
    header[11] = pmu_count
    header[26] = device
    return struct.pack("<32I", *header) + payload + bytes(buffer_bytes - 128 - len(payload))


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
                "sys.argv", [str(SCRIPT), "--samples", str(dump), "--output", str(output)]
            ):
                MODULE.main()
            with (output / "qread_histogram.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["qread_bytes"] for row in rows], ["16", "32"])
            self.assertEqual([row["samples"] for row in rows], ["2", "2"])
            self.assertEqual([row["percent_of_running_samples"] for row in rows], ["40.0", "40.0"])
            self.assertEqual([row["percent_of_all_samples"] for row in rows], ["33.33", "33.33"])


if __name__ == "__main__":
    unittest.main()
