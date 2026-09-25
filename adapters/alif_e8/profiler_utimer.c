/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_utimer.c
 * Description:  Alif Ensemble E8 per-core UTIMER sampling adapter
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include PROFILER_DEVICE_HEADER
#include "profiler_utimer_config.h"

#ifndef PROFILER_TIMER_CLOCK_HZ
    #error "Set PROFILER_TIMER_CLOCK_HZ to the UTIMER input clock configured by your board"
#endif
_Static_assert(PROFILER_TIMER_CLOCK_HZ > 0U && PROFILER_TIMER_CLOCK_HZ <= UINT32_MAX,
               "Timer clock must fit a positive uint32");
#define CHANNEL (UTIMER->UTIMER_CHANNEL_CFG[PROFILER_ALIF_UTIMER_CHANNEL])
#define CHANNEL_MASK (1UL << PROFILER_ALIF_UTIMER_CHANNEL)
#define OVERFLOW 0x80U
#define PROGRAM_ENABLE 0x80000000U
_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");
static uint32_t owned;

/** @brief Configure only this image's reserved channel; shared clocks must already be enabled. */
int profiler_timer_init(struct ProfilerClock *clock)
{
    uint32_t period = profiler_timer_period(PROFILER_TIMER_CLOCK_HZ, UINT32_MAX);
    /* Startup owns the shared clock register and reserves this channel across cores. */
    if (!period || !(UTIMER->UTIMER_GLB_CLOCK_ENABLE & CHANNEL_MASK))
        return profiler_init_fail(
            PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, PROFILER_TIMER_CLOCK_HZ, PROFILER_SAMPLE_HZ);
    if (NVIC_GetTargetState(PROFILER_ALIF_TIMER_IRQ))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_DENIED, PROFILER_ALIF_TIMER_IRQ, 0);
    if (!owned &&
        ((UTIMER->UTIMER_GLB_CNTR_RUNNING & CHANNEL_MASK) || (CHANNEL.UTIMER_CNTR_CTRL & 1U) ||
         NVIC_GetEnableIRQ(PROFILER_ALIF_TIMER_IRQ)))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BUSY, PROFILER_ALIF_TIMER_IRQ, 0);
    owned = 1U;
    CHANNEL.UTIMER_START_0_SRC = 0U;
    CHANNEL.UTIMER_STOP_0_SRC = 0U;
    CHANNEL.UTIMER_CLEAR_0_SRC = 0U;
    CHANNEL.UTIMER_START_1_SRC = PROGRAM_ENABLE;
    CHANNEL.UTIMER_STOP_1_SRC = PROGRAM_ENABLE;
    CHANNEL.UTIMER_CLEAR_1_SRC = PROGRAM_ENABLE;
    profiler_timer_stop();
    CHANNEL.UTIMER_CNTR_CTRL = 1U; /* Enabled, continuous up-count. */
    CHANNEL.UTIMER_BUF_OP_CTRL = 0U;
    CHANNEL.UTIMER_COMPARE_CTRL_A = 0U;
    CHANNEL.UTIMER_COMPARE_CTRL_B = 0U;
    CHANNEL.UTIMER_CNTR = 0U;
    CHANNEL.UTIMER_CNTR_PTR = period - 1U;
    NVIC_SetPriority(PROFILER_ALIF_TIMER_IRQ, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = PROFILER_TIMER_CLOCK_HZ;
    clock->timer_period = period;
    return 1;
}
void profiler_timer_start(void)
{
    CHANNEL.UTIMER_CHAN_INTERRUPT = OVERFLOW;
    CHANNEL.UTIMER_CHAN_INTERRUPT_MASK = ~OVERFLOW;
    NVIC_ClearPendingIRQ(PROFILER_ALIF_TIMER_IRQ);
    NVIC_EnableIRQ(PROFILER_ALIF_TIMER_IRQ);
    UTIMER->UTIMER_GLB_CNTR_START = CHANNEL_MASK;
}
void profiler_timer_stop(void)
{
    if (!owned)
        return;
    NVIC_DisableIRQ(PROFILER_ALIF_TIMER_IRQ);
    CHANNEL.UTIMER_CHAN_INTERRUPT_MASK = UINT32_MAX;
    UTIMER->UTIMER_GLB_CNTR_STOP = CHANNEL_MASK;
    UTIMER->UTIMER_GLB_CNTR_CLEAR = CHANNEL_MASK;
    CHANNEL.UTIMER_CHAN_INTERRUPT = 0xFFU;
    NVIC_ClearPendingIRQ(PROFILER_ALIF_TIMER_IRQ);
}
int profiler_timer_ack(void)
{
    if (!owned || !(CHANNEL.UTIMER_CHAN_STATUS & OVERFLOW))
        return 0;
    CHANNEL.UTIMER_CHAN_INTERRUPT = OVERFLOW;
    __DSB();
    return 1;
}
PROFILER_DEFINE_IRQ_HANDLER(PROFILER_ALIF_TIMER_HANDLER)
