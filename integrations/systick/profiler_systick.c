/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_systick.c
 * Description:  Exclusive SysTick sampling timer integration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include PROFILER_DEVICE_HEADER

/* Explicit exclusive ownership. No HAL/RTOS tick chaining. */
_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");
static uint32_t owned;
int profiler_timer_init(struct ProfilerClock *clock)
{
    uint32_t period = profiler_timer_period(SystemCoreClock, 0x1000000U);
    if (!period || (!owned && (SysTick->CTRL & SysTick_CTRL_ENABLE_Msk)))
        return 0;
    owned = 1U;
    profiler_timer_stop();
    SysTick->LOAD = period - 1U;
    SysTick->VAL = 0U;
    NVIC_SetPriority(SysTick_IRQn, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = SystemCoreClock;
    clock->timer_period = period;
    return 1;
}
void profiler_timer_start(void)
{
    SysTick->CTRL = SysTick_CTRL_ENABLE_Msk | SysTick_CTRL_TICKINT_Msk | SysTick_CTRL_CLKSOURCE_Msk;
}
void profiler_timer_stop(void)
{
    if (!owned)
        return;
    SysTick->CTRL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
}
int profiler_timer_ack(void) { return owned && (SysTick->CTRL & SysTick_CTRL_ENABLE_Msk); }
PROFILER_DEFINE_IRQ_HANDLER(SysTick_Handler)
