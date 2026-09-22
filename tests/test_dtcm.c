/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_dtcm.c
 * Description:  DTCM size detection and stack boundary tests
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "fake_device.h"
#include "sampling_profiler_cortex_m.h"
#include <assert.h>
#include <stddef.h>

struct FakeMEMSYSCTL fake_memsysctl;
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
    /* Each encoding must refresh the whitelist on re-init, without hardcoding
     * a device's TCM capacity. The synthetic outside pointer is never read. */
    for (uint32_t size = 3U; size <= 15U; ++size)
    {
        MEMSYSCTL->DTCMCR = MEMSYSCTL_DTCMCR_EN_Msk | (size << MEMSYSCTL_DTCMCR_SZ_Pos);
        assert(sampling_profiler_init());
        sampling_profiler_enable();
        statistical_sampling_tick(fake_stack, 0xFFFFFFF9U);
        assert(statistical_samples.header.count == 1U);
        uintptr_t bytes = (uintptr_t)512U << size;
        const uint32_t *outside = (const uint32_t *)((uintptr_t)fake_stack + bytes - 28U);
        statistical_sampling_tick(outside, 0xFFFFFFF9U);
        assert(statistical_samples.header.rejected == 1U);
        sampling_profiler_stop(1U, 1U);
        assert(!running);
    }
    /* Disabled, absent, and reserved sizes must fail before enabling the timer. */
    const uint32_t invalid[] = {0U, 1U, 9U, 17U, 8U << MEMSYSCTL_DTCMCR_SZ_Pos};
    for (size_t i = 0U; i < sizeof(invalid) / sizeof(invalid[0]); ++i)
    {
        MEMSYSCTL->DTCMCR = invalid[i];
        assert(!sampling_profiler_init());
        sampling_profiler_enable();
        assert(!running && !statistical_sampling_gate);
    }
    return 0;
}
