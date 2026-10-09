# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""TOSA summary uses only an exact PTE/Vela alignment."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import summarize_tosa_operators as tosa


class TosaSummaryTests(unittest.TestCase):
    def test_grouped_samples_and_estimates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "vela_alignment.json").write_text(
                json.dumps(
                    {
                        "listing_matches_pte": True,
                        "debug_queue_operations": 2,
                        "assigned_samples": 3,
                        "running_samples": 4,
                    }
                )
            )
            with (root / "ethosu_operator_samples.csv").open("w", newline="") as target:
                writer = csv.DictWriter(
                    target, fieldnames=("tosa_op", "samples", "est_cycles", "macs")
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "tosa_op": "Conv2D",
                            "samples": 2,
                            "est_cycles": 10,
                            "macs": 20,
                        },
                        {
                            "tosa_op": "Conv2D",
                            "samples": 1,
                            "est_cycles": 12,
                            "macs": 30,
                        },
                    ]
                )
            rows = tosa.summarize(root)
            self.assertEqual(rows[0]["operators"], 2)
            self.assertEqual(rows[0]["samples"], 3)
            self.assertEqual(rows[0]["est_cycles"], 22)
            self.assertEqual(rows[0]["percent_of_running_samples"], 75)
            alignment = json.loads((root / "vela_alignment.json").read_text())
            alignment["listing_matches_pte"] = False
            (root / "vela_alignment.json").write_text(json.dumps(alignment))
            with self.assertRaisesRegex(ValueError, "does not match"):
                tosa.summarize(root)


if __name__ == "__main__":
    unittest.main()
