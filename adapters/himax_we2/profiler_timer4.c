/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_timer4.c
 * Description:  Himax WE2 TIMER4 sampling adapter
 *
 * $Date:        2 October 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include <stdint.h>

#include "WE2_core.h"
#include "hx_drv_timer.h"
#include "profiler_backend.h"

#define PROFILER_TIMER_ID  TIMER_ID_4
#define PROFILER_TIMER_IRQ TIMER4INT_IRQn

_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");

static uint32_t owned;
static TIMER_CFG_T timer_config = {
    .period = 1U,
    .mode = TIMER_MODE_PERIODICAL,
    .ctrl = TIMER_CTRL_CPU,
    .state = TIMER_STATE_DC,
};

void profiler_timer4_irq_handler(void);

static void unused_vendor_callback(uint32_t event) { (void)event; }

int profiler_timer_init(struct ProfilerClock *clock)
{
    uint8_t used = 0U;
    uint32_t divider = 0U;
    uint32_t source_hz = 0U;
    uint32_t timer_hz;
    uint32_t period;

    if ((1000U % PROFILER_SAMPLE_HZ) != 0U)
    {
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, 1000U, PROFILER_SAMPLE_HZ);
    }

    if ((hx_drv_timer_get_used(PROFILER_TIMER_ID, &used) != TIMER_NO_ERROR) ||
        ((!owned) && ((used != 0U) || (NVIC_GetEnableIRQ(PROFILER_TIMER_IRQ) != 0U))))
    {
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BUSY, PROFILER_TIMER_IRQ, used);
    }

    if ((hx_drv_timer_get_clk(PROFILER_TIMER_ID, &source_hz) != TIMER_NO_ERROR) ||
        (hx_drv_timer_get_clk_div(PROFILER_TIMER_ID, &divider) != TIMER_NO_ERROR) || (divider == 0U))
    {
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, source_hz, divider);
    }

    timer_hz = source_hz / divider;
    period = profiler_timer_period(timer_hz, UINT32_MAX);
    if (period == 0U)
    {
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, timer_hz, PROFILER_SAMPLE_HZ);
    }

    timer_config.period = 1000U / PROFILER_SAMPLE_HZ;
    owned = 1U;
    profiler_timer_stop();
    EPII_NVIC_SetVector(PROFILER_TIMER_IRQ, (uint32_t)(uintptr_t)profiler_timer4_irq_handler);
    NVIC_SetPriority(PROFILER_TIMER_IRQ, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = timer_hz;
    clock->timer_period = period;
    return 1;
}

int profiler_timer_start(void)
{
    NVIC_ClearPendingIRQ(PROFILER_TIMER_IRQ);
    int status = hx_drv_timer_hw_start(PROFILER_TIMER_ID, &timer_config, unused_vendor_callback);
    if (status != TIMER_NO_ERROR)
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_UNAVAILABLE, PROFILER_TIMER_IRQ, (uint32_t)status);

    EPII_NVIC_SetVector(PROFILER_TIMER_IRQ, (uint32_t)(uintptr_t)profiler_timer4_irq_handler);
    NVIC_EnableIRQ(PROFILER_TIMER_IRQ);
    return 1;
}

void profiler_timer_stop(void)
{
    if (owned == 0U)
    {
        return;
    }

    NVIC_DisableIRQ(PROFILER_TIMER_IRQ);
    (void)hx_drv_timer_hw_stop(PROFILER_TIMER_ID);
    hx_drv_timer_ClearIRQ(PROFILER_TIMER_ID);
    __DSB();
    NVIC_ClearPendingIRQ(PROFILER_TIMER_IRQ);
}

int profiler_timer_ack(void)
{
    if ((owned == 0U) || (hx_drv_timer_StatusIRQ(PROFILER_TIMER_ID) == 0U))
    {
        return 0;
    }

    hx_drv_timer_ClearIRQ(PROFILER_TIMER_ID);
    __DSB();
    return 1;
}

PROFILER_DEFINE_IRQ_HANDLER(profiler_timer4_irq_handler)
