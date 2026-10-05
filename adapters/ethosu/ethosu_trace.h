/* Copyright 2026 Arm Limited and/or its affiliates.
 * SPDX-License-Identifier: Apache-2.0
 */
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
#define ETHOSU_TRACE_BASE_WORDS   4U
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
    uint32_t stream_bytes, streams_seen, invalid_qread;
    uint32_t start_timestamp, start_tick, stop_timestamp, stop_tick;
    uint32_t iterations, validation_passed;
    uint32_t device_type; /* 55, 65, or 85; event enum values depend on it. */
    uint32_t reserved[5];
};

#if PROFILER_ETHOSU_TRACE
struct EthosuTraceBuffer
{
    struct EthosuTraceHeader header;
    uint32_t records[(PROFILER_ETHOSU_TRACE_BUFFER_BYTES - ETHOSU_TRACE_HEADER_BYTES) / 4U];
};

    #ifdef __cplusplus
extern "C" {
    #endif
extern volatile struct EthosuTraceBuffer ethosu_trace_samples;
void ethosu_trace_bind(struct ethosu_driver *driver);
int ethosu_trace_start(void);
void ethosu_trace_stop(uint32_t iterations, uint32_t validation_passed);
int ethosu_trace_full(void);
/* Called by the optional profiler hook on each CPU sampling interrupt. */
void profiler_aux_sample(uint32_t timestamp, uint32_t tick);
    #ifdef __cplusplus
}
    #endif
#endif

#endif
