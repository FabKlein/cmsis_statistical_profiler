#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0
# CMSIS Statistical Profiler: generate the draft HTML reference.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec doxygen profiler.dxy
