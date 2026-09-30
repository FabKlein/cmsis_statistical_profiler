#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        capture_uart.py
# Description:  Capture a framed profiler buffer from a Himax WE2 UART
#
# $Date:        30 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

import argparse
from pathlib import Path
import re
import sys
import time

import serial


MARKER = re.compile(rb"SCPF_BEGIN (\d+)\r+\n")


def main():
    parser = argparse.ArgumentParser(description="Capture an SCPF buffer from a Himax WE2 UART")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baudrate", type=int, default=921600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    prefix = bytearray()
    with serial.Serial(args.port, args.baudrate, timeout=0.1) as uart:
        while time.monotonic() < deadline:
            byte = uart.read(1)
            if not byte:
                continue
            prefix += byte
            sys.stdout.buffer.write(byte)
            sys.stdout.buffer.flush()
            match = MARKER.search(prefix)
            if match:
                size = int(match.group(1))
                break
            if len(prefix) > 4096:
                del prefix[:-1024]
        else:
            raise TimeoutError("SCPF_BEGIN marker not received")

        payload = bytearray()
        while len(payload) < size and time.monotonic() < deadline:
            payload += uart.read(size - len(payload))
        if len(payload) != size:
            raise TimeoutError(f"received {len(payload)} of {size} bytes")

    if payload[:4] != b"SCPF":
        raise ValueError(f"invalid capture magic: {payload[:4]!r}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"\nCaptured {size} bytes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
