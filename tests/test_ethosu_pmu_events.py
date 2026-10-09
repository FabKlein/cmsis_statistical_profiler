# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_ethosu_pmu_events.py
# Description:  Device-specific PMU catalog and counter selection checks
#
# $Date:        9 October 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from ethosu_pmu_events import describe_events, event_info


class EthosuPmuEventsTests(unittest.TestCase):
    def test_driver_ids_are_not_hardware_encodings(self):
        for device, active, mac in ((55, 5, 6), (65, 5, 6), (85, 4, 5)):
            with self.subTest(device=device):
                self.assertEqual(
                    event_info(device, active)["symbol"], "ETHOSU_PMU_NPU_ACTIVE"
                )
                self.assertEqual(event_info(device, active)["hardware_event"], 0x23)
                self.assertEqual(
                    event_info(device, mac)["symbol"], "ETHOSU_PMU_MAC_ACTIVE"
                )
                self.assertEqual(event_info(device, mac)["hardware_event"], 0x30)

    def test_full_driver_enum_coverage_and_sentinel_exclusion(self):
        for device, count in ((55, 74), (65, 74), (85, 171)):
            with self.subTest(device=device):
                entries = describe_events(device, range(count))
                self.assertTrue(all(entry["known"] for entry in entries))
                self.assertEqual(len({entry["symbol"] for entry in entries}), count)
                self.assertFalse(event_info(device, count)["known"])
                self.assertFalse(event_info(device, 0xFFFF)["known"])
        self.assertEqual(describe_events(55, range(74)), describe_events(65, range(74)))
        # End-of-list U85 events must not fall back to one of the 4 demo names.
        self.assertEqual(
            event_info(85, 170)["symbol"], "ETHOSU_PMU_EXT1_WR_STALL_LIMIT"
        )
        self.assertEqual(event_info(85, 170)["hardware_event"], 0x29F)

    def test_transaction_event_has_generic_count_unit(self):
        event = event_info(55, 38)
        self.assertEqual(event["symbol"], "ETHOSU_PMU_AXI0_RD_TRANS_ACCEPTED")
        self.assertEqual(event["hardware_event"], 0x80)
        self.assertEqual(event["unit"], "events")
        self.assertEqual(event_info(55, 5)["unit"], "cycles")

    def test_repeated_and_unknown_events_keep_distinct_columns(self):
        entries = describe_events(55, (5, 5, 99, 99))
        self.assertEqual(
            [entry["key"] for entry in entries],
            [
                "npu_active_pmu0",
                "npu_active_pmu1",
                "pmu2_event_0063",
                "pmu3_event_0063",
            ],
        )
        self.assertEqual(entries[0]["semantic_key"], entries[1]["semantic_key"])
        self.assertIsNone(entries[2]["hardware_event"])
        self.assertEqual(event_info(55, 5)["key"], "npu_active")

    def test_unsupported_device_is_not_assumed_to_be_u55(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            event_info(99, 5)


if __name__ == "__main__":
    unittest.main()
