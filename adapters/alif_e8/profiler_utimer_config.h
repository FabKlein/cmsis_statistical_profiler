/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_utimer_config.h
 * Description:  Alif per-image UTIMER channel and interrupt selection
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file profiler_utimer_config.h
 * @brief Map each image's reserved UTIMER channel to its overflow vector.
 */
#ifndef PROFILER_ALIF_UTIMER_CONFIG_H
#define PROFILER_ALIF_UTIMER_CONFIG_H

#if defined(RTSS_HP) && defined(RTSS_HE)
    #error "Select only one Alif RTSS core per firmware image"
#endif

/** @brief UTIMER channel 0..11. Defaults to HP=0 or HE=1; override per image. */
#ifndef PROFILER_ALIF_UTIMER_CHANNEL
    #if defined(RTSS_HP)
        #define PROFILER_ALIF_UTIMER_CHANNEL 0
    #elif defined(RTSS_HE)
        #define PROFILER_ALIF_UTIMER_CHANNEL 1
    #else
        #error "Select RTSS_HP/RTSS_HE or define PROFILER_ALIF_UTIMER_CHANNEL"
    #endif
#endif

#if PROFILER_ALIF_UTIMER_CHANNEL == 0
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ7_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ7Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 1
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ15_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ15Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 2
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ23_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ23Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 3
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ31_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ31Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 4
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ39_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ39Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 5
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ47_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ47Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 6
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ55_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ55Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 7
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ63_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ63Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 8
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ71_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ71Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 9
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ79_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ79Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 10
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ87_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ87Handler
#elif PROFILER_ALIF_UTIMER_CHANNEL == 11
    #define PROFILER_ALIF_TIMER_IRQ UTIMER_IRQ95_IRQn
    #define PROFILER_ALIF_TIMER_HANDLER UTIMER_IRQ95Handler
#else
    #error "PROFILER_ALIF_UTIMER_CHANNEL must be 0..11 for Ensemble E8"
#endif
#endif
