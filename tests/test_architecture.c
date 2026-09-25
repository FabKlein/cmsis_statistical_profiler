/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_architecture.c
 * Description:  Architecture, security state and custom timestamp tests
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "fake_device.h"
#include "sampling_profiler_cortex_m.h"
#include <assert.h>
#include <stdio.h>

uint32_t fake_stack[16], fake_primask, SystemCoreClock;
static uint32_t timestamp = 0xFFFFF000U, running;
int profiler_timestamp_init(uint32_t *hz)
{
    *hz = 1000000U;
    return 1;
}
uint32_t profiler_timestamp_read(void) { return timestamp; }
int profiler_timer_init(struct ProfilerClock *clock)
{
    clock->timer_hz = 37000000U;
    clock->timer_period = profiler_timer_period(clock->timer_hz, UINT32_MAX);
    return clock->timer_period != 0U;
}
void profiler_timer_start(void) { running = 1; }
void profiler_timer_stop(void) { running = 0; }
int profiler_timer_ack(void) { return running; }
static void sample(uint32_t exc)
{
    timestamp += 3003U;
    statistical_sampling_tick(fake_stack, exc);
}
#if PROFILER_PRECISE_STACK_BOUNDS
static uint32_t bounds_mode, bounds_calls;
int profiler_stack_bounds(uint32_t exc, struct ProfilerStackBounds *bounds)
{
    ++bounds_calls;
    bounds->base = (uintptr_t)(fake_stack + ((exc & 4U) ? 8U : 0U));
    bounds->bytes = 32U;
    if (bounds_mode == 1U)
        return 0;
    if (bounds_mode == 2U)
        bounds->bytes = 0U;
    if (bounds_mode == 3U)
        bounds->bytes = 28U;
    if (bounds_mode == 4U)
    {
        bounds->base = UINTPTR_MAX - 15U;
        bounds->bytes = 64U; /* Wrapping allocation must be rejected. */
    }
    if (bounds_mode == 5U)
    {
        bounds->base = 0x1000U;
        bounds->bytes = 32U; /* Outside the RAM whitelist despite precise bounds. */
    }
    return 1;
}

static void check_precise_bounds(uint32_t basic)
{
    assert(sampling_profiler_init());
    assert(!statistical_samples.header.rejected);
    for (unsigned i = 0; i < PROFILER_REJECT_REASON_COUNT; ++i)
        assert(!statistical_samples.header.rejected_reason[i]);
    sampling_profiler_enable();
    bounds_calls = 0;
    sample(basic | 2U);
    sample(basic & ~8U);
    assert(!bounds_calls); /* Invalid metadata is rejected before invoking the hook. */
    for (bounds_mode = 1U; bounds_mode <= 4U; ++bounds_mode)
        sample(basic);
    bounds_mode = 5U;
    statistical_sampling_tick((const uint32_t *)(uintptr_t)0x1000U, basic);
    bounds_mode = 0U;
    sample(basic | 4U);                               /* MSP memory must not pass the selected PSP allocation. */
    statistical_sampling_tick(fake_stack + 1, basic); /* Crosses precise end, still inside RAM. */
    assert(statistical_samples.header.rejected_reason[PROFILER_REJECT_STACK_BOUNDS] == 7U);
    assert(statistical_samples.header.rejected == 9U && !statistical_samples.header.count);
    sample(basic); /* Exact MSP allocation. */
    for (unsigned i = 0; i < 8U; ++i)
        fake_stack[i + 8U] = fake_stack[i];
    statistical_sampling_tick(fake_stack + 8, basic | 4U); /* Exact PSP allocation. */
    assert(statistical_samples.header.count == 2U);
    uint32_t calls = bounds_calls;
    sampling_profiler_disable();
    sample(basic);
    assert(bounds_calls == calls && statistical_samples.header.rejected == 9U);
    sampling_profiler_stop(1U, 1U);
}
#endif

int main(int argc, char **argv)
{
    assert(argc == 2);
    /* A custom timestamp does not depend on SystemCoreClock, DWT or TCM. */
    assert(sampling_profiler_init());
    assert(statistical_samples.header.timestamp_hz == 1000000U);
    assert(statistical_samples.header.version == 2U);
    fake_stack[5] = 0x10002001U;
    fake_stack[6] = 0x10001004U;
    fake_stack[7] = xPSR_T_Msk;
    sampling_profiler_enable();
#if defined(TEST_V8) && defined(TEST_NONSECURE)
    const uint32_t basic = 0xFFFFFFB8U, other_state = 0xFFFFFFF9U;
#else
    const uint32_t basic = 0xFFFFFFF9U, other_state = 0xFFFFFFB8U;
#endif
    sample(other_state);
    sample(basic & ~8U);    /* Handler mode */
    sample(basic & ~0x20U); /* Non-default callee frame / reserved legacy bit */
    sample(basic | 2U);
    assert(statistical_samples.header.rejected == 4U);
    sample(basic);
#if PROFILER_PRECISE_STACK_BOUNDS
    /* The bounds hook maps PSP to the other half of fake_stack. */
    for (unsigned i = 0; i < 8U; ++i)
        fake_stack[i + 8U] = fake_stack[i];
    timestamp += 3003U;
    statistical_sampling_tick(fake_stack + 8, basic | 4U);
#else
    sample(basic | 4U); /* PSP */
#endif
    sample(basic & ~0x10U); /* Extended frame requires FP/MVE hardware */
#if __FPU_PRESENT
    assert(statistical_samples.header.count == 3U);
#else
    assert(statistical_samples.header.count == 2U);
    assert(statistical_samples.header.rejected == 5U);
    sample(basic);
#endif
    sampling_profiler_stop(1U, 1U);
    FILE *out = fopen(argv[1], "wb");
    assert(out && fwrite((const void *)&statistical_samples, sizeof(statistical_samples), 1, out) == 1);
    assert(fclose(out) == 0);
#if PROFILER_PRECISE_STACK_BOUNDS
    check_precise_bounds(basic);
#endif
    return 0;
}
