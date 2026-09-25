/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler.h
 * Description:  SRAM statistical sampling interface and capture format
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.2
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler.h
 * @brief SRAM statistical sampling interface and capture format.
 */

#ifndef PROFILER_SAMPLING_PROFILER_H
#define PROFILER_SAMPLING_PROFILER_H

#include <stdint.h>

#include "sampling_profiler_config.h"

/** @brief Best-effort unwind outcome; all failures preserve the valid prefix. */
enum ProfilerUnwindStatus
{
    PROFILER_UNWIND_COMPLETE = 0, /**< Recovered an explicit zero return address. */
    PROFILER_UNWIND_NO_TABLE,     /**< Missing entry or EXIDX_CANTUNWIND. */
    PROFILER_UNWIND_UNSUPPORTED,  /**< Unsupported or malformed unwind recipe. */
    PROFILER_UNWIND_BOUNDS,       /**< Stack address outside the precise readable allocation. */
    PROFILER_UNWIND_INVALID_PC,   /**< Return address outside executable code or not Thumb. */
    PROFILER_UNWIND_NO_PROGRESS,  /**< Stack moved backwards or repeated the same PC/SP. */
    PROFILER_UNWIND_DEPTH_LIMIT   /**< Configured maximum callers recovered; older frames were not attempted. */
};

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

/* First failing check wins; counters wrap modulo 2^32 like rejected. */
/**
 * @brief First failing frame check; exactly 1 reason is counted per rejection.
 */
enum ProfilerRejection
{
    PROFILER_REJECT_EXC_RETURN,        /**< Invalid EXC_RETURN encoding. */
    PROFILER_REJECT_UNSUPPORTED_FRAME, /**< Unsupported mode, security state or frame type. */
    PROFILER_REJECT_STACK_BOUNDS,      /**< Frame is outside allowed stack memory. */
    PROFILER_REJECT_XPSR,              /**< Invalid interrupted program state. */
    PROFILER_REJECT_REASON_COUNT       /**< Number of rejection counters. */
};

/**
 * @brief Capture metadata stored as 44 little-endian 32-bit words.
 * @details All counters wrap modulo 2^32. Read after sampling_profiler_stop().
 */
struct ProfilerSamplingHeader
{
    uint32_t magic;             /**< SCPF capture magic. */
    uint32_t version;           /**< Sole supported format identifier. */
    uint32_t record_base_bytes; /**< Base bytes: 24 + 4 * pmu_count + 4 if unwinding is enabled. */
    uint32_t buffer_bytes;      /**< Total allocated object size in bytes. */
    uint32_t bytes_used;        /**< Committed record bytes, excluding the header. */
    uint32_t count;             /**< Committed sample count. */
    uint32_t rejected;          /**< Total rejected frame count. */
    uint32_t active;            /**< Nonzero while recording is gated on. */
    uint32_t timestamp_hz;      /**< Timestamp counter frequency in Hz. */
    uint32_t timer_period;      /**< Timer input counts per sample interrupt. */
    uint32_t start_timestamp;   /**< Timestamp at capture initialization. */
    uint32_t start_tick;        /**< Sampling interrupt count at initialization. */
    uint32_t stop_timestamp;    /**< Timestamp after stopping collection. */
    uint32_t stop_tick;         /**< Sampling interrupt count after stopping. */
    uint32_t full;              /**< Nonzero when recording stops for lack of space. */
    uint32_t complete;          /**< Nonzero after stop finalizes the capture. */
    uint32_t iterations;        /**< Application workload iteration count. */
    uint32_t validation_passed; /**< Nonzero when application validation passed. */
    uint32_t sample_hz;         /**< Requested sampling rate in Hz. */
    uint32_t timer_hz;          /**< Actual sampling timer input frequency in Hz. */
    uint32_t rejected_reason[PROFILER_REJECT_REASON_COUNT]; /**< Per-reason rejection counters in enum order. */
    uint32_t pmu_status;       /**< 0 disabled, 1 unavailable, 2 active, 3 busy, 4 unsupported, 5 denied */
    uint32_t pmu_count;        /**< Counter words per record: 1-4 when active, otherwise 0. */
    uint32_t pmu_requested;    /**< Requested event count, including when collection is unavailable. */
    uint32_t pmu_events[4];    /**< Requested architectural event IDs; 0 when disabled. */
    uint32_t pmu_counter_bits; /**< 32 when active, otherwise 0. */
    uint32_t pmu_start[4];     /**< Counter snapshots at collection start. */
    uint32_t pmu_stop[4];      /**< Counter snapshots after collection stops. */
    uint32_t pmu_flags;        /**< Bits 0-3: event overflow; bit 4: incoherent read. */
    uint32_t unwind_max_depth; /**< 0: absent; otherwise maximum EHABI caller depth. */
    uint32_t header_bytes;     /**< Serialized header length; must match this format version. */
    uint32_t features;         /**< Bit 0: active PMU words; bit 1: EHABI backtraces. */
};

