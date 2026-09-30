/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_ctimer4.c
 * Description:  NXP MIMXRT685 CTIMER4 sampling adapter
 *
 * $Date:        30 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include "fsl_clock.h"
#include "fsl_reset.h"

#define PROFILER_CTIMER CTIMER4
#define PROFILER_CTIMER_IRQ CTIMER4_IRQn
#define PROFILER_CTIMER_CLOCK_GATE CLKCTL1_PSCCTL2_CT32BIT4_CLK_MASK
#define PROFILER_CTIMER_MATCH_FLAG CTIMER_IR_MR0INT_MASK

_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");

static uint32_t owned;

int profiler_timer_init(struct ProfilerClock *clock)
{
    uint32_t hz;
    uint32_t period;

    if (!owned && (((CLKCTL1->PSCCTL2 & PROFILER_CTIMER_CLOCK_GATE) != 0U) ||
                   (NVIC_GetEnableIRQ(PROFILER_CTIMER_IRQ) != 0U)))
    {
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BUSY, PROFILER_CTIMER_IRQ, 0U);
    }

    CLOCK_AttachClk(kMAIN_CLK_to_CTIMER4);
    CLOCK_EnableClock(kCLOCK_Ct32b4);
    hz = CLOCK_GetCtimerClkFreq(4U);
    period = profiler_timer_period(hz, UINT32_MAX);
    if (period == 0U)
    {
        CLOCK_DisableClock(kCLOCK_Ct32b4);
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, hz, PROFILER_SAMPLE_HZ);
    }

    RESET_PeripheralReset(kCT32B4_RST_SHIFT_RSTn);
    owned = 1U;
    profiler_timer_stop();
    PROFILER_CTIMER->CTCR = 0U;
    PROFILER_CTIMER->PR = 0U;
    PROFILER_CTIMER->MR[0] = period;
    PROFILER_CTIMER->MCR = CTIMER_MCR_MR0I_MASK | CTIMER_MCR_MR0R_MASK;
    PROFILER_CTIMER->IR = PROFILER_CTIMER_MATCH_FLAG;
    NVIC_SetPriority(PROFILER_CTIMER_IRQ, PROFILER_IRQ_PRIORITY);

    clock->timer_hz = hz;
    clock->timer_period = period;
    return 1;
}

void profiler_timer_start(void)
{
    PROFILER_CTIMER->TCR = CTIMER_TCR_CRST_MASK;
    PROFILER_CTIMER->TCR = 0U;
    PROFILER_CTIMER->IR = PROFILER_CTIMER_MATCH_FLAG;
    NVIC_ClearPendingIRQ(PROFILER_CTIMER_IRQ);
    NVIC_EnableIRQ(PROFILER_CTIMER_IRQ);
    PROFILER_CTIMER->TCR = CTIMER_TCR_CEN_MASK;
}

void profiler_timer_stop(void)
{
    if (owned == 0U)
    {
        return;
    }

    NVIC_DisableIRQ(PROFILER_CTIMER_IRQ);
    PROFILER_CTIMER->TCR = 0U;
    PROFILER_CTIMER->IR = PROFILER_CTIMER_MATCH_FLAG;
    __DSB();
    NVIC_ClearPendingIRQ(PROFILER_CTIMER_IRQ);
}

int profiler_timer_ack(void)
{
    if ((owned == 0U) || ((PROFILER_CTIMER->IR & PROFILER_CTIMER_MATCH_FLAG) == 0U))
    {
        return 0;
    }

    PROFILER_CTIMER->IR = PROFILER_CTIMER_MATCH_FLAG;
    __DSB();
    return 1;
}

PROFILER_DEFINE_IRQ_HANDLER(CTIMER4_IRQHandler)
