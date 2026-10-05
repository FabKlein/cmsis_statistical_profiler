/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_ethosu_streams.c
 * Description:  Native Ethos-U stream discovery and capture regression
 *
 * $Date:        5 October 2026
 * $Revision:    V.1.0.2
 *
 * Target :  Arm(R) M-Profile Architecture
 * -------------------------------------------------------------------- */

#include "ethosu_driver.h"
#include "ethosu_trace.h"
#include "pmu_ethosu.h"
#include "sampling_profiler.h"
#include <assert.h>
#include <stdio.h>

struct FakeCoreCapture statistical_samples = {{1000U, 1000000U}};
static uint32_t status, qread, ticks, enabled;
static int power_references;
static struct ethosu_driver driver;
/* COP1, NOP padding, COMMAND_STREAM(length=4 words), command bytes. */
static uint32_t payloads[3][8] = {{0x31504F43U, 5U, 5U, 0x00040002U, 0U, 0U, 0U, 0U},
                                  {0x31504F43U, 5U, 5U, 0x00040002U, 0U, 0U, 0U, 0U},
                                  {0x31504F43U, 5U, 5U, 0x00040002U, 0U, 0U, 0U, 0U}};
void ethosu_inference_begin(struct ethosu_driver *, void *);
#if !PROFILER_ETHOSU_DRIVER_CALLBACK
/* Simulate an application-owned callback alongside its existing bookkeeping. */
static uint32_t application_notifications;
void ethosu_inference_begin(struct ethosu_driver *drv, void *user_arg)
{
    ++application_notifications;
    trace_ethosu_inference_begin(drv, user_arg);
}
#endif

