# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        build_vela_qread_map.py
# Description:  Build canonical operator metadata from supplied Vela artifacts
#
# $Date:        6 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

"""Join a Vela debug database and PTE command listing into QREAD intervals."""

import argparse
import csv
import io
import re
from pathlib import Path


def tables_from_debug_db(path):
    xml = path.read_text()
    return {
        name: list(csv.DictReader(io.StringIO(body.strip())))
        for name, body in re.findall(
            r'<table name="(\w+)">\s*<!\[CDATA\[(.*?)\]\]>', xml, re.DOTALL
        )
    }


def listing_kicks(path, base):
    kicks = {}
    stop_offsets = []
    for line in path.read_text().splitlines():
        match = re.match(
            r"^0x([0-9a-fA-F]+):.*\bNPU_OP_(CONV|DEPTHWISE|POOL|ELEMENTWISE|STOP)\b", line
        )
        if not match:
            continue
        offset = int(match.group(1), 16) - base
        if offset < 0:
            raise ValueError(f"command offset precedes stream base: {line}")
        if match.group(2) == "STOP":
            stop_offsets.append(offset + 4)
        else:
            kicks[offset] = match.group(2)
    if not stop_offsets:
        raise ValueError("listing has no NPU_OP_STOP")
    return kicks, max(stop_offsets)


def build_map(debug_db, listing, base):
    tables = tables_from_debug_db(debug_db)
    source = {row["id"]: row for row in tables["source"]}
    perf = {row["id"]: row for row in tables["perf"]}
    shape = {row["id"]: row for row in tables["perf_debug"]}
    queue = sorted(tables["queue"], key=lambda row: int(row["offset"]))
    if len({row["cmdstream_id"] for row in queue}) != 1:
        raise ValueError("debug database must contain one command stream per map")
    kicks, stream_end = listing_kicks(listing, base)
    offsets = [int(row["offset"]) for row in queue]
    if not queue or set(offsets) != set(kicks) or len(offsets) != len(kicks):
        raise ValueError("Vela queue offsets do not match decoded compute kicks")
    if offsets[-1] >= stream_end:
        raise ValueError("last Vela queue offset is outside the command stream")
    total_cycles = sum(int(perf[row["scheduled_id"]]["op_cycles"] or 0) for row in queue)
    columns = [
        "op",
        "kick_offset",
        "next_kick_offset",
        "npu_op",
        "vela_op",
        "tosa_op",
        "name",
        "ifm_hwc",
        "ifm2_hwc",
        "ofm_hwc",
        "est_cycles",
        "est_cycles_pct",
        "macs",
        "sram_ac",
        "flash_ac",
    ]
    rows = []
    for index, item in enumerate(queue):
        offset = offsets[index]
        next_offset = offsets[index + 1] if index + 1 < len(offsets) else stream_end
        scheduled = item["scheduled_id"]
        p = perf[scheduled]
        s = shape[scheduled]
        original = source.get(p["source_id"], {}).get("operator", "")

        def hwc(kind, shape):
            return (
                "x".join(shape[f"{kind}_shape_{axis}"] for axis in "hwc")
                if shape[f"{kind}_shape_c"] != "0"
                else ""
            )

        cycles = int(p["op_cycles"] or 0)
        rows.append(
            {
                "op": index,
                "kick_offset": f"0x{offset:05x}",
                "next_kick_offset": f"0x{next_offset:05x}",
                "npu_op": kicks[offset],
                "vela_op": p["operator"],
                "tosa_op": original,
                "name": p["name"],
                "ifm_hwc": hwc("ifm", s),
                "ifm2_hwc": hwc("ifm2", s),
                "ofm_hwc": hwc("ofm", s),
                "est_cycles": cycles,
                "est_cycles_pct": f"{100 * cycles / total_cycles:.2f}" if total_cycles else "0.00",
                "macs": p["mac_count"],
                "sram_ac": p["Sram_ac"],
                "flash_ac": p["OffChipFlash_ac"],
            }
        )
    return columns, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug-db", required=True, type=Path, help="Vela out_debug.xml")
    parser.add_argument(
        "--listing", required=True, type=Path, help="decoded command listing with PTE file offsets"
    )
    parser.add_argument(
        "--command-file-offset",
        required=True,
        type=lambda value: int(value, 0),
        help="PTE file offset of the first command word, e.g. 0xd0",
    )
    parser.add_argument("--output", required=True, type=Path, help="output qread_ops.csv")
    args = parser.parse_args()
    try:
        columns, rows = build_map(args.debug_db, args.listing, args.command_file_offset)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f"map generation failed: {error}\n")
    print(f"Wrote {len(rows)} operator intervals to {args.output}")


if __name__ == "__main__":
    main()
