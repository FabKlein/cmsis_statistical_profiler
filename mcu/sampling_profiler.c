/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler.c
 * Description:  Board-independent sample storage and capture lifecycle
 *
 * $Date:        1 October 2026
 * $Revision:    V.1.0.4
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler.c
 * @brief Board-independent sample storage and capture lifecycle.
 *
 * The application controls when recording is allowed. The Cortex-M backend
 * supplies validated samples from the sampling Interrupt Service Routine (ISR).
 * This file owns the RAM buffer and capture metadata, not the hardware timer.
 *
 * Application: init -> enable <-> disable -> stop -> export buffer
 *                        |          |
 *                        |          +-- timer still runs; no records appended
 *                        v
 * Sampling ISR: validate frame -> record or reject
 *                                  |
 *                                  +-- buffer full: close recording gate
 *                                      application must still call stop
 *
 * Lifecycle calls are serialized in privileged thread mode on 1 core. Only
 * 1 sampling ISR appends records. Volatile state and barriers support this
 * arrangement; they are not a lock for multiple cores or concurrent callers.
 */

#include "sampling_profiler_port.h"
#include <string.h>

/* Check the on-wire header layout and ensure even the first record can fit. */
_Static_assert(sizeof(struct ProfilerSamplingHeader) == PROFILER_HEADER_BYTES, "Header format");
_Static_assert(PROFILER_SAMPLE_BUFFER_BYTES >= PROFILER_HEADER_BYTES + PROFILER_BASE_RECORD_BYTES +
                       4U * PROFILER_PMU_COUNT + 4U * PROFILER_STACK_UNWIND,
               "Buffer must hold a header and sample");
#ifdef PROFILER_SRAM_REGION_BYTES
_Static_assert(PROFILER_SAMPLE_BUFFER_BYTES <= PROFILER_SRAM_REGION_BYTES, "Buffer exceeds reserved sampling SRAM");
#endif
_Static_assert(PROFILER_SAMPLE_HZ > 0U && PROFILER_SAMPLE_HZ <= UINT32_MAX,
               "Sample frequency must fit a positive uint32");

/** Complete capture allocation: header followed by packed, variable-size records.
 * The application/linker selects placement and alignment through
 * PROFILER_BUFFER_ATTRIBUTES. The debugger exports this symbol after stop.
 * Volatile preserves accesses shared with the ISR; it does not provide cache
 * coherence, which is handled explicitly when the capture is finalized.
 */
PROFILER_BUFFER_ATTRIBUTES volatile struct ProfilerSamplingBuffer statistical_samples;

/** Fast recording permission checked by the sampling ISR: 0 = closed, 1 = open.
 * Closing this gate prevents buffer updates without stopping the timer. A full
 * buffer also closes it. header.active mirrors recording state for the host.
 */
volatile uint32_t statistical_sampling_gate;

/** Nonzero only after successful initialization of the current capture.
 * This is not a "currently recording" flag: it remains set after disable/stop.
 * The complete/full header flags prevent a finalized/full capture reopening.
 */
static uint32_t initialized;

/** Last initialization result, including the failing stage and useful values.
 * Reset on each init; shared with backend error reporting, not written by the ISR.
 * Applications read it through profiler_diagnostics() when init fails.
 */
static struct ProfilerDiagnostics diagnostics;

const struct ProfilerDiagnostics *profiler_diagnostics(void) { return &diagnostics; }

/* Backend/adapter failures use this helper so callers receive a reason, not just 0. */
int profiler_init_fail(enum ProfilerInitStage stage, enum ProfilerInitReason reason, uint32_t value0, uint32_t value1)
{
    diagnostics = (struct ProfilerDiagnostics){stage, reason, value0, value1};
    return 0;
}