int ethosu_request_power(struct ethosu_driver *drv)
{
    assert(drv == &driver);
    ++power_references;
    return 0;
}
void ethosu_release_power(struct ethosu_driver *drv)
{
    assert(drv == &driver && power_references > 0);
    --power_references;
}
void ETHOSU_PMU_Enable(struct ethosu_driver *drv) { ethosu_request_power(drv); }
void ETHOSU_PMU_Disable(struct ethosu_driver *drv) { ethosu_release_power(drv); }
void ETHOSU_PMU_Set_EVTYPER(struct ethosu_driver *drv, uint32_t n, enum ethosu_pmu_event_type event)
{
    (void)drv;
    (void)n;
    (void)event;
}
void ETHOSU_PMU_Set_EVCNTR(struct ethosu_driver *drv, uint32_t n, uint32_t value)
{
    (void)drv;
    (void)n;
    (void)value;
}
void ETHOSU_PMU_CNTR_Enable(struct ethosu_driver *drv, uint32_t mask)
{
    (void)drv;
    enabled |= mask;
}
void ETHOSU_PMU_CNTR_Disable(struct ethosu_driver *drv, uint32_t mask)
{
    (void)drv;
    enabled &= ~mask;
}
uint32_t ETHOSU_PMU_CNTR_Status(struct ethosu_driver *drv)
{
    (void)drv;
    return enabled;
}
uint32_t ETHOSU_PMU_Get_EVCNTR(struct ethosu_driver *drv, uint32_t n)
{
    assert(drv == &driver);
    return ticks + n;
}
uint32_t ETHOSU_PMU_Get_QREAD(struct ethosu_driver *drv)
{
    assert(drv == &driver);
    return qread;
}
uint32_t ETHOSU_PMU_Get_STATUS(struct ethosu_driver *drv)
{
    assert(drv == &driver);
    return status;
}
uint32_t profiler_port_timestamp(void) { return ticks * 1000U; }
uint32_t profiler_port_ticks(void) { return ticks; }
void profiler_port_barrier(void) {}
void profiler_port_flush(const void *address, uint32_t bytes)
{
    assert(address == (const void *)&ethosu_trace_samples && bytes == sizeof(ethosu_trace_samples));
}
static void submit(unsigned index)
{
    status = 0U;
    driver.job.custom_data_ptr = payloads[index];
    driver.job.custom_data_size = sizeof(payloads[index]);
    ethosu_inference_begin(&driver, NULL);
    status = 1U;
    qread = 4U;
}
static void sample(uint32_t expected_id)
{
    uint32_t before = ethosu_trace_samples.header.count;
    uint32_t stride = ethosu_trace_samples.header.record_bytes / 4U;
    ++ticks;
    profiler_aux_sample(profiler_port_timestamp(), ticks);
    assert(ethosu_trace_samples.header.count == before + 1U);
    assert(ethosu_trace_samples.records[before * stride + 4U] == expected_id);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    struct ethosu_driver other_driver = {0};

    assert(trace_ethosu_bind(&driver));
    assert(trace_ethosu_start());
    /* Rejected binding changes must leave sampling and cleanup on driver. */
    assert(!trace_ethosu_bind(&other_driver));
    assert(!trace_ethosu_bind(NULL));
    assert(!trace_ethosu_bind(&driver));
    /* Starting during an inference has no observed begin callback yet. */
    status = 1U;
    qread = 4U;
    sample(0U);
    submit(0);
    sample(1U);
    submit(1);
    sample(2U);
    submit(0);
    sample(1U);
    assert(ethosu_trace_samples.header.stream_count == 2U);
    assert(ethosu_trace_samples.streams[0].stream_bytes == 16U);
    assert(ethosu_trace_samples.streams[0].command_address == (uint32_t)(uintptr_t)&payloads[0][4]);
    /* Capacity exhaustion preserves known IDs and never aliases a new stream. */
    submit(2);
    sample(0U);
    submit(1);
    qread = 20U;
    sample(2U);
    assert(ethosu_trace_samples.header.invalid_qread == 1U);
    assert(ethosu_trace_samples.header.unregistered_streams == 1U);
    /* Malformed lengths and negative driver sizes must not reuse the last ID. */
    driver.job.custom_data_size = 4;
    ethosu_inference_begin(&driver, NULL);
    sample(0U);
    driver.job.custom_data_size = -1;
    ethosu_inference_begin(&driver, NULL);
    sample(0U);
    assert(ethosu_trace_samples.header.unregistered_streams == 3U);
    status = 0U;
    uint32_t capacity = sizeof(ethosu_trace_samples.records) / ethosu_trace_samples.header.record_bytes;
    while (ethosu_trace_samples.header.count < capacity)
        sample(0U);
    profiler_aux_sample(0, 0);
    assert(trace_ethosu_full());
    assert(!trace_ethosu_bind(&other_driver));
    assert(!trace_ethosu_bind(NULL));
    trace_ethosu_stop(1, 1);
    assert(power_references == 0 && enabled == 0U);
    FILE *output = fopen(argv[1], "wb");
    assert(output);
    assert(fwrite((const void *)&ethosu_trace_samples, 1, sizeof(ethosu_trace_samples), output) ==
           sizeof(ethosu_trace_samples));
    assert(fclose(output) == 0);
    /* Once stopped, rebinding and detaching are allowed. */
    assert(trace_ethosu_bind(&other_driver));
    assert(trace_ethosu_bind(NULL));
    assert(!trace_ethosu_start());
    assert(power_references == 0);
    assert(trace_ethosu_bind(&driver));

    /* Restart resets IDs and diagnostics, rather than retaining stale metadata. */
    assert(trace_ethosu_start());
    assert(ethosu_trace_samples.header.stream_count == 0U);
    assert(ethosu_trace_samples.header.unknown_stream_samples == 0U);
    submit(1);
    sample(1U);
    trace_ethosu_stop(1, 1);
    trace_ethosu_stop(1, 1);
    assert(power_references == 0);
#if !PROFILER_ETHOSU_DRIVER_CALLBACK
    assert(application_notifications == 8U);
#endif
    return 0;
}
