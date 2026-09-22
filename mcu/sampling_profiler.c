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
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler.c
 * @brief Board-independent sample storage and capture lifecycle.
 */

#include "sampling_profiler.h"
#include "sampling_profiler_port.h"
#include <string.h>

_Static_assert(sizeof(struct ProfilerSamplingHeader) == PROFILER_HEADER_BYTES, "Header format");
_Static_assert(PROFILER_SAMPLE_BUFFER_BYTES >=
                   PROFILER_HEADER_BYTES + PROFILER_BASE_RECORD_BYTES + 4U * PROFILER_PMU_COUNT,
               "Buffer must hold a header and sample");
#ifdef PROFILER_SRAM_REGION_BYTES
_Static_assert(PROFILER_SAMPLE_BUFFER_BYTES <= PROFILER_SRAM_REGION_BYTES, "Buffer exceeds reserved sampling SRAM");
#endif
_Static_assert(PROFILER_SAMPLE_HZ > 0U && PROFILER_SAMPLE_HZ <= UINT32_MAX,
               "Sample frequency must fit a positive uint32");

PROFILER_BUFFER_ATTRIBUTES volatile struct ProfilerSamplingBuffer statistical_samples;
volatile uint32_t statistical_sampling_gate;
static uint32_t initialized;

int sampling_profiler_init(void)
{
    sampling_profiler_disable();
    profiler_port_stop();
#if PROFILER_PMU_COUNT
    profiler_pmu_stop();
#endif
    initialized = 0;
    memset((void *)&statistical_samples, 0, sizeof(statistical_samples));
    statistical_samples.header.magic = PROFILER_CAPTURE_MAGIC;
    statistical_samples.header.version = PROFILER_FORMAT_VERSION;
    statistical_samples.header.record_size = PROFILER_BASE_RECORD_BYTES;
    statistical_samples.header.buffer_bytes = sizeof(statistical_samples);
    statistical_samples.header.sample_hz = PROFILER_SAMPLE_HZ;
    struct ProfilerClock clock;
    if (!profiler_port_init(&clock))
        return 0;
    statistical_samples.header.timestamp_hz = clock.timestamp_hz;
    statistical_samples.header.timer_period = clock.timer_period;
    statistical_samples.header.timer_hz = clock.timer_hz;
#if PROFILER_PMU_COUNT
    profiler_pmu_init();
#endif
    statistical_samples.header.record_size = PROFILER_BASE_RECORD_BYTES + 4U * statistical_samples.header.pmu_count;
    statistical_samples.header.capacity = sizeof(statistical_samples.records) / statistical_samples.header.record_size;
    statistical_samples.header.start_timestamp = profiler_port_timestamp();
    statistical_samples.header.start_tick = profiler_port_ticks();
    initialized = 1;
    return 1;
}

void sampling_profiler_enable(void)
{
    if (initialized && !statistical_samples.header.full && !statistical_samples.header.complete)
    {
        statistical_samples.header.active = 1;
        profiler_port_barrier();
        statistical_sampling_gate = 1;
    }
}

void sampling_profiler_disable(void)
{
    statistical_sampling_gate = 0;
    profiler_port_barrier();
    statistical_samples.header.active = 0;
}

int sampling_profiler_full(void) { return statistical_samples.header.full != 0; }

void sampling_profiler_stop(uint32_t iterations, uint32_t validation_passed)
{
    sampling_profiler_disable();
    if (!initialized)
        return;
    profiler_port_stop();
#if PROFILER_PMU_COUNT
    profiler_pmu_stop();
#endif
    statistical_samples.header.stop_timestamp = profiler_port_timestamp();
    statistical_samples.header.stop_tick = profiler_port_ticks();
    statistical_samples.header.iterations = iterations;
    statistical_samples.header.validation_passed = validation_passed;
    statistical_samples.header.complete = 1;
    profiler_port_barrier();
    profiler_port_flush((const void *)&statistical_samples, sizeof(statistical_samples));
}

void sampling_profiler_reject(enum ProfilerRejection reason)
{
    if (!statistical_sampling_gate || (unsigned)reason >= PROFILER_REJECT_REASON_COUNT)
        return;
    ++statistical_samples.header.rejected;
    ++statistical_samples.header.rejected_reason[reason];
}

void sampling_profiler_record(const struct ProfilerSample *sample)
{
    if (!statistical_sampling_gate)
        return;
    uint32_t index = statistical_samples.header.count;
    if (index >= statistical_samples.header.capacity)
        return;
    volatile uint32_t *record = &statistical_samples.records[index * (statistical_samples.header.record_size / 4U)];
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
    profiler_port_barrier();
    statistical_samples.header.count = index + 1U;
    if (index + 1U == statistical_samples.header.capacity)
    {
        statistical_samples.header.full = 1;
        statistical_sampling_gate = 0;
        statistical_samples.header.active = 0;
    }
}
