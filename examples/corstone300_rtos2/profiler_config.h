/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_config.h
 * Description:  Corstone-300 CMSIS-RTOS2 illustration configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef PROFILER_CORSTONE_RTOS2_CONFIG_H
#define PROFILER_CORSTONE_RTOS2_CONFIG_H
#define PROFILER_DEVICE_HEADER "SSE300MPS3.h"
/* Place all application and RTOS stacks, including idle/system tasks, in DTCM.
 * Adjust the whitelist if your RTOS linker configuration uses another RAM. */
#define PROFILER_STACK_BASE DTCM0_BASE_S
#define PROFILER_STACK_BYTES (DTCM_BLK_SIZE * DTCM_BLK_NUM)
/* Portable baseline: no ISR-time kernel introspection. */
#if defined(PROFILER_PRECISE_STACK_BOUNDS) && PROFILER_PRECISE_STACK_BOUNDS
    #error "This illustration requires an RTOS-specific bounds adapter before enabling precise bounds"
#endif
#endif
