/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_cortex_m.c
 * Description:  Cortex-M timestamping, frame validation and sampling backend
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.2
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_cortex_m.c
 * @brief Cortex-M timestamping, frame validation and sampling backend.
 */

#include "sampling_profiler_cortex_m.h"
#if PROFILER_STACK_UNWIND
    #include "sampling_profiler_unwind.h"
#endif
#include PROFILER_DEVICE_HEADER
#include <stddef.h>

#ifndef __CORTEX_M
    #error "A CMSIS Cortex-M device header is required"
#endif

/* Armv8-M changes the reserved legacy security bits in EXC_RETURN. */
#if (__CORTEX_M == 23U) || (__CORTEX_M == 33U) || (__CORTEX_M == 35U) || (__CORTEX_M == 52U) || (__CORTEX_M == 55U) || \
    (__CORTEX_M == 85U)
    #if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3)
        #define PROFILER_FRAME_STATE 0x61U
    #else
        #define PROFILER_FRAME_STATE 0x20U
    #endif
#else
    #define PROFILER_FRAME_STATE 0x61U
#endif

#if !PROFILER_TIMESTAMP_CUSTOM
    #ifndef DWT_CTRL_CYCCNTENA_Msk
        #error "No DWT CYCCNT: set PROFILER_TIMESTAMP_CUSTOM=1 and supply a timestamp timer"
    #else
int profiler_timestamp_init(uint32_t *frequency_hz)
{
    if (!SystemCoreClock)
        return 0;
    DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
    if ((DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) != 0U)
        return 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    __DSB();
    __ISB();
    uint32_t before = DWT->CYCCNT;
    for (volatile uint32_t delay = 0; delay < 100U; ++delay)
        __NOP();
    if (DWT->CYCCNT == before)
        return 0;
    *frequency_hz = SystemCoreClock;
    return 1;
}
uint32_t profiler_timestamp_read(void) { return DWT->CYCCNT; }
    #endif
#endif

/**
 * @brief 1 initialized, CPU-readable RAM range allowed to contain exception frames.
 */
struct StackRegion
{
    uintptr_t address;
    size_t bytes;
};
#ifdef PROFILER_STACK_SIZE_FROM_DTCM
static struct StackRegion stack_regions[] = PROFILER_STACK_REGIONS;
#else
static const struct StackRegion stack_regions[] = PROFILER_STACK_REGIONS;
#endif

/**
 * @brief Resolve the optional DTCM-derived region once at initialization.
 * @return 0 if opted-in DTCM is disabled or has an unsupported size; otherwise 1.
 */
static int configure_stack_regions(void)
{
#ifdef PROFILER_STACK_SIZE_FROM_DTCM
    #if !defined(MEMSYSCTL_DTCMCR_SZ_Msk)
        #error "Automatic DTCM sizing requires MEMSYSCTL; supply explicit stack regions on this core"
    #endif
    uint32_t dtcm = MEMSYSCTL->DTCMCR;
    uint32_t size = (dtcm & MEMSYSCTL_DTCMCR_SZ_Msk) >> MEMSYSCTL_DTCMCR_SZ_Pos;
    /* Cortex-M55 SZ: 0 = absent, 1/2 = reserved, 3..15 = 4 KiB..16 MiB.
     * Query only at init; frame validation has no per-sample register reads. */
    if (!(dtcm & MEMSYSCTL_DTCMCR_EN_Msk) || size < 3U)
        return 0;
    stack_regions[0].bytes = (size_t)512U << size;
#endif
    return 1;
}

static volatile uint32_t interrupt_ticks;
static volatile uint32_t milliseconds;
static uint32_t timer_clock_hz;
static uint32_t tick_whole_ms;
static uint32_t tick_fraction;
static uint32_t ms_fraction;

/**
 * @brief Advance timer-derived time using an exact fractional millisecond accumulator.
 */
static void profiler_cortex_m_tick(void)
{
    ++interrupt_ticks;
    uint32_t elapsed_ms = tick_whole_ms;
    /* No division in the ISR; accumulate fractional milliseconds exactly. */
    if (ms_fraction >= timer_clock_hz - tick_fraction)
    {
        ms_fraction -= timer_clock_hz - tick_fraction;
        ++elapsed_ms;
    }
    else
        ms_fraction += tick_fraction;
    milliseconds += elapsed_ms;
}

