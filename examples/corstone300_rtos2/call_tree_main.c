/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        call_tree_main.c
 * Description:  CMSIS-RTOS2 dual-thread backtrace test
 *
 * $Date:        2 October 2026
 * $Revision:    V.1.0.6
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/* Application overview
 * Test backtraces across thread switches with RTX or FreeRTOS. A higher-priority
 * controller captures 2 seconds of 2 equal-priority workers, each repeatedly
 * calling a known, non-inlined function tree with its own validation state.
 * Distinct names let the host detect callers incorrectly mixed between threads.
 * Static stacks give the sampling interrupt precise, stable bounds for unwinding.
 *
 * main: start kernel -> controller: create workers, enable capture, sleep 2 s
 *                          |
 *               kernel time-slices these workers
 *                          |
 *       worker  -> run_once  -> A  -> B  -> C  -> D  -> E  -> F
 *       worker1 -> run_once1 -> A1 -> B1 -> C1 -> D1 -> E1 -> F1
 *                          |
 *              TIMER0 samples PC and caller addresses
 *                          v
 *                  statistical_samples
 *                          |
 *       controller wakes -> stop, validate, suspend workers
 *                        -> check sampling stopped while kernel tick continues
 *                        -> export samples.bin, exit simulator
 *
 * PC = Program Counter (instruction address). Semihosting exports the buffer
 * through the simulator to the host filesystem. Host scripts decode it using
 * the matching executable and check the call trees before drawing a flamegraph.
 * The kernel retains ownership of SysTick, PendSV and SVC (tick, context switches
 * and service calls). Sampling uses its own TIMER0 interrupt.
 */

#include "SSE300MPS3.h"
#include "cmsis_os2.h"
#include "profiler_backend.h"
#include "sampling_profiler.h"
#include "syscounter_armv8-m_cntrl_reg_map.h"

/* System Counter Control Register (CNTCR), enable bit (EN).
 * The Board Support Package (BSP) defines this bit only in its driver source. */
#define CNTCR_ENABLE (1UL << 0)

/* Fixed pair of distinct workloads plus 1 controller; 8 KiB per thread stack.
 * Changing the worker count also requires updating the workload functions. */
#define WORKER_COUNT     2U
#define THREAD_COUNT     (WORKER_COUNT + 1U)
#define CONTROLLER_INDEX WORKER_COUNT
#define STACK_WORDS      2048U
#define CAPTURE_SECONDS  2U

#if PROFILER_EXAMPLE_FREERTOS
    #include "FreeRTOS.h"
    #include "task.h"
/* FreeRTOS needs a Task Control Block (TCB), its bookkeeping, plus a stack for each static task. */
static StaticTask_t control_blocks[THREAD_COUNT];
    #define THREAD_CONTROL_BLOCK(index) .cb_mem = &control_blocks[index], .cb_size = sizeof(control_blocks[index]),
#else
    #define THREAD_CONTROL_BLOCK(index)
#endif

extern int run_once(void), validate(void), run_once1(void), validate1(void);
extern void example_exit(uint32_t status);
extern unsigned char __StackLimit[], __StackTop[];

/* Fixed stack storage remains valid for the entire capture. */
__attribute__((aligned(8))) static uint32_t stacks[THREAD_COUNT][STACK_WORDS];
static volatile uint32_t runs[WORKER_COUNT], failures[WORKER_COUNT];

/* Debugger-visible result: 0 = not finished, 1 = success, 2 = failure. */
volatile uint32_t profiler_rtos_example_result;

/** Process Stack Pointer (PSP) selects the interrupted thread's stack.
 * Main Stack Pointer (MSP) serves exception handlers and startup.
 * Permanent stack registry: no task creation/deletion while capturing.
 * TIMER0 has lowest priority, so a kernel context switch completes first.
 * Unknown/kernel PSP allocations are rejected rather than using broad RAM bounds.
 */
