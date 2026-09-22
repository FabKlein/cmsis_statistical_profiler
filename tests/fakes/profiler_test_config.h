/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_test_config.h
 * Description:  Native capture and architecture test configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef TEST_PROFILER_CONFIG_H
#define TEST_PROFILER_CONFIG_H
#define PROFILER_DEVICE_HEADER "fake_device.h"
#define PROFILER_SAMPLE_BUFFER_BYTES (208U + 24U * !!PROFILER_PMU_ENABLE)
#define PROFILER_STACK_REGIONS                                                                                         \
    {                                                                                                                  \
        {(uintptr_t)fake_stack, sizeof(fake_stack)}, {UINTPTR_MAX - 15U, 8U}, { 0U, 0U }                               \
    }
#endif
