/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_config.h
 * Description:  Board-independent capture configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_config.h
 * @brief Board-independent capture configuration.
 *
 * @par PROFILER_USER_CONFIG
 * Optional quoted application configuration header, included before board defaults.
 */

/**
 * @def PROFILER_SAMPLING_ENABLED
 * @brief Nonzero enables frame collection in the sampling ISR; default 1.
 */
/**
 * @def PROFILER_SAMPLE_BUFFER_BYTES
 * @brief Allocation budget including header and records; default 32 KiB, rounded down to words.
 */
/**
 * @def PROFILER_SAMPLE_HZ
 * @brief Requested sampling frequency in Hz; default 1000. Adapter reports the actual period.
 */
/**
 * @def PROFILER_BUFFER_ATTRIBUTES
 * @brief Capture storage attributes; defaults to 32-byte alignment in ordinary BSS.
 */
/**
 * @def PROFILER_TIMESTAMP_CUSTOM
 * @brief Set to 1 to supply timestamp hooks instead of DWT CYCCNT; default 0.
 */
/**
 * @def PROFILER_PRECISE_STACK_BOUNDS
 * @brief Set to 1 to require the ISR-safe precise stack bounds hook; default 0.
 */
/**
 * @def PROFILER_PMU_ENABLE
 * @brief Set to 1 to request 2 32-bit PMU events; default 0. Unavailable PMU uses compact records.
 */
/**
 * @def PROFILER_PMU_EVENT0
 * @brief First architectural event ID; default 0x0003, L1 data cache refill.
 */
/**
 * @def PROFILER_PMU_EVENT1
 * @brief Second architectural event ID; default 0x0024, backend stall.
 */

#ifndef PROFILER_CONFIG_H
#define PROFILER_CONFIG_H

/* Application settings, followed by the shared board configuration contract. */
#ifdef PROFILER_USER_CONFIG
    #include PROFILER_USER_CONFIG
#endif
#include "profiler_board_config.h"

#ifndef PROFILER_SAMPLING_ENABLED
    #define PROFILER_SAMPLING_ENABLED 1
#endif
#ifndef PROFILER_SAMPLE_BUFFER_BYTES
    #define PROFILER_SAMPLE_BUFFER_BYTES (32U * 1024U)
#endif
#ifndef PROFILER_SAMPLE_HZ
    #define PROFILER_SAMPLE_HZ 1000U
#endif
/* Ordinary BSS by default; an adapter may opt into a dedicated section. */
#ifndef PROFILER_BUFFER_ATTRIBUTES
    #define PROFILER_BUFFER_ATTRIBUTES __attribute__((aligned(32)))
#endif

/* Select a board-provided free-running timestamp counter instead of DWT. */
#ifndef PROFILER_TIMESTAMP_CUSTOM
    #define PROFILER_TIMESTAMP_CUSTOM 0
#endif

/* Optional adapter hook narrows the readable RAM whitelist to 1 stack. */
#ifndef PROFILER_PRECISE_STACK_BOUNDS
    #define PROFILER_PRECISE_STACK_BOUNDS 0
#endif

/* Optional PMU event snapshots; raw architectural event IDs keep the core
 * independent of device headers. The backend uses CMSIS PMU functions. */
#ifndef PROFILER_PMU_ENABLE
    #define PROFILER_PMU_ENABLE 0
#endif
#ifndef PROFILER_PMU_EVENT0
    #define PROFILER_PMU_EVENT0 0x0003U /* ARM_PMU_L1D_CACHE_REFILL */
#endif
#ifndef PROFILER_PMU_EVENT1
    #define PROFILER_PMU_EVENT1 0x0024U /* ARM_PMU_STALL_BACKEND */
#endif

#endif
