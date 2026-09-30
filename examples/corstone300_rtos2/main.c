/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        main.c
 * Description:  Corstone-300 CMSIS-RTOS2 sampling integration illustration
 *
 * $Date:        30 September 2026
 * $Revision:    V.1.0.3
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/* Application overview
 * Demonstrate statistical profiling with a Real-Time Operating System (RTOS).
 * A higher-priority controller records about 250 ms of 2 workers performing
 * different repeatable calculations. Each worker checks its result and yields
 * to the other. Keeping them ready avoids idle sleep stopping the cycle counter.
 * After capture, check worker progress and that sampling stops while RTOS time
 * continues. Break at profiler_rtos_capture_complete() to inspect the result
 * and export statistical_samples with the debugger.
 *
 * main: initialize clocks and kernel
 *   |
 *   +--> controller: create workers, start capture, sleep ~250 ms
 *          |                                      |
 *          |     worker_a <--- yield ---> worker_b |
 *          |        multiply/add          XOR/shift
 *          |                    |                 |
 *          |       TIMER0 interrupt samples PCs   |
 *          |                    v                 |
 *          |           statistical_samples        |
 *          +<-------------- wake -----------------+
 *          |
 *          +--> stop capture, validate, suspend workers
 *          +--> verify sampling stopped; signal debugger
 *
 */

#include "SSE300MPS3.h"
#include "cmsis_os2.h"
#include "sampling_profiler.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"

/* System Counter Control Register (CNTCR), enable bit (EN).
 * The Board Support Package (BSP) defines this bit only in its driver source. */
#define CNTCR_ENABLE (1UL << 0)

/* 2 workload tasks plus 1 controller; each stack has 512 uint32_t words (2 KiB).
 * Changing the worker count also requires updating the workload functions. */
#define WORKER_COUNT 2U
#define STACK_WORDS 512U

/* The RTOS owns SysTick, PendSV and SVC. This example defines none of them.
 * Supply an RTOS-enabled startup, kernel configuration and linker from your BSP.
 * Run this secure example with privileged threads and no low-power tick stopping. */
__attribute__((aligned(8))) static uint32_t controller_stack[STACK_WORDS];
__attribute__((aligned(8))) static uint32_t worker_stacks[WORKER_COUNT][STACK_WORDS];
static volatile uint32_t runs[WORKER_COUNT], failures[WORKER_COUNT];
/* 0 = not complete, 1 = success, 2 = failure; inspect at the completion hook. */
volatile uint32_t profiler_rtos_example_result;

__attribute__((used, noinline)) void profiler_rtos_capture_complete(void) { __DSB(); }

static void failed(void)
{
    profiler_rtos_example_result = 2U;
    profiler_rtos_capture_complete();
    for (;;)
        __WFI();
}

__attribute__((noinline)) static void worker_a(void *argument)
{
    (void)argument;
    for (;;)
    {
        uint32_t value = 0x12345678U;
        for (uint32_t i = 0; i < 10000U; ++i)
            value = value * 1664525U + 1013904223U;
        if (value != 0xF0D18BC8U)
            failures[0] = 1U;
        ++runs[0];
        if (osThreadYield() != osOK)
            failures[0] = 1U;
    }
}

__attribute__((noinline)) static void worker_b(void *argument)
{
    (void)argument;
    for (;;)
    {
        uint32_t value = 0x12345678U;
        for (uint32_t i = 0; i < 10000U; ++i)
        {
            value ^= value << 13;
            value ^= value >> 17;
            value ^= value << 5;
        }
        if (value != 0x65CBD6D6U)
            failures[1] = 1U;
        ++runs[1];
        if (osThreadYield() != osOK)
            failures[1] = 1U;
    }
}

static void controller(void *argument)
{
    (void)argument;
    const osThreadAttr_t attributes[WORKER_COUNT] = {{.name = "worker_a",
                                                      .stack_mem = worker_stacks[0],
                                                      .stack_size = sizeof(worker_stacks[0]),
                                                      .priority = osPriorityNormal},
                                                     {.name = "worker_b",
                                                      .stack_mem = worker_stacks[1],
                                                      .stack_size = sizeof(worker_stacks[1]),
                                                      .priority = osPriorityNormal}};
    osThreadId_t workers[WORKER_COUNT];
    workers[0] = osThreadNew(worker_a, NULL, &attributes[0]);
    workers[1] = osThreadNew(worker_b, NULL, &attributes[1]);
    if (!workers[0] || !workers[1])
        failed();
    /* Controller has higher priority: neither worker runs until osDelay below.
     * Both workers stay ready and yield to each other, avoiding idle sleep that
     * could stop DWT and invalidate its relationship with TIMER0 timestamps. */
    uint32_t hz = osKernelGetTickFreq();
    if (!hz || !profiler_init())
        failed();
    uint32_t duration = (uint32_t)(((uint64_t)hz + 3U) / 4U); /* ~250 ms */
    uint32_t started = osKernelGetTickCount();

    profiler_enable();
    osStatus_t delay_status = osDelay(duration);
    profiler_disable();

    uint32_t elapsed = osKernelGetTickCount() - started;
    uint32_t valid = delay_status == osOK && elapsed >= duration && runs[0] && runs[1] && !failures[0] && !failures[1];

    profiler_stop(runs[0] + runs[1], valid);

    /* Suspend only our workers after capture; the RTOS clock remains active. */
    if (osThreadSuspend(workers[0]) != osOK || osThreadSuspend(workers[1]) != osOK)
        valid = 0U;
    uint32_t stopped_ticks = profiler_sample_ticks();
    if (osDelay(2U) != osOK || profiler_sample_ticks() != stopped_ticks)
        valid = 0U;
    profiler_rtos_example_result = valid ? 1U : 2U;

    profiler_rtos_capture_complete(); /* Break here and dump statistical_samples. */
    for (;;)
        osDelay(hz);
}

int main(void)
{
    /* Startup must already have initialized memory and called SystemInit(). */
    SystemCoreClockUpdate();
    /* Standalone example board setup: reserve/start the shared reference counter
     * unscaled, before starting the kernel. Do not overwrite an existing clock
     * setup when incorporating this illustration into a larger application. */
    struct cnt_control_base_reg_map_t *counter = (void *)SYSCNTR_CNTRL_BASE_S;
    counter->cntcr = CNTCR_ENABLE;
    __DSB();
    if (osKernelInitialize() != osOK)
        failed();
    const osThreadAttr_t attributes = {.name = "profiler_controller",
                                       .stack_mem = controller_stack,
                                       .stack_size = sizeof(controller_stack),
                                       .priority = osPriorityAboveNormal};
    if (!osThreadNew(controller, NULL, &attributes) || osKernelStart() != osOK)
        failed();
    failed(); /* A successfully started kernel does not return here. */
    return 1;
}
