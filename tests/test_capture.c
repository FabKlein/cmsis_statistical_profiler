/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_capture.c
 * Description:  Capture lifecycle, sampling timer and frame validation tests
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
#include <string.h>

struct FakeSysTick fake_systick = {7U, 99999U, 50U};
struct FakeDWT fake_dwt;
struct FakeDCB fake_dcb;
struct FakeSCB fake_scb = {SCB_CCR_DC_Msk, 0U};
uint32_t SystemCoreClock = 100000000U, fake_stack[16];
uint32_t fake_primask, fake_priority = 3U;
int fake_counter_runs = 1;
static uint32_t clean_count;
static uint32_t timer_hz = 37000000U, timer_period, timer_running, timer_event;
static uint32_t timer_busy;
int profiler_timer_init(struct ProfilerClock *clock)
{
    timer_period = profiler_timer_period(timer_hz, UINT32_MAX);
    if (timer_busy || !timer_period)
        return 0;
    clock->timer_hz = timer_hz;
    clock->timer_period = timer_period;
    return 1;
}
void profiler_timer_start(void) { timer_running = 1U; }
void profiler_timer_stop(void) { timer_running = timer_event = 0U; }
int profiler_timer_ack(void)
{
    uint32_t event = timer_running && timer_event;
    timer_event = 0U;
    return event != 0U;
}

void SCB_CleanDCache_by_Addr(void *address, int32_t bytes)
{
    assert(address == (void *)&statistical_samples);
    assert(bytes == sizeof(statistical_samples));
    assert(statistical_samples.header.complete == 1U);
    assert(statistical_samples.header.active == 0U && !statistical_sampling_gate);
    ++clean_count;
}

static void frame(uint32_t *words)
{
    words[5] = 0x10002001U;
    words[6] = 0x10001004U;
    words[7] = xPSR_T_Msk;
}

static void tick(const uint32_t *words, uint32_t exc)
{
    fake_dwt.CYCCNT += (uint32_t)((uint64_t)timer_period * SystemCoreClock / timer_hz);
    timer_event = timer_running;
    statistical_sampling_tick(words, exc);
}

static void sample(const uint32_t *words, uint32_t exc) { tick(words, exc); }