uint32_t profiler_port_ticks(void) { return interrupt_ticks; }
uint32_t profiler_port_millis(void) { return milliseconds; }

/**
 * @brief Validate the 8 core frame words against readable RAM and optional stack bounds.
 * @param[in] frame Candidate frame address, not dereferenced by this check.
 * @param exception_return Selects the interrupted stack for precise bounds.
 * @param[out] selected Intersection of the allocation and readable RAM region.
 * @return Nonzero when aligned and contained in all required bounds.
 */
static int readable_frame(const uint32_t *frame, uint32_t exception_return, struct ProfilerStackBounds *selected)
{
    uintptr_t address = (uintptr_t)frame;
    const size_t bytes = 8U * sizeof(uint32_t);
    if ((address & 3U) != 0U)
        return 0;
#if PROFILER_PRECISE_STACK_BOUNDS
    struct ProfilerStackBounds bounds = {0U, 0U};
    if (!profiler_stack_bounds(exception_return, &bounds) || bounds.bytes < bytes ||
        bounds.bytes - 1U > UINTPTR_MAX - bounds.base || address < bounds.base ||
        address - bounds.base > bounds.bytes - bytes)
        return 0;
#else
    (void)exception_return;
#endif
    for (size_t i = 0; i < sizeof(stack_regions) / sizeof(stack_regions[0]); ++i)
    {
        /* Subtraction avoids overflowing base+size or underflowing size-32. */
        if (stack_regions[i].bytes >= bytes && address >= stack_regions[i].address &&
            address - stack_regions[i].address <= stack_regions[i].bytes - bytes)
        {
            selected->base = stack_regions[i].address;
            selected->bytes = stack_regions[i].bytes;
#if PROFILER_PRECISE_STACK_BOUNDS
            uintptr_t base = bounds.base > selected->base ? bounds.base : selected->base;
            size_t a = bounds.bytes - (base - bounds.base);
            size_t b = selected->bytes - (base - selected->base);
            selected->base = base;
            selected->bytes = a < b ? a : b;
#endif
            return 1;
        }
    }
    return 0;
}

uint32_t profiler_timer_period(uint32_t timer_hz, uint32_t max_period)
{
    uint64_t period = ((uint64_t)timer_hz + PROFILER_SAMPLE_HZ / 2U) / PROFILER_SAMPLE_HZ;
    if (!timer_hz || period < 2U || period > max_period)
        return 0;
    return (uint32_t)period;
}

void profiler_port_stop(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    profiler_timer_stop();
    __DSB();
    __ISB();
    __set_PRIMASK(primask);
}

int profiler_port_init(struct ProfilerClock *clock)
{
    uint32_t timestamp_hz = 0U;
    if (!configure_stack_regions())
        return profiler_init_fail(PROFILER_INIT_STACK, PROFILER_INIT_INVALID_CONFIG, 0, 0);
    if (!profiler_timestamp_init(&timestamp_hz) || !timestamp_hz)
        return profiler_init_fail(PROFILER_INIT_TIMESTAMP, PROFILER_INIT_UNAVAILABLE, timestamp_hz, 0);

#if PROFILER_STACK_UNWIND
    if (!profiler_unwind_init())
        return 0;
#endif
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    clock->timestamp_hz = timestamp_hz;
    if (!profiler_timer_init(clock))
    {
        __set_PRIMASK(primask);
        if (sampling_profiler_diagnostics()->reason == PROFILER_INIT_OK)
            profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_UNAVAILABLE, 0, 0);
        return 0;
    }
    /* 2-period decoding tolerance must stay below half a timestamp wrap. */
    if (!clock->timer_hz || clock->timer_period < 2U ||
        (uint64_t)clock->timer_period * timestamp_hz / clock->timer_hz >= 0x40000000ULL)
    {
        profiler_timer_stop();
        __set_PRIMASK(primask);
        return profiler_init_fail(PROFILER_INIT_TIMER, PROFILER_INIT_BAD_CLOCK, clock->timer_hz, clock->timer_period);
    }
    timer_clock_hz = clock->timer_hz;
    uint64_t numerator = (uint64_t)clock->timer_period * 1000U;
    tick_whole_ms = (uint32_t)(numerator / timer_clock_hz);
    tick_fraction = (uint32_t)(numerator % timer_clock_hz);
    ms_fraction = 0U;
    profiler_timer_start();
    __DSB();
    __ISB();
    __set_PRIMASK(primask);
    return 1;
}

