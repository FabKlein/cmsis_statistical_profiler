/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_unwind_entry.c
 * Description:  Interrupted register and task-stack reconstruction tests
 *
 * $Date:        24 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "fake_device.h"
#include "sampling_profiler_unwind.h"
#include <assert.h>
#include <string.h>
uint32_t unwind_stacks[128], fake_primask;
static uint32_t running, calls, expected_sp, expected_base, mode, expected_exc;
int profiler_timestamp_init(uint32_t *hz)
{
    *hz = 1000000;
    return 1;
}
uint32_t profiler_timestamp_read(void) { return 1000; }
int profiler_timer_init(struct ProfilerClock *clock)
{
    clock->timer_hz = 1000000;
    clock->timer_period = 1000;
    return 1;
}
void profiler_timer_start(void) { running = 1; }
void profiler_timer_stop(void) { running = 0; }
int profiler_timer_ack(void) { return running; }
int profiler_unwind_init(void) { return 1; }
int profiler_stack_bounds(uint32_t exc, struct ProfilerStackBounds *bounds)
{
    assert(exc == expected_exc);
    bounds->base = (uintptr_t)(unwind_stacks + ((exc & 4U) ? 64U : 0U));
    bounds->bytes = mode == 1U ? 32U : 64U * 4U;
    if (mode == 2U)
        bounds->base = (uintptr_t)(unwind_stacks + ((exc & 4U) ? 0U : 64U));
    return 1;
}
void profiler_unwind_capture(struct ProfilerSample *sample, uint32_t regs[16], const struct ProfilerStackBounds *bounds)
{
    ++calls;
    for (unsigned i = 0; i < 13; ++i)
        assert(regs[i] == 0x100U + i);
    assert(regs[13] == expected_sp && regs[14] == 0x2005U && regs[15] == 0x1004U);
    assert(bounds->base == expected_base && bounds->bytes == 64U * 4U);
    sample->unwind = 1U | (PROFILER_UNWIND_NO_TABLE << 8);
    sample->callers[0] = 0x2005U;
}
int main(void)
{
    uint32_t saved[] = {0x108, 0x109, 0x10A, 0x10B, 0x104, 0x105, 0x106, 0x107};
    for (unsigned psp = 0; psp < 2; ++psp)
        for (unsigned fp = 0; fp < 2; ++fp)
            for (unsigned padding = 0; padding < 2; ++padding)
            {
                mode = calls = 0;
                uint32_t *frame = unwind_stacks + (psp ? 64 : 0);
                expected_exc = (0xFFFFFFF9U | (psp << 2)) & ~(fp << 4);
                expected_base = (uint32_t)(uintptr_t)frame;
                expected_sp = expected_base + (fp ? 104U : 32U) + 4U * padding;
                for (unsigned i = 0; i < 4; ++i)
                    frame[i] = 0x100U + i;
                frame[4] = 0x10CU;
                frame[5] = 0x2005U;
                frame[6] = 0x1004U;
                frame[7] = (1U << 24) | (padding << 9);
                assert(sampling_profiler_init());
                sampling_profiler_enable();
                statistical_sampling_tick(frame, expected_exc, saved);
                assert(calls == 1 && statistical_samples.header.count == 1 && !statistical_samples.header.rejected);
                assert(statistical_samples.records[6] == (1U | (PROFILER_UNWIND_NO_TABLE << 8)));
                assert(statistical_samples.records[7] == 0x2005);
                mode = 1; /* Core frame readable, but extended/aligned frame does not fit. */
                if (fp || padding)
                {
                    calls = 0;
                    assert(sampling_profiler_init());
                    sampling_profiler_enable();
                    statistical_sampling_tick(frame, expected_exc, saved);
                    assert(calls == 0 && statistical_samples.header.count == 1);
                    assert(statistical_samples.records[6] == (PROFILER_UNWIND_BOUNDS << 8));
                    for (unsigned i = 7; i < 15; ++i)
                        assert(statistical_samples.records[i] == 0);
                }
                mode = 2; /* Wrong current task / context-switch mismatch. */
                calls = 0;
                assert(sampling_profiler_init());
                sampling_profiler_enable();
                statistical_sampling_tick(frame, expected_exc, saved);
                assert(calls == 0 && statistical_samples.header.count == 0 && statistical_samples.header.rejected == 1);
            }
    return 0;
}
