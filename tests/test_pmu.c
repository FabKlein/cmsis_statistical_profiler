/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_pmu.c
 * Description:  PMU lifecycle, chaining, ownership and snapshot tests
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "fake_device.h"
#include "sampling_profiler_port.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct FakeDWT fake_dwt;
uint32_t fake_stack[16];
static uint32_t ticks, timestamp = 100U;
int profiler_port_init(struct ProfilerClock *clock)
{
    clock->timestamp_hz = 1000000U;
    clock->timer_hz = 1000000U;
    clock->timer_period = 1000U;
    return 1;
}
void profiler_port_stop(void) {}
uint32_t profiler_port_timestamp(void) { return timestamp; }
uint32_t profiler_port_ticks(void) { return ticks; }
uint32_t profiler_port_millis(void) { return ticks; }
void profiler_port_barrier(void) {}
void profiler_port_flush(const void *p, uint32_t n)
{
    (void)p;
    (void)n;
}
#ifdef TEST_PMU
struct FakePMU fake_pmu;
uint32_t pmu_read_mode, pmu_read_count;
static void set_counter(uint32_t pair, uint32_t value)
{
    PMU->EVCNTR[pair * 2U] = value & 0xFFFFU;
    PMU->EVCNTR[pair * 2U + 1U] = value >> 16;
}
#endif
static void record(void)
{
    timestamp += 1000U;
    ++ticks;
    struct ProfilerSample sample = {.timestamp = timestamp,
                                    .tick = ticks,
                                    .pc = 0x10001004U,
                                    .lr = 0x10002001U,
                                    .xpsr = 1U << 24,
                                    .exception_return = 0xFFFFFFF9U};
    profiler_pmu_snapshot(sample.pmu);
    sampling_profiler_record(&sample);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
#ifdef TEST_PMU
    PMU->TYPE = (31U << 8) | 2U;
    assert(sampling_profiler_init() && statistical_samples.header.pmu_status == 4U);
    PMU->TYPE = (31U << 8) | 8U;
    assert(sampling_profiler_init() && statistical_samples.header.pmu_status == 5U);
    PMU->AUTHSTATUS = (3U << 6) | (3U << 2);
    PMU->CNTENSET = 0x10U;
    assert(sampling_profiler_init() && statistical_samples.header.pmu_status == 3U);
    assert(PMU->CNTENSET == 0x10U && PMU->CTRL == 0U);
    PMU->CNTENSET = 1U << 31; /* Shared timestamp's cycle counter must survive. */
    PMU->INTENSET = 0x10U;
    assert(sampling_profiler_init() && statistical_samples.header.pmu_status == 3U);
    assert(PMU->INTENSET == 0x10U);
    PMU->INTENSET = 0U;
    PMU->CTRL = 1U;
    assert(sampling_profiler_init() && statistical_samples.header.pmu_status == 3U);
    PMU->CTRL = 0U;
    fake_dwt.CYCCNT = 0x12345678U;
#endif
    assert(sampling_profiler_init());
    assert(statistical_samples.header.version == 1U &&
           statistical_samples.header.record_size == 24U + 4U * statistical_samples.header.pmu_count);
#ifdef TEST_PMU
    assert(statistical_samples.header.pmu_status == 2U);
    assert(PMU->CNTENSET == ((1U << 31) | 15U));
    assert(PMU->EVTYPER[0] == 3U && PMU->EVTYPER[1] == ARM_PMU_CHAIN);
    assert(PMU->EVTYPER[2] == 0x24U && PMU->EVTYPER[3] == ARM_PMU_CHAIN);
    set_counter(0, 0xFFFFU);
    pmu_read_mode = 1U;
    uint32_t values[2];
    profiler_pmu_snapshot(values);
    assert(values[0] == 0x10005U && !statistical_samples.header.pmu_flags);
    assert(fake_dwt.CYCCNT == 0x12345678U);
#else
    assert(statistical_samples.header.pmu_status == 1U && !statistical_samples.header.pmu_count);
#endif
    sampling_profiler_enable();
    for (uint32_t i = 1U; i <= statistical_samples.header.capacity; ++i)
    {
#ifdef TEST_PMU
        set_counter(0, 0x10000U + i * 5U);
        set_counter(1, 0x20000U + i * 7U);
        PMU->OVSSET |= 5U; /* Low-half rollovers are expected, not 32-bit overflows. */
#endif
        record();
    }
    assert(sampling_profiler_full());
    assert(statistical_samples.header.capacity == (statistical_samples.header.pmu_count ? 3U : 4U));
    sampling_profiler_stop(1U, 1U);
#ifdef TEST_PMU
    assert(PMU->CNTENSET == (1U << 31));
    assert(!statistical_samples.header.pmu_flags);
    assert(statistical_samples.header.pmu_stop[0] == 0x1000FU);
    assert(statistical_samples.header.pmu_stop[1] == 0x20015U);
#endif
    FILE *out = fopen(argv[1], "wb");
    assert(out && fwrite((const void *)&statistical_samples, sizeof(statistical_samples), 1, out) == 1);
    assert(!fclose(out));
#ifdef TEST_PMU
    assert(sampling_profiler_init());
    assert(PMU->EVCNTR[0] == 0U && PMU->OVSSET == 0U);
    PMU->OVSSET = 10U; /* Both high halves overflow: full 32-bit events lost. */
    pmu_read_mode = 2U;
    pmu_read_count = 0U;
    profiler_pmu_snapshot(values);
    assert(statistical_samples.header.pmu_flags == 7U);
    assert(pmu_read_count == 12U); /* 3 failed attempts + 1 good second pair. */
    pmu_read_mode = 0U;
    sampling_profiler_stop(1U, 1U);
    assert(fake_dwt.CYCCNT == 0x12345678U);
#endif
    return 0;
}
