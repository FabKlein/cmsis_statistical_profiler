/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_timer0.c
 * Description:  Corstone-300 TIMER0 sampling adapter
 *
 * $Date:        30 September 2026
 * $Revision:    V.1.0.2
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include PROFILER_DEVICE_HEADER
#include "syscounter_armv8-m_cntrl_reg_map.h"
#include "systimer_armv8-m_reg_map.h"

/* System Counter Control Register (CNTCR), enable bit (EN).
 * The Board Support Package (BSP) defines this bit only in its driver source. */
#define CNTCR_ENABLE (1UL << 0)

/* SSE-300 secure TIMER0, Armv8-M system timer with auto-increment.
 * This is a reference-counter clock, not necessarily SystemCoreClock. */
#ifndef PROFILER_TIMER_CLOCK_HZ
    #error "Set PROFILER_TIMER_CLOCK_HZ to the platform reference counter frequency"
#endif
_Static_assert(PROFILER_TIMER_CLOCK_HZ > 0U && PROFILER_TIMER_CLOCK_HZ <= UINT32_MAX,
               "Timer clock must fit a positive uint32");
/* Physical timer register fields, following the BSP system-timer driver:
 * CTL = control, IMASK = interrupt mask, ISTATUS = interrupt status,
 * CFG = configuration, AIVAL = auto-increment value, IRQ = interrupt request. */
#define CNTP_CTL_ENABLE (1UL << 0)
#define CNTP_CTL_IMASK (1UL << 1)
#define CNTP_CTL_ISTATUS (1UL << 2)
#define CNTP_CFG_AUTOINC (1UL << 0)
#define CNTP_AIVAL_CTL_ENABLE (1UL << 0)
#define CNTP_AIVAL_CTL_IRQ_CLEAR (1UL << 1)

#define TIMER ((struct cnt_base_reg_map_t *)SYSTIMER0_ARMV8_M_BASE_S)
_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");
static uint32_t owned;

int profiler_timer_init(struct ProfilerClock *clock)
{
    uint32_t period = profiler_timer_period(PROFILER_TIMER_CLOCK_HZ, UINT32_MAX);
    const struct cnt_control_base_reg_map_t *counter = (const void *)SYSCNTR_CNTRL_BASE_S;
    if (!(counter->cntcr & CNTCR_ENABLE) || !period)
        return profiler_init_fail(
            PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, PROFILER_TIMER_CLOCK_HZ, PROFILER_SAMPLE_HZ);
    if (!(TIMER->cntp_cfg & CNTP_CFG_AUTOINC))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_UNAVAILABLE, TIMER0_IRQn, 0);
    if (NVIC_GetTargetState(TIMER0_IRQn))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_DENIED, TIMER0_IRQn, 0);
    if (!owned && ((TIMER->cntp_ctl & CNTP_CTL_ENABLE) || NVIC_GetEnableIRQ(TIMER0_IRQn)))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BUSY, TIMER0_IRQn, 0);
    owned = 1U;
    profiler_timer_stop();
    TIMER->cntfrq = PROFILER_TIMER_CLOCK_HZ; /* Informational; does not change clock. */
    TIMER->cntp_aival_reload = period;
    NVIC_SetPriority(TIMER0_IRQn, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = PROFILER_TIMER_CLOCK_HZ;
    clock->timer_period = period;
    return 1;
}
void profiler_timer_start(void)
{
    TIMER->cntp_ctl = CNTP_CTL_ENABLE | CNTP_CTL_IMASK; /* Enable while masked, before starting auto-increment. */
    TIMER->cntp_aival_ctl = CNTP_AIVAL_CTL_ENABLE;
    TIMER->cntp_ctl = CNTP_CTL_ENABLE;
    NVIC_ClearPendingIRQ(TIMER0_IRQn);
    NVIC_EnableIRQ(TIMER0_IRQn);
}
void profiler_timer_stop(void)
{
    if (!owned)
        return;
    NVIC_DisableIRQ(TIMER0_IRQn);
    TIMER->cntp_ctl = CNTP_CTL_IMASK;
    TIMER->cntp_aival_ctl = 0U;
    NVIC_ClearPendingIRQ(TIMER0_IRQn);
}
int profiler_timer_ack(void)
{
    if (!owned || !(TIMER->cntp_ctl & CNTP_CTL_ISTATUS))
        return 0;
    /* Auto-increment interrupt status is cleared by writing bit 1 as 0. */
    TIMER->cntp_aival_ctl &= ~CNTP_AIVAL_CTL_IRQ_CLEAR;
    __DSB();
    return 1;
}
PROFILER_DEFINE_IRQ_HANDLER(TFM_TIMER0_IRQ_Handler)
