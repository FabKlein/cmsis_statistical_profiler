/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* Exercise the real adapter against vendor API doubles, without an Arm entry. */
#include "fake_himax_timer.h"
#include "profiler_backend.h"
#include <assert.h>
#include <stddef.h>

#undef PROFILER_DEFINE_IRQ_HANDLER
#define PROFILER_DEFINE_IRQ_HANDLER(name)                                                                              \
    void name(void) {}
#include "../adapters/himax_we2/profiler_timer4.c"

uint32_t fake_priority, fake_himax_enabled, fake_himax_pending, fake_himax_vector;
uint32_t fake_himax_vector_calls, fake_himax_enable_calls;
static uint32_t starts, stops, event, running;
static uint8_t used;
static int start_status;
static enum ProfilerInitReason last_reason;
static uint32_t context0, context1;

int profiler_init_fail(enum ProfilerInitStage stage, enum ProfilerInitReason reason, uint32_t value0, uint32_t value1)
{
    assert(stage == PROFILER_INIT_TIMER);
    last_reason = reason;
    context0 = value0;
    context1 = value1;
    return 0;
}
uint32_t profiler_timer_period(uint32_t hz, uint32_t maximum)
{
    uint32_t count = hz / PROFILER_SAMPLE_HZ;
    return count <= maximum ? count : 0U;
}
int hx_drv_timer_get_used(int id, uint8_t *value)
{
    assert(id == TIMER_ID_4);
    *value = used;
    return TIMER_NO_ERROR;
}
int hx_drv_timer_get_clk(int id, uint32_t *hz)
{
    assert(id == TIMER_ID_4);
    *hz = 100000000U;
    return TIMER_NO_ERROR;
}
int hx_drv_timer_get_clk_div(int id, uint32_t *divider)
{
    assert(id == TIMER_ID_4);
    *divider = 100U;
    return TIMER_NO_ERROR;
}
int hx_drv_timer_hw_start(int id, const TIMER_CFG_T *config, void (*callback)(uint32_t))
{
    assert(id == TIMER_ID_4 && config->period == 1000U / PROFILER_SAMPLE_HZ);
    assert(config->mode == TIMER_MODE_PERIODICAL && config->ctrl == TIMER_CTRL_CPU && config->state == TIMER_STATE_DC);
    assert(callback != NULL);
    ++starts;
    /* A vendor call can install its vector and touch hardware before failing. */
    fake_himax_vector = 0xABCDU;
    fake_himax_enabled = fake_himax_pending = event = running = 1U;
    return start_status;
}
int hx_drv_timer_hw_stop(int id)
{
    assert(id == TIMER_ID_4);
    ++stops;
    running = 0U;
    return TIMER_NO_ERROR;
}
void hx_drv_timer_ClearIRQ(int id)
{
    assert(id == TIMER_ID_4);
    event = 0U;
}
uint32_t hx_drv_timer_StatusIRQ(int id)
{
    assert(id == TIMER_ID_4);
    return event;
}
int main(void)
{
    struct ProfilerClock clock = {.timestamp_hz = 123U};
    profiler_timer_stop();
    assert(stops == 0U);
#ifdef TEST_INVALID_RATE
    assert(!profiler_timer_init(&clock));
    assert(last_reason == PROFILER_INIT_BAD_CLOCK && !starts && !stops);
    return 0;
#endif
    used = 1U;
    assert(!profiler_timer_init(&clock) && last_reason == PROFILER_INIT_BUSY);
    assert(!stops && !fake_himax_vector_calls);
    used = 0U;
    fake_himax_enabled = 1U;
    assert(!profiler_timer_init(&clock) && last_reason == PROFILER_INIT_BUSY);
    assert(fake_himax_enabled && !stops && !fake_himax_vector_calls);
    fake_himax_enabled = 0U;
    assert(profiler_timer_init(&clock));
    assert(clock.timestamp_hz == 123U && clock.timer_hz == 1000000U);
    assert(clock.timer_period == 1000000U / PROFILER_SAMPLE_HZ);
    uint32_t vectors = fake_himax_vector_calls;
    start_status = 7;
    assert(!profiler_timer_start());
    assert(last_reason == PROFILER_INIT_UNAVAILABLE && context0 == TIMER4INT_IRQn && context1 == 7U);
    assert(fake_himax_vector_calls == vectors && fake_himax_vector == 0xABCDU);
    assert(!fake_himax_enable_calls); /* No profiler handoff after a vendor failure. */
    profiler_timer_stop();            /* Backend performs this cleanup before restoring IRQs. */
    assert(!fake_himax_enabled && !fake_himax_pending && !event && !running);
    used = 1U; /* Reservation persists for restart in the same image. */
    assert(profiler_timer_init(&clock));
    start_status = TIMER_NO_ERROR;
    assert(profiler_timer_start());
    assert(fake_himax_enabled && fake_himax_enable_calls == 1U);
    assert(fake_himax_vector == (uint32_t)(uintptr_t)profiler_timer4_irq_handler);
    assert(profiler_timer_ack() && !profiler_timer_ack());
    profiler_timer_stop();
    assert(!running && !fake_himax_enabled && !fake_himax_pending && starts == 2U);
    return 0;
}
