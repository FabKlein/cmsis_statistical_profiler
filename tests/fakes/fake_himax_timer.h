/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* Native timer API doubles; not SDK headers or a hardware register model. */
#ifndef FAKE_HIMAX_TIMER_H
#define FAKE_HIMAX_TIMER_H

#include "fake_device.h"

#define TIMER4INT_IRQn        4
#define TIMER_ID_4            4
#define TIMER_NO_ERROR        0
#define TIMER_MODE_PERIODICAL 1
#define TIMER_CTRL_CPU        1
#define TIMER_STATE_DC        1

typedef struct
{
    uint32_t period, mode, ctrl, state;
} TIMER_CFG_T;

extern uint32_t fake_himax_enabled, fake_himax_pending, fake_himax_vector;
extern uint32_t fake_himax_vector_calls, fake_himax_enable_calls;
#define NVIC_GetEnableIRQ(irq)           ((void)(irq), fake_himax_enabled)
#define NVIC_EnableIRQ(irq)              ((void)(irq), ++fake_himax_enable_calls, fake_himax_enabled = 1U)
#define NVIC_DisableIRQ(irq)             ((void)(irq), fake_himax_enabled = 0U)
#define NVIC_ClearPendingIRQ(irq)        ((void)(irq), fake_himax_pending = 0U)
#define EPII_NVIC_SetVector(irq, vector) ((void)(irq), ++fake_himax_vector_calls, fake_himax_vector = (vector))

int hx_drv_timer_get_used(int id, uint8_t *used);
int hx_drv_timer_get_clk(int id, uint32_t *hz);
int hx_drv_timer_get_clk_div(int id, uint32_t *divider);
int hx_drv_timer_hw_start(int id, const TIMER_CFG_T *config, void (*callback)(uint32_t));
int hx_drv_timer_hw_stop(int id);
void hx_drv_timer_ClearIRQ(int id);
uint32_t hx_drv_timer_StatusIRQ(int id);

#endif
