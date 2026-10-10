/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_format.h
 * Description:  SRAM capture format and buffer export interface
 *
 * $Date:        9 October 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file sampling_profiler_format.h
 * @brief Capture layout and buffer export interface; requires application configuration.
 */

#ifndef PROFILER_SAMPLING_PROFILER_FORMAT_H
#define PROFILER_SAMPLING_PROFILER_FORMAT_H

#include "sampling_profiler_config.h"
#include <stdint.h>

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
 * @details All counters wrap modulo 2^32. Read after profiler_stop().
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
 * Dump the whole object, including unused allocation space. Initialization resets
 * metadata only; bytes beyond bytes_used may retain earlier capture contents.
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

#ifdef __cplusplus
}
#endif

#endif
