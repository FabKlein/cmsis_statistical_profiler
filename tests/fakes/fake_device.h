/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        fake_device.h
 * Description:  Mock CMSIS device registers and intrinsics for native tests
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef TEST_FAKE_DEVICE_H
#define TEST_FAKE_DEVICE_H
#include <stdint.h>

#ifndef __CORTEX_M
    #define __CORTEX_M 55U
#endif
#ifndef TEST_NONSECURE
    #define __ARM_FEATURE_CMSE 3
#endif
#ifndef __FPU_PRESENT
    #define __FPU_PRESENT 1U
#endif
#ifndef __DCACHE_PRESENT
    #define __DCACHE_PRESENT 1U
#endif
#define SysTick_CTRL_ENABLE_Msk 1U
#define SysTick_CTRL_TICKINT_Msk 2U
#define SysTick_CTRL_CLKSOURCE_Msk 4U
#define SysTick_LOAD_RELOAD_Msk 0xFFFFFFU
#define __NVIC_PRIO_BITS 3U
#define SysTick_IRQn (-1)
#define SCB_ICSR_PENDSTCLR_Msk (1U << 25)
#define DCB_DEMCR_TRCENA_Msk (1U << 24)
#define DWT_CTRL_NOCYCCNT_Msk (1U << 25)
#define DWT_CTRL_CYCCNTENA_Msk 1U
#define SCB_CCR_DC_Msk (1U << 16)
#define EXC_RETURN_S 0x40U
#define EXC_RETURN_DCRS 0x20U
#define EXC_RETURN_MODE 8U
#define EXC_RETURN_ES 1U
#define xPSR_T_Msk (1U << 24)
#define xPSR_ISR_Msk 0x1FFU

struct FakeMEMSYSCTL
{
    uint32_t DTCMCR;
};
extern struct FakeMEMSYSCTL fake_memsysctl;
#define MEMSYSCTL (&fake_memsysctl)
#define MEMSYSCTL_DTCMCR_EN_Msk 1U
#define MEMSYSCTL_DTCMCR_SZ_Pos 3U
#define MEMSYSCTL_DTCMCR_SZ_Msk (15U << MEMSYSCTL_DTCMCR_SZ_Pos)

struct FakeSysTick
{
    uint32_t CTRL, LOAD, VAL;
};
struct FakeDWT
{
    uint32_t CTRL, CYCCNT;
};
struct FakeDCB
{
    uint32_t DEMCR;
};
struct FakeSCB
{
    uint32_t CCR, ICSR;
};
extern struct FakeSysTick fake_systick;
extern struct FakeDWT fake_dwt;
extern struct FakeDCB fake_dcb;
extern struct FakeSCB fake_scb;
extern uint32_t SystemCoreClock, fake_stack[16];
extern int fake_counter_runs;
extern uint32_t fake_primask, fake_priority;
#define SysTick (&fake_systick)
#define DWT (&fake_dwt)
#define DCB (&fake_dcb)
#define SCB (&fake_scb)
#define __DSB() ((void)0)
#define __ISB() ((void)0)
#define __DMB() ((void)0)
#define __NOP() (fake_dwt.CYCCNT += fake_counter_runs ? 1U : 0U)
#define __get_PRIMASK() fake_primask
#define __disable_irq() (fake_primask = 1U)
#define __set_PRIMASK(value) (fake_primask = (value))
#define NVIC_GetPriority(irq) ((void)(irq), fake_priority)
#define NVIC_SetPriority(irq, priority) ((void)(irq), fake_priority = (priority))
void SCB_CleanDCache_by_Addr(void *address, int32_t bytes);
#ifdef TEST_PMU
    #include "fake_pmu.h"
#endif
#endif
