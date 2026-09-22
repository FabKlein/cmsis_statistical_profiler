/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        fake_pmu.h
 * Description:  Mock CMSIS PMU registers and counter access for native tests
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef PROFILER_FAKE_PMU_H
#define PROFILER_FAKE_PMU_H
#define __PMU_PRESENT 1U
#define ARM_PMU_CHAIN 0x1EU
#define PMU_TYPE_NUM_CNTS_Msk 0xFFU
#define PMU_TYPE_SIZE_CNTS_Msk (0x3FU << 8)
#define PMU_TYPE_SIZE_CNTS_Pos 8U
#define PMU_EVCNTR_CNT_Msk 0xFFFFU
#define PMU_AUTHSTATUS_SNID_Msk (3U << 6)
#define PMU_AUTHSTATUS_SNID_Pos 6U
#define PMU_AUTHSTATUS_NSNID_Msk (3U << 2)
#define PMU_AUTHSTATUS_NSNID_Pos 2U
#define PMU_CTRL_ENABLE_Msk 1U
#define PMU_CTRL_CYCCNT_DISABLE_Msk (1U << 5)
struct FakePMU
{
    uint32_t EVCNTR[8], EVTYPER[8], TYPE, AUTHSTATUS, CTRL, CNTENSET, INTENSET, OVSSET;
};
extern struct FakePMU fake_pmu;
extern uint32_t pmu_read_mode, pmu_read_count;
#define PMU (&fake_pmu)
static inline void ARM_PMU_Enable(void) { PMU->CTRL |= 1U; }
static inline void ARM_PMU_Set_EVTYPER(uint32_t n, uint32_t event) { PMU->EVTYPER[n] = event; }
static inline void ARM_PMU_CNTR_Enable(uint32_t bits) { PMU->CNTENSET |= bits; }
static inline void ARM_PMU_CNTR_Disable(uint32_t bits) { PMU->CNTENSET &= ~bits; }
static inline void ARM_PMU_Set_CNTR_IRQ_Disable(uint32_t bits) { PMU->INTENSET &= ~bits; }
static inline void ARM_PMU_Set_CNTR_OVS(uint32_t bits) { PMU->OVSSET &= ~bits; }
static inline uint32_t ARM_PMU_Get_CNTR_OVS(void) { return PMU->OVSSET; }
static inline uint32_t ARM_PMU_Get_EVCNTR(uint32_t n)
{
    ++pmu_read_count;
    uint32_t value = PMU->EVCNTR[n] & 0xFFFFU;
    if (n == 0U && pmu_read_mode)
    {
        ++PMU->EVCNTR[1];
        PMU->EVCNTR[0] = 5U;
        if (pmu_read_mode == 1U)
            pmu_read_mode = 0U; /* 1 rollover, second high/low/high succeeds. */
    }
    return value;
}
#endif
