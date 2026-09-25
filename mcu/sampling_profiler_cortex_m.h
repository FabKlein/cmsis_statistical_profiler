/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_cortex_m.h
 * Description:  Cortex-M timer hooks, timestamp interface and IRQ entry
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_cortex_m.h
 * @brief Cortex-M timer hooks, timestamp interface and IRQ entry.
 */

#ifndef PROFILER_CORTEX_M_H
#define PROFILER_CORTEX_M_H

#include "sampling_profiler_port.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif
/**
 * @brief CPU-visible allocation of the interrupted MSP or PSP stack.
 */
struct ProfilerStackBounds
{
    uintptr_t base; /**< CPU-visible lowest address of the allocation. */
    size_t bytes;   /**< Allocation length in bytes. */
};

/* Optional: set PROFILER_PRECISE_STACK_BOUNDS=1 and implement this hook.
 * Return 1 with the interrupted stack's CPU-visible allocation, or 0 to reject.
 * Select MSP/PSP using EXC_RETURN bit 2, not the ISR's current SP. An RTOS adapter
 * must identify the interrupted task. Called only for otherwise supported frames.
 * Bounds narrow the configured readable RAM whitelist; they never expand it.
 * Must be bounded, ISR-safe, integer-only and must not dereference the frame.
 * No allocation, blocking or logging. With the option disabled, no hook is called. */
/**
 * @brief Resolve precise bounds of an otherwise supported interrupted stack.
 * @param exception_return EXC_RETURN from interrupt entry; bit 2 selects MSP/PSP.
 * @param[out] bounds Non-NULL destination for the stack allocation.
 * @return 1 with valid bounds, or 0 to reject the frame.
 * @note Optional hook enabled by PROFILER_PRECISE_STACK_BOUNDS. Must be bounded,
 * ISR-safe and integer-only; no allocation, blocking, logging or frame dereference.
 * The returned bounds narrow, never expand, the readable RAM whitelist.
 */
int profiler_stack_bounds(uint32_t exception_return, struct ProfilerStackBounds *bounds);

/* Default: DWT CYCCNT. Set PROFILER_TIMESTAMP_CUSTOM=1 and implement these
 * for cores without CYCCNT (M0/M0+/M1/M23), or to use a peripheral timer.
 * Init returns 1 with a nonzero, fixed frequency. Read returns a free-running
 * uint32 upcounter, wrapping modulo 2^32. Do not reset a shared timer.
 * Read must be ISR-safe, bounded, and use no FP instructions. */
/**
 * @brief Initialize a timestamp source without resetting a shared counter.
 * @param[out] frequency_hz Non-NULL destination for the fixed, nonzero frequency.
 * @return 1 on success, 0 when the source cannot be used.
 * @note Implement when PROFILER_TIMESTAMP_CUSTOM is enabled; otherwise DWT is used.
 */
int profiler_timestamp_init(uint32_t *frequency_hz);
/**
 * @brief Read the timestamp source from thread or interrupt context.
 * @return Free-running upcounter modulo 2^32.
 * @note Must be bounded and integer-only, at the frequency reported by initialization.
 */
uint32_t profiler_timestamp_read(void);

/* Select exactly 1 timer implementation. Init reserves/configures it stopped;
 * return 0 without claiming a busy peripheral. Called with interrupts masked.
 * Stop is safe before init. Ack returns 1 only for a real sampling event. */
/**
 * @brief Reserve and configure the adapter timer, leaving it stopped.
 * @param[in,out] clock Set timer_hz and timer_period; preserve timestamp_hz.
 * @return 1 on success, 0 for an unsupported setting or busy peripheral.
 * @note Called with interrupts masked. Do not claim a busy peripheral.
 */
int profiler_timer_init(struct ProfilerClock *clock);
/**
 * @brief Start the configured sampling timer and its interrupt.
 * @pre Timer initialization succeeded; interrupts are masked by the caller.
 */
void profiler_timer_start(void);
/**
 * @brief Stop the sampling timer and clear its pending interrupt.
 * @note Called with interrupts masked; must be safe before initialization.
 */
void profiler_timer_stop(void);
/**
 * @brief Acknowledge a timer interrupt in the sampling ISR.
 * @return 1 for a real sampling event, 0 for a spurious interrupt.
 */
int profiler_timer_ack(void);
/* Rounded timer count, or 0 for an unsupported clock/rate/range. */
/**
 * @brief Round the requested sample rate to a supported timer period.
 * @param timer_hz Actual input clock frequency in Hz.
 * @param max_period Largest period accepted by the adapter.
 * @return Rounded count, or 0 for an invalid clock or out-of-range period.
 */
uint32_t profiler_timer_period(uint32_t timer_hz, uint32_t max_period);
/**
 * @brief Acknowledge a sample interrupt, validate its frame and record it.
 * @param[in] frame Original hardware-stacked register frame selected by EXC_RETURN.
 * @param exception_return Original LR value at exception entry.
 * @note Enter via PROFILER_DEFINE_IRQ_HANDLER; never via an ordinary C ISR wrapper.
 */
