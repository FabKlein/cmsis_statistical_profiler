/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_port.h
 * Description:  Internal capture core and platform backend interface
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_port.h
 * @brief Internal capture core and platform backend interface.
 */

#ifndef PROFILER_PORT_H
#define PROFILER_PORT_H

#include "sampling_profiler.h"
#include <stdint.h>

/* Internal boundary: no vendor or CMSIS types cross into the capture core.
 * Timestamps use a fixed-frequency 32-bit counter and a sampling-interrupt counter.
 * APIs run on 1 core, in privileged thread mode; 1 ISR produces samples. */
/**
 * @brief Frequencies and period shared between the timer adapter and capture core.
 */
struct ProfilerClock
{
    uint32_t timestamp_hz; /**< Timestamp counter frequency in Hz. */
    uint32_t timer_period; /**< Timer input counts per sample interrupt. */
    uint32_t timer_hz;     /**< Actual sampling timer input frequency in Hz. */
};

#ifdef __cplusplus
extern "C" {
#endif

/* Backend initialization starts the selected sampling timer, with capture gated off. */
/**
 * @brief Initialize the backend and start its timer with recording gated off.
 * @param[out] clock Non-NULL destination for actual timer and timestamp settings.
 * @return 1 on success, 0 if the configuration or hardware is unavailable.
 */
int profiler_port_init(struct ProfilerClock *clock);
/**
 * @brief Stop sampling interrupts while preserving the caller's interrupt mask.
 * @note Must be safe before initialization and on repeated calls.
 */
void profiler_port_stop(void);
/* Sampling time only: continues while gated off/full, freezes at stop. */
/**
 * @brief Read the modulo-2^32 sampling interrupt count.
 * @return Count advances while gated off or full and freezes when stopped.
 */
uint32_t profiler_port_ticks(void);
/**
 * @brief Read elapsed sampling-timer milliseconds, modulo 2^32.
 * @return Timer-derived milliseconds; independent of HAL and RTOS ticks.
 */
uint32_t profiler_port_millis(void);

/* Cortex-M backend: timestamp counter, publication barrier, debugger visibility. */
/**
 * @brief Read the free-running timestamp.
 * @return Counter value modulo 2^32 at the initialized timestamp frequency.
 */
uint32_t profiler_port_timestamp(void);
/**
 * @brief Order capture writes before publishing sample counts or gate changes.
 */
void profiler_port_barrier(void);
/* Optional PMU backend. PMU scope is init through stop, independent of gate. */
/**
 * @brief Try to reserve and start 2 chained 32-bit PMU events.
 * @pre Capture header was cleared and sampling is gated off.
 * @details Records failure status without preventing PC sampling. Counting covers
 * init through stop, including interrupts and gated-off intervals.
 */
void profiler_pmu_init(void);
/**
 * @brief Stop owned event counters and save final values without releasing ownership.
 * @note Safe when no PMU collection is running; preserves the shared cycle counter.
 */
void profiler_pmu_stop(void);
/**
 * @brief Read both chained event counters with bounded rollover retries.
 * @param[out] values Non-NULL 2-word destination; 0 when collection is inactive.
 * @details ISR-safe. Overflow or incoherent reads set capture validity flags.
 */
void profiler_pmu_snapshot(uint32_t values[2]);
/**
 * @brief Make completed capture data visible to an external debugger.
 * @param[in] address Start of the capture allocation.
 * @param bytes Allocation size in bytes.
 */
void profiler_port_flush(const void *address, uint32_t bytes);

/* ISR-only capture operations; record requires a non-NULL sample. */
/**
 * @brief Single-core producer gate; nonzero allows the ISR to record samples.
 */
extern volatile uint32_t statistical_sampling_gate;
/**
 * @brief Count 1 rejected frame while recording is enabled.
 * @param reason First failing check; out-of-range reasons are ignored.
 * @note Called only by the sampling ISR.
 */
void sampling_profiler_reject(enum ProfilerRejection reason);
/**
 * @brief Append a validated sample and close the gate when the buffer fills.
 * @param[in] sample Non-NULL sample; PMU words are stored only if pmu_count is nonzero.
 * @note Single sampling-ISR producer only. Existing records are never overwritten.
 */
void sampling_profiler_record(const struct ProfilerSample *sample);

#ifdef __cplusplus
}
#endif
#endif
