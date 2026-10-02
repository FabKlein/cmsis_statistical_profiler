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
 * $Date:        2 October 2026
 * $Revision:    V.1.0.2
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file reference_timestamp.c
 * @brief Read the shared reference counter without changing its state.
 */

#include "SSE300MPS3.h"
#include "profiler_backend.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"
#include "systimer_armv8-m_reg_map.h"

/* System Counter Control Register (CNTCR), enable bit (EN).
 * The Board Support Package (BSP) defines this bit only in its driver source. */
#define CNTCR_ENABLE (1UL << 0)

_Static_assert(PROFILER_TIMER_CLOCK_HZ > 0U && PROFILER_TIMER_CLOCK_HZ <= UINT32_MAX,
               "Reference clock must fit a positive uint32");

/** @brief Use the unscaled reference counter started by the example application. */
int profiler_timestamp_init(uint32_t *frequency_hz)
{
    const struct cnt_control_base_reg_map_t *counter = (const void *)SYSCNTR_CNTRL_BASE_S;
    if (!(counter->cntcr & CNTCR_ENABLE))
        return 0;
    *frequency_hz = PROFILER_TIMER_CLOCK_HZ;
    return 1;
}

/** @brief Read the low word atomically; wrapping is modulo 2^32. */
uint32_t profiler_timestamp_read(void)
{
    const struct cnt_base_reg_map_t *timer = (const void *)SYSTIMER0_ARMV8_M_BASE_S;
    return timer->cntpct_low;
}
