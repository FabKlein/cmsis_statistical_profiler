/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profile_workload.h
 * Description:  Callback-driven profiling example interface
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef PROFILER_WORKLOAD_H
#define PROFILER_WORKLOAD_H

#ifdef __cplusplus
extern "C" {
#endif

int profile_workload(int (*run_once)(void), int (*validate)(void));
void profiler_capture_complete(void);

#ifdef __cplusplus
}
#endif

#endif
