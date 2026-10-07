# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0
"""Extract and list Vela COP1 Ethos-U register streams from an existing PTE.

Requires the matching ethos-u-vela Python package for its command opcode names.
The listing preserves PTE file offsets for build_vela_qread_map.py and
align_vela_qread.py. It does not recover Vela's high-level operator comments.
"""

import argparse
import hashlib
import struct
from pathlib import Path


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def streams_in_pte(data):
    """Find bounded Vela driver actions, rather than guessing a command offset."""
    found = []
    cursor = 0
    while (cop1 := data.find(b"COP1", cursor)) >= 0:
        cursor = cop1 + 4
        action = cursor
        for _ in range(64):
            if action + 4 > len(data):
                break
            tag = word(data, action)
            kind = tag & 0xFF
            if kind == 1:  # Config, followed by config and architecture words.
                action += 12
            elif kind == 5:  # Alignment NOP.
                action += 4
            elif kind == 2:  # CmdStream: high eight count bits in tag bits 8..15.
                count = ((tag >> 8) & 0xFF) << 16 | (tag >> 16)
                start = action + 4
                end = start + 4 * count
                if count and end <= len(data) and (word(data, end - 4) & 0xFFFF) == 0:
                    found.append((cop1, start, data[start:end]))
                break
            else:
                break
    return found


def list_stream(stream, start):
    try:
        from ethosu.vela.ethos_u55_regs.ethos_u55_regs import cmd0, cmd1
    except ImportError as error:
        raise ValueError("ethos-u-vela is required for command opcode names") from error

    names0 = {command.value: command.name for command in cmd0}
    names1 = {command.value: command.name for command in cmd1}
    rows = []
    offset = 0
    stopped = False
    while offset < len(stream):
        first = word(stream, offset)
        code = first & 0x3FF
        long = bool(first & 0x4000)
        name = (names1 if long else names0).get(code)
        if name is None:
            raise ValueError(
                f"unknown command opcode {code:#x} at stream offset {offset:#x}; check Vela version"
            )
        if long:
            if offset + 8 > len(stream):
                raise ValueError(f"truncated long command at stream offset {offset:#x}")
            payload = word(stream, offset + 4)
            rows.append(f"0x{start + offset:06x}: {first:08x} {payload:08x}  {name}")
            offset += 8
        else:
            rows.append(f"0x{start + offset:06x}: {first:08x}           {name}")
            offset += 4
        if name == "NPU_OP_STOP":
            stopped = True
            if offset != len(stream):
                raise ValueError("command stream has data after NPU_OP_STOP")
    if not stopped:
        raise ValueError("command stream has no NPU_OP_STOP")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pte", required=True, type=Path, help="exact deployed PTE")
    parser.add_argument("--listing", required=True, type=Path, help="command listing output")
    parser.add_argument(
        "--stream-index", type=int, help="choose one stream when PTE contains several"
    )
    parser.add_argument("--raw", type=Path, help="also write the raw register stream")
    args = parser.parse_args()
    try:
        streams = streams_in_pte(args.pte.read_bytes())
        if not streams:
            raise ValueError("no supported Vela COP1 command stream found in PTE")
        if args.stream_index is None and len(streams) != 1:
            choices = ", ".join(f"{i}: {start:#x}" for i, (_, start, _) in enumerate(streams))
            raise ValueError(f"found {len(streams)} streams ({choices}); select --stream-index")
        index = args.stream_index if args.stream_index is not None else 0
        if not 0 <= index < len(streams):
            raise ValueError(f"stream index {index} outside 0..{len(streams) - 1}")
        cop1, start, stream = streams[index]
        commands = list_stream(stream, start)
        args.listing.parent.mkdir(parents=True, exist_ok=True)
        args.listing.write_text(
            f"; Vela COP1 driver action at PTE file offset {cop1:#x}\n"
            f"; command stream at PTE file offset {start:#x}, {len(stream)} bytes\n"
            f"; stream SHA-256 {hashlib.sha256(stream).hexdigest()}\n" + "\n".join(commands) + "\n"
        )
        if args.raw:
            args.raw.parent.mkdir(parents=True, exist_ok=True)
            args.raw.write_bytes(stream)
        print(f"Wrote {len(commands)} commands, {len(stream)} bytes, PTE offset {start:#x}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"unwrap failed: {error}\n")


if __name__ == "__main__":
    main()
