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
 * $Date:        5 October 2026
 * $Revision:    V.1.0.3
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_config.h
 * @brief Board-independent capture configuration.
 *
 * @par PROFILER_USER_CONFIG
 * Optional quoted application configuration header, included before optional defaults.
 *
 * @par PROFILER_DEVICE_HEADER
 * Required quoted CMSIS device header selected by the board layer or application.
 */

/**
 * @def PROFILER_SAMPLING_ENABLED
 * @brief Nonzero enables frame collection in the sampling ISR; default 1.
 */
/**
 * @def PROFILER_SAMPLE_BUFFER_BYTES
 * @brief Allocation budget including header and records; default 64 KiB, rounded down to words.
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
 * @def PROFILER_PMU_COUNT
 * @brief Number of 32-bit PMU events, 0-4; default 0 (disabled). Unavailable PMU uses compact records.
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

/* Application settings, followed by required target and stack-memory checks. */
#ifdef PROFILER_USER_CONFIG
    #include PROFILER_USER_CONFIG
#endif
#ifndef PROFILER_DEVICE_HEADER
    #error "Select a board layer or define PROFILER_DEVICE_HEADER to your CMSIS device header"
#endif
#include "profiler_stack_regions.h"

#ifndef PROFILER_SAMPLING_ENABLED
    #define PROFILER_SAMPLING_ENABLED 1
#endif
#ifndef PROFILER_SAMPLE_BUFFER_BYTES
    #define PROFILER_SAMPLE_BUFFER_BYTES (64U * 1024U)
#endif
#ifndef PROFILER_SAMPLE_HZ
    #define PROFILER_SAMPLE_HZ 1000U
#endif
/* Optional independent companion-device sampler called once per acknowledged
 * timer interrupt, before CPU frame validation. The application supplies the
 * ISR-safe hook and owns its storage and lifecycle. */
#ifndef PROFILER_AUX_SAMPLE_HOOK
    #define PROFILER_AUX_SAMPLE_HOOK 0
#endif
#if PROFILER_AUX_SAMPLE_HOOK != 0 && PROFILER_AUX_SAMPLE_HOOK != 1
    #error "PROFILER_AUX_SAMPLE_HOOK must be 0 or 1"
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

/** @brief Enable best-effort EHABI backtraces (0/1), default 0; needs exact stack bounds. */
#ifndef PROFILER_STACK_UNWIND
    #define PROFILER_STACK_UNWIND 0
#endif
#if PROFILER_STACK_UNWIND != 0 && PROFILER_STACK_UNWIND != 1
    #error "PROFILER_STACK_UNWIND must be 0 or 1"
#endif
#if PROFILER_STACK_UNWIND && !PROFILER_PRECISE_STACK_BOUNDS
    #error "Stack unwinding requires PROFILER_PRECISE_STACK_BOUNDS=1 and the stack bounds hook"
#endif

/* Optional PMU event snapshots; raw architectural event IDs keep the core
 * independent of device headers. The backend uses CMSIS PMU functions. */
#ifndef PROFILER_PMU_COUNT
    #define PROFILER_PMU_COUNT 0
#endif
#if PROFILER_PMU_COUNT < 0 || PROFILER_PMU_COUNT > 4
    #error "PROFILER_PMU_COUNT must be between 0 and 4"
#endif
#ifndef PROFILER_PMU_EVENT0
    #define PROFILER_PMU_EVENT0 0x0003U /* ARM_PMU_L1D_CACHE_REFILL */
#endif
#ifndef PROFILER_PMU_EVENT1
    #define PROFILER_PMU_EVENT1 0x0024U /* ARM_PMU_STALL_BACKEND */
#endif
/** @brief Third event; default 0x0008, instructions retired. */
#ifndef PROFILER_PMU_EVENT2
    #define PROFILER_PMU_EVENT2 0x0008U
#endif
/** @brief Fourth event; default 0x0011, CPU cycles. */
#ifndef PROFILER_PMU_EVENT3
    #define PROFILER_PMU_EVENT3 0x0011U
#endif

/** @brief Maximum recovered callers; limits ISR work and temporary storage. */
#ifndef PROFILER_UNWIND_MAX_DEPTH
    #define PROFILER_UNWIND_MAX_DEPTH 16U
#endif
#if PROFILER_UNWIND_MAX_DEPTH < 1 || PROFILER_UNWIND_MAX_DEPTH > 255
    #error "PROFILER_UNWIND_MAX_DEPTH must be 1..255"
#endif

#endif
