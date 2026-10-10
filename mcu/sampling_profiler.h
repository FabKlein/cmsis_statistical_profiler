/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler.h
 * Description:  Application API for SRAM statistical sampling
 *
 * $Date:        30 September 2026
 * $Revision:    V.1.0.3
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler.h
 * @brief Application API for SRAM statistical sampling.
 */

#ifndef PROFILER_SAMPLING_PROFILER_H
#define PROFILER_SAMPLING_PROFILER_H

#include <stdint.h>

/** @brief Initialization stage; NONE means no initialization failure. */
enum ProfilerInitStage
{
    PROFILER_INIT_NONE,
    PROFILER_INIT_BACKEND,
    PROFILER_INIT_STACK,
    PROFILER_INIT_TIMESTAMP,
    PROFILER_INIT_UNWIND,
    PROFILER_INIT_TIMER
};
/** @brief Failure category; PMU fallback remains in the capture header. */
enum ProfilerInitReason
{
    PROFILER_INIT_OK,
    PROFILER_INIT_UNAVAILABLE,
    PROFILER_INIT_INVALID_CONFIG,
    PROFILER_INIT_BUSY,
    PROFILER_INIT_BAD_CLOCK,
    PROFILER_INIT_DENIED,
    PROFILER_INIT_MISSING_TABLES,
    PROFILER_INIT_MALFORMED_TABLES
};
/** @brief Last initialization failure, readable without logging or a running timer. */
struct ProfilerDiagnostics
{
    enum ProfilerInitStage stage;   /**< Failed subsystem. */
    enum ProfilerInitReason reason; /**< Failure category. */
    uint32_t value0;                /**< Context, defined by the failing subsystem. */
    uint32_t value1;                /**< Context, defined by the failing subsystem. */
};

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Reset capture metadata and initialize the timer and optional PMU.
 * @retval 1 Sampling timer started, with recording gated off.
 * @retval 0 Initialization failed; recording remains disabled.
 * @note Call lifecycle APIs serially on 1 core in privileged thread mode.
 * PMU unavailability is recorded in metadata and does not fail initialization.
 * Record storage is not erased; unused tail bytes can contain earlier captures.
 */
int profiler_init(void);
/** @brief Last init result; reset on the next init, valid until then. Thread-mode use only. */
const struct ProfilerDiagnostics *profiler_diagnostics(void);
/**
 * @brief Enable recording for an initialized, incomplete, non-full capture.
 * @note Does nothing before successful initialization or after completion.
 */
void profiler_enable(void);
/**
 * @brief Gate off recording without stopping the timer or PMU.
 * @note Recording can resume with profiler_enable().
 */
void profiler_disable(void);
/**
 * @brief Query whether the capture has run out of space for a complete record.
 * @return Nonzero when full; 0 otherwise. Stop is still required to finalize it.
 */
int profiler_full(void);
/**
 * @brief Read the cumulative sampling interrupt count, modulo 2^32.
 * @note Advances while recording is disabled or the buffer is full; freezes at stop.
 * Initialization does not reset it. Subtract 2 readings to measure an interval.
 * This is not the stored sample count or the operating system tick count.
 */
uint32_t profiler_sample_ticks(void);
/**
 * @brief Read cumulative sampling-timer milliseconds, modulo 2^32.
 * @note Same lifetime as profiler_sample_ticks(); independent of HAL/RTOS time.
 * Subtract 2 readings to measure elapsed sampling time across an interval.
 */
uint32_t profiler_elapsed_ms(void);

/**
 * @brief Stop sampling and PMU collection, finalize metadata and clean the cache.
 * @param iterations Application-reported workload iteration count.
 * @param validation_passed Application validation result; nonzero means passed.
 * @note Does nothing before successful initialization or after completion.
 * The first stop's metadata is preserved until the next init. Stops the dedicated
 * sampling timer; does not reset the shared timestamp counter.
 */
void profiler_stop(uint32_t iterations, uint32_t validation_passed);

#ifdef __cplusplus
}
#endif

#endif
