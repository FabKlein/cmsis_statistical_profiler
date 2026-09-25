/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        call_tree_main.c
 * Description:  CMSIS-RTX dual-thread backtrace test
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "SSE300MPS3.h"
#include "cmsis_os2.h"
#include "sampling_profiler.h"
#include "sampling_profiler_cortex_m.h"
#include "sampling_profiler_port.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"

extern int run_once(void), validate(void), run_once1(void), validate1(void);
extern void example_exit(uint32_t status);
extern unsigned char __StackLimit[], __StackTop[];
__attribute__((aligned(8))) static uint32_t stacks[3][2048];
static volatile uint32_t runs[2], failures[2];
volatile uint32_t profiler_rtos_example_result;

/** Permanent stack registry: no task creation/deletion while capturing.
 * TIMER0 has lowest priority, so a kernel context switch completes first.
 * Unknown/kernel PSP allocations are rejected rather than using broad RAM bounds.
 */
int profiler_stack_bounds(uint32_t exc, struct ProfilerStackBounds *bounds)
{
    if (!(exc & 4U))
    {
        bounds->base = (uintptr_t)__StackLimit;
        bounds->bytes = (uintptr_t)__StackTop - (uintptr_t)__StackLimit;
        return 1;
    }
    uintptr_t sp = __get_PSP();
    for (unsigned i = 0; i < 3; ++i)
        if (sp >= (uintptr_t)stacks[i] && sp - (uintptr_t)stacks[i] < sizeof(stacks[i]))
        {
            bounds->base = (uintptr_t)stacks[i];
            bounds->bytes = sizeof(stacks[i]);
            return 1;
        }
    return 0;
}

__attribute__((noinline)) static void worker(void *arg)
{
    (void)arg;
    for (;;)
    {
        if (!run_once() || !validate())
            failures[0] = 1;
        ++runs[0];
    }
}
__attribute__((noinline)) static void worker1(void *arg)
{
    (void)arg;
    for (;;)
    {
        if (!run_once1() || !validate1())
            failures[1] = 1;
        ++runs[1];
    }
}

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
/** Higher-priority controller starts capture before releasing the 2 workers. */
static void controller(void *arg)
{
    (void)arg;
    const osThreadAttr_t attr[2] = {{.name = "A-F",
                                     .attr_bits = osThreadPrivileged,
                                     .stack_mem = stacks[0],
                                     .stack_size = sizeof(stacks[0]),
                                     .priority = osPriorityNormal},
                                    {.name = "A1-F1",
                                     .attr_bits = osThreadPrivileged,
                                     .stack_mem = stacks[1],
                                     .stack_size = sizeof(stacks[1]),
                                     .priority = osPriorityNormal}};
    osThreadId_t threads[2] = {osThreadNew(worker, 0, &attr[0]), osThreadNew(worker1, 0, &attr[1])};
    if (!threads[0] || !threads[1] || !sampling_profiler_init())
        example_exit(10);
    uint32_t start = osKernelGetTickCount();
    sampling_profiler_enable();
    osStatus_t delayed = osDelay(osKernelGetTickFreq() * 2U);
    sampling_profiler_disable();
    uint32_t valid = delayed == osOK && runs[0] && runs[1] && !failures[0] && !failures[1] &&
        osKernelGetTickCount() - start >= osKernelGetTickFreq() * 2U;
    sampling_profiler_stop(runs[0] + runs[1], valid);
    if (osThreadSuspend(threads[0]) != osOK || osThreadSuspend(threads[1]) != osOK)
        valid = 0;
    uint32_t stopped = profiler_port_ticks();
    if (osDelay(2) != osOK || profiler_port_ticks() != stopped)
        valid = 0;
    profiler_rtos_example_result = valid ? 1U : 2U;
    if (!export_capture())
        example_exit(11);
    example_exit(valid ? 0U : 12U);
}

int main(void)
{
    SystemCoreClockUpdate();
    ((struct cnt_control_base_reg_map_t *)0x58100000UL)->cntcr = 1U;
    __DSB();
    if (osKernelInitialize() != osOK)
        example_exit(13);
    const osThreadAttr_t attr = {.name = "controller",
                                 .attr_bits = osThreadPrivileged,
                                 .stack_mem = stacks[2],
                                 .stack_size = sizeof(stacks[2]),
                                 .priority = osPriorityAboveNormal};
    if (!osThreadNew(controller, 0, &attr) || osKernelStart() != osOK)
        example_exit(14);
    example_exit(15);
    return 1;
}
