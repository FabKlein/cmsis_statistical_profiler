/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_stack_regions.c
 * Description:  Explicit stack-region boundary tests
 *
 * $Date:        1 October 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "fake_device.h"
#include "sampling_profiler_cortex_m.h"
#include <assert.h>
#include <stddef.h>

struct FakeDWT fake_dwt;
struct FakeDCB fake_dcb;
struct FakeSCB fake_scb;
uint32_t SystemCoreClock = 100000000U, fake_stack[16];
uint32_t fake_primask, fake_priority;
int fake_counter_runs = 1;
static uint32_t running;

int profiler_timer_init(struct ProfilerClock *clock)
{
    clock->timer_hz = SystemCoreClock;
    clock->timer_period = profiler_timer_period(SystemCoreClock, UINT32_MAX);
    return clock->timer_period != 0U;
}
void profiler_timer_start(void) { running = 1U; }
void profiler_timer_stop(void) { running = 0U; }
int profiler_timer_ack(void) { return running != 0U; }
void SCB_CleanDCache_by_Addr(void *address, int32_t bytes)
{
    (void)address;
    (void)bytes;
}

int main(void)
{
    fake_stack[6] = 0x10001004U;
    fake_stack[7] = xPSR_T_Msk;
    assert(profiler_init());
    profiler_enable();
    statistical_sampling_tick(fake_stack, 0xFFFFFFF9U);
    assert(statistical_samples.header.count == 1U);
    /* A complete exception frame cannot start this close to the region end. */
    statistical_sampling_tick(fake_stack + 9, 0xFFFFFFF9U);
    assert(statistical_samples.header.rejected == 1U);
    profiler_stop(1U, 1U);
    assert(!running);
    return 0;
}