/* 1 supported format: base words, active PMU words, optional depth/status and actual callers. */
/** @brief Capture signature identifying SCPF(Statistical Capture Profiler Format) data. */
#define PROFILER_CAPTURE_MAGIC 0x46504353U /* SCPF */
/** @brief Identifier checked by the matching host decoder. */
#define PROFILER_FORMAT_VERSION 2U
/** @brief Size of the capture header in bytes. */
#define PROFILER_HEADER_BYTES 176U
/** @brief Size of the 6 mandatory record words in bytes. */
#define PROFILER_BASE_RECORD_BYTES 24U
/** @brief Whole words available for packed records within the allocation budget. */
#define PROFILER_STORAGE_WORDS ((PROFILER_SAMPLE_BUFFER_BYTES - PROFILER_HEADER_BYTES) / 4U)

/**
 * @brief Fixed allocation containing a header and densely packed variable-stride records.
 * @details The base fields are fixed after PMU initialization; each record then
 * appends only its recovered callers. bytes_used bounds the committed stream.
 * Dump the whole object, including unused allocation space.
 */
struct ProfilerSamplingBuffer
{
    struct ProfilerSamplingHeader header;
    /* Packed words; each record appends only its recovered caller addresses. */
    uint32_t records[PROFILER_STORAGE_WORDS];
};

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Capture object to dump after stopping and halting the target.
 */
extern volatile struct ProfilerSamplingBuffer statistical_samples;
/**
 * @brief Clear the previous capture and initialize the timer and optional PMU.
 * @retval 1 Sampling timer started, with recording gated off.
 * @retval 0 Initialization failed; recording remains disabled.
 * @note Call lifecycle APIs serially on 1 core in privileged thread mode.
 * PMU unavailability is recorded in metadata and does not fail initialization.
 */
int sampling_profiler_init(void);
/** @brief Last init result; reset on the next init, valid until then. Thread-mode use only. */
const struct ProfilerDiagnostics *sampling_profiler_diagnostics(void);
/**
 * @brief Enable recording for an initialized, incomplete, non-full capture.
 * @note Does nothing before successful initialization or after completion.
 */
void sampling_profiler_enable(void);
/**
 * @brief Gate off recording without stopping the timer or PMU.
 * @note Recording can resume with sampling_profiler_enable().
 */
void sampling_profiler_disable(void);
/**
 * @brief Query whether the capture has run out of space for a complete record.
 * @return Nonzero when full; 0 otherwise. Stop is still required to finalize it.
 */
int sampling_profiler_full(void);
/**
 * @brief Stop sampling and PMU collection, finalize metadata and clean the cache.
 * @param iterations Application-reported workload iteration count.
 * @param validation_passed Application validation result; nonzero means passed.
 * @note Does nothing if initialization has not succeeded. Stops the dedicated
 * sampling timer; does not reset the shared timestamp counter.
 */
void sampling_profiler_stop(uint32_t iterations, uint32_t validation_passed);

#ifdef __cplusplus
}
#endif

#endif
