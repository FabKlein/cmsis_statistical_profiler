/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_alif_device.h
 * Description:  Alif Ensemble E8 CMSIS device header integration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef PROFILER_ALIF_DEVICE_H
#define PROFILER_ALIF_DEVICE_H

/* The SDK's alif.h also imports DMA/driver configuration unrelated to sampling. */
/* soc.h establishes CMSIS register qualifiers used by core_defines.h. */
// clang-format off
#include "soc.h"
#include "core_defines.h"
#include "system.h"
// clang-format on

#endif
