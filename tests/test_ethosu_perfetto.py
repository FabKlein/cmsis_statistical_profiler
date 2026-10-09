# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_ethosu_perfetto.py
# Description:  Synchronized CPU/NPU Perfetto export regression tests
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
import combine_perfetto_captures as merger
import ethosu_perfetto
import test_combine_perfetto_captures as fixtures
from visualize_profiler_report import read_report


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class EthosuPerfettoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixtures.CombinedPerfettoTests().make_run(self.root)
        aggregate = json.loads((self.root / "summary.json").read_text())
        aggregate.update(ethosu_ticks=4, ethosu_records=4)
        (self.root / "summary.json").write_text(json.dumps(aggregate))
        with (self.root / "captures.csv").open() as stream:
            manifest = list(csv.DictReader(stream))
        for item in manifest:
            item.update(ethosu_ticks=2, ethosu_records=2)
            capture = self.root / item["capture_dir"]
            cpu = capture / "cortex_m_report"
            header = json.loads((cpu / "summary.json").read_text())["header"]
            with (cpu / "samples.csv").open() as stream:
                samples = list(csv.DictReader(stream))
            for i, sample in enumerate(samples):
                sample.update(
                    tick=i + 1,
                    timestamp=(header["start_timestamp"] + int(sample["time_us"]))
                    & 0xFFFFFFFF,
                )
            write_csv(cpu / "samples.csv", samples)
            npu = capture / "ethosu_report"
            npu.mkdir()
            summary = {
                "count": 2,
                "complete": 1,
                "active": 0,
                "validation_passed": 1,
                "full": 0,
                "device_type": 55,
                "sample_hz": 1000,
                "timestamp_hz": 1_000_000,
                "pmu_count": 2,
                "pmu_status": 1,
                "pmu_event0": 5,
                "pmu_event1": 5,
                "start_timestamp": (header["start_timestamp"] + 100) & 0xFFFFFFFF,
                "stop_timestamp": (header["stop_timestamp"] - 50) & 0xFFFFFFFF,
                "start_tick": 0,
                "stop_tick": 2,
                "total_samples": 2,
                "running_samples": 1,
                "idle_samples": 1,
                "unknown_stream_samples": 0,
                "invalid_qread": 0,
                "stream_count": 1,
                "streams": [
                    {"stream_id": 1, "stream_bytes": 64, "command_address": "0x1000"}
                ],
            }
            (npu / "summary.json").write_text(json.dumps(summary))
            records = [
                {
                    "timestamp": sample["timestamp"],
                    "tick": sample["tick"],
                    "status": int(i == 0),
                    "running": int(i == 0),
                    "qread": 4 if i == 0 else "",
                    "stream_id": int(i == 0),
                    "idle_count": i,
                    "sample_count": 1,
                    "pmu0": 0xFFFFFFFE if i == 0 else 3,
                    "pmu1": 10 if i == 0 else 20,
                }
                for i, sample in enumerate(samples)
            ]
            write_csv(npu / "samples.csv", records)
        write_csv(self.root / "captures.csv", manifest)

    def load(self):
        cpu, samples = read_report(self.root / "capture_00/cortex_m_report")
        return self.root / "capture_00/ethosu_report", cpu["header"], samples

    def test_cpu_and_npu_align_across_windows_with_separate_counters(self):
        target = self.root / "combined.perfetto.json"
        self.assertEqual(merger.combine(self.root, target, True), (2, 4, 4000))
        events = json.loads(target.read_text())["traceEvents"]
        for category in ("pc.sample", "ethosu.sample"):
            self.assertEqual(
                [e["ts"] for e in events if e.get("cat") == category],
                [500, 1500, 2500, 3500],
            )
        rates = [e for e in events if e.get("cat") == "ethosu.pmu.idle_clamped_rate"]
        self.assertEqual(
            [e["ts"] for e in rates],
            [100, 100, 1500, 1500, 1950, 1950, 2100, 2100, 3500, 3500, 3950, 3950],
        )
        self.assertTrue(all(e["args"]["events_per_second"] == 0 for e in rates))
        self.assertEqual(
            [
                e["args"][f"pmu{slot}_measured_events_per_second"]
                for e in events
                if e.get("cat") == "ethosu.sample" and not e["args"]["running"]
                for slot in range(2)
            ],
            [5000, 10000, 5000, 10000],
        )
        self.assertEqual(len({e["name"] for e in rates}), 2)
        self.assertTrue(all(set(e["args"]) == {"events_per_second"} for e in rates))
        self.assertEqual({e["pid"] for e in events}, {1, 2})
        metadata = [e for e in events if e.get("name") == "Ethos-U capture information"]
        self.assertEqual([e["ts"] for e in metadata], [100, 2100])

    def test_disabled_option_preserves_cpu_only_output(self):
        target = self.root / "cpu.json"
        merger.combine(self.root, target)
        self.assertEqual(
            {e["pid"] for e in json.loads(target.read_text())["traceEvents"]}, {1}
        )

    def test_missing_npu_report_preserves_existing_output(self):
        (self.root / "capture_01/ethosu_report/summary.json").unlink()
        target = self.root / "combined.json"
        target.write_text("previous trace")
        with self.assertRaises(FileNotFoundError):
            merger.combine(self.root, target, True)
        self.assertEqual(target.read_text(), "previous trace")

    def test_alignment_and_configuration_failures(self):
        directory, header, samples = self.load()
        original = json.loads((directory / "summary.json").read_text())
        for field, value in (
            ("timestamp_hz", 2_000_000),
            ("complete", 0),
            ("total_samples", 3),
            ("pmu_count", 5),
        ):
            with self.subTest(field=field):
                (directory / "summary.json").write_text(
                    json.dumps({**original, field: value})
                )
                with self.assertRaises(ValueError):
                    ethosu_perfetto.trace_events(directory, header, samples)
        (directory / "summary.json").write_text(json.dumps(original))
        samples[0]["timestamp"] = str(int(samples[0]["timestamp"]) + 1)
        with self.assertRaisesRegex(ValueError, "timestamps differ"):
            ethosu_perfetto.trace_events(directory, header, samples)

    def test_compressed_idle_without_pmu_remains_one_observation(self):
        directory, header, samples = self.load()
        summary = json.loads((directory / "summary.json").read_text())
        summary.update(
            count=1, running_samples=0, idle_samples=2, pmu_count=0, pmu_status=0
        )
        (directory / "summary.json").write_text(json.dumps(summary))
        write_csv(
            directory / "samples.csv",
            [
                {
                    "timestamp": samples[-1]["timestamp"],
                    "tick": 2,
                    "status": 0,
                    "running": 0,
                    "stream_id": 0,
                    "qread": "",
                    "sample_count": 2,
                    "idle_count": 2,
                }
            ],
        )
        events, _, _ = ethosu_perfetto.trace_events(directory, header, samples)
        records = [e for e in events if e.get("cat") == "ethosu.sample"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["args"]["sample_count"], 2)
        self.assertEqual(records[0]["ts"], 1500)
        self.assertFalse(any(e["ph"] in ("C", "X") for e in events))

    def test_compressed_idle_across_multiple_timestamp_wraps(self):
        directory, header, _ = self.load()
        summary = json.loads((directory / "summary.json").read_text())
        hz = 400_000_000
        header.update(
            timestamp_hz=hz,
            start_timestamp=0,
            stop_timestamp=(12 * hz) & 0xFFFFFFFF,
            stop_tick=12000,
            timer_hz=hz,
            timer_period=400000,
        )
        summary.update(
            timestamp_hz=hz,
            start_timestamp=100,
            stop_timestamp=(12 * hz - 50) & 0xFFFFFFFF,
            stop_tick=12000,
            total_samples=11000,
            idle_samples=10999,
        )
        (directory / "summary.json").write_text(json.dumps(summary))
        records = [
            {
                "timestamp": 400000,
                "tick": 1,
                "status": 1,
                "running": 1,
                "qread": 4,
                "stream_id": 1,
                "idle_count": 0,
                "sample_count": 1,
                "pmu0": 0,
                "pmu1": 0,
            },
            {
                "timestamp": (11 * hz) & 0xFFFFFFFF,
                "tick": 11000,
                "status": 0,
                "running": 0,
                "qread": "",
                "stream_id": 0,
                "idle_count": 10999,
                "sample_count": 10999,
                "pmu0": 100,
                "pmu1": 200,
            },
        ]
        write_csv(directory / "samples.csv", records)
        cpu = [
            {"tick": r["tick"], "timestamp": r["timestamp"], "time_us": t}
            for r, t in zip(records, (1000, 11_000_000))
        ]
        events, _, _ = ethosu_perfetto.trace_events(directory, header, cpu)
        self.assertEqual(
            [e["ts"] for e in events if e.get("cat") == "ethosu.sample"],
            [1000, 11_000_000],
        )
        rate = next(
            e["args"]["pmu0_measured_events_per_second"]
            for e in events
            if e.get("cat") == "ethosu.sample" and not e["args"]["running"]
        )
        self.assertAlmostEqual(rate, 100 / 10.999)
        zeros = [e for e in events if e.get("cat") == "ethosu.pmu.idle_clamped_rate"]
        self.assertEqual([e["ts"] for e in zeros][2:4], [2000, 2000])

    def test_idle_display_clamps_early_and_resumes_without_losing_measurements(self):
        directory, header, _ = self.load()
        summary = json.loads((directory / "summary.json").read_text())
        header.update(start_timestamp=0, stop_timestamp=6000, stop_tick=6)
        summary.update(
            start_timestamp=100,
            stop_timestamp=5950,
            stop_tick=6,
            count=4,
            total_samples=6,
            running_samples=3,
            idle_samples=3,
        )
        (directory / "summary.json").write_text(json.dumps(summary))
        # Idle occupies ticks 3..5; only tick 5 has a retained NPU snapshot.
        # Tick 3 was slightly late: use its CPU timestamp, not a nominal period.
        cpu = [
            {"tick": i, "timestamp": t, "time_us": t}
            for i, t in enumerate((500, 1500, 2600, 3500, 4500, 5500), 1)
        ]
        records = [
            {
                "timestamp": cpu[i - 1]["timestamp"],
                "tick": i,
                "status": int(i != 5),
                "running": int(i != 5),
                "qread": 4 if i != 5 else "",
                "stream_id": int(i != 5),
                "sample_count": 3 if i == 5 else 1,
                "idle_count": 3 if i == 5 else 0,
                "pmu0": i * 10,
                "pmu1": i * 20,
            }
            for i in (1, 2, 5, 6)
        ]
        write_csv(directory / "samples.csv", records)
        for missing in (False, True):
            with self.subTest(missing_first_idle_cpu_tick=missing):
                samples = [r for r in cpu if not missing or r["tick"] != 3]
                events, _, _ = ethosu_perfetto.trace_events(directory, header, samples)
                counters = [
                    e
                    for e in events
                    if e["ph"] == "C" and e["name"].startswith("PMU 0:")
                ]
                self.assertEqual(
                    [(e["ts"], e["args"]["events_per_second"]) for e in counters],
                    [
                        (100, 0),
                        (1500, 10000),
                        (2500 if missing else 2600, 0),
                        (5500, 10000),
                        (5950, 0),
                    ],
                )
                idle = next(
                    e["args"]
                    for e in events
                    if e.get("cat") == "ethosu.sample" and not e["args"]["running"]
                )
                self.assertEqual(idle["pmu0_measured_events_per_second"], 10000)
                self.assertEqual(
                    "estimated" in idle["idle_display_start_source"], missing
                )
        # A contradictory CPU time at the reconstructed boundary must fail.
        cpu[2]["timestamp"] = 4600
        cpu[2]["time_us"] = 4600
        with self.assertRaisesRegex(ValueError, "idle-start timing"):
            ethosu_perfetto.trace_events(directory, header, cpu)

    def test_initial_compressed_idle_uses_first_tick_across_tick_wrap(self):
        directory, header, _ = self.load()
        summary = json.loads((directory / "summary.json").read_text())
        header.update(start_timestamp=0, start_tick=0xFFFFFFFE, stop_tick=0)
        summary.update(
            start_tick=0xFFFFFFFE,
            stop_tick=0,
            count=1,
            running_samples=0,
            idle_samples=2,
        )
        (directory / "summary.json").write_text(json.dumps(summary))
        write_csv(
            directory / "samples.csv",
            [
                {
                    "timestamp": 1500,
                    "tick": 0,
                    "status": 0,
                    "running": 0,
                    "qread": "",
                    "stream_id": 0,
                    "idle_count": 2,
                    "sample_count": 2,
                    "pmu0": 10,
                    "pmu1": 20,
                }
            ],
        )
        cpu = [
            {"timestamp": 500, "tick": 0xFFFFFFFF, "time_us": 500},
            {"timestamp": 1500, "tick": 0, "time_us": 1500},
        ]
        events, _, _ = ethosu_perfetto.trace_events(directory, header, cpu)
        idle = next(e["args"] for e in events if e.get("cat") == "ethosu.sample")
        self.assertEqual(idle["idle_display_start_us"], 500)
        self.assertNotIn("pmu0_measured_events_per_second", idle)


if __name__ == "__main__":
    unittest.main()