uint32_t profiler_port_timestamp(void) { return profiler_timestamp_read(); }
void profiler_port_barrier(void) { __DMB(); }

void profiler_port_flush(const void *address, uint32_t bytes)
{
#if defined(__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
    if ((SCB->CCR & SCB_CCR_DC_Msk) != 0U)
        SCB_CleanDCache_by_Addr((void *)address, (int32_t)bytes);
#else
    (void)address;
    (void)bytes;
#endif
    __DSB();
}

__attribute__((used, noinline)) void statistical_sampling_tick(const uint32_t *frame,
                                                               uint32_t exception_return
#if PROFILER_STACK_UNWIND
                                                               ,
                                                               const uint32_t *saved_r8_r11_r4_r7
#endif
)
{
    if (!profiler_timer_ack())
        return;
    uint32_t timestamp = profiler_timestamp_read();
    profiler_cortex_m_tick();
    if (!PROFILER_SAMPLING_ENABLED || !statistical_sampling_gate)
        return;
    int extended_supported = 0;
#if (defined(__FPU_PRESENT) && (__FPU_PRESENT == 1U)) || (defined(__MVE_PRESENT) && (__MVE_PRESENT == 1U))
    extended_supported = 1;
#endif
    if ((exception_return & 0xFFFFFF80U) != 0xFFFFFF80U || (exception_return & 2U) != 0U)
    {
        sampling_profiler_reject(PROFILER_REJECT_EXC_RETURN);
        return;
    }
    if ((exception_return & 0x69U) != (PROFILER_FRAME_STATE | 8U) ||
        (!(exception_return & 0x10U) && !extended_supported))
    {
        sampling_profiler_reject(PROFILER_REJECT_UNSUPPORTED_FRAME);
        return;
    }
    struct ProfilerStackBounds bounds;
    if (!readable_frame(frame, exception_return, &bounds))
    {
        sampling_profiler_reject(PROFILER_REJECT_STACK_BOUNDS);
        return;
    }
    uint32_t xpsr = frame[7];
    if ((xpsr & xPSR_T_Msk) == 0U || (xpsr & xPSR_ISR_Msk) != 0U)
    {
        sampling_profiler_reject(PROFILER_REJECT_XPSR);
        return;
    }
    /* R0..xPSR are first in both basic and FP/MVE extended frames on this
     * backend. DCRS/security checks above exclude additional callee frames. */
    /* Assign mandatory fields explicitly: aggregate zero-initialization of the
     * optional trace can introduce an ISR call to a vectorized libc memset. */
    struct ProfilerSample sample;
    sample.timestamp = timestamp;
    sample.tick = profiler_port_ticks();
    sample.pc = frame[6];
    sample.lr = frame[5];
    sample.xpsr = xpsr;
    sample.exception_return = exception_return;
#if PROFILER_PMU_COUNT
    profiler_pmu_snapshot(sample.pmu);
#endif
#if PROFILER_STACK_UNWIND
    /* Hardware frame: core words, optionally 18 FP words, optionally alignment padding.
     * Lazy FP stacking reserves the same space even when FP values were not written. */
    uint32_t frame_bytes = ((exception_return & 0x10U) ? 8U : 26U) * 4U + ((xpsr & (1U << 9)) ? 4U : 0U);
    uintptr_t address = (uintptr_t)frame;
    if (bounds.bytes < frame_bytes || address - bounds.base > bounds.bytes - frame_bytes ||
        address > UINT32_MAX - frame_bytes)
    {
        sample.unwind = PROFILER_UNWIND_BOUNDS << 8;
        volatile uint32_t *callers = sample.callers;
        for (uint32_t i = 0; i < PROFILER_UNWIND_MAX_DEPTH; ++i)
            callers[i] = 0;
    }
    else
    {
        uint32_t regs[16];
        for (uint32_t i = 0; i < 4U; ++i)
        {
            regs[i] = frame[i];
            regs[i + 4U] = saved_r8_r11_r4_r7[i + 4U];
            regs[i + 8U] = saved_r8_r11_r4_r7[i];
        }
        regs[12] = frame[4];
        regs[13] = (uint32_t)address + frame_bytes;
        regs[14] = frame[5];
        regs[15] = frame[6];
        profiler_unwind_capture(&sample, regs, &bounds);
    }
#endif
    sampling_profiler_record(&sample);
}
