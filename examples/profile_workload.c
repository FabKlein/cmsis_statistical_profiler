/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profile_workload.c
 * Description:  Profile an application-supplied workload without a model dependency
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "profile_workload.h"
#include "sampling_profiler.h"
#include "sampling_profiler_port.h"

#ifndef PROFILER_SAMPLE_DURATION_MS
    #define PROFILER_SAMPLE_DURATION_MS 30000U
#endif
_Static_assert(PROFILER_SAMPLE_DURATION_MS > 0U && PROFILER_SAMPLE_DURATION_MS < 0x80000000U,
               "Capture timeout must be positive and wrap-safe");

__attribute__((noinline, used)) void profiler_capture_complete(void) { profiler_port_barrier(); }

int profile_workload(int (*run_once)(void), int (*validate)(void))
{
#if PROFILER_SAMPLING_ENABLED
    if (run_once == 0 || validate == 0 || !sampling_profiler_init())
        return 0;
    uint32_t iterations = 0;
    uint32_t started = profiler_port_millis();
    uint32_t valid = 1;
    do
    {
        sampling_profiler_enable();
        int executed = run_once();
        sampling_profiler_disable();
        if (!executed || !validate())
        {
            valid = 0;
            break;
        }
        ++iterations;
    } while (!sampling_profiler_full() && profiler_port_millis() - started < PROFILER_SAMPLE_DURATION_MS);
    sampling_profiler_stop(iterations, valid);
    profiler_capture_complete();
    return valid && statistical_samples.header.count != 0U && statistical_samples.header.rejected == 0U;
#else
    (void)run_once;
    (void)validate;
    return 0;
#endif
}