int profiler_init(void)
{
    /* Stop producers before clearing a previous capture. Reinitialization
     * intentionally discards its records, even if they have not been exported. */
    profiler_disable();
    profiler_port_stop();
#if PROFILER_PMU_COUNT
    profiler_pmu_stop();
#endif

    /* Begin a fresh capture and clear any failure reported by the previous init. */
    initialized = 0;
    diagnostics = (struct ProfilerDiagnostics){0};
    /* Only metadata needs resetting; unused record bytes retain old contents.
     * The decoder bounds records by count/bytes_used, not by zero-filled RAM.
     * Restore this full clear only when the application needs data erasure:
     * memset((void *)&statistical_samples, 0, sizeof(statistical_samples)); */
    memset((void *)&statistical_samples.header, 0, sizeof(statistical_samples.header));

    /* Describe the allocation so the host can validate the dump before decoding. */
    statistical_samples.header.magic = PROFILER_CAPTURE_MAGIC;
    statistical_samples.header.version = PROFILER_FORMAT_VERSION;
    statistical_samples.header.header_bytes = PROFILER_HEADER_BYTES;
    statistical_samples.header.record_base_bytes = PROFILER_BASE_RECORD_BYTES;
    statistical_samples.header.buffer_bytes = sizeof(statistical_samples);
    statistical_samples.header.sample_hz = PROFILER_SAMPLE_HZ;

    /* Start the backend timer with the recording gate still closed. The actual
     * timer and timestamp frequencies may differ from each other. */
    struct ProfilerClock clock;
    if (!profiler_port_init(&clock))
    {
        /* Preserve a specific adapter error; supply a fallback if none was set. */
        if (diagnostics.reason == PROFILER_INIT_OK)
            profiler_init_fail(PROFILER_INIT_BACKEND, PROFILER_INIT_UNAVAILABLE, 0, 0);
        return 0;
    }

    statistical_samples.header.timestamp_hz = clock.timestamp_hz;
    statistical_samples.header.timer_period = clock.timer_period;
    statistical_samples.header.timer_hz = clock.timer_hz;

#if PROFILER_PMU_COUNT
    /* Optional Performance Monitoring Unit (PMU) counters can be unavailable.
     * Their active count, not the requested count, determines record storage. */
    profiler_pmu_init();
#endif

    /* Fixed record portion: 6 base words, active PMU words, and optional unwind
     * metadata. Recovered caller addresses are added separately for each sample. */
    statistical_samples.header.unwind_max_depth = PROFILER_STACK_UNWIND ? PROFILER_UNWIND_MAX_DEPTH : 0U;
    statistical_samples.header.record_base_bytes =
        PROFILER_BASE_RECORD_BYTES + 4U * statistical_samples.header.pmu_count + 4U * PROFILER_STACK_UNWIND;
    statistical_samples.header.features =
        (statistical_samples.header.pmu_count ? 1U : 0U) | (PROFILER_STACK_UNWIND ? 2U : 0U);

    /* Save the capture epoch without resetting the backend's cumulative clocks.
     * Recording begins only when the application calls profiler_enable(). */
    statistical_samples.header.start_timestamp = profiler_port_timestamp();
    statistical_samples.header.start_tick = profiler_port_ticks();
    initialized = 1;
    return 1;
}

void profiler_enable(void)
{
    if (initialized && !statistical_samples.header.full && !statistical_samples.header.complete)
    {
        /* Publish the header state before permitting the ISR to append. */
        statistical_samples.header.active = 1;
        profiler_port_barrier();
        statistical_sampling_gate = 1;
    }
}

void profiler_disable(void)
{
    /* Close ISR access first. Timer interrupts and PMU counting continue. */
    statistical_sampling_gate = 0;
    profiler_port_barrier();
    statistical_samples.header.active = 0;
}

/* Public timing queries: these count sampling time, including gated-off periods,
 * rather than stored records. Subtract readings to measure a time interval. */
uint32_t profiler_sample_ticks(void) { return profiler_port_ticks(); }
uint32_t profiler_elapsed_ms(void) { return profiler_port_millis(); }

int profiler_full(void) { return statistical_samples.header.full != 0; }

