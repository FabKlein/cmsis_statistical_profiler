# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        ethosu_pmu_events.py
# Description:  Shared device-specific driver event names and hardware encodings
#
# $Date:        9 October 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Describe EUTR PMU selections without confusing driver IDs with register values.

The capture stores ethosu_pmu_event_type enum values. These are positions in the
driver's event list, NOT hardware encodings from the Technical Reference Manual.
For example, NPU_ACTIVE is driver ID 5 on U55/U65 and 4 on U85, but register
encoding 0x23 on all 3 devices.

Numeric tables below were extracted from Arm ethos-u-core-driver 1.26.2:
  include/pmu_ethosu.h: enum order
  src/ethosu{55,65,85}_interface.h: PMU_EVENT_* register encodings
U55 and U65 lists were compared before sharing their table. Every exported enum
except SENTINEL is covered. A listed event is not a runtime availability check;
hardware configuration, channel selectors and clock gating can affect counting.

Official register meanings and restrictions:
  U55 TRM: https://documentation-service.arm.com/static/60b5e972e022752339b44b4c
  U65 TRM: https://documentation-service.arm.com/static/60cb2a5b0320e92fa40b3787
  U85 TRM: https://documentation-service.arm.com/static/67b5ba01ce2747241fce860f

Readable labels expand driver symbols; they do not replace TRM definitions.
Units default to generic "events" unless cycle semantics are explicitly known.
Capture metadata currently has no driver-version identifier: select host tools
matching the firmware's driver. Unknown IDs retain numeric labels rather than
being interpreted as hardware encodings. Decoding never requires the SDK.
"""

from collections import Counter

DRIVER_VERSION = "1.26.2"

# Rows are in driver enum order: index = captured ID, value = (name, HW encoding).
# Do not sort these tables: sorting would silently change captured-ID meanings.
_U55_U65 = (
    ("NO_EVENT", 0x0000),
    ("CYCLE", 0x0011),
    ("NPU_IDLE", 0x0020),
    ("CC_STALLED_ON_BLOCKDEP", 0x0021),
    ("CC_STALLED_ON_SHRAM_RECONFIG", 0x0022),
    ("NPU_ACTIVE", 0x0023),
    ("MAC_ACTIVE", 0x0030),
    ("MAC_ACTIVE_8BIT", 0x0031),
    ("MAC_ACTIVE_16BIT", 0x0032),
    ("MAC_DPU_ACTIVE", 0x0033),
    ("MAC_STALLED_BY_WD_ACC", 0x0034),
    ("MAC_STALLED_BY_WD", 0x0035),
    ("MAC_STALLED_BY_ACC", 0x0036),
    ("MAC_STALLED_BY_IB", 0x0037),
    ("MAC_ACTIVE_32BIT", 0x0038),
    ("MAC_STALLED_BY_INT_W", 0x0039),
    ("MAC_STALLED_BY_INT_ACC", 0x003A),
    ("AO_ACTIVE", 0x0040),
    ("AO_ACTIVE_8BIT", 0x0041),
    ("AO_ACTIVE_16BIT", 0x0042),
    ("AO_STALLED_BY_OFMP_OB", 0x0043),
    ("AO_STALLED_BY_OFMP", 0x0044),
    ("AO_STALLED_BY_OB", 0x0045),
    ("AO_STALLED_BY_ACC_IB", 0x0046),
    ("AO_STALLED_BY_ACC", 0x0047),
    ("AO_STALLED_BY_IB", 0x0048),
    ("WD_ACTIVE", 0x0050),
    ("WD_STALLED", 0x0051),
    ("WD_STALLED_BY_WS", 0x0052),
    ("WD_STALLED_BY_WD_BUF", 0x0053),
    ("WD_PARSE_ACTIVE", 0x0054),
    ("WD_PARSE_STALLED", 0x0055),
    ("WD_PARSE_STALLED_IN", 0x0056),
    ("WD_PARSE_STALLED_OUT", 0x0057),
    ("WD_TRANS_WS", 0x0058),
    ("WD_TRANS_WB", 0x0059),
    ("WD_TRANS_DW0", 0x005A),
    ("WD_TRANS_DW1", 0x005B),
    ("AXI0_RD_TRANS_ACCEPTED", 0x0080),
    ("AXI0_RD_TRANS_COMPLETED", 0x0081),
    ("AXI0_RD_DATA_BEAT_RECEIVED", 0x0082),
    ("AXI0_RD_TRAN_REQ_STALLED", 0x0083),
    ("AXI0_WR_TRANS_ACCEPTED", 0x0084),
    ("AXI0_WR_TRANS_COMPLETED_M", 0x0085),
    ("AXI0_WR_TRANS_COMPLETED_S", 0x0086),
    ("AXI0_WR_DATA_BEAT_WRITTEN", 0x0087),
    ("AXI0_WR_TRAN_REQ_STALLED", 0x0088),
    ("AXI0_WR_DATA_BEAT_STALLED", 0x0089),
    ("AXI0_ENABLED_CYCLES", 0x008C),
    ("AXI0_RD_STALL_LIMIT", 0x008E),
    ("AXI0_WR_STALL_LIMIT", 0x008F),
    ("AXI_LATENCY_ANY", 0x00A0),
    ("AXI_LATENCY_32", 0x00A1),
    ("AXI_LATENCY_64", 0x00A2),
    ("AXI_LATENCY_128", 0x00A3),
    ("AXI_LATENCY_256", 0x00A4),
    ("AXI_LATENCY_512", 0x00A5),
    ("AXI_LATENCY_1024", 0x00A6),
    ("ECC_DMA", 0x00B0),
    ("ECC_SB0", 0x00B1),
    ("AXI1_RD_TRANS_ACCEPTED", 0x0180),
    ("AXI1_RD_TRANS_COMPLETED", 0x0181),
    ("AXI1_RD_DATA_BEAT_RECEIVED", 0x0182),
    ("AXI1_RD_TRAN_REQ_STALLED", 0x0183),
    ("AXI1_WR_TRANS_ACCEPTED", 0x0184),
    ("AXI1_WR_TRANS_COMPLETED_M", 0x0185),
    ("AXI1_WR_TRANS_COMPLETED_S", 0x0186),
    ("AXI1_WR_DATA_BEAT_WRITTEN", 0x0187),
    ("AXI1_WR_TRAN_REQ_STALLED", 0x0188),
    ("AXI1_WR_DATA_BEAT_STALLED", 0x0189),
    ("AXI1_ENABLED_CYCLES", 0x018C),
    ("AXI1_RD_STALL_LIMIT", 0x018E),
    ("AXI1_WR_STALL_LIMIT", 0x018F),
    ("ECC_SB1", 0x01B1),
)

_U85 = (
    ("NO_EVENT", 0x0000),
    ("CYCLE", 0x0011),
    ("NPU_IDLE", 0x0020),
    ("CC_STALLED_ON_BLOCKDEP", 0x0021),
    ("NPU_ACTIVE", 0x0023),
    ("MAC_ACTIVE", 0x0030),
    ("MAC_DPU_ACTIVE", 0x0033),
    ("MAC_STALLED_BY_W_OR_ACC", 0x0034),
    ("MAC_STALLED_BY_W", 0x0035),
    ("MAC_STALLED_BY_ACC", 0x0036),
    ("MAC_STALLED_BY_IB", 0x0037),
    ("AO_ACTIVE", 0x0040),
    ("AO_STALLED_BY_BS_OR_OB", 0x0043),
    ("AO_STALLED_BY_BS", 0x0044),
    ("AO_STALLED_BY_OB", 0x0045),
    ("AO_STALLED_BY_AB_OR_CB", 0x0046),
    ("AO_STALLED_BY_AB", 0x0047),
    ("AO_STALLED_BY_CB", 0x0048),
    ("WD_ACTIVE", 0x0050),
    ("WD_STALLED", 0x0051),
    ("WD_STALLED_BY_WD_BUF", 0x0053),
    ("WD_STALLED_BY_WS_FC", 0x0054),
    ("WD_STALLED_BY_WS_TC", 0x0055),
    ("WD_TRANS_WBLK", 0x0059),
    ("WD_TRANS_WS_FC", 0x005A),
    ("WD_TRANS_WS_TC", 0x005B),
    ("WD_STALLED_BY_WS_SC0", 0x0060),
    ("WD_STALLED_BY_WS_SC1", 0x0061),
    ("WD_STALLED_BY_WS_SC2", 0x0062),
    ("WD_STALLED_BY_WS_SC3", 0x0063),
    ("WD_PARSE_ACTIVE_SC0", 0x0064),
    ("WD_PARSE_ACTIVE_SC1", 0x0065),
    ("WD_PARSE_ACTIVE_SC2", 0x0066),
    ("WD_PARSE_ACTIVE_SC3", 0x0067),
    ("WD_PARSE_STALL_SC0", 0x0068),
    ("WD_PARSE_STALL_SC1", 0x0069),
    ("WD_PARSE_STALL_SC2", 0x006A),
    ("WD_PARSE_STALL_SC3", 0x006B),
    ("WD_PARSE_STALL_IN_SC0", 0x006C),
    ("WD_PARSE_STALL_IN_SC1", 0x006D),
    ("WD_PARSE_STALL_IN_SC2", 0x006E),
    ("WD_PARSE_STALL_IN_SC3", 0x006F),
    ("WD_PARSE_STALL_OUT_SC0", 0x0070),
    ("WD_PARSE_STALL_OUT_SC1", 0x0071),
    ("WD_PARSE_STALL_OUT_SC2", 0x0072),
    ("WD_PARSE_STALL_OUT_SC3", 0x0073),
    ("WD_TRANS_WS_SC0", 0x0074),
    ("WD_TRANS_WS_SC1", 0x0075),
    ("WD_TRANS_WS_SC2", 0x0076),
    ("WD_TRANS_WS_SC3", 0x0077),
    ("WD_TRANS_WB0", 0x0078),
    ("WD_TRANS_WB1", 0x0079),
    ("WD_TRANS_WB2", 0x007A),
    ("WD_TRANS_WB3", 0x007B),
    ("SRAM_RD_TRANS_ACCEPTED", 0x0080),
    ("SRAM_RD_TRANS_COMPLETED", 0x0081),
    ("SRAM_RD_DATA_BEAT_RECEIVED", 0x0082),
    ("SRAM_RD_TRAN_REQ_STALLED", 0x0083),
    ("SRAM_WR_TRANS_ACCEPTED", 0x0084),
    ("SRAM_WR_TRANS_COMPLETED_M", 0x0085),
    ("SRAM_WR_TRANS_COMPLETED_S", 0x0086),
    ("SRAM_WR_DATA_BEAT_WRITTEN", 0x0087),
    ("SRAM_WR_TRAN_REQ_STALLED", 0x0088),
    ("SRAM_WR_DATA_BEAT_STALLED", 0x0089),
    ("SRAM_ENABLED_CYCLES", 0x008C),
    ("SRAM_RD_STALL_LIMIT", 0x008E),
    ("SRAM_WR_STALL_LIMIT", 0x008F),
    ("AXI_LATENCY_ANY", 0x00A0),
    ("AXI_LATENCY_32", 0x00A1),
    ("AXI_LATENCY_64", 0x00A2),
    ("AXI_LATENCY_128", 0x00A3),
    ("AXI_LATENCY_256", 0x00A4),
    ("AXI_LATENCY_512", 0x00A5),
    ("AXI_LATENCY_1024", 0x00A6),
    ("ECC_DMA", 0x00B0),
    ("ECC_MAC_IB", 0x00B1),
    ("ECC_MAC_AB", 0x00B2),
    ("ECC_AO_CB", 0x00B3),
    ("ECC_AO_OB", 0x00B4),
    ("ECC_AO_LUT", 0x00B5),
    ("EXT_RD_TRANS_ACCEPTED", 0x0180),
    ("EXT_RD_TRANS_COMPLETED", 0x0181),
    ("EXT_RD_DATA_BEAT_RECEIVED", 0x0182),
    ("EXT_RD_TRAN_REQ_STALLED", 0x0183),
    ("EXT_WR_TRANS_ACCEPTED", 0x0184),
    ("EXT_WR_TRANS_COMPLETED_M", 0x0185),
    ("EXT_WR_TRANS_COMPLETED_S", 0x0186),
    ("EXT_WR_DATA_BEAT_WRITTEN", 0x0187),
    ("EXT_WR_TRAN_REQ_STALLED", 0x0188),
    ("EXT_WR_DATA_BEAT_STALLED", 0x0189),
    ("EXT_ENABLED_CYCLES", 0x018C),
    ("EXT_RD_STALL_LIMIT", 0x018E),
    ("EXT_WR_STALL_LIMIT", 0x018F),
    ("SRAM0_RD_TRANS_ACCEPTED", 0x0200),
    ("SRAM0_RD_TRANS_COMPLETED", 0x0201),
    ("SRAM0_RD_DATA_BEAT_RECEIVED", 0x0202),
    ("SRAM0_RD_TRAN_REQ_STALLED", 0x0203),
    ("SRAM0_WR_TRANS_ACCEPTED", 0x0204),
    ("SRAM0_WR_TRANS_COMPLETED_M", 0x0205),
    ("SRAM0_WR_TRANS_COMPLETED_S", 0x0206),
    ("SRAM0_WR_DATA_BEAT_WRITTEN", 0x0207),
    ("SRAM0_WR_TRAN_REQ_STALLED", 0x0208),
    ("SRAM0_WR_DATA_BEAT_STALLED", 0x0209),
    ("SRAM0_ENABLED_CYCLES", 0x020C),
    ("SRAM0_RD_STALL_LIMIT", 0x020E),
    ("SRAM0_WR_STALL_LIMIT", 0x020F),
    ("SRAM1_RD_TRANS_ACCEPTED", 0x0210),
    ("SRAM1_RD_TRANS_COMPLETED", 0x0211),
    ("SRAM1_RD_DATA_BEAT_RECEIVED", 0x0212),
    ("SRAM1_RD_TRAN_REQ_STALLED", 0x0213),
    ("SRAM1_WR_TRANS_ACCEPTED", 0x0214),
    ("SRAM1_WR_TRANS_COMPLETED_M", 0x0215),
    ("SRAM1_WR_TRANS_COMPLETED_S", 0x0216),
    ("SRAM1_WR_DATA_BEAT_WRITTEN", 0x0217),
    ("SRAM1_WR_TRAN_REQ_STALLED", 0x0218),
    ("SRAM1_WR_DATA_BEAT_STALLED", 0x0219),
    ("SRAM1_ENABLED_CYCLES", 0x021C),
    ("SRAM1_RD_STALL_LIMIT", 0x021E),
    ("SRAM1_WR_STALL_LIMIT", 0x021F),
    ("SRAM2_RD_TRANS_ACCEPTED", 0x0220),
    ("SRAM2_RD_TRANS_COMPLETED", 0x0221),
    ("SRAM2_RD_DATA_BEAT_RECEIVED", 0x0222),
    ("SRAM2_RD_TRAN_REQ_STALLED", 0x0223),
    ("SRAM2_WR_TRANS_ACCEPTED", 0x0224),
    ("SRAM2_WR_TRANS_COMPLETED_M", 0x0225),
    ("SRAM2_WR_TRANS_COMPLETED_S", 0x0226),
    ("SRAM2_WR_DATA_BEAT_WRITTEN", 0x0227),
    ("SRAM2_WR_TRAN_REQ_STALLED", 0x0228),
    ("SRAM2_WR_DATA_BEAT_STALLED", 0x0229),
    ("SRAM2_ENABLED_CYCLES", 0x022C),
    ("SRAM2_RD_STALL_LIMIT", 0x022E),
    ("SRAM2_WR_STALL_LIMIT", 0x022F),
    ("SRAM3_RD_TRANS_ACCEPTED", 0x0230),
    ("SRAM3_RD_TRANS_COMPLETED", 0x0231),
    ("SRAM3_RD_DATA_BEAT_RECEIVED", 0x0232),
    ("SRAM3_RD_TRAN_REQ_STALLED", 0x0233),
    ("SRAM3_WR_TRANS_ACCEPTED", 0x0234),
    ("SRAM3_WR_TRANS_COMPLETED_M", 0x0235),
    ("SRAM3_WR_TRANS_COMPLETED_S", 0x0236),
    ("SRAM3_WR_DATA_BEAT_WRITTEN", 0x0237),
    ("SRAM3_WR_TRAN_REQ_STALLED", 0x0238),
    ("SRAM3_WR_DATA_BEAT_STALLED", 0x0239),
    ("SRAM3_ENABLED_CYCLES", 0x023C),
    ("SRAM3_RD_STALL_LIMIT", 0x023E),
    ("SRAM3_WR_STALL_LIMIT", 0x023F),
    ("EXT0_RD_TRANS_ACCEPTED", 0x0280),
    ("EXT0_RD_TRANS_COMPLETED", 0x0281),
    ("EXT0_RD_DATA_BEAT_RECEIVED", 0x0282),
    ("EXT0_RD_TRAN_REQ_STALLED", 0x0283),
    ("EXT0_WR_TRANS_ACCEPTED", 0x0284),
    ("EXT0_WR_TRANS_COMPLETED_M", 0x0285),
    ("EXT0_WR_TRANS_COMPLETED_S", 0x0286),
    ("EXT0_WR_DATA_BEAT_WRITTEN", 0x0287),
    ("EXT0_WR_TRAN_REQ_STALLED", 0x0288),
    ("EXT0_WR_DATA_BEAT_STALLED", 0x0289),
    ("EXT0_ENABLED_CYCLES", 0x028C),
    ("EXT0_RD_STALL_LIMIT", 0x028E),
    ("EXT0_WR_STALL_LIMIT", 0x028F),
    ("EXT1_RD_TRANS_ACCEPTED", 0x0290),
    ("EXT1_RD_TRANS_COMPLETED", 0x0291),
    ("EXT1_RD_DATA_BEAT_RECEIVED", 0x0292),
    ("EXT1_RD_TRAN_REQ_STALLED", 0x0293),
    ("EXT1_WR_TRANS_ACCEPTED", 0x0294),
    ("EXT1_WR_TRANS_COMPLETED_M", 0x0295),
    ("EXT1_WR_TRANS_COMPLETED_S", 0x0296),
    ("EXT1_WR_DATA_BEAT_WRITTEN", 0x0297),
    ("EXT1_WR_TRAN_REQ_STALLED", 0x0298),
    ("EXT1_WR_DATA_BEAT_STALLED", 0x0299),
    ("EXT1_ENABLED_CYCLES", 0x029C),
    ("EXT1_RD_STALL_LIMIT", 0x029E),
    ("EXT1_WR_STALL_LIMIT", 0x029F),
)

_TABLES = {55: _U55_U65, 65: _U55_U65, 85: _U85}
SUPPORTED_DEVICES = tuple(_TABLES)

# A deliberately small semantic overlay: all other events still have their
# official symbol/encoding and readable label, with a generic count unit.
_CYCLE_DESCRIPTIONS = {
    "CYCLE": "Elapsed NPU clock cycles while counting is enabled.",
    "NPU_IDLE": "Cycles observed with the NPU stopped.",
    "NPU_ACTIVE": "Cycles observed with the NPU running.",
    "MAC_ACTIVE": "Cycles with active MAC block traversal.",
    "MAC_STALLED_BY_IB": "Cycles when MAC progress is stalled by the input buffer.",
}
_WORDS = {
    "NPU": "NPU",
    "MAC": "MAC",
    "CC": "command controller",
    "AO": "activation output",
    "WD": "weight decoder",
    "DPU": "dot-product unit",
    "IB": "input buffer",
    "OB": "output buffer",
    "ACC": "accumulator",
    "RD": "read",
    "WR": "write",
    "TRANS": "transactions",
    "TRAN": "transaction",
    "REQ": "request",
    "BUF": "buffer",
    "IN": "input",
    "OUT": "output",
    "BLOCKDEP": "block dependency",
    "SHRAM": "shared RAM",
    "RECONFIG": "reconfiguration",
    "INT": "internal",
    "W": "weights",
    "ECC": "ECC",
    "DMA": "DMA",
}


def event_info(device_type, event_id):
    """Return fresh metadata for 1 captured driver ID; never program HW with it."""
    table = _TABLES.get(device_type)
    if table is None:
        raise ValueError(f"unsupported Ethos-U device type: {device_type}")
    if not 0 <= event_id < len(table):
        return {
            "event_id": event_id,
            "key": f"event_{event_id:04x}",
            "label": f"Event 0x{event_id:04X}",
            "symbol": None,
            "hardware_event": None,
            "unit": "events",
            "description": "Unknown driver event ID; no hardware meaning inferred.",
            "known": False,
        }
    name, encoding = table[event_id]
    label = " ".join(
        _WORDS.get(word, word if any(c.isdigit() for c in word) else word.lower())
        for word in name.split("_")
    )
    label = label[0].upper() + label[1:]
    return {
        "event_id": event_id,
        "key": name.lower(),
        "label": label,
        "symbol": "ETHOSU_PMU_" + name,
        "hardware_event": encoding,
        "unit": "cycles" if name in _CYCLE_DESCRIPTIONS else "events",
        "description": _CYCLE_DESCRIPTIONS.get(
            name, label + "; see the device TRM for counting conditions."
        ),
        "known": True,
    }


def describe_events(device_type, event_ids):
    """Describe ordered counter selections, giving repeated events distinct keys.

    key names output columns; semantic_key names the event independently of its
    counter slot. Consumers must use semantic_key when deriving event ratios.
    """
    selected = [event_info(device_type, code) for code in event_ids]
    repetitions = Counter(event["key"] for event in selected)
    for index, event in enumerate(selected):
        event["semantic_key"] = event["key"]
        if not event["known"]:
            event["key"] = f"pmu{index}_{event['key']}"
        elif repetitions[event["key"]] > 1:
            event["key"] += f"_pmu{index}"
    return selected