int profiler_stack_bounds(uint32_t exc, struct ProfilerStackBounds *bounds)
{
    /* Exception-return bit 2 selects the stack: 0 = main stack, 1 = process stack. */
    if (!(exc & 4U))
    {
        bounds->base = (uintptr_t)__StackLimit;
        bounds->bytes = (uintptr_t)__StackTop - (uintptr_t)__StackLimit;
        return 1;
    }

    /* Find the interrupted task without calling the kernel from the sampling interrupt. */
    uintptr_t sp = __get_PSP();
    for (unsigned i = 0; i < THREAD_COUNT; ++i)
        if (sp >= (uintptr_t)stacks[i] && sp - (uintptr_t)stacks[i] < sizeof(stacks[i]))
        {
            bounds->base = (uintptr_t)stacks[i];
            bounds->bytes = sizeof(stacks[i]);
            return 1;
        }

    /* Unknown stacks must not be read by the unwinder. */
    return 0;
}

/* Run the A-F tree continuously; the kernel preempts this worker to run its peer. */
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

/* Same workload with independent state and A1-F1 symbols in the host report. */
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

#if PROFILER_EXAMPLE_FREERTOS
/** Common application root for the flamegraph.
 * FreeRTOS supplies a synthetic task-return address in LR (Link Register);
 * it is not a real caller, so the host uses worker_entry as the graph base. */
__attribute__((noinline)) static void worker_entry(void *arg)
{
    if ((uintptr_t)arg == 0U)
        worker(0);
    else
        worker1(0);
}

/** Fail the test if a kernel stack check detects corruption. */
void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    example_exit(21U);
}
#endif

/* Arm semihosting operations and normal application termination reason. */
enum
{
    SEMIHOST_SYS_OPEN = 0x01U,
    SEMIHOST_SYS_CLOSE = 0x02U,
    SEMIHOST_SYS_WRITE = 0x05U,
    SEMIHOST_SYS_EXIT_EXTENDED = 0x20U,
    SEMIHOST_ADP_STOPPED_APPLICATION_EXIT = 0x20026U
};

static int semihost(uint32_t operation, const void *arguments)
{
    register uint32_t r0 __asm("r0") = operation;
    register const void *r1 __asm("r1") = arguments;
    /* The simulator handles this breakpoint as a host-service request. */
    __asm volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return (int)r0;
}

static int export_capture(void)
{
    /* Open a binary output file on the host; mode 5 means "wb". */
    const char filename[] = "samples.bin";
    const uint32_t open_args[] = {(uint32_t)filename, 5U, sizeof(filename) - 1U};
    int handle = semihost(SEMIHOST_SYS_OPEN, open_args);
    if (handle < 0)
        return 0;

    /* Export the whole stopped buffer, including unused space. */
    const uint32_t write_args[] = {(uint32_t)handle, (uint32_t)&statistical_samples, sizeof(statistical_samples)};
    int remaining = semihost(SEMIHOST_SYS_WRITE, write_args);

    /* SYS_WRITE returns bytes NOT written; successful export leaves none. */
    const uint32_t close_args[] = {(uint32_t)handle};
    int closed = semihost(SEMIHOST_SYS_CLOSE, close_args);

    return remaining == 0 && closed == 0;
}

void example_exit(uint32_t status)
{
    /* Finish the simulator run: status 0 means success, nonzero means failure. */
    const uint32_t args[] = {SEMIHOST_ADP_STOPPED_APPLICATION_EXIT, status};
    semihost(SEMIHOST_SYS_EXIT_EXTENDED, args);

    /* Fallback if the host returns from the exit request. */
    for (;;)
        __WFI();
}

