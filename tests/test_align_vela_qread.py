# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_align_vela_qread.py
# Description:  Operator percentages and supplied-artifact validation regressions
#
# $Date:        6 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

import csv
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "host/align_vela_qread.py"
SPEC = importlib.util.spec_from_file_location("align_vela_qread", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
with mock.patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
    SPEC.loader.exec_module(MODULE)


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.debug = self.root / "debug"
        self.debug.mkdir()
        self.pte = self.root / "model.pte"
        # Synthetic listing sufficient to exercise the aligner's byte comparison.
        self.pte.write_bytes(struct.pack("<III", 0, 1, 2))
        (self.debug / "cmdstream_listing.txt").write_text(
            "0x00000000: 00000000 NPU_SET_IFM_REGION\n"
            "0x00000004: 00000001 NPU_OP_CONV\n"
            "0x00000008: 00000002 NPU_OP_STOP\n"
        )
        tables = {
            "queue": "offset,cmdstream_id,scheduled_id\n4,0,7\n",
            "source": "id,operator\n1,CONV2D\n",
            "perf": (
                "id,source_id,operator,name,op_cycles,mac_count,Sram_ac,OffChipFlash_ac\n"
                "7,1,Conv2D,conv_test,100,20,30,40\n"
            ),
            "perf_debug": (
                "id,ifm_shape_h,ifm_shape_w,ifm_shape_c,ifm2_shape_h,ifm2_shape_w,"
                "ifm2_shape_c,ofm_shape_h,ofm_shape_w,ofm_shape_c\n"
                "7,4,4,8,0,0,0,2,2,16\n"
            ),
        }
        (self.debug / "out_debug.xml").write_text(
            "<debug>"
            + "".join(
                f'<table name="{name}"><![CDATA[{body}]]></table>'
                for name, body in tables.items()
            )
            + "</debug>"
        )
        self.columns, self.map_rows = MODULE.build_map(
            self.debug / "out_debug.xml", self.debug / "cmdstream_listing.txt", 0
        )
        self.write_map(self.map_rows)
        self.histogram = self.root / "histogram.csv"
        self.histogram.write_text("stream_id,qread_bytes,samples\n1,4,20\n")
        self.summary = {
            "ethosu_running_ticks": 100,
            "stream_identity": [{"stream_id": 1, "stream_bytes": 12}],
        }
        self.write_summary()
        self.output = self.root / "output"

    def write_map(self, rows):
        with (self.debug / "qread_ops.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_provenance_states_verification_limits_and_records_hashes(self):
        result = self.align()
        self.assertTrue(result["listing_matches_pte"])
        self.assertTrue(result["map_matches_supplied_debug_database"])
        self.assertFalse(result["capture_pte_identity_verified"])
        self.assertNotIn("command_stream_exact_match", result)
        for key, path in {
            "pte": self.pte,
            "listing": self.debug / "cmdstream_listing.txt",
            "debug_database": self.debug / "out_debug.xml",
            "operator_map": self.debug / "qread_ops.csv",
            "histogram": self.histogram,
            "aggregate_summary": self.root / "summary.json",
        }.items():
            self.assertEqual(
                result["input_sha256"][key],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

    def test_changed_map_metadata_fails_before_output(self):
        for field in (
            "name",
            "vela_op",
            "tosa_op",
            "ifm_hwc",
            "ifm2_hwc",
            "ofm_hwc",
            "est_cycles",
            "est_cycles_pct",
            "macs",
            "sram_ac",
            "flash_ac",
        ):
            with self.subTest(field=field):
                rows = [dict(self.map_rows[0], **{field: "wrong"})]
                self.write_map(rows)
                with self.assertRaisesRegex(ValueError, field + " differs"):
                    self.align()
                self.assertFalse(self.output.exists())

    def test_changed_database_label_with_same_offsets_fails(self):
        path = self.debug / "out_debug.xml"
        path.write_text(path.read_text().replace("conv_test", "different_model"))
        with self.assertRaisesRegex(ValueError, "name differs"):
            self.align()
        self.assertFalse(self.output.exists())

    def test_listing_pte_mismatch_fails(self):
        self.pte.write_bytes(bytes(12))
        with self.assertRaisesRegex(ValueError, "differs from PTE"):
            self.align()
        self.assertFalse(self.output.exists())

    def write_summary(self):
        (self.root / "summary.json").write_text(json.dumps(self.summary))

    def align(self):
        return MODULE.align(self.pte, self.debug, self.histogram, self.output)

    def test_excluded_samples_remain_in_denominator(self):
        result = self.align()
        row = MODULE.read_csv(self.output / "ethosu_operator_samples.csv")[0]
        self.assertEqual(float(row["percent_of_running_samples"]), 20.0)
        self.assertEqual(result["running_samples"], 100)
        self.assertEqual(result["histogram_samples"], 20)
        self.assertEqual(result["excluded_samples"], 80)
        self.assertEqual(result["assigned_samples"], 20)
        self.assertEqual(result["unmatched_samples"], 0)

    def test_unmatched_histogram_samples_are_separate_from_excluded(self):
        self.histogram.write_text("stream_id,qread_bytes,samples\n1,4,20\n1,0,10\n")
        result = self.align()
        self.assertEqual(result["histogram_samples"], 30)
        self.assertEqual(result["excluded_samples"], 70)
        self.assertEqual(result["unmatched_samples"], 10)
        row = MODULE.read_csv(self.output / "ethosu_operator_samples.csv")[0]
        self.assertEqual(float(row["percent_of_running_samples"]), 20.0)

    def test_fully_attributed_capture(self):
        self.summary["ethosu_running_ticks"] = 20
        self.write_summary()
        result = self.align()
        self.assertEqual(result["excluded_samples"], 0)
        row = MODULE.read_csv(self.output / "ethosu_operator_samples.csv")[0]
        self.assertEqual(float(row["percent_of_running_samples"]), 100.0)

    def test_missing_summary_fails_before_output(self):
        (self.root / "summary.json").unlink()
        with self.assertRaisesRegex(ValueError, "summary.json is required"):
            self.align()
        self.assertFalse(self.output.exists())

    def test_invalid_or_inconsistent_running_total(self):
        for value in (None, -1, 0, 19, True, 100.5, "100"):
            with self.subTest(value=value):
                self.summary["ethosu_running_ticks"] = value
                self.write_summary()
                with self.assertRaises(ValueError):
                    self.align()
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
