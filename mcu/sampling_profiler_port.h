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
 * $Date:        5 October 2026
 * $Revision:    V.1.0.3
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
#include "sampling_profiler_format.h"
#include <stdint.h>

/**
 * @brief Validated sample passed internally from the ISR to capture storage.
 * @details The wire record contains 6 base words, header.pmu_count event words and optional backtrace words;
 * this staging type is not used as the wire stride.
 */
struct ProfilerSample
{
    uint32_t timestamp;        /**< Timestamp counter at sampling time. */
    uint32_t tick;             /**< Sampling interrupt counter at sampling time. */
    uint32_t pc;               /**< Interrupted program counter. */
    uint32_t lr;               /**< Interrupted link register; not a reconstructed call stack. */
    uint32_t xpsr;             /**< Interrupted program status register. */
    uint32_t exception_return; /**< EXC_RETURN captured at interrupt entry. */
#if PROFILER_PMU_COUNT
    uint32_t pmu[PROFILER_PMU_COUNT]; /**< Staging snapshot; only active event words are stored. */
#endif
#if PROFILER_STACK_UNWIND
    uint32_t unwind;                             /**< Depth in bits 0-7, ProfilerUnwindStatus in bits 8-15. */
    uint32_t callers[PROFILER_UNWIND_MAX_DEPTH]; /**< Raw Thumb return addresses, immediate caller first. */
#endif
};

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
/** @brief Record an init failure and return 0; never call from the sampling ISR.
 * @details Timer bad-clock context is input Hz/requested Hz; busy/denied context is IRQ/0.
 * A vendor timer-start failure records IRQ/vendor status with reason UNAVAILABLE.
 * Unwind context is entry or region index/0. Other context values are 0 unless documented.
 */
int profiler_init_fail(enum ProfilerInitStage stage, enum ProfilerInitReason reason, uint32_t value0, uint32_t value1);
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
 * @brief Try to reserve and start the configured chained 32-bit PMU events.
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
 * @brief Read the configured chained event counters with bounded rollover retries.
 * @param[out] values Non-NULL PROFILER_PMU_COUNT-word destination; 0 when collection is inactive.
 * @details ISR-safe. Overflow or incoherent reads set capture validity flags.
 */
void profiler_pmu_snapshot(uint32_t *values);
/**
 * @brief Make completed capture data visible to an external debugger.
 * @param[in] address Start of the capture allocation.
 * @param bytes Allocation size in bytes.
 */
void profiler_port_flush(const void *address, uint32_t bytes);

/* ISR-only capture operations, after the backend admits the tick through the
 * gate. Lifecycle calls cannot preempt this producer; no gate recheck is needed. */
/**
 * @brief Single-core producer gate; nonzero allows the ISR to record samples.
 */
extern volatile uint32_t statistical_sampling_gate;
/**
 * @brief Count 1 rejected frame from an admitted sampling interrupt.
 * @param reason First failing check; out-of-range reasons are ignored.
 * @pre The backend checked statistical_sampling_gate in this interrupt.
 * @note Called only by the sampling ISR.
 */
void profiler_reject(enum ProfilerRejection reason);
/**
 * @brief Append a validated sample and close the gate when the buffer fills.
 * @param[in] sample Non-NULL sample; PMU words are stored only if pmu_count is nonzero.
 * @pre The backend checked statistical_sampling_gate in this interrupt.
 * @note Single sampling-ISR producer only. Existing records are never overwritten.
 * Readers must wait for profiler_stop() to return; no per-record hardware barrier.
 */
void profiler_record(const struct ProfilerSample *sample);

#if PROFILER_AUX_SAMPLE_HOOK
/** @brief Application-owned companion sampler, called from the timer ISR.
 * @note The timestamp and tick are from the same clock/interrupt as the CPU
 * capture. The hook must be bounded, integer-only and safe in interrupt mode.
 * It runs even when the interrupted CPU frame is rejected or CPU recording is
 * gated off, so its own recording gate and capacity are independent.
 */
void profiler_aux_sample(uint32_t timestamp, uint32_t tick);
#endif

#ifdef __cplusplus
}
#endif
#endif
