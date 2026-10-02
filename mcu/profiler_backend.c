/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_backend.c
 * Description:  Cortex-M timestamping, frame validation and sampling backend
 *
 * $Date:        2 October 2026
 * $Revision:    V.1.0.10
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file profiler_backend.c
 * @brief Cortex-M timestamping, frame validation and sampling backend.
 *
 * Bridges the timer adapter and the architecture-independent capture storage.
 * The assembly IRQ wrapper preserves the interrupted registers before entering C:
 *
 *     timer IRQ -> acknowledge + timestamp -> recording gate
 *                                             |
 *                                  validate exception frame
 *                                             |
 *                              PC/LR + optional PMU/backtrace
 *                                             |
 *                                      profiler_record()
 *
 * The timer clock schedules samples; the timestamp clock dates them. They may
 * run at different frequencies. Neither replaces the application's RTOS tick.
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

/* EXC_RETURN bits 31:7 must all be 1; bits 6:0 are validated separately. */
#define EXC_RETURN_PREFIX_MASK  0xFFFFFF80U
#define EXC_RETURN_RESERVED_BIT (1UL << 1) /* Must be 0 on every supported core. */
#define EXC_RETURN_THREAD_MODE  (1UL << 3)
#define EXC_RETURN_BASIC_FRAME  (1UL << 4) /* 1: core registers only; 0: extended FP/MVE frame. */

/* Armv8-M security/stacking fields. On older cores these bit positions are
 * reserved and must all be 1, rather than describing a security state. */
#define EXC_RETURN_SECURE_HANDLER          (1UL << 0) /* ES: exception was taken to Secure state. */
#define EXC_RETURN_DEFAULT_CALLEE_STACKING (1UL << 5) /* DCRS: default callee-register stacking rules. */
#define EXC_RETURN_SECURE_STACK            (1UL << 6) /* S: interrupted registers are on the Secure stack. */
#define EXC_RETURN_FRAME_STATE_MASK                                                                                    \
    (EXC_RETURN_SECURE_STACK | EXC_RETURN_DEFAULT_CALLEE_STACKING | EXC_RETURN_SECURE_HANDLER)
#define EXC_RETURN_SUPPORTED_MODE_MASK (EXC_RETURN_FRAME_STATE_MASK | EXC_RETURN_THREAD_MODE)

/* Stacked xPSR bit 9 records an extra word used to align the exception stack. */
#define STACKED_XPSR_ALIGNMENT (1UL << 9)

/* Word indices in the hardware exception frame, starting at the captured SP.
 * These are frame positions, not architectural register numbers: r12 is word 4.
 *
 * Low address -> r0 r1 r2 r3 r12 LR PC xPSR [FP/MVE area] [alignment word]
 */
enum
{
    FRAME_R0_IDX = 0,
    FRAME_R1_IDX,
    FRAME_R2_IDX,
    FRAME_R3_IDX,
    FRAME_R12_IDX,
    FRAME_LR_IDX,
    FRAME_PC_IDX,
    FRAME_XPSR_IDX,
    FRAME_CORE_WORDS
};

/* The extension reserves S0-S15, FPSCR and 1 additional word. Lazy stacking
 * reserves this space even if the floating-point registers are not written. */
#define FRAME_EXTENSION_WORDS 18U

#if PROFILER_STACK_UNWIND
/* Architectural register numbers in the virtual register set given to EHABI. */
enum
{
    REG_R0_IDX = 0,
    REG_R4_IDX = 4,
    REG_R8_IDX = 8,
    REG_R12_IDX = 12,
    REG_SP_IDX,
    REG_LR_IDX,
    REG_PC_IDX,
    REG_COUNT
};

    /* The assembly wrapper saves 2 groups of 4 registers, with r8-r11 first. */
    #define SAVED_REGISTER_GROUP_WORDS 4U
    #define SAVED_R8_OFFSET            0U
    #define SAVED_R4_OFFSET            SAVED_REGISTER_GROUP_WORDS
#endif