void profiler_stop(uint32_t iterations, uint32_t validation_passed)
{
    /* A finalized capture stays unchanged until the next initialization. */
    if (!initialized || statistical_samples.header.complete)
        return;

    /* Gate off writes before stopping the hardware and taking final snapshots. */
    profiler_disable();

    profiler_port_stop();
#if PROFILER_PMU_COUNT
    profiler_pmu_stop();
#endif

    /* Application-supplied workload results are stored alongside the stop epoch. */
    statistical_samples.header.stop_timestamp = profiler_port_timestamp();
    statistical_samples.header.stop_tick = profiler_port_ticks();
    statistical_samples.header.iterations = iterations;
    statistical_samples.header.validation_passed = validation_passed;

    /* Mark the capture ready and make it visible to an external debugger.
     * Export only after this function returns, including the cache flush. */
    statistical_samples.header.complete = 1;
    profiler_port_barrier();
    profiler_port_flush((const void *)&statistical_samples, sizeof(statistical_samples));
}

/* A rejected frame consumes no record space. Keep totals and reasons so the
 * host can distinguish a quiet workload from failed frame validation. */
void profiler_reject(enum ProfilerRejection reason)
{
    if ((unsigned)reason >= PROFILER_REJECT_REASON_COUNT)
        return;

    ++statistical_samples.header.rejected;
    ++statistical_samples.header.rejected_reason[reason];
}

/* Append 1 backend-admitted, validated sample; called only by the sampling ISR.
 * Record layout (32-bit words):
 *   [timestamp, tick, PC, LR, xPSR, exception return]
 *   [0-4 PMU values] [optional unwind metadata + recovered callers]
 * PC = Program Counter, LR = Link Register, xPSR = program status register.
 * No heap allocation, padding for unused callers, or circular overwrite.
 */
void profiler_record(const struct ProfilerSample *sample)
{
    /* Work out the complete record size before touching buffer contents. */
    uint32_t index = statistical_samples.header.count;
    uint32_t bytes = statistical_samples.header.record_base_bytes;
#if PROFILER_STACK_UNWIND
    /* The metadata low byte contains the number of recovered caller addresses. */
    uint32_t depth = sample->unwind & 255U;
    if (depth > PROFILER_UNWIND_MAX_DEPTH)
        return;
    bytes += 4U * depth;
#endif

    /* bytes_used counts only the records area, not the header. Refuse a record
     * that cannot fit in full; previously captured records remain untouched. */
    uint32_t used = statistical_samples.header.bytes_used;
    if (bytes > sizeof(statistical_samples.records) - used)
        goto full;

    /* Copy the architectural sample first, then its enabled optional fields. */
    volatile uint32_t *record = &statistical_samples.records[used / 4U];
    record[0] = sample->timestamp;
    record[1] = sample->tick;
    record[2] = sample->pc;
    record[3] = sample->lr;
    record[4] = sample->xpsr;
    record[5] = sample->exception_return;
#if PROFILER_PMU_COUNT
    for (uint32_t event = 0; event < statistical_samples.header.pmu_count; ++event)
        record[6U + event] = sample->pmu[event];
#endif
#if PROFILER_STACK_UNWIND
    uint32_t offset = 6U + statistical_samples.header.pmu_count;
    record[offset] = sample->unwind;
    for (uint32_t i = 0; i < depth; ++i)
        record[offset + 1U + i] = sample->callers[i];
#endif

    /* Volatile stores keep the record before its lengths/count in program order.
     * No live readers: the single-core ISR finishes before thread-mode stop,
     * which orders and flushes the entire capture before export. */
    statistical_samples.header.bytes_used = used + bytes;
    statistical_samples.header.count = index + 1U;

    /* Close the gate immediately if even a minimum-size next record cannot fit.
     * The timer still runs; profiler_stop() is needed to finalize the capture. */
    if (sizeof(statistical_samples.records) - used - bytes >= statistical_samples.header.record_base_bytes)
        return;

full:
    statistical_samples.header.full = 1;
    statistical_sampling_gate = 0;
    statistical_samples.header.active = 0;
}
