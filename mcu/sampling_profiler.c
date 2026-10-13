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
 * @details One sampling ISR produces records; lifecycle calls are serialized in
 * privileged thread mode on the same core. Disable/full closes recording without
 * stopping the timer. Readers must wait for stop and its final cache flush.
 * Volatile state and barriers do not synchronize multiple cores or callers.
 */

#include "sampling_profiler_port.h"
#include <string.h>

_Static_assert(sizeof((uint32_t[])PROFILER_FIRMWARE_ID) == 16U, "Firmware identity requires four words");

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

/** Header and variable records, placed by the application. Export after stop;
 * volatile supports ISR access, while finalization provides cache visibility. */
PROFILER_BUFFER_ATTRIBUTES volatile struct ProfilerSamplingBuffer statistical_samples;
/* Volatile reads below keep this read-only symbol reachable under linker GC/LTO. */
__attribute__((used, section(".profiler_firmware_id"))) const uint32_t profiler_firmware_id[4] = PROFILER_FIRMWARE_ID;

/** ISR recording gate, mirrored by header.active; closing it leaves the timer running. */
volatile uint32_t statistical_sampling_gate;

/** Successful init, retained through disable/stop. Complete/full prevents reopening. */
static uint32_t initialized;

/** Reset at init; backend/adapter failures write diagnostics outside the ISR. */
static struct ProfilerDiagnostics diagnostics;

const struct ProfilerDiagnostics *profiler_diagnostics(void) { return &diagnostics; }

/* Backend/adapter failures use this helper so callers receive a reason, not just 0. */
int profiler_init_fail(enum ProfilerInitStage stage, enum ProfilerInitReason reason, uint32_t value0, uint32_t value1)
{
    diagnostics = (struct ProfilerDiagnostics){stage, reason, value0, value1};
    return 0;
}

#if PROFILER_PMU_COUNT
/* The backend owns hardware state; only storage translates it to wire fields. */
static void save_pmu(const struct ProfilerPmuInfo *info)
{
    volatile struct ProfilerSamplingHeader *header = &statistical_samples.header;
    header->pmu_status = info->status;
    header->pmu_count = info->count;
    header->pmu_requested = info->requested;
    header->pmu_counter_bits = info->counter_bits;
    header->pmu_flags = info->flags;
    for (uint32_t i = 0; i < 4U; ++i)
    {
        header->pmu_events[i] = info->events[i];
        header->pmu_start[i] = info->start[i];
        header->pmu_stop[i] = info->stop[i];
    }
}
#endif

int profiler_init(void)
{
    /* Reinitialization stops producers and discards any previous capture. */
    profiler_disable();
    profiler_port_stop();
#if PROFILER_PMU_COUNT
    profiler_pmu_stop(NULL);
#endif

    initialized = 0;
    diagnostics = (struct ProfilerDiagnostics){0};
    /* Records are bounded by count/bytes_used; old tails remain undefined.
     * For applications requiring data erasure, restore the full clear:
     * memset((void *)&statistical_samples, 0, sizeof(statistical_samples)); */
    memset((void *)&statistical_samples.header, 0, sizeof(statistical_samples.header));

    statistical_samples.header.magic = PROFILER_CAPTURE_MAGIC;
    statistical_samples.header.version = PROFILER_FORMAT_VERSION;
    statistical_samples.header.header_bytes = PROFILER_HEADER_BYTES;
    statistical_samples.header.record_base_bytes = PROFILER_BASE_RECORD_BYTES;
    statistical_samples.header.buffer_bytes = sizeof(statistical_samples);
    statistical_samples.header.sample_hz = PROFILER_SAMPLE_HZ;
    for (uint32_t i = 0; i < 4U; ++i)
        statistical_samples.header.firmware_id[i] = ((const volatile uint32_t *)profiler_firmware_id)[i];

    /* Start the timer gated off; timer and timestamp clocks may differ. */
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
    /* Record width uses the active PMU count, including fallback to zero. */
    struct ProfilerPmuInfo pmu;
    profiler_pmu_init(&pmu);
    save_pmu(&pmu);
#endif

    /* The fixed portion excludes variable recovered-caller words. */
    statistical_samples.header.unwind_max_depth = PROFILER_STACK_UNWIND ? PROFILER_UNWIND_MAX_DEPTH : 0U;
    statistical_samples.header.record_base_bytes =
        PROFILER_BASE_RECORD_BYTES + 4U * statistical_samples.header.pmu_count + 4U * PROFILER_STACK_UNWIND;
    statistical_samples.header.features =
        (statistical_samples.header.pmu_count ? 1U : 0U) | (PROFILER_STACK_UNWIND ? 2U : 0U);

    /* Capture epochs do not reset cumulative backend clocks. */
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
    struct ProfilerPmuInfo pmu;
    profiler_pmu_stop(&pmu);
    save_pmu(&pmu);
#endif

    statistical_samples.header.stop_timestamp = profiler_port_timestamp();
    statistical_samples.header.stop_tick = profiler_port_ticks();
    statistical_samples.header.iterations = iterations;
    statistical_samples.header.validation_passed = (validation_passed != 0U);

    /* Complete is published before flushing; readers wait for stop to return. */
    statistical_samples.header.complete = 1;
    profiler_port_barrier();
    profiler_port_flush((const void *)&statistical_samples, sizeof(statistical_samples));
}

/* Rejections consume no record space; retain the first failure reason. */
void profiler_reject(enum ProfilerRejection reason)
{
    if ((unsigned)reason >= PROFILER_REJECT_REASON_COUNT)
        return;

    ++statistical_samples.header.rejected;
    ++statistical_samples.header.rejected_reason[reason];
}

/* ISR-only append: six base words, active PMU words, optional depth/status and
 * recovered callers. No padding for unused callers or circular overwrite. */
void profiler_record(const struct ProfilerSample *sample)
{
    uint32_t index = statistical_samples.header.count;
    uint32_t bytes = statistical_samples.header.record_base_bytes;
#if PROFILER_STACK_UNWIND
    uint32_t depth = sample->unwind & 255U;
    if (depth > PROFILER_UNWIND_MAX_DEPTH)
        return;
    bytes += 4U * depth;
#endif

    /* Reject the whole append before writing; bytes_used excludes the header. */
    uint32_t used = statistical_samples.header.bytes_used;
    if (bytes > sizeof(statistical_samples.records) - used)
        goto full;

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

    /* No live readers: this ISR finishes before same-core stop orders/flushes
     * the capture. Volatile preserves record-before-count store order. */
    statistical_samples.header.bytes_used = used + bytes;
    statistical_samples.header.count = index + 1U;

    /* Full closes recording, not the timer; the application must still stop. */
    if (sizeof(statistical_samples.records) - used - bytes >= statistical_samples.header.record_base_bytes)
        return;

full:
    statistical_samples.header.full = 1;
    statistical_sampling_gate = 0;
    statistical_samples.header.active = 0;
}