/* EXC_RETURN is the exception-return token supplied by hardware, not a code
 * address. Its bits describe the interrupted mode, stack and frame layout.
 * Armv8-M assigns security meanings to bits reserved on older cores. Only the
 * frame state supported by this build is accepted; no cross-security unwinding. */
#if defined(__ARM_ARCH) && (__ARM_ARCH >= 8)
    #if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3)
        #define PROFILER_FRAME_STATE EXC_RETURN_FRAME_STATE_MASK
    #else
        #define PROFILER_FRAME_STATE EXC_RETURN_DEFAULT_CALLEE_STACKING
    #endif
#else
    #define PROFILER_FRAME_STATE EXC_RETURN_FRAME_STATE_MASK
#endif

#if !PROFILER_TIMESTAMP_CUSTOM
    #ifndef DWT_CTRL_CYCCNTENA_Msk
        #error "No DWT CYCCNT: set PROFILER_TIMESTAMP_CUSTOM=1 and supply a timestamp timer"
    #else
int profiler_timestamp_init(uint32_t *frequency_hz)
{
    if (!SystemCoreClock)
        return 0;
    /* Enable the debug/trace block and its Data Watchpoint and Trace (DWT)
     * cycle counter. Leave the existing count intact: it may have other users. */
    DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
    if ((DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) != 0U)
        return 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    __DSB();
    __ISB();

    /* A present counter can still be locked or unavailable. Verify progress
     * instead of reporting a usable clock based only on the feature bits. */
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

/* Readable RAM is the outer safety boundary. Optional precise bounds further
 * restrict reads to the interrupted task's allocation, not all of that RAM. */
static const struct StackRegion stack_regions[] = PROFILER_STACK_REGIONS;

/* Written by the sampling IRQ and read by thread-mode timing queries. Counts
 * survive capture reinitialization and advance even while recording is gated off.
 * These count serviced timer interrupts, not periods lost while IRQs are masked. */
static volatile uint32_t interrupt_ticks;
static volatile uint32_t milliseconds;
/* Precomputed conversion from the actual timer period to milliseconds. The
 * remainder is in timer-clock units and avoids rounding drift at rates like 333 Hz. */
static uint32_t timer_clock_hz;
static uint32_t tick_whole_ms;
static uint32_t tick_fraction;
static uint32_t ms_fraction;

/**
 * @brief Advance timer-derived time using an exact fractional millisecond accumulator.
 */
static void profiler_tick(void)
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
    const size_t bytes = FRAME_CORE_WORDS * sizeof(uint32_t);

    if ((address % sizeof(uint32_t)) != 0U)
        return 0;
#if PROFILER_PRECISE_STACK_BOUNDS
    /* The application identifies the active stack without calling RTOS services
     * from this ISR. Validate its range before using it for any memory read. */
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
            /* Pass only the intersection to the unwinder, so caller recovery
             * cannot escape either the task stack or the readable RAM window. */
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
    /* Round to the closest realizable period; callers publish the actual timer
     * frequency/period so the host need not assume the requested rate was exact. */
    uint64_t period = ((uint64_t)timer_hz + PROFILER_SAMPLE_HZ / 2U) / PROFILER_SAMPLE_HZ;

    if (!timer_hz || period < 2U || period > max_period)
        return 0;

    return (uint32_t)period;
}

