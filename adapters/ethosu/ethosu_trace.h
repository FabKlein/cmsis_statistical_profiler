/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        ethosu_trace.h
 * Description:  Ethos-U trace buffer format and lifecycle interface
 *
 * $Date:        5 October 2026
 * $Revision:    V.1.0.5
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#ifndef CMSIS_STATISTICAL_PROFILER_ETHOSU_TRACE_H
#define CMSIS_STATISTICAL_PROFILER_ETHOSU_TRACE_H

#include "sampling_profiler_config.h"
#include <stdint.h>

struct ethosu_driver;

/* Separate wire format and allocation from the Cortex-M SCPF capture. All
 * fields are little-endian 32-bit words. Export the whole object after stop. */
#define ETHOSU_TRACE_MAGIC        0x52545545U /* EUTR */
#define ETHOSU_TRACE_VERSION      1U
#define ETHOSU_TRACE_HEADER_BYTES 128U
#define ETHOSU_TRACE_BASE_WORDS   5U
#define ETHOSU_TRACE_NO_QREAD     UINT32_MAX

enum EthosuTracePmuStatus
{
    ETHOSU_TRACE_PMU_DISABLED = 0,
    ETHOSU_TRACE_PMU_ACTIVE = 1,
    ETHOSU_TRACE_PMU_BUSY = 2
};

struct EthosuTraceHeader
{
    uint32_t magic, version, header_bytes, record_bytes;
    uint32_t buffer_bytes, count, active, full, complete;
    uint32_t sample_hz, timestamp_hz, pmu_count, pmu_status;
    uint32_t pmu_events[4];
    uint32_t stream_count, streams_seen, invalid_qread;
    uint32_t start_timestamp, start_tick, stop_timestamp, stop_tick;
    uint32_t iterations, validation_passed;
    uint32_t device_type; /* 55, 65, or 85; event enum values depend on it. */
    uint32_t stream_capacity, unknown_stream_samples, unregistered_streams;
    uint32_t reserved[2];
};

/* IDs are 1-based table indices, valid only within this capture. Address is
 * CPU-visible, not necessarily the remapped NPU QBASE. Contents must be immutable. */
struct EthosuTraceStream
{
    uint32_t command_address, stream_bytes;
};

#if PROFILER_ETHOSU_TRACE
    #ifndef PROFILER_ETHOSU_MAX_STREAMS
        #define PROFILER_ETHOSU_MAX_STREAMS 16U
    #endif
    /* Disable when the application supplies ethosu_inference_begin itself. */
    #ifndef PROFILER_ETHOSU_DRIVER_CALLBACK
        #define PROFILER_ETHOSU_DRIVER_CALLBACK 1
    #endif
    #if PROFILER_ETHOSU_DRIVER_CALLBACK != 0 && PROFILER_ETHOSU_DRIVER_CALLBACK != 1
        #error "PROFILER_ETHOSU_DRIVER_CALLBACK must be 0 or 1"
    #endif
    #define ETHOSU_TRACE_RECORD_OFFSET (ETHOSU_TRACE_HEADER_BYTES + 8U * PROFILER_ETHOSU_MAX_STREAMS)

struct EthosuTraceBuffer
{
    struct EthosuTraceHeader header;
    struct EthosuTraceStream streams[PROFILER_ETHOSU_MAX_STREAMS];
    uint32_t records[(PROFILER_ETHOSU_TRACE_BUFFER_BYTES - ETHOSU_TRACE_RECORD_OFFSET) / 4U];
};

    #ifdef __cplusplus
extern "C" {
    #endif
extern volatile struct EthosuTraceBuffer ethosu_trace_samples;
/** @brief Select a driver, or detach with NULL, while stopped.
 * @return 1 on success; 0 while started, leaving the current binding unchanged.
 * @note A full buffer must still be stopped before rebinding. Serialize bind,
 * start and stop in privileged thread mode on 1 core; these calls do not lock.
 */
int trace_ethosu_bind(struct ethosu_driver *driver);
/** @brief Start capture, acquiring PMU counters if requested and available.
 * @note Collected PMU counters require exclusive ownership until stop returns,
 * including after buffer full. External PMU changes are not detected.
 * Set PROFILER_ETHOSU_PMU_COUNT=0 when the application owns the PMU.
 */
int trace_ethosu_start(void);
void trace_ethosu_stop(uint32_t iterations, uint32_t validation_passed);
int trace_ethosu_full(void);
/** @brief Discover the submitted stream before driver submission.
 * @note Called by the optional driver callback wrapper, or forwarded exactly
 * once by the application's ethosu_inference_begin callback. No-op when not
 * capturing or when drv is not the bound driver. Does not take ownership of user_arg.
 */
void trace_ethosu_inference_begin(struct ethosu_driver *drv, void *user_arg);
/* Called by the optional profiler hook on each CPU sampling interrupt. */
void profiler_aux_sample(uint32_t timestamp, uint32_t tick);
    #ifdef __cplusplus
}
    #endif
#endif

#endif
