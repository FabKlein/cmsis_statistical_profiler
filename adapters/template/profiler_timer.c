/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_timer.c
 * Description:  Board sampling timer adapter template
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include PROFILER_DEVICE_HEADER

/* TODO(timer): complete every hardware operation below, then remove this guard.
 * This file is a porting skeleton, not an operational fallback timer. */
#error "Complete TODO(timer) in the copied adapter before compiling it"

/* TODO(timer): use the external IRQ enum and EXACT symbol from your startup
 * vector table. Reserve the entire selected timer/IRQ for this adapter. */
#define TIMER_IRQ YOUR_TIMER_IRQn
#define TIMER_HANDLER YOUR_TIMER_IRQHandler
/* TODO(timer): maximum PERIOD in input counts, not the largest reload value.
 * Examples: 16-bit reload timer => 65536U; 32-bit => UINT32_MAX (format limit). */
#define TIMER_MAX_PERIOD UINT32_MAX

_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");
static uint32_t owned;

int profiler_timer_init(struct ProfilerClock *clock)
{
    /* TODO(timer): query the actual timer clock after mux/prescaler, or use an
     * application-supplied constant. Do not assume SystemCoreClock. */
    uint32_t hz = YOUR_TIMER_INPUT_HZ;
    uint32_t period = profiler_timer_period(hz, TIMER_MAX_PERIOD);
#if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3)
    if (NVIC_GetTargetState(TIMER_IRQ))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_DENIED, TIMER_IRQ, 0);
#endif
    if (!period)
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, hz, PROFILER_SAMPLE_HZ);
    if (!owned && NVIC_GetEnableIRQ(TIMER_IRQ))
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BUSY, TIMER_IRQ, 0);

    /* TODO(timer): before any writes, reject an already claimed/configured
     * peripheral on first init (!owned), even if its IRQ is disabled. Check
     * its clock gate/enable state without accessing clock-gated registers.
     * Shared/multicore peripherals also need application-level reservation.
     * Then enable only this timer's peripheral clock/access as necessary.
     * Any failure must leave unowned application resources unchanged. */
    owned = 1U;
    profiler_timer_stop();

    /* TODO(timer): configure periodic operation, stopped and IRQ-masked.
     * Program the prescaler/reload/compare to give EXACTLY 'period' counts;
     * many down/up counters use period-1, while compare timers may use period.
     * Latch configuration if required, reset this timer's phase, clear its
     * event flag, and leave unrelated timers/channels untouched.
     * All operations that can fail must be checked before returning success. */
    NVIC_SetPriority(TIMER_IRQ, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = hz;
    clock->timer_period = period;
    /* timestamp_hz is the timestamp frequency, already filled by the common backend. */
    return 1;
}

void profiler_timer_start(void)
{
    /* TODO(timer): clear the peripheral event flag; enable its interrupt
     * source and periodic counter in the order required by the hardware.
     * Clear stale NVIC state before enabling delivery. This function cannot
     * report failure: init must already have validated all prerequisites. */
    NVIC_ClearPendingIRQ(TIMER_IRQ);
    NVIC_EnableIRQ(TIMER_IRQ);
}

void profiler_timer_stop(void)
{
    /* Called even before the first init, and on every re-init/stop. */
    if (!owned)
        return;
    NVIC_DisableIRQ(TIMER_IRQ);
    /* TODO(timer): mask this peripheral's interrupt, stop the counter and
     * clear its event flag. Clear the source BEFORE clearing NVIC pending.
     * Keep the reservation; repeated captures must be able to restart. */
    __DSB();
    NVIC_ClearPendingIRQ(TIMER_IRQ);
}

int profiler_timer_ack(void)
{
    /* Runs in the sampling ISR even while capture is gated off or full.
     * TODO(timer): test this timer's event status. Return 0 for spurious IRQs.
     * Replace this placeholder with a register/status read. */
    uint32_t event_pending = 0U;
    if (!owned || !event_pending)
        return 0;
    /* TODO(timer): acknowledge only the sampling event using the documented
     * write-1-to-clear/write-0-to-clear semantics. Avoid read-modify-write
     * on status registers where it could clear other flags. */
    __DSB();
    return 1;
}

/* Actual vector entry, not a function to call from an ordinary C ISR.
 * Keep this path integer-only; do not dispatch via a vendor HAL IRQ handler. */
PROFILER_DEFINE_IRQ_HANDLER(TIMER_HANDLER)
