/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_dtcm_config.h
 * Description:  Native DTCM detection test configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef TEST_PROFILER_DTCM_CONFIG_H
#define TEST_PROFILER_DTCM_CONFIG_H
#define PROFILER_DEVICE_HEADER "fake_device.h"
#define PROFILER_SAMPLE_BUFFER_BYTES (240U + 12U * PROFILER_PMU_COUNT)
#define PROFILER_DEFAULT_DTCM_BASE ((uintptr_t)fake_stack)
#endif