/** Higher-priority controller starts capture before releasing the 2 workers. */
static void controller(void *arg)
{
    (void)arg;

    /* Give each worker its own stack and the same scheduling priority. */
    const osThreadAttr_t attr[WORKER_COUNT] = {{.name = "A-F",
                                                THREAD_CONTROL_BLOCK(0).attr_bits = osThreadPrivileged,
                                                .stack_mem = stacks[0],
                                                .stack_size = sizeof(stacks[0]),
                                                .priority = osPriorityNormal},
                                               {.name = "A1-F1",
                                                THREAD_CONTROL_BLOCK(1).attr_bits = osThreadPrivileged,
                                                .stack_mem = stacks[1],
                                                .stack_size = sizeof(stacks[1]),
                                                .priority = osPriorityNormal}};

    /* Workers cannot run yet: this controller has higher priority. */
#if PROFILER_EXAMPLE_FREERTOS
    osThreadId_t threads[WORKER_COUNT] = {osThreadNew(worker_entry, (void *)0U, &attr[0]),
                                          osThreadNew(worker_entry, (void *)1U, &attr[1])};
#else
    osThreadId_t threads[WORKER_COUNT] = {osThreadNew(worker, 0, &attr[0]), osThreadNew(worker1, 0, &attr[1])};
#endif
    /* Initialize sampling with recording gated off; failure aborts the test. */
    if (!threads[0] || !threads[1] || !profiler_init())
        example_exit(10);

    uint32_t start = osKernelGetTickCount();

    /* Enable statistical profiler recording. */
    profiler_enable();

    /* Sleep only the controller. The kernel now time-slices the 2 workers. */
    osStatus_t delayed = osDelay(osKernelGetTickFreq() * CAPTURE_SECONDS);

    /* Close the recording window as soon as the controller wakes. */
    profiler_disable();

    /* Check that both workers made progress, produced correct results,
     * and ran for the requested capture duration. */
    uint32_t valid = delayed == osOK && runs[0] && runs[1] && !failures[0] && !failures[1] &&
        osKernelGetTickCount() - start >= osKernelGetTickFreq() * CAPTURE_SECONDS;

    /* Stop the sampling timer and finalize the capture metadata. */
    profiler_stop(runs[0] + runs[1], valid);

    /* Park the workers after capture; leave the kernel tick running. */
    if (osThreadSuspend(threads[0]) != osOK || osThreadSuspend(threads[1]) != osOK)
        valid = 0;

    /* Wait 2 kernel ticks and verify that sampling interrupts have stopped. */
    uint32_t stopped = profiler_sample_ticks();
    if (osDelay(2) != osOK || profiler_sample_ticks() != stopped)
        valid = 0;

    /* Export even a failed capture for inspection. The exit status also covers
     * the post-capture checks, which occur after the header was finalized. */
    profiler_rtos_example_result = valid ? 1U : 2U;
    if (!export_capture())
        example_exit(11);

    example_exit(valid ? 0U : 12U);
}

int main(void)
{
    /* Standalone board setup: start the reference counter used by TIMER0. */
    SystemCoreClockUpdate();
    ((struct cnt_control_base_reg_map_t *)SYSCNTR_CNTRL_BASE_S)->cntcr = CNTCR_ENABLE;
    __DSB();

    /* Initialize kernel services before creating any tasks. */
    if (osKernelInitialize() != osOK)
        example_exit(13);

    /* The controller runs above the worker priority to bound the capture window. */
    const osThreadAttr_t attr = {.name = "controller",
                                 THREAD_CONTROL_BLOCK(CONTROLLER_INDEX).attr_bits = osThreadPrivileged,
                                 .stack_mem = stacks[CONTROLLER_INDEX],
                                 .stack_size = sizeof(stacks[CONTROLLER_INDEX]),
                                 .priority = osPriorityAboveNormal};

    /* Create the controller, then hand execution to the scheduler. */
    if (!osThreadNew(controller, 0, &attr) || osKernelStart() != osOK)
        example_exit(14);

    /* A successfully started kernel should never return here. */
    example_exit(15);
    return 1;
}
