/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_config.h
 * Description:  Corstone-300 example device and stack memory configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef PROFILER_CORSTONE_EXAMPLE_CONFIG_H
#define PROFILER_CORSTONE_EXAMPLE_CONFIG_H
/* This example's linker scripts place MSP and the optional PSP array in DTCM.
 * The memory range comes from the selected BSP, not a library board default. */
#define PROFILER_DEVICE_HEADER "SSE300MPS3.h"
#define PROFILER_STACK_BASE DTCM0_BASE_S
#define PROFILER_STACK_BYTES (DTCM_BLK_SIZE * DTCM_BLK_NUM)
#endif