#if PROFILER_STACK_UNWIND
/** @param[in] saved_r8_r11_r4_r7 Original callee registers saved by the naked entry. */
void statistical_sampling_tick(const uint32_t *frame, uint32_t exception_return, const uint32_t *saved_r8_r11_r4_r7);
#else
void statistical_sampling_tick(const uint32_t *frame, uint32_t exception_return);
#endif
#ifdef __cplusplus
}
#endif

/* Must be the actual vector entry: never call this from an ordinary C ISR.
 * Preserves EXC_RETURN and the original MSP/PSP exception frame.
 * No FP/vector instructions are permitted in the IRQ path. */
/**
 * @brief Define the actual naked sampling vector entry without altering the frame.
 * @param name Vector handler symbol required by the device startup file.
 * @warning No floating-point or vector instructions are permitted in the IRQ path.
 */
#if PROFILER_STACK_UNWIND
    /* Armv6-M-compatible entry (including Cortex-M0/M0+). Select the original frame before modifying MSP.
     * Save r8-r11, r4-r7, EXC_RETURN and 1 padding word (40 bytes, 8-byte aligned).
     * Restore every callee-saved register before returning from the exception. */
    #define PROFILER_DEFINE_IRQ_HANDLER(name)                                                                          \
        __attribute__((naked)) void name(void)                                                                         \
        {                                                                                                              \
            /* r1 = original EXC_RETURN; bit 2 selects the interrupted stack. */                                       \
            __asm volatile("mov    r1, lr\n"                                                                           \
                           "movs   r2, #4\n"                                                                           \
                           "tst    r1, r2\n"                                                                           \
                           "beq    1f\n" /* r0 = original hardware frame, before any handler stack changes. */         \
                           "mrs    r0, psp\n"                                                                          \
                           "b      2f\n"                                                                               \
                           "1:\n"                                                                                      \
                           "mrs    r0, msp\n"                                                                          \
                           "2:\n"            /* Handler mode uses MSP. Reserve padding to keep C-call alignment. */    \
                           "sub    sp, #4\n" /* Preserve interrupted low callee registers and EXC_RETURN. */           \
                           "push   {r4-r7, lr}\n" /* Armv6-M PUSH cannot save r8-r11 directly; stage through r4-r7. */ \
                           "mov    r4, r8\n"                                                                           \
                           "mov    r5, r9\n"                                                                           \
                           "mov    r6, r10\n"                                                                          \
                           "mov    r7, r11\n"                                                                          \
                           "push   {r4-r7}\n" /* r2 points to saved r8-r11, then r4-r7, then EXC_RETURN/padding. */    \
                           "mov    r2, sp\n"                                                                           \
                           "ldr    r3, =statistical_sampling_tick\n" /* Call C with (frame, EXC_RETURN, saved          \
                                                                        registers); BLX replaces LR. */                \
                           "blx    r3\n" /* Restore high registers first, using low registers as scratch. */           \
                           "pop    {r4-r7}\n"                                                                          \
                           "mov    r8, r4\n"                                                                           \
                           "mov    r9, r5\n"                                                                           \
                           "mov    r10, r6\n"                                                                          \
                           "mov    r11, r7\n" /* Restore low registers, reload EXC_RETURN, then discard padding. */    \
                           "pop    {r4-r7}\n"                                                                          \
                           "pop    {r3}\n"                                                                             \
                           "add    sp, #4\n" /* EXC_RETURN makes hardware restore the original exception frame. */     \
                           "bx     r3\n");                                                                             \
        }
#else
    #define PROFILER_DEFINE_IRQ_HANDLER(name)                                                                          \
        __attribute__((naked)) void name(void)                                                                         \
        {                                                                                                              \
            /* r1 = original EXC_RETURN; bit 2 selects the interrupted stack. */                                       \
            __asm volatile("mov    r1, lr\n"                                                                           \
                           "movs   r2, #4\n"                                                                           \
                           "tst    r1, r2\n"                                                                           \
                           "beq    1f\n" /* r0 = original hardware frame, before any handler stack changes. */         \
                           "mrs    r0, psp\n"                                                                          \
                           "b      2f\n"                                                                               \
                           "1:\n"                                                                                      \
                           "mrs    r0, msp\n"                                                                          \
                           "2:\n" /* Tail-branch to C: keep LR = EXC_RETURN and leave MSP untouched. */                \
                           "ldr    r3, =statistical_sampling_tick\n"                                                   \
                           "bx     r3\n");                                                                             \
        }
#endif
#ifndef PROFILER_IRQ_PRIORITY
    /**
     *     @brief Sampling IRQ priority; defaults to the lowest implemented priority.
     */
    #define PROFILER_IRQ_PRIORITY ((1U << __NVIC_PRIO_BITS) - 1U)
#endif
#endif
