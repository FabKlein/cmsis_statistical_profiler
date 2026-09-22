/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        fake_alif_timer.h
 * Description:  Mock shared Alif timer and per-core interrupt state
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 * -------------------------------------------------------------------- */

#ifndef FAKE_ALIF_TIMER_H
#define FAKE_ALIF_TIMER_H
#include <stdint.h>
#define __NVIC_PRIO_BITS 3U
#define UTIMER_IRQ7_IRQn 384
#define UTIMER_IRQ15_IRQn 392
#define UTIMER_IRQ23_IRQn 400
#define UTIMER_IRQ31_IRQn 408
#define UTIMER_IRQ39_IRQn 416
#define UTIMER_IRQ47_IRQn 424
#define UTIMER_IRQ55_IRQn 432
#define UTIMER_IRQ63_IRQn 440
#define UTIMER_IRQ71_IRQn 448
#define UTIMER_IRQ79_IRQn 456
#define UTIMER_IRQ87_IRQn 464
#define UTIMER_IRQ95_IRQn 472

struct FakeAlifChannel
{
    uint32_t UTIMER_START_0_SRC, UTIMER_STOP_0_SRC, UTIMER_CLEAR_0_SRC;
    uint32_t UTIMER_START_1_SRC, UTIMER_STOP_1_SRC, UTIMER_CLEAR_1_SRC;
    uint32_t UTIMER_CNTR_CTRL, UTIMER_BUF_OP_CTRL;
    uint32_t UTIMER_COMPARE_CTRL_A, UTIMER_COMPARE_CTRL_B;
    uint32_t UTIMER_CNTR, UTIMER_CNTR_PTR;
    uint32_t UTIMER_CHAN_INTERRUPT, UTIMER_CHAN_INTERRUPT_MASK, UTIMER_CHAN_STATUS;
};
struct FakeAlifTimer
{
    uint32_t UTIMER_GLB_CLOCK_ENABLE, UTIMER_GLB_CNTR_RUNNING;
    uint32_t UTIMER_GLB_CNTR_START, UTIMER_GLB_CNTR_STOP, UTIMER_GLB_CNTR_CLEAR;
    struct FakeAlifChannel UTIMER_CHANNEL_CFG[12];
};
extern struct FakeAlifTimer fake_timer;
extern uint32_t fake_enabled[480], fake_pending[480], fake_priority[480], fake_target[480];
#define UTIMER (&fake_timer)
#define NVIC_GetTargetState(irq) (fake_target[irq])
#define NVIC_GetEnableIRQ(irq) (fake_enabled[irq])
#define NVIC_EnableIRQ(irq) (fake_enabled[irq] = 1U)
#define NVIC_DisableIRQ(irq) (fake_enabled[irq] = 0U)
#define NVIC_ClearPendingIRQ(irq) (fake_pending[irq] = 0U)
#define NVIC_SetPriority(irq, priority) (fake_priority[irq] = (priority))
#define __DSB() ((void)0)
#endif
