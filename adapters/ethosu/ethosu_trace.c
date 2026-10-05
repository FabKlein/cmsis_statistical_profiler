/* Copyright 2026 Arm Limited and/or its affiliates.
 * SPDX-License-Identifier: Apache-2.0
 */
#include "ethosu_trace.h"

#if PROFILER_ETHOSU_TRACE
    #include "ethosu_driver.h"
    #include "pmu_ethosu.h"
    #include "sampling_profiler.h"
    #include "sampling_profiler_port.h"
    #include <string.h>

_Static_assert(sizeof(struct EthosuTraceHeader) == ETHOSU_TRACE_HEADER_BYTES, "Ethos-U trace header");
_Static_assert(PROFILER_ETHOSU_TRACE_BUFFER_BYTES > ETHOSU_TRACE_HEADER_BYTES + 32U,
               "Ethos-U trace allocation is too small");
_Static_assert((PROFILER_ETHOSU_TRACE_BUFFER_BYTES & 31U) == 0U, "Ethos-U trace allocation alignment");
_Static_assert(PROFILER_ETHOSU_PMU_COUNT >= 0 && PROFILER_ETHOSU_PMU_COUNT <= 4, "Ethos-U PMU count must be 0..4");

    #ifndef PROFILER_ETHOSU_BUFFER_ATTRIBUTES
        #define PROFILER_ETHOSU_BUFFER_ATTRIBUTES __attribute__((aligned(32)))
    #endif
PROFILER_ETHOSU_BUFFER_ATTRIBUTES
volatile struct EthosuTraceBuffer ethosu_trace_samples;

static struct ethosu_driver *trace_driver;
static volatile uint32_t trace_gate;
static uint32_t trace_started;
    #if PROFILER_ETHOSU_PMU_COUNT
static const enum ethosu_pmu_event_type configured_events[PROFILER_ETHOSU_PMU_COUNT] = {
        #if PROFILER_ETHOSU_PMU_COUNT > 0
    PROFILER_ETHOSU_PMU_EVENT0,
        #endif
        #if PROFILER_ETHOSU_PMU_COUNT > 1
    PROFILER_ETHOSU_PMU_EVENT1,
        #endif
        #if PROFILER_ETHOSU_PMU_COUNT > 2
    PROFILER_ETHOSU_PMU_EVENT2,
        #endif
        #if PROFILER_ETHOSU_PMU_COUNT > 3
    PROFILER_ETHOSU_PMU_EVENT3,
        #endif
};
    #endif

void ethosu_trace_bind(struct ethosu_driver *driver) { trace_driver = driver; }

int ethosu_trace_start(void)
{
    trace_gate = 0U;
    if (trace_started)
    {
        ethosu_trace_stop(0U, 0U);
    }
    memset((void *)&ethosu_trace_samples, 0, sizeof(ethosu_trace_samples));
    volatile struct EthosuTraceHeader *header = &ethosu_trace_samples.header;
    header->magic = ETHOSU_TRACE_MAGIC;
    header->version = ETHOSU_TRACE_VERSION;
    header->header_bytes = ETHOSU_TRACE_HEADER_BYTES;
    header->buffer_bytes = sizeof(ethosu_trace_samples);
    header->sample_hz = statistical_samples.header.sample_hz;
    header->timestamp_hz = statistical_samples.header.timestamp_hz;
    header->record_bytes = 4U * ETHOSU_TRACE_BASE_WORDS;
    #if defined(ETHOSU55)
    header->device_type = 55U;
    #elif defined(ETHOSU65)
    header->device_type = 65U;
    #elif defined(ETHOSU85)
    header->device_type = 85U;
    #else
        #error "Ethos-U trace requires a supported Ethos-U core driver variant"
    #endif
    if (!trace_driver || !header->timestamp_hz || ethosu_request_power(trace_driver) != 0)
        return 0;
    trace_started = 1U;

    #if PROFILER_ETHOSU_PMU_COUNT
    /* The driver soft-reset on the first power request makes these settings
     * stable across invocations while this trace retains the power reference.
     * Never seize counters that are already enabled by another owner. */
    if ((ETHOSU_PMU_Get_STATUS(trace_driver) & 1U) != 0U || ETHOSU_PMU_CNTR_Status(trace_driver) != 0U)
    {
        header->pmu_status = ETHOSU_TRACE_PMU_BUSY;
    }
    else
    {
        header->pmu_status = ETHOSU_TRACE_PMU_ACTIVE;
        header->pmu_count = PROFILER_ETHOSU_PMU_COUNT;
        ETHOSU_PMU_Enable(trace_driver);
        for (uint32_t i = 0; i < PROFILER_ETHOSU_PMU_COUNT; ++i)
        {
            header->pmu_events[i] = (uint32_t)configured_events[i];
            ETHOSU_PMU_Set_EVTYPER(trace_driver, i, configured_events[i]);
            ETHOSU_PMU_Set_EVCNTR(trace_driver, i, 0U);
        }
        ETHOSU_PMU_CNTR_Enable(trace_driver, (1U << PROFILER_ETHOSU_PMU_COUNT) - 1U);
    }
    #endif
    header->record_bytes += 4U * header->pmu_count;
    header->start_timestamp = profiler_port_timestamp();
    header->start_tick = profiler_port_ticks();
    header->active = 1U;
    profiler_port_barrier();
    trace_gate = 1U;
    return 1;
}