void profiler_port_stop(void)
{
    /* Prevent the sampling ISR from racing timer shutdown. Restore the caller's
     * interrupt mask, including when interrupts were already disabled. */
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

    if (!profiler_timestamp_init(&timestamp_hz) || !timestamp_hz)
        return profiler_init_fail(PROFILER_INIT_TIMESTAMP, PROFILER_INIT_UNAVAILABLE, timestamp_hz, 0);

#if PROFILER_STACK_UNWIND
    if (!profiler_unwind_init())
        return 0;
#endif
    /* Keep the timer IRQ out until its time conversion state is ready. Slow
     * setup and table validation above do not require masking interrupts. */
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    clock->timestamp_hz = timestamp_hz;

    if (!profiler_timer_init(clock))
    {
        __set_PRIMASK(primask);
        if (profiler_diagnostics()->reason == PROFILER_INIT_OK)
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

    /* Use the adapter's actual period, not PROFILER_SAMPLE_HZ. Division stays
     * here in initialization; each interrupt only adds the precomputed parts. */
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
/* Data Memory Barrier: order record/state publication. This does not mask
 * interrupts or write dirty cache lines back to RAM. */
void profiler_port_barrier(void) { __DMB(); }

void profiler_port_flush(const void *address, uint32_t bytes)
{
    /* Called after capture stops: make dirty buffer data visible in RAM for a
     * debugger/export reader. DSB waits for these writes to complete. */
#if defined(__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
    if ((SCB->CCR & SCB_CCR_DC_Msk) != 0U)
        SCB_CleanDCache_by_Addr((void *)address, (int32_t)bytes);
#else
    (void)address;
    (void)bytes;
#endif
    __DSB();
}

/**
 * @brief Handle an acknowledged sampling source and validate before reading RAM.
 * @details Called by the assembly wrapper; frame points to the interrupted
 * hardware frame, not this handler's C stack. Keep this path integer-only and
 * bounded, including all optional hooks and the unwinder.
 */
__attribute__((used, noinline)) void statistical_sampling_tick(const uint32_t *frame,
                                                               uint32_t exception_return
#if PROFILER_STACK_UNWIND
                                                               ,
                                                               const uint32_t *saved_r8_r11_r4_r7
#endif
)
{
    /* Ignore unrelated/spurious entries. Timestamp early to limit the skew
     * introduced by validation and optional backtrace work. */
    if (!profiler_timer_ack())
        return;

    uint32_t timestamp = profiler_timestamp_read();

    profiler_tick();

    /* Timer bookkeeping continues while capture is disabled or the buffer is
     * full; only the sample extraction/storage path is gated. */
    if (!PROFILER_SAMPLING_ENABLED || !statistical_sampling_gate)
        return;

    int extended_supported = 0;
#if (defined(__FPU_PRESENT) && (__FPU_PRESENT == 1U)) || (defined(__MVE_PRESENT) && (__MVE_PRESENT == 1U))
    extended_supported = 1;
#endif
    const int extended_frame = (exception_return & EXC_RETURN_BASIC_FRAME) == 0U;

    /* Check the token before trusting the stack pointer. Accept thread-mode
     * frames only: sampling another handler would describe interrupt work. */
    if ((exception_return & EXC_RETURN_PREFIX_MASK) != EXC_RETURN_PREFIX_MASK ||
        (exception_return & EXC_RETURN_RESERVED_BIT) != 0U)
    {
        profiler_reject(PROFILER_REJECT_EXC_RETURN);
        return;
    }

    /* Reject handler-mode, cross-security and extra callee-stacking layouts.
     * The frame offsets below are valid only for the accepted layout. */
    if ((exception_return & EXC_RETURN_SUPPORTED_MODE_MASK) != (PROFILER_FRAME_STATE | EXC_RETURN_THREAD_MODE))
    {
        profiler_reject(PROFILER_REJECT_UNSUPPORTED_FRAME);
        return;
    }

    /* A basic frame is valid without FP/MVE support; an extended frame is not. */
    if (extended_frame && !extended_supported)
    {
        profiler_reject(PROFILER_REJECT_UNSUPPORTED_FRAME);
        return;
    }

    /* No frame dereference is allowed until all 8 core words fit in bounds. */
    struct ProfilerStackBounds bounds;

    if (!readable_frame(frame, exception_return, &bounds))
    {
        profiler_reject(PROFILER_REJECT_STACK_BOUNDS);
        return;
    }

    /* Stacked status must describe Thumb thread execution (no active exception).
     * This is a plausibility check, not proof that arbitrary RAM is a frame. */
    uint32_t xpsr = frame[FRAME_XPSR_IDX];

    if ((xpsr & xPSR_T_Msk) == 0U || (xpsr & xPSR_ISR_Msk) != 0U)
    {
        profiler_reject(PROFILER_REJECT_XPSR);
        return;
    }

    /* R0..xPSR are first in both basic and FP/MVE extended frames on this
     * backend. DCRS/security checks above exclude additional callee frames. */
    /* Assign mandatory fields explicitly: aggregate zero-initialization of the
     * optional trace can introduce an ISR call to a vectorized libc memset. */
    struct ProfilerSample sample;

    sample.timestamp = timestamp;
    sample.tick = profiler_port_ticks();
    sample.pc = frame[FRAME_PC_IDX];
    sample.lr = frame[FRAME_LR_IDX];
    sample.xpsr = xpsr;
    sample.exception_return = exception_return;
#if PROFILER_PMU_COUNT
    /* Counters include all execution since their start, including interrupts;
     * their deltas must not be attributed solely to this sampled PC. */
    profiler_pmu_snapshot(sample.pmu);
#endif
#if PROFILER_STACK_UNWIND
    /* Recover SP as it was before the interrupt by stepping past everything
     * hardware reserved. The optional alignment word belongs to this frame too. */
    uint32_t frame_bytes = FRAME_CORE_WORDS * sizeof(uint32_t);
    uintptr_t address = (uintptr_t)frame;

    if (extended_frame)
        frame_bytes += FRAME_EXTENSION_WORDS * sizeof(uint32_t);

    if ((xpsr & STACKED_XPSR_ALIGNMENT) != 0U)
        frame_bytes += sizeof(uint32_t);

    /* readable_frame() already checked the base and core words. Check the
     * complete frame before deriving SP; subtraction avoids address overflow. */
    int complete_frame_fits = bounds.bytes >= frame_bytes;

    if (complete_frame_fits)
        complete_frame_fits = address - bounds.base <= bounds.bytes - frame_bytes;

    /* The virtual Cortex-M SP must also fit in a 32-bit register. */
    if (!complete_frame_fits || address > UINT32_MAX - frame_bytes)
    {
        /* Keep the valid PC sample even when the full exception frame cannot
         * fit. Backtrace failure must not discard ordinary sampling data. */
        sample.unwind = PROFILER_UNWIND_BOUNDS << 8; /* Status in bits 15:8; depth in bits 7:0. */
        /* Depth is 0, so storage does not read the caller array. */
    }
    else
    {
        /* Reconstruct the interrupted register set, not the handler's registers.
         * Hardware saved r0-r3/r12/LR/PC; the wrapper saved r4-r11 separately.
         * The pre-exception SP lies above the entire frame, including padding.
         *
         * frame:        r0 r1 r2 r3 r12 LR PC xPSR [FP area] [padding]
         * saved block:  r8 r9 r10 r11 r4 r5 r6 r7
         * regs:         r0 ... r12 SP LR PC  -> EHABI interpreter
         */
        uint32_t regs[REG_COUNT];

        /* Merge the hardware frame and the wrapper's software snapshot.
         * Neither contains the C handler's current working register values. */
        for (uint32_t i = 0; i < SAVED_REGISTER_GROUP_WORDS; ++i)
        {
            regs[REG_R0_IDX + i] = frame[FRAME_R0_IDX + i];
            regs[REG_R4_IDX + i] = saved_r8_r11_r4_r7[SAVED_R4_OFFSET + i];
            regs[REG_R8_IDX + i] = saved_r8_r11_r4_r7[SAVED_R8_OFFSET + i];
        }

        regs[REG_R12_IDX] = frame[FRAME_R12_IDX];
        regs[REG_SP_IDX] = (uint32_t)address + frame_bytes;
        regs[REG_LR_IDX] = frame[FRAME_LR_IDX];
        regs[REG_PC_IDX] = frame[FRAME_PC_IDX];

        /* The unwinder updates this local register set, never the real frame. */
        profiler_unwind_capture(&sample, regs, &bounds);
    }
#endif

    /* Storage owns capacity checks and publication; this backend owns only
     * hardware interpretation and validation of the sampled context. */
    profiler_record(&sample);
}
