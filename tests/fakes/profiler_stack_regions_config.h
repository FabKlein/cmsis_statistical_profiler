/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_stack_regions_config.h
 * Description:  Native explicit stack-region test configuration
 *
 * $Date:        1 October 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef TEST_PROFILER_STACK_REGIONS_CONFIG_H
#define TEST_PROFILER_STACK_REGIONS_CONFIG_H
#define PROFILER_DEVICE_HEADER "fake_device.h"
#define PROFILER_SAMPLE_BUFFER_BYTES (248U + 12U * PROFILER_PMU_COUNT)
#define PROFILER_STACK_REGIONS                                                                                         \
    {                                                                                                                  \
        {                                                                                                              \
            (uintptr_t) fake_stack, sizeof(fake_stack)                                                                 \
        }                                                                                                              \
    }
#endif
