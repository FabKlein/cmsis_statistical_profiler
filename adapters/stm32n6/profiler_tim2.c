/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_tim2.c
 * Description:  STM32N6 TIM2 sampling adapter
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_cortex_m.h"
#include "stm32n6xx_hal.h"
#include "stm32n6xx_hal_rcc.h"
#include "stm32n6xx_hal_rcc_ex.h"

/* Reserve the entire 32-bit TIM2, including its interrupt, for sampling. */
_Static_assert(PROFILER_IRQ_PRIORITY < (1U << __NVIC_PRIO_BITS), "Invalid sampling IRQ priority");
static uint32_t owned;
int profiler_timer_init(struct ProfilerClock *clock)
{
    uint32_t hz = HAL_RCCEx_GetTIMGFreq();
    uint32_t period = profiler_timer_period(hz, UINT32_MAX);
    if (!period || NVIC_GetTargetState(TIM2_IRQn) ||
        (!owned && (__HAL_RCC_TIM2_IS_CLK_ENABLED() || NVIC_GetEnableIRQ(TIM2_IRQn))))
        return 0;
    __HAL_RCC_TIM2_CLK_ENABLE();
    owned = 1U;
    profiler_timer_stop();
    __HAL_RCC_TIM2_FORCE_RESET();
    __HAL_RCC_TIM2_RELEASE_RESET();
    TIM2->PSC = 0U;
    TIM2->ARR = period - 1U;
    TIM2->EGR = TIM_EGR_UG;
    TIM2->SR = 0U;
    NVIC_SetPriority(TIM2_IRQn, PROFILER_IRQ_PRIORITY);
    clock->timer_hz = hz;
    clock->timer_period = period;
    return 1;
}
void profiler_timer_start(void)
{
    TIM2->CNT = 0U;
    TIM2->SR = 0U;
    TIM2->DIER = TIM_DIER_UIE;
    NVIC_ClearPendingIRQ(TIM2_IRQn);
    NVIC_EnableIRQ(TIM2_IRQn);
    TIM2->CR1 = TIM_CR1_CEN;
}
void profiler_timer_stop(void)
{
    if (!owned)
        return;
    NVIC_DisableIRQ(TIM2_IRQn);
    TIM2->CR1 = 0U;
    TIM2->DIER = 0U;
    TIM2->SR = 0U;
    NVIC_ClearPendingIRQ(TIM2_IRQn);
}
int profiler_timer_ack(void)
{
    if (!owned || !(TIM2->SR & TIM_SR_UIF))
        return 0;
    TIM2->SR = ~TIM_SR_UIF;
    __DSB();
    return 1;
}
PROFILER_DEFINE_IRQ_HANDLER(TIM2_IRQHandler)
