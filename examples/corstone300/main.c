/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        main.c
 * Description:  Corstone-300 capture and workload validation example
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "SSE300MPS3.h"
#include "profile_workload.h"
#include "sampling_profiler.h"
#include "sampling_profiler_cortex_m.h"
#include "sampling_profiler_port.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"

#if PROFILER_PRECISE_STACK_BOUNDS
    #ifdef __ARMCC_VERSION
extern unsigned char __StackLimit[] __asm("Image$$ARM_LIB_STACK$$ZI$$Base");
extern unsigned char __StackTop[] __asm("Image$$ARM_LIB_STACK$$ZI$$Limit");
    #else
extern unsigned char __StackLimit[], __StackTop[];
    #endif
#endif

volatile uint32_t profiler_example_result;
#ifndef PROFILER_EXAMPLE_CALL_TREE
static volatile uint32_t result;
#endif
volatile uint32_t application_millis;
void SysTick_Handler(void) { ++application_millis; }

#ifdef PROFILER_EXAMPLE_CALL_TREE
extern int run_once(void);
extern int validate(void);
#else
    #ifdef PROFILER_EXAMPLE_FLOAT
static volatile float fp_result;
    #endif

__attribute__((noinline)) static int run_once(void)
{
    uint32_t value = 0x12345678U;
    for (uint32_t i = 0; i < 10000U; ++i)
        value = value * 1664525U + 1013904223U;
    result = value;
    #ifdef PROFILER_EXAMPLE_FLOAT
    float fp = 1.0f;
    for (uint32_t i = 0; i < 10000U; ++i)
        fp = fp * 0.5f + 1.0f;
    fp_result = fp;
    #endif
    return 1;
}

static int validate(void)
{
    #ifdef PROFILER_EXAMPLE_FLOAT
    if (fp_result != 2.0f)
        return 0;
    #endif
    return result == 0xF0D18BC8U;
}

#endif

__attribute__((used, noinline)) static int capture(void) { return profile_workload(run_once, validate); }

#ifdef PROFILER_EXAMPLE_PSP
__attribute__((used, aligned(8))) static uint32_t psp_stack[1024];
__attribute__((naked)) static int capture_on_psp(void)
{
    /* Switch stacks only at this assembly boundary. R4 preserves CONTROL;
     * the saved LR and R4 stay on MSP until the C capture function returns. */
    __asm volatile("push {r4, lr}\n"
                   "mrs r4, control\n"
                   "ldr r1, =psp_stack + 4096\n"
                   "msr psp, r1\n"
                   "orr r1, r4, #2\n"
                   "msr control, r1\n"
                   "isb\n"
                   "bl capture\n"
                   "msr control, r4\n"
                   "isb\n"
                   "pop {r4, pc}\n");
}
#endif

#ifdef PROFILER_FVP_SEMIHOSTING
/* Export only AFTER capture. On FPGA use the ordinary debugger dump instead. */
static int semihost(uint32_t operation, const void *arguments)
{
    register uint32_t r0 __asm("r0") = operation;
    register const void *r1 __asm("r1") = arguments;
    __asm volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return (int)r0;
}

static int export_capture(void)
{
    const char filename[] = "samples.bin";
    const uint32_t open_args[] = {(uint32_t)filename, 5U, sizeof(filename) - 1U};
    int handle = semihost(0x01U, open_args);
    if (handle < 0)
        return 0;
    const uint32_t write_args[] = {(uint32_t)handle, (uint32_t)&statistical_samples, sizeof(statistical_samples)};
    int remaining = semihost(0x05U, write_args);
    const uint32_t close_args[] = {(uint32_t)handle};
    int closed = semihost(0x02U, close_args);
    return remaining == 0 && closed == 0;
}

void example_exit(uint32_t status)
{
    const uint32_t args[] = {0x20026U, status};
    semihost(0x20U, args);
    for (;;)
        __WFI();
}
#else
void example_exit(uint32_t status)
{
    (void)status;
    for (;;)
        __WFI();
}
#endif

#if PROFILER_PRECISE_STACK_BOUNDS
int profiler_stack_bounds(uint32_t exc, struct ProfilerStackBounds *bounds)
{
    if (exc & 4U)
    {
    #ifdef PROFILER_EXAMPLE_PSP
        bounds->base = (uintptr_t)psp_stack;
        bounds->bytes = sizeof(psp_stack);
        return 1;
    #else
        return 0;
    #endif
    }
    bounds->base = (uintptr_t)__StackLimit;
    bounds->bytes = (uintptr_t)__StackTop - (uintptr_t)__StackLimit;
    return 1;
}
#endif

int main(void)
{
    /* Application owns SysTick. TIMER0 sampling must leave it untouched. */
    SystemCoreClockUpdate();
    /* Minimal board setup: start the shared reference counter unscaled.
     * Real applications supply this as part of their existing clock setup. */
    struct cnt_control_base_reg_map_t *counter = (void *)0x58100000UL;
    counter->cntcr = 1U;
    __DSB();
    if (SysTick_Config(SystemCoreClock / 1000U))
        example_exit(6U);
    for (uint32_t attempt = 0; attempt < PROFILER_EXAMPLE_CAPTURES; ++attempt)
    {
        uint32_t started = application_millis;
        uint32_t sampling_started = profiler_port_millis();
        uint32_t load = SysTick->LOAD;
        uint32_t priority = NVIC_GetPriority(SysTick_IRQn);
#ifdef PROFILER_EXAMPLE_PSP
        profiler_example_result = (uint32_t)capture_on_psp();
#else
        profiler_example_result = (uint32_t)capture();
#endif
        uint32_t application_elapsed = application_millis - started;
        uint32_t sampling_elapsed = profiler_port_millis() - sampling_started;
        uint32_t period_ms =
            (uint32_t)(((uint64_t)statistical_samples.header.timer_period * 1000U + PROFILER_TIMER_CLOCK_HZ - 1U) /
                       PROFILER_TIMER_CLOCK_HZ);
        if (SysTick->LOAD != load || NVIC_GetPriority(SysTick_IRQn) != priority || (SysTick->CTRL & 7U) != 7U ||
            application_elapsed + 2U < sampling_elapsed || application_elapsed > sampling_elapsed + period_ms + 5U ||
            NVIC_GetEnableIRQ(TIMER0_IRQn))
            example_exit(7U);
        if (!profiler_example_result)
            example_exit(3U);
        uint32_t stopped_ticks = profiler_port_ticks();
        uint32_t stopped_ms = application_millis;
        while (application_millis - stopped_ms < 3U)
            __WFI();
        if (profiler_port_ticks() != stopped_ticks)
            example_exit(8U);
    }
#ifdef PROFILER_FVP_SEMIHOSTING
    if (!export_capture())
        example_exit(2U);
#endif
    example_exit(profiler_example_result ? 0U : 3U);
    return 0;
}
