/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_unwind_store.c
 * Description:  Backtrace record storage with variable PMU stride
 *
 * $Date:        24 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_port.h"
#include <assert.h>
#include <stdio.h>
static uint32_t ticks;
int profiler_port_init(struct ProfilerClock *clock)
{
    *clock = (struct ProfilerClock){.timestamp_hz = 1000000, .timer_hz = 1000000, .timer_period = 1000};
    return 1;
}
void profiler_port_stop(void) {}
uint32_t profiler_port_timestamp(void) { return ticks * 1000; }
uint32_t profiler_port_ticks(void) { return ticks; }
void profiler_port_barrier(void) {}
void profiler_port_flush(const void *address, uint32_t bytes)
{
    (void)address;
    (void)bytes;
}
void profiler_pmu_init(void)
{
#if PROFILER_PMU_COUNT
    statistical_samples.header.pmu_requested = PROFILER_PMU_COUNT;
    #ifdef TEST_UNAVAILABLE
    statistical_samples.header.pmu_status = 1;
    #else
    statistical_samples.header.pmu_status = 2;
    statistical_samples.header.pmu_count = PROFILER_PMU_COUNT;
    statistical_samples.header.pmu_counter_bits = 32;
    #endif
#endif
}
void profiler_pmu_stop(void) {}
int main(int argc, char **argv)
{
    assert(argc == 2 && sampling_profiler_init());
    sampling_profiler_enable();
    struct ProfilerSample sample = {.timestamp = 1000,
                                    .tick = 1,
                                    .pc = 0x1004,
                                    .lr = 0x2005,
                                    .xpsr = 1U << 24,
                                    .exception_return = 0xFFFFFFFD,
                                    .unwind = 1,
                                    .callers = {0x2005}};
#if PROFILER_PMU_COUNT
    for (unsigned i = 0; i < PROFILER_PMU_COUNT; ++i)
        sample.pmu[i] = 100 + i;
#endif
    sampling_profiler_record(&sample);
#ifdef TEST_MIXED
    const uint32_t depths[] = {0U, PROFILER_UNWIND_MAX_DEPTH, 2U};
    unsigned attempt = 0;
    while (!sampling_profiler_full())
    {
        uint32_t depth = depths[attempt++ % 3U];
        if (depth > PROFILER_UNWIND_MAX_DEPTH)
            depth = PROFILER_UNWIND_MAX_DEPTH;
        sample.unwind = depth;
        for (uint32_t i = 0; i < depth; ++i)
            sample.callers[i] = 0x2005;
        uint32_t before = statistical_samples.header.bytes_used;
        uint32_t count = statistical_samples.header.count;
        uint32_t remaining = sizeof(statistical_samples.records) - before;
        sampling_profiler_record(&sample);
        if (statistical_samples.header.record_base_bytes + 4U * depth > remaining)
        {
            assert(statistical_samples.header.count == count);
            assert(statistical_samples.header.bytes_used == before);
            const volatile uint32_t *tail = statistical_samples.records + before / 4U;
            for (uint32_t i = 0; i < remaining / 4U; ++i)
                assert(tail[i] == 0U); /* Failed append left no partial record. */
        }
    }
    uint32_t committed = statistical_samples.header.bytes_used;
    sampling_profiler_enable();
    sampling_profiler_record(&sample);
    assert(statistical_samples.header.bytes_used == committed);
#endif
    ticks = 1;
    sampling_profiler_stop(1, 1);
    FILE *out = fopen(argv[1], "wb");
    assert(out && fwrite((const void *)&statistical_samples, sizeof(statistical_samples), 1, out) == 1);
    assert(!fclose(out));
    return 0;
}
