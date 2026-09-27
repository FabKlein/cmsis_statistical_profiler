/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        FreeRTOSConfig.h
 * Description:  Secure-only Corstone-300 dual-worker test configuration
 *
 * $Date:        27 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 * -------------------------------------------------------------------- */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include "SSE300MPS3.h"

/* 1 core, privileged tasks, no Secure/Non-secure task transitions. */
#define configNUMBER_OF_CORES 1
#define configUSE_CORE_AFFINITY 0
#define configRUN_FREERTOS_SECURE_ONLY 1
#define configENABLE_TRUSTZONE 0
#define configENABLE_MPU 0
#define configENABLE_FPU 1
#define configENABLE_MVE 0
#define configENABLE_PAC 0
#define configENABLE_BTI 0

/* The CMSIS wrapper owns SysTick_Handler and forwards ticks to the port. */
#define SysTick_Handler xPortSysTickHandler

/* CMSIS-RTOS2 priority values map directly to FreeRTOS priorities. */
#define configCPU_CLOCK_HZ (SystemCoreClock)
#define configTICK_RATE_HZ 1000U
#define configMAX_PRIORITIES 56
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 0
#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configUSE_TICKLESS_IDLE 0
#define configUSE_16_BIT_TICKS 0
#define configKERNEL_INTERRUPT_PRIORITY 255
#define configMAX_SYSCALL_INTERRUPT_PRIORITY 128

/* Application task stacks/TCBs are static; kernel tasks use kernel-owned storage. */
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 1
#define configKERNEL_PROVIDED_STATIC_MEMORY 1
#define configMINIMAL_STACK_SIZE 256U
#define configTOTAL_HEAP_SIZE (16U * 1024U)
#define configCHECK_FOR_STACK_OVERFLOW 2

/* Features required by the pack's CMSIS-RTOS2 wrapper. */
#define configUSE_TIMERS 1
#define configTIMER_TASK_PRIORITY 2
#define configTIMER_TASK_STACK_DEPTH 256U
#define configTIMER_QUEUE_LENGTH 5
#define configUSE_MUTEXES 1
#define configUSE_RECURSIVE_MUTEXES 1
#define configUSE_COUNTING_SEMAPHORES 1
#define configUSE_TASK_NOTIFICATIONS 1
#define configUSE_TRACE_FACILITY 1
#define INCLUDE_xSemaphoreGetMutexHolder 1
#define INCLUDE_vTaskDelay 1
#define INCLUDE_xTaskDelayUntil 1
#define INCLUDE_vTaskDelete 1
#define INCLUDE_xTaskGetCurrentTaskHandle 1
#define INCLUDE_xTaskGetSchedulerState 1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define INCLUDE_uxTaskPriorityGet 1
#define INCLUDE_vTaskPrioritySet 1
#define INCLUDE_eTaskGetState 1
#define INCLUDE_vTaskSuspend 1
#define INCLUDE_xTaskAbortDelay 1
#define INCLUDE_xTimerPendFunctionCall 1

/* Fail FVP promptly instead of spinning forever on a kernel assertion. */
extern void example_exit(uint32_t status);
#define configASSERT(condition)                                                                                        \
    do                                                                                                                 \
    {                                                                                                                  \
        if (!(condition))                                                                                              \
            example_exit(20U);                                                                                         \
    } while (0)

#endif
