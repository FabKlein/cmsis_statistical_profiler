/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_pmu.c
 * Description:  Optional CMSIS PMU snapshots using up to 4 chained 32-bit counters
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_pmu.c
 * @brief Optional CMSIS PMU snapshots using up to 4 chained 32-bit counters.
 */

#include "sampling_profiler_port.h"
#include PROFILER_DEVICE_HEADER

#if PROFILER_PMU_COUNT
    #define CHECK_EVENT(event)                                                                                         \
        _Static_assert((event) >= 0 && (event) <= 0xFFFFU && (event) != 0x001EU,                                       \
                       "Invalid PMU event ID (CHAIN is reserved)")
CHECK_EVENT(PROFILER_PMU_EVENT0);
    #if PROFILER_PMU_COUNT > 1
CHECK_EVENT(PROFILER_PMU_EVENT1);
    #endif
    #if PROFILER_PMU_COUNT > 2
CHECK_EVENT(PROFILER_PMU_EVENT2);
    #endif
    #if PROFILER_PMU_COUNT > 3
CHECK_EVENT(PROFILER_PMU_EVENT3);
    #endif
static const uint32_t events[PROFILER_PMU_COUNT] = {
    PROFILER_PMU_EVENT0,
    #if PROFILER_PMU_COUNT > 1
    PROFILER_PMU_EVENT1,
    #endif
    #if PROFILER_PMU_COUNT > 2
    PROFILER_PMU_EVENT2,
    #endif
    #if PROFILER_PMU_COUNT > 3
    PROFILER_PMU_EVENT3,
    #endif
};

    #if defined(__PMU_PRESENT) && (__PMU_PRESENT == 1U)
/* Reserve the event-counter bank for the firmware lifetime. Do not reset the
 * cycle counter: PMU CCNTR aliases the timestamp's DWT CYCCNT. No DebugMon IRQ. */
static uint32_t owned, running;
        #define EVENT_MASK ((1U << (2U * PROFILER_PMU_COUNT)) - 1U)

/**
 * @brief Latch high-half overflow flags; low-half rollovers are normal chaining.
 */
static void note_overflow(void)
{
    uint32_t overflow = ARM_PMU_Get_CNTR_OVS();
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        statistical_samples.header.pmu_flags |= ((overflow >> (2U * event + 1U)) & 1U) << event;
}

/**
 * @brief Read 1 chained counter without tearing across a low-half rollover.
 * @param low Index of the low 16-bit counter; the next counter holds the high half.
 * @return Coherent 32-bit value, or 0 with a validity flag after 3 failed attempts.
 */
static uint32_t read_pair(uint32_t low)
{
    /* High/low/high avoids tearing when the low half rolls over. Bounded retries
     * ensure a failing device cannot trap the CPU inside the sampling ISR. */
    for (uint32_t attempt = 0; attempt < 3U; ++attempt)
    {
        uint32_t high = ARM_PMU_Get_EVCNTR(low + 1U);
        uint32_t value = ARM_PMU_Get_EVCNTR(low);
        if (high == ARM_PMU_Get_EVCNTR(low + 1U))
            return (high << 16) | value;
    }
    statistical_samples.header.pmu_flags |= 16U;
    return 0U;
}
    #endif

void profiler_pmu_snapshot(uint32_t *values)
{
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        values[event] = 0U;
    #if defined(__PMU_PRESENT) && (__PMU_PRESENT == 1U)
    if (!running)
        return;
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        values[event] = read_pair(2U * event);
    note_overflow();
    #endif
}

