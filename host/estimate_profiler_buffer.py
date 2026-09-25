# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        estimate_profiler_buffer.py
# Description:  Estimate capture storage and duration
#
# $Date:        25 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Estimate capture duration at minimum, expected and maximum recovered caller depth."""
import argparse
import json
from analyze_profiler_buffer import HEADER


def estimate(buffer_bytes, sample_hz, pmu_count=0, max_depth=0, expected_depth=0):
    if buffer_bytes <= HEADER.size or sample_hz <= 0 or not 0 <= pmu_count <= 4 or not 0 <= expected_depth <= max_depth <= 255:
        raise ValueError('Require buffer > header, positive Hz, 0–4 events and 0 <= expected depth <= max depth <= 255')
    base = 24 + 4 * pmu_count + (4 if max_depth else 0)
    payload = buffer_bytes // 4 * 4 - HEADER.size
    return {name: dict(record_bytes=base + 4 * depth,
                       samples=payload // (base + 4 * depth),
                       seconds=(payload // (base + 4 * depth)) / sample_hz)
            for name, depth in [('minimum', 0), ('expected', expected_depth), ('maximum', max_depth)]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--buffer-bytes', type=int, required=True)
    p.add_argument('--sample-hz', type=int, required=True)
    p.add_argument('--pmu-count', type=int, default=0)
    p.add_argument('--max-depth', type=int, default=0, help='0 disables backtraces')
    p.add_argument('--expected-depth', type=int, default=0)
    args = p.parse_args()
    try:
        print(json.dumps(estimate(**vars(args)), indent=2))
    except ValueError as error:
        p.error(str(error))


if __name__ == '__main__':
    main()
