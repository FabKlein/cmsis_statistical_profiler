/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        call_tree_startup.c
 * Description:  Corstone-300 startup and interrupt vector table
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "SSE300MPS3.h"

#ifdef __ARMCC_VERSION
extern uint32_t __StackTop __asm("Image$$ARM_LIB_STACK$$ZI$$Limit");
extern void __main(void);
#else
extern uint32_t __StackTop, __data_start__, __data_end__, __data_load__, __bss_start__, __bss_end__;
#endif
extern void SysTick_Handler(void);
extern void SVC_Handler(void);
extern void PendSV_Handler(void);
extern void TFM_TIMER0_IRQ_Handler(void);
extern int main(void);
extern void example_exit(uint32_t status);

static void Default_Handler(void) { example_exit(4U); }

void Reset_Handler(void)
{
#ifdef __ARMCC_VERSION
    SystemInit();
    __main(); /* Arm runtime initializes scatter-loaded data and calls main. */
#else
    uint32_t *source = &__data_load__;
    for (uint32_t *dest = &__data_start__; dest < &__data_end__; ++dest)
        *dest = *source++;
    for (uint32_t *dest = &__bss_start__; dest < &__bss_end__; ++dest)
        *dest = 0;
    SystemInit();
    (void)main();
#endif
    example_exit(5U);
}

__attribute__((section(".vectors"), used, aligned(2048)))
const VECTOR_TABLE_Type __VECTOR_TABLE[496] = {(VECTOR_TABLE_Type)&__StackTop,
                                               Reset_Handler,
                                               [2 ... 10] = Default_Handler,
                                               [11] = SVC_Handler,
                                               [12 ... 13] = Default_Handler,
                                               [14] = PendSV_Handler,
                                               [15] = SysTick_Handler,
                                               [16 ... 18] = Default_Handler,
                                               [19] = TFM_TIMER0_IRQ_Handler,
                                               [20 ... 495] = Default_Handler};
