/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_alif_timer.c
 * Description:  Check per-core channel isolation and shared-clock ownership
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 * -------------------------------------------------------------------- */

#include "fake_alif_timer.h"
#include "profiler_utimer_config.h"
#include "sampling_profiler_cortex_m.h"
#include <assert.h>
#include <string.h>

/* Execute real timer operations on fake registers without an Arm IRQ prologue. */
#undef PROFILER_DEFINE_IRQ_HANDLER
#define PROFILER_DEFINE_IRQ_HANDLER(name)                                                                              \
    void name(void) {}
#include "../adapters/alif_e8/profiler_utimer.c"

struct FakeAlifTimer fake_timer;
uint32_t fake_enabled[480], fake_pending[480], fake_priority[480], fake_target[480];
uint32_t profiler_timer_period(uint32_t hz, uint32_t max)
{
    (void)max;
    return hz / PROFILER_SAMPLE_HZ;
}

int main(void)
{
    const uint32_t channel = PROFILER_ALIF_UTIMER_CHANNEL;
    const uint32_t other = (channel + 1U) % 12U;
    const uint32_t irq = PROFILER_ALIF_TIMER_IRQ;
    const uint32_t other_irq = 384U + 8U * other;
    struct ProfilerClock clock = {.timestamp_hz = 123U};
    struct FakeAlifChannel sentinel;
    memset(&sentinel, 0xA5, sizeof(sentinel));
    fake_timer.UTIMER_CHANNEL_CFG[other] = sentinel;
    fake_enabled[other_irq] = 1U;
    fake_pending[other_irq] = 1U;
    fake_timer.UTIMER_GLB_CLOCK_ENABLE = 1U << other;
    profiler_timer_stop(); /* Must not write anything before ownership. */
    assert(!fake_timer.UTIMER_GLB_CNTR_STOP);
    assert(!profiler_timer_init(&clock)); /* Missing startup clock enable. */
    assert(fake_timer.UTIMER_GLB_CLOCK_ENABLE == (1U << other));
    fake_timer.UTIMER_GLB_CLOCK_ENABLE |= 1U << channel; /* Serialized board setup. */
    uint32_t clocks = fake_timer.UTIMER_GLB_CLOCK_ENABLE;
    fake_target[irq] = 1U;
    assert(!profiler_timer_init(&clock));
    fake_target[irq] = 0U;
    fake_enabled[irq] = 1U;
    assert(!profiler_timer_init(&clock));
    fake_enabled[irq] = 0U;
    CHANNEL.UTIMER_CNTR_CTRL = 1U;
    assert(!profiler_timer_init(&clock));
    CHANNEL.UTIMER_CNTR_CTRL = 0U;
    fake_timer.UTIMER_GLB_CNTR_RUNNING = CHANNEL_MASK;
    assert(!profiler_timer_init(&clock));
    fake_timer.UTIMER_GLB_CNTR_RUNNING = 1U << other;
    assert(profiler_timer_init(&clock));
    assert(clock.timestamp_hz == 123U && clock.timer_hz == PROFILER_TIMER_CLOCK_HZ);
    assert(CHANNEL.UTIMER_CNTR_PTR == clock.timer_period - 1U);
    assert(fake_priority[irq] == PROFILER_IRQ_PRIORITY);
    assert(fake_timer.UTIMER_GLB_CNTR_STOP == CHANNEL_MASK);
    assert(fake_timer.UTIMER_GLB_CNTR_CLEAR == CHANNEL_MASK);
    profiler_timer_start();
    assert(fake_enabled[irq] && !fake_pending[irq]);
    assert(fake_timer.UTIMER_GLB_CNTR_START == CHANNEL_MASK);
    assert(!profiler_timer_ack());
    CHANNEL.UTIMER_CHAN_STATUS = OVERFLOW;
    assert(profiler_timer_ack() && CHANNEL.UTIMER_CHAN_INTERRUPT == OVERFLOW);
    profiler_timer_stop();
    assert(!fake_enabled[irq]);
    assert(profiler_timer_init(&clock)); /* Repeated captures keep ownership. */
    assert(fake_timer.UTIMER_GLB_CLOCK_ENABLE == clocks);
    assert(fake_timer.UTIMER_GLB_CNTR_RUNNING == (1U << other));
    assert(!memcmp(&sentinel, &fake_timer.UTIMER_CHANNEL_CFG[other], sizeof(sentinel)));
    assert(fake_enabled[other_irq] && fake_pending[other_irq]);
    PROFILER_ALIF_TIMER_HANDLER();
    return 0;
}
