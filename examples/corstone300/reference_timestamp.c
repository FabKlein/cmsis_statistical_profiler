/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        reference_timestamp.c
 * Description:  Corstone-300 reference-counter timestamp for the example
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file reference_timestamp.c
 * @brief Read the shared reference counter without changing its state.
 */

#include "sampling_profiler_cortex_m.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"
#include "systimer_armv8-m_reg_map.h"

_Static_assert(PROFILER_TIMER_CLOCK_HZ > 0U && PROFILER_TIMER_CLOCK_HZ <= UINT32_MAX,
               "Reference clock must fit a positive uint32");

/** @brief Use the unscaled reference counter started by the example application. */
int profiler_timestamp_init(uint32_t *frequency_hz)
{
    const struct cnt_control_base_reg_map_t *counter = (const void *)0x58100000UL;
    if (!(counter->cntcr & 1U))
        return 0;
    *frequency_hz = PROFILER_TIMER_CLOCK_HZ;
    return 1;
}

/** @brief Read the low word atomically; wrapping is modulo 2^32. */
uint32_t profiler_timestamp_read(void)
{
    const struct cnt_base_reg_map_t *timer = (const void *)0x58000000UL;
    return timer->cntpct_low;
}
