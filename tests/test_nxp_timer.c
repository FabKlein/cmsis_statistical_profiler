/* SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: Apache-2.0 */
#include "fake_nxp_timer.h"
#include "profiler_backend.h"
#include <assert.h>

/* Native register tests do not execute the Arm exception-entry assembly. */
#undef PROFILER_DEFINE_IRQ_HANDLER
#define PROFILER_DEFINE_IRQ_HANDLER(name)                                                                              \
    void name(void) {}
#include "../adapters/nxp_rt685/profiler_ctimer4.c"

struct FakeClockControl fake_clock_control;
static struct FakeCtimer registers;
static uint32_t clock_hz, off_accesses, irq_enabled, attach_count;
static enum ProfilerInitReason last_reason;
struct FakeCtimer *fake_ctimer_access(void)
{
    if (!(fake_clock_control.PSCCTL2 & 1U))
        ++off_accesses;
    return &registers;
}
void CLOCK_AttachClk(int source)
{
    (void)source;
    ++attach_count;
}
void CLOCK_EnableClock(int gate)
{
    (void)gate;
    fake_clock_control.PSCCTL2 |= 1U;
}
void CLOCK_DisableClock(int gate)
{
    (void)gate;
    fake_clock_control.PSCCTL2 &= ~1U;
}
uint32_t CLOCK_GetCtimerClkFreq(unsigned timer)
{
    (void)timer;
    return clock_hz;
}
void RESET_PeripheralReset(int reset) { (void)reset; }
uint32_t NVIC_GetEnableIRQ(int irq)
{
    (void)irq;
    return irq_enabled;
}
void NVIC_SetPriority(int irq, unsigned priority)
{
    (void)irq;
    (void)priority;
}
void NVIC_ClearPendingIRQ(int irq) { (void)irq; }
void NVIC_EnableIRQ(int irq)
{
    (void)irq;
    irq_enabled = 1U;
}
void NVIC_DisableIRQ(int irq)
{
    (void)irq;
    irq_enabled = 0U;
}
int profiler_init_fail(enum ProfilerInitStage stage, enum ProfilerInitReason reason, uint32_t a, uint32_t b)
{
    (void)stage;
    (void)a;
    (void)b;
    last_reason = reason;
    return 0;
}
uint32_t profiler_timer_period(uint32_t hz, uint32_t max)
{
    (void)max;
    return hz / PROFILER_SAMPLE_HZ;
}
int main(void)
{
    struct ProfilerClock clock;
    irq_enabled = 1U;
    assert(!profiler_timer_init(&clock) && last_reason == PROFILER_INIT_BUSY);
    assert(irq_enabled && !attach_count);
    irq_enabled = 0U;
    fake_clock_control.PSCCTL2 = 3U;
    assert(!profiler_timer_init(&clock) && !attach_count);
    fake_clock_control.PSCCTL2 = 2U; /* Preserve an unrelated gate throughout. */
    assert(!profiler_timer_init(&clock) && last_reason == PROFILER_INIT_BAD_CLOCK);
    profiler_timer_stop();
    assert(fake_clock_control.PSCCTL2 == 2U && !off_accesses);
    clock_hz = 48000000U;
    assert(profiler_timer_init(&clock));
    assert(profiler_timer_start());
    profiler_timer_stop();
    clock_hz = 0U;
    assert(!profiler_timer_init(&clock));
    profiler_timer_stop();
    profiler_timer_stop();
    assert(!off_accesses && fake_clock_control.PSCCTL2 == 3U && !irq_enabled);
    clock_hz = 48000000U;
    assert(profiler_timer_init(&clock) && profiler_timer_start());
    profiler_timer_stop();
    assert(!off_accesses);
    return 0;
}