int main(int argc, char **argv)
{
    assert(argc == 2);
#ifdef TEST_INVALID_RATE
    assert(!sampling_profiler_init());
    assert(SysTick->LOAD == 99999U && SysTick->CTRL == 7U);
    sampling_profiler_enable();
    assert(!statistical_sampling_gate);
    return 0;
#endif
    sampling_profiler_enable();
    tick(NULL, 0U); /* Ungated ISR still maintains time; must never read NULL. */
    assert(profiler_port_ticks() == 0U && !statistical_samples.header.count);
    SystemCoreClock = 0U;
    assert(!sampling_profiler_init());
    assert(sampling_profiler_diagnostics()->stage == PROFILER_INIT_TIMESTAMP);
    assert(sampling_profiler_diagnostics()->reason == PROFILER_INIT_UNAVAILABLE);
    sampling_profiler_enable();
    assert(!statistical_sampling_gate);
    timer_busy = 1U;
    SystemCoreClock = 100000000U;
    assert(!sampling_profiler_init());
    timer_busy = 0U;
    SystemCoreClock = 100000000U;
    fake_counter_runs = 0;
    assert(!sampling_profiler_init());
    fake_counter_runs = 1;
    DWT->CTRL = DWT_CTRL_NOCYCCNT_Msk;
    assert(!sampling_profiler_init());
    DWT->CTRL = 0;
    fake_primask = 1U;
    assert(sampling_profiler_init());
    assert(sampling_profiler_diagnostics()->reason == PROFILER_INIT_OK);
    assert(fake_primask == 1U && fake_priority == 3U); /* Preserve IRQ policy. */
    fake_primask = 0U;
    uint32_t period = (uint32_t)(((uint64_t)timer_hz + PROFILER_SAMPLE_HZ / 2U) / PROFILER_SAMPLE_HZ);
    assert(SysTick->LOAD == 99999U && SysTick->CTRL == 7U && SysTick->VAL == 50U);
    assert(timer_running && statistical_samples.header.timer_hz == timer_hz);
    uint32_t ticks_at_init = profiler_port_ticks(), millis_at_init = profiler_port_millis();
    frame(fake_stack);
    frame(fake_stack + 8); /* A frame ending exactly at the range boundary. */
    sampling_profiler_enable();
    /* A spurious IRQ must neither consume a record nor advance time. */
    uint32_t before_spurious = profiler_port_ticks();
    statistical_sampling_tick(fake_stack, 0xFFFFFFF9U);
    assert(profiler_port_ticks() == before_spurious && !statistical_samples.header.count);
    tick(fake_stack, 0xFFFFFFF9U);
    assert(statistical_samples.header.count == 1U);
    sampling_profiler_disable();
    sample(NULL, 0U); /* Inactive ticks maintain time without reading the frame. */
    sampling_profiler_enable();
    assert(statistical_samples.header.count == 1U);
    assert(statistical_samples.records[2] == fake_stack[6]);
    sample(fake_stack + 8, 0xFFFFFFEDU); /* FP/MVE, PSP */
    assert(statistical_samples.header.count == 2U);
    sample(fake_stack, 0xFFFFFFFDU);
    assert(sampling_profiler_full() && statistical_samples.header.count == 3U);
    uint32_t ticks = profiler_port_ticks();
    sample(NULL, 0U);
    assert(profiler_port_ticks() == ticks + 1U && !statistical_samples.header.rejected);
    for (unsigned i = 0; i < 10007U; ++i)
        tick(NULL, 0U);
    uint32_t expected_ms = (uint32_t)((uint64_t)(profiler_port_ticks() - ticks_at_init) * period * 1000U / timer_hz);
    assert(profiler_port_millis() - millis_at_init == expected_ms);
    sampling_profiler_enable();
    assert(!statistical_sampling_gate);
    sampling_profiler_stop(7U, 1U);
    assert(!timer_running);
    uint32_t stopped_ticks = profiler_port_ticks();
    sample(NULL, 0U);
    assert(profiler_port_ticks() == stopped_ticks);
    assert(statistical_samples.header.iterations == 7U);
    assert(statistical_samples.header.validation_passed == 1U);
#if __DCACHE_PRESENT
    assert(clean_count == 1U);
#else
    assert(clean_count == 0U);
#endif
    /* This native-produced binary is also decoded by the Python test suite. */
    FILE *output = fopen(argv[1], "wb");
    assert(output);
    assert(fwrite((const void *)&statistical_samples, sizeof(statistical_samples), 1, output) == 1);
    assert(fclose(output) == 0);

    SysTick->VAL = 77U;
    uint32_t previous_ms = profiler_port_millis();
    assert(sampling_profiler_init());
    assert(SysTick->VAL == 77U &&
           profiler_port_millis() == previous_ms); /* Application timer is untouched on recapture. */
    assert(!statistical_samples.header.count && !statistical_samples.header.complete);
    sampling_profiler_enable();
    sample(NULL, 0xFFFFFFF9U);
    sample((const uint32_t *)((uintptr_t)fake_stack + 1U), 0xFFFFFFF9U);
    sample(fake_stack + 9, 0xFFFFFFF9U); /* Insufficient readable bytes. */
    sample((const uint32_t *)(UINTPTR_MAX - 15U), 0xFFFFFFF9U);
    sample(fake_stack, 0xFFFFFFB8U); /* Non-secure */
    sample(fake_stack, 0xFFFFFFF1U); /* Handler mode */
    sample(fake_stack, 0xFFFFFFD9U); /* Additional callee stacking */
    sample(fake_stack, 0xFFFFFFFBU); /* Reserved bit */
    sample(fake_stack, 0x00000079U); /* Invalid prefix */
    fake_stack[7] = 0;
    sample(fake_stack, 0xFFFFFFF9U);
    fake_stack[7] = xPSR_T_Msk | 15U;
    sample(fake_stack, 0xFFFFFFF9U);
    assert(statistical_samples.header.rejected == 11U && !statistical_samples.header.count);
    assert(statistical_samples.header.rejected_reason[PROFILER_REJECT_EXC_RETURN] == 2U);
    assert(statistical_samples.header.rejected_reason[PROFILER_REJECT_UNSUPPORTED_FRAME] == 3U);
    assert(statistical_samples.header.rejected_reason[PROFILER_REJECT_STACK_BOUNDS] == 4U);
    assert(statistical_samples.header.rejected_reason[PROFILER_REJECT_XPSR] == 2U);
    frame(fake_stack);
    sample(fake_stack, 0xFFFFFFF9U);
    assert(statistical_samples.header.count == 1U);
    fake_scb.CCR = 0U;
    sampling_profiler_stop(1U, 0U);
    sampling_profiler_enable();
    assert(!statistical_sampling_gate);
#if __DCACHE_PRESENT
    assert(clean_count == 1U); /* Disabled cache needs no clean. */
#endif
    assert(SysTick->CTRL == 7U && SysTick->LOAD == 99999U && SysTick->VAL == 77U);
    assert(fake_priority == 3U && !fake_primask);
    puts("Capture lifecycle, timebase, frame bounds, security and cache checks passed");
    return 0;
}