void ethosu_trace_stop(uint32_t iterations, uint32_t validation_passed)
{
    trace_gate = 0U;
    profiler_port_barrier();
    if (!trace_started)
        return;
    volatile struct EthosuTraceHeader *header = &ethosu_trace_samples.header;
    header->active = 0U;
    if (header->pmu_count)
    {
        ETHOSU_PMU_CNTR_Disable(trace_driver, (1U << header->pmu_count) - 1U);
        ETHOSU_PMU_Disable(trace_driver);
    }
    header->stop_timestamp = profiler_port_timestamp();
    header->stop_tick = profiler_port_ticks();
    header->iterations = iterations;
    header->validation_passed = validation_passed;
    header->complete = 1U;
    profiler_port_barrier();
    profiler_port_flush((const void *)&ethosu_trace_samples, sizeof(ethosu_trace_samples));
    ethosu_release_power(trace_driver);
    trace_started = 0U;
}

int ethosu_trace_full(void) { return ethosu_trace_samples.header.full != 0U; }

/* Only this ISR writes records. STATUS bit 0 is the running state. QREAD is an
 * offset in bytes, not an address; QSIZE cannot be read while running. The
 * inference-begin hook publishes the software-known stream size instead. */
void profiler_aux_sample(uint32_t timestamp, uint32_t tick)
{
    if (!trace_gate)
        return;
    volatile struct EthosuTraceHeader *header = &ethosu_trace_samples.header;
    const uint32_t stride = header->record_bytes / 4U;
    const uint32_t capacity = sizeof(ethosu_trace_samples.records) / 4U;
    const uint32_t index = header->count * stride;
    if (index > capacity || stride > capacity - index)
    {
        header->full = 1U;
        header->active = 0U;
        trace_gate = 0U;
        return;
    }

    uint32_t status = ETHOSU_PMU_Get_STATUS(trace_driver);
    uint32_t qread = ETHOSU_TRACE_NO_QREAD;
    if ((status & 1U) != 0U)
    {
        qread = ETHOSU_PMU_Get_QREAD(trace_driver);
        uint32_t bytes = header->stream_bytes;
        if ((bytes != 0U && qread > bytes) || (qread & 3U) != 0U)
        {
            qread = ETHOSU_TRACE_NO_QREAD;
            ++header->invalid_qread;
        }
    }
    volatile uint32_t *record = &ethosu_trace_samples.records[index];
    record[0] = timestamp;
    record[1] = tick;
    record[2] = status;
    record[3] = qread;
    for (uint32_t i = 0; i < header->pmu_count; ++i)
        record[4U + i] = ETHOSU_PMU_Get_EVCNTR(trace_driver, i);
    profiler_port_barrier();
    header->count++;
}

/* The public driver calls this weak callback immediately before submitting a
 * Vela command stream. Its COP1 payload carries the length in 32-bit words.
 * Unknown/malformed payloads leave stream_bytes=0; raw aligned QREAD remains
 * available, without an inferred upper bound. */
void ethosu_inference_begin(struct ethosu_driver *drv, void *user_arg)
{
    (void)user_arg;
    if (!trace_gate || drv != trace_driver)
        return;
    const uint8_t *data = (const uint8_t *)drv->job.custom_data_ptr;
    uint32_t size = (uint32_t)drv->job.custom_data_size;
    uint32_t stream_bytes = 0U;
    if (data && size >= 8U && data[0] == 'C' && data[1] == 'O' && data[2] == 'P' && data[3] == '1')
    {
        uint32_t offset = 4U;
        while (offset <= size - 4U)
        {
            uint8_t action = data[offset];
            uint32_t words = 1U;
            if (action == 1U)
                words = 3U;
            else if (action == 2U)
                words += ((uint32_t)data[offset + 2U] | ((uint32_t)data[offset + 3U] << 8) |
                          ((uint32_t)data[offset + 1U] << 16));
            else if (action != 5U)
                break;
            if (words > (size - offset) / 4U)
                break;
            if (action == 2U)
            {
                stream_bytes = (words - 1U) * 4U;
                break;
            }
            offset += words * 4U;
        }
    }
    ethosu_trace_samples.header.stream_bytes = stream_bytes;
    ++ethosu_trace_samples.header.streams_seen;
    profiler_port_barrier();
}
#endif
