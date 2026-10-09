# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_generate_aggregate_mcu_report.py
# Description:  Aggregate MCU accounting, rendering and publication checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))

import aggregate_profiler_captures as aggregate
import generate_aggregate_mcu_report as mcu
import test_aggregate_capture_variants as fixtures
from analyze_profiler_buffer import flamegraph_summary, pmu_statistics
from combine_perfetto_captures import capture_rows
from test_aggregate_capture_variants import write_csv


class AggregateMcuReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = fixtures.AggregateVariantTests()
        # A tiny test double exercises invocation/publication, not rendering
        # correctness. Production still requires Brendan Gregg's renderer.
        self.renderer = self.root / "flamegraph.pl"
        self.renderer.write_text(
            'print qq{<svg xmlns="http://www.w3.org/2000/svg"/>\n};\n'
        )

    def capture(self, name="capture_00", statuses=None, root="worker", events=()):
        capture = self.fixture.make_capture(
            self.root, name, ethos=False, cpu_events=events
        )
        report = capture / "cortex_m_report"
        path = report / "summary.json"
        summary = json.loads(path.read_text())
        if events:
            summary["header"]["pmu"].update(
                flags=0, start=[0] * len(events), stop=[10, 12][: len(events)]
            )
            summary["pmu_events"] = pmu_statistics(summary["header"])
        if statuses is not None:
            summary["header"].update(
                count=len(statuses), features=2, unwind_max_depth=16
            )
            details = [
                {
                    "flamegraph_status": status,
                    "unwind_status": "complete",
                    "callers_raw": "[]",
                }
                for status in statuses
            ]
            summary["flamegraph"] = flamegraph_summary(details, root)
            summary["unwind_status_counts"] = {"complete": len(statuses)}
            folded = Counter({"worker;work": statuses.count("included")})
            mcu.write_folded(report / "stacks.folded", +folded)
            rows = [
                {"tick": i + 1, "pc": "0x10", "function": "work", **detail}
                for i, detail in enumerate(details)
            ]
            if rows:
                write_csv(report / "samples.csv", rows)
                write_csv(
                    report / "functions.csv",
                    [{"address": "0x10", "function": "work", "hits": len(rows)}],
                )
            else:
                (report / "samples.csv").write_text(
                    "tick,pc,function,flamegraph_status\n"
                )
                (report / "functions.csv").write_text("address,function,hits\n")
        path.write_text(json.dumps(summary))
        return capture

    def fake_render(self, renderer, folded, output, title, subtitle):
        self.assertTrue(folded.read_text())
        output.write_text("<svg/>\n")

    def test_repeated_pmu_events_preserve_slot_totals_and_coverage(self):
        captures = [self.capture(f"capture_{i:02d}", events=(17, 17)) for i in range(2)]
        aggregate.aggregate(captures, self.root)
        self.assertEqual(
            mcu.generate(self.root)["pmu_event_totals"], {"pmu0": 20, "pmu1": 24}
        )
        path = captures[1] / "cortex_m_report/summary.json"
        summary = json.loads(path.read_text())
        summary["pmu_events"][1].update(status="invalid_overflow_or_read", count=None)
        path.write_text(json.dumps(summary))
        aggregate.aggregate(captures, self.root)
        result = mcu.generate(self.root)
        self.assertEqual(result["pmu_event_totals"], {"pmu0": 20, "pmu1": None})
        first, second = (result["pmu_event_details"][key] for key in ("pmu0", "pmu1"))
        self.assertEqual(first["event"], second["event"])
        self.assertEqual(first["valid_captures"], 2)
        self.assertEqual(first["invalid_or_missing_captures"], 0)
        self.assertEqual(second["valid_count"], 12)
        self.assertEqual(second["valid_captures"], 1)
        self.assertEqual(second["invalid_or_missing_captures"], 1)

    def test_root_missing_and_unreliable_samples_stay_distinct(self):
        capture = self.capture(statuses=["included", "root_missing", "unreliable"])
        aggregate.aggregate([capture], self.root)
        with patch.object(mcu, "render_flamegraph", side_effect=self.fake_render):
            result = mcu.generate(self.root, self.renderer)
        self.assertEqual(result["pc_only_samples"], 2)
        self.assertEqual(result["root_missing_samples"], 1)
        self.assertEqual(result["all_pc_flamegraph_samples"], 3)
        output = self.root / "mcu_report"
        self.assertEqual(
            dict(mcu.folded_rows(output / "stacks.folded")),
            {
                "worker;work": 1,
                f"{mcu.PC_ONLY};work": 1,
                f"{mcu.ROOT_MISSING};work": 1,
            },
        )
        self.assertEqual(
            dict(mcu.folded_rows(output / "stacks_recovered.folded")),
            {"worker;work": 1},
        )
        with (output / "function_reconciliation.csv").open() as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(
            (
                row["hotspot_pc_samples"],
                row["recovered_stack_samples"],
                row["pc_only_samples"],
            ),
            ("3", "1", "2"),
        )

    def test_root_filter_without_recovered_samples_omits_empty_graph(self):
        capture = self.capture(statuses=["root_missing"])
        aggregate.aggregate([capture], self.root)
        with patch.object(
            mcu, "render_flamegraph", side_effect=self.fake_render
        ) as render:
            mcu.generate(self.root, self.renderer)
        self.assertEqual(render.call_count, 1)
        self.assertFalse((self.root / "mcu_report/flamegraph_recovered.svg").exists())
        self.assertEqual(
            (self.root / "mcu_report/stacks_recovered.folded").read_text(), ""
        )

    def test_empty_backtrace_capture_needs_no_renderer(self):
        capture = self.capture(statuses=[])
        aggregate.aggregate([capture], self.root)
        result = mcu.generate(self.root)
        self.assertEqual(result["all_pc_flamegraph_samples"], 0)
        self.assertFalse((self.root / "mcu_report/flamegraph.svg").exists())

    def test_selected_roots_must_match(self):
        captures = [
            self.capture("capture_00", ["included"], "worker"),
            self.capture("capture_01", ["included"], "other"),
        ]
        aggregate.aggregate(captures, self.root)
        with self.assertRaisesRegex(ValueError, "stack root differs"):
            mcu.generate(self.root, self.renderer)

    def test_separate_output_manifest_survives_tree_relocation(self):
        capture = self.capture()
        destination = self.root / "results" / "aggregate"
        aggregate.aggregate([capture], destination)
        self.assertEqual(
            capture_rows(destination)[0]["capture_dir"], "../../capture_00"
        )
        self.assertEqual(mcu.generate(destination)["cpu_samples"], 1)
        moved = self.root / "relocated"
        moved.mkdir()
        shutil.move(str(self.root / "results"), moved)
        shutil.move(str(capture), moved)
        self.assertEqual(mcu.generate(moved / "results/aggregate")["cpu_samples"], 1)

    @unittest.skipUnless(shutil.which("perl"), "Perl not installed")
    def test_standalone_renderer_records_content_hash_without_git(self):
        capture = self.capture(statuses=["included"])
        aggregate.aggregate([capture], self.root)
        result = mcu.generate(self.root, self.renderer)
        self.assertEqual(
            result["flamegraph_sha256"],
            hashlib.sha256(self.renderer.read_bytes()).hexdigest(),
        )
        self.assertIsNone(result["flamegraph_revision"])
        self.assertIn("<svg", (self.root / "mcu_report/flamegraph.svg").read_text())
        self.assertIn(
            "<svg", (self.root / "mcu_report/flamegraph_recovered.svg").read_text()
        )

    def test_renderer_hash_works_when_git_is_missing(self):
        with patch.object(mcu.subprocess, "run", side_effect=FileNotFoundError("git")):
            result = mcu.renderer_provenance(self.renderer)
        self.assertIsNone(result["flamegraph_revision"])
        self.assertEqual(
            result["flamegraph_sha256"],
            hashlib.sha256(self.renderer.read_bytes()).hexdigest(),
        )

    def test_failures_preserve_previous_report(self):
        for failure in ("renderer", "reconciliation", "publish"):
            with self.subTest(failure=failure):
                capture = self.root / "capture_00"
                if capture.exists():
                    shutil.rmtree(capture)
                capture = self.capture(statuses=["included"])
                aggregate.aggregate([capture], self.root)
                output = self.root / "mcu_report"
                output.mkdir(exist_ok=True)
                (output / "summary.json").write_text('{"previous": true}\n')
                (output / "flamegraph.svg").write_text("previous graph\n")
                before = {path.name: path.read_bytes() for path in output.iterdir()}
                if failure == "reconciliation":
                    (capture / "cortex_m_report/stacks.folded").write_text(
                        "worker;wrong_leaf 1\n"
                    )

                original_replace = Path.replace

                def replace(
                    path,
                    target,
                    failure=failure,
                    output=output,
                    original_replace=original_replace,
                ):
                    if (
                        failure == "publish"
                        and path.name == "report"
                        and target == output
                    ):
                        raise OSError("publication failed")
                    return original_replace(path, target)

                def render(*args, failure=failure):
                    self.fake_render(*args)
                    if failure == "renderer":
                        raise subprocess.CalledProcessError(1, "flamegraph.pl")

                with (
                    patch.object(mcu, "render_flamegraph", side_effect=render),
                    patch.object(Path, "replace", replace),
                    self.assertRaises(
                        (ValueError, OSError, subprocess.CalledProcessError)
                    ),
                ):
                    mcu.generate(self.root, self.renderer)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in output.iterdir()}, before
                )
                self.assertEqual(list(self.root.glob(".mcu-report-*")), [])

    def test_successful_pc_only_run_removes_old_optional_artifacts(self):
        capture = self.capture()
        summary = json.loads((capture / "cortex_m_report/summary.json").read_text())
        self.assertIsNone(summary["flamegraph"])
        aggregate.aggregate([capture], self.root)
        output = self.root / "mcu_report"
        output.mkdir()
        (output / "flamegraph.svg").write_text("stale")
        result = mcu.generate(self.root)
        self.assertFalse(result["backtraces_available"])
        self.assertFalse((output / "flamegraph.svg").exists())
        self.assertTrue((output / "hotspots.svg").exists())

    def test_null_flamegraph_with_stale_folded_file_is_rejected(self):
        capture = self.capture()
        (capture / "cortex_m_report/stacks.folded").write_text("old;work 1\n")
        aggregate.aggregate([capture], self.root)
        with self.assertRaisesRegex(ValueError, "Incomplete backtrace report"):
            mcu.generate(self.root)
        self.assertFalse((self.root / "mcu_report").exists())

    def test_failed_rollback_preserves_backup_and_reports_its_path(self):
        capture = self.capture()
        aggregate.aggregate([capture], self.root)
        output = self.root / "mcu_report"
        output.mkdir()
        (output / "summary.json").write_text('{"previous": true}\n')
        (output / "hotspots.svg").write_text("previous chart\n")
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        original_replace = Path.replace

        def replace(path, target):
            if path.name in ("report", "previous") and target == output:
                raise OSError("injected publication/rollback failure")
            return original_replace(path, target)

        with (
            patch.object(Path, "replace", replace),
            self.assertRaises(OSError) as raised,
        ):
            mcu.generate(self.root)
        backups = list(self.root.glob(".mcu-report-*/previous"))
        self.assertEqual(len(backups), 1)
        self.assertIn(str(backups[0].resolve()), str(raised.exception))
        self.assertEqual(
            {path.name: path.read_bytes() for path in backups[0].iterdir()}, before
        )
        self.assertFalse(output.exists())
        # Once the filesystem error is resolved, the reported directory is a
        # complete report that can be restored without rebuilding anything.
        backups[0].replace(output)
        self.assertEqual(
            {path.name: path.read_bytes() for path in output.iterdir()}, before
        )


if __name__ == "__main__":
    unittest.main()
