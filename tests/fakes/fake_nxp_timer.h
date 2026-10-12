/* SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: Apache-2.0 */
#ifndef TEST_FAKE_NXP_TIMER_H
#define TEST_FAKE_NXP_TIMER_H
#include <stdint.h>
struct FakeCtimer
{
    uint32_t CTCR, PR, MR[4], MCR, IR, TCR;
};
struct FakeClockControl
{
    uint32_t PSCCTL2;
};
extern struct FakeClockControl fake_clock_control;
struct FakeCtimer *fake_ctimer_access(void);
#define CTIMER4                           fake_ctimer_access()
#define CLKCTL1                           (&fake_clock_control)
#define CTIMER4_IRQn                      4
#define CLKCTL1_PSCCTL2_CT32BIT4_CLK_MASK 1U
#define CTIMER_IR_MR0INT_MASK             1U
#define CTIMER_MCR_MR0I_MASK              1U
#define CTIMER_MCR_MR0R_MASK              2U
#define CTIMER_TCR_CRST_MASK              2U
#define CTIMER_TCR_CEN_MASK               1U
#define kMAIN_CLK_to_CTIMER4              0
#define kCLOCK_Ct32b4                     0
#define kCT32B4_RST_SHIFT_RSTn            0
#define __NVIC_PRIO_BITS                  3
#define __DSB()                           ((void)0)
void CLOCK_AttachClk(int source);
void CLOCK_EnableClock(int gate);
void CLOCK_DisableClock(int gate);
uint32_t CLOCK_GetCtimerClkFreq(unsigned timer);
void RESET_PeripheralReset(int reset);
uint32_t NVIC_GetEnableIRQ(int irq);
void NVIC_SetPriority(int irq, unsigned priority);
void NVIC_ClearPendingIRQ(int irq);
void NVIC_EnableIRQ(int irq);
void NVIC_DisableIRQ(int irq);
#endif