void profiler_pmu_init(void)
{
    statistical_samples.header.pmu_status = 1U;
    statistical_samples.header.pmu_requested = PROFILER_PMU_COUNT;
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        statistical_samples.header.pmu_events[event] = events[event];
    #if defined(__PMU_PRESENT) && (__PMU_PRESENT == 1U)
    uint32_t type = PMU->TYPE;
    /* TYPE.SIZE describes register spacing (31 = 32-bit words), not the
     * 16-bit event-counter width. CMSIS supplies the event count field mask. */
    uint32_t spacing = (type & PMU_TYPE_SIZE_CNTS_Msk) >> PMU_TYPE_SIZE_CNTS_Pos;
    if ((type & PMU_TYPE_NUM_CNTS_Msk) < 2U * PROFILER_PMU_COUNT || spacing != 31U || PMU_EVCNTR_CNT_Msk != 0xFFFFU)
    {
        statistical_samples.header.pmu_status = 4U;
        return;
    }
        #if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3)
    uint32_t auth = (PMU->AUTHSTATUS & PMU_AUTHSTATUS_SNID_Msk) >> PMU_AUTHSTATUS_SNID_Pos;
        #else
    uint32_t auth = (PMU->AUTHSTATUS & PMU_AUTHSTATUS_NSNID_Msk) >> PMU_AUTHSTATUS_NSNID_Pos;
        #endif
    if (auth != 3U)
    {
        statistical_samples.header.pmu_status = 5U;
        return;
    }
        /* Preserve any externally owned PMU configuration, including IRQs. The cycle
         * counter's bit 31 may already be enabled by DWT timestamp initialization. */
        #if defined(DWT_CTRL_CPIEVTENA_Msk)
    if (!owned &&
        (DWT->CTRL &
         (DWT_CTRL_CPIEVTENA_Msk | DWT_CTRL_EXCEVTENA_Msk | DWT_CTRL_SLEEPEVTENA_Msk | DWT_CTRL_LSUEVTENA_Msk |
          DWT_CTRL_FOLDEVTENA_Msk)))
    {
        statistical_samples.header.pmu_status = 3U;
        return;
    }
        #endif
    if (!owned &&
        ((PMU->CTRL & ~PMU_CTRL_CYCCNT_DISABLE_Msk) || (PMU->CNTENSET & 0x7FFFFFFFU) || (PMU->INTENSET & 0x7FFFFFFFU)))
    {
        statistical_samples.header.pmu_status = 3U;
        return;
    }
    owned = 1U;
    ARM_PMU_CNTR_Disable(EVENT_MASK);
    ARM_PMU_Set_CNTR_IRQ_Disable(EVENT_MASK);
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
    {
        ARM_PMU_Set_EVTYPER(2U * event, events[event]);
        ARM_PMU_Set_EVTYPER(2U * event + 1U, ARM_PMU_CHAIN);
        /* CMSIS has no individual counter-write function. Never use a global reset. */
        PMU->EVCNTR[2U * event] = 0U;
        PMU->EVCNTR[2U * event + 1U] = 0U;
    }
    ARM_PMU_Set_CNTR_OVS(EVENT_MASK);
    statistical_samples.header.pmu_count = PROFILER_PMU_COUNT;
    statistical_samples.header.pmu_counter_bits = 32U;
    statistical_samples.header.pmu_status = 2U;
    running = 1U;
    ARM_PMU_Enable();
    ARM_PMU_CNTR_Enable(EVENT_MASK);
    __DSB();
    __ISB();
    uint32_t values[PROFILER_PMU_COUNT];
    profiler_pmu_snapshot(values);
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        statistical_samples.header.pmu_start[event] = values[event];
    #endif
}

void profiler_pmu_stop(void)
{
    #if defined(__PMU_PRESENT) && (__PMU_PRESENT == 1U)
    if (!running)
        return;
    ARM_PMU_CNTR_Disable(EVENT_MASK);
    __DSB();
    __ISB();
    uint32_t values[PROFILER_PMU_COUNT];
    profiler_pmu_snapshot(values);
    for (uint32_t event = 0; event < PROFILER_PMU_COUNT; ++event)
        statistical_samples.header.pmu_stop[event] = values[event];
    running = 0U;
        /* Keep global PMU/cycle state and reservation; only our event counters stop. */
    #endif
}
#endif
