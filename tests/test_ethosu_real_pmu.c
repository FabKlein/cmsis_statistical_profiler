/* SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * SPDX-License-Identifier: Apache-2.0 */
#include "ethosu_driver.h"
#include "ethosu_interface.h"
#include "ethosu_trace.h"
#include "pmu_ethosu.h"
#include "sampling_profiler_port.h"
#include <assert.h>

/* Real driver register accesses in RAM: alias writes are observed, not emulated.
 * Power is already held, so this models acquisition without a first-power reset. */
static struct NPU_REG registers;
static struct ethosu_driver driver;
const uint32_t profiler_firmware_id[4] = {1U, 2U, 3U, 4U};
int ethosu_request_power(struct ethosu_driver *drv)
{
    ++drv->power_request_counter;
    return 0;
}
void ethosu_release_power(struct ethosu_driver *drv)
{
    assert(drv->power_request_counter);
    --drv->power_request_counter;
}
int profiler_port_clock(struct ProfilerClock *clock)
{
    *clock = (struct ProfilerClock){1000000U, 1000U, 1000000U};
    return 1;
}
uint32_t profiler_port_timestamp(void) { return 1000U; }
uint32_t profiler_port_ticks(void) { return 1U; }
void profiler_port_barrier(void) {}
void profiler_port_flush(const void *address, uint32_t bytes)
{
    (void)address;
    (void)bytes;
}
int main(void)
{
    driver.dev.reg = &registers;
    driver.power_request_counter = 1U;
    registers.PMEVTYPER[0].word = 0x1234U;
    registers.PMINTSET.word = 1U;
    assert(trace_ethosu_bind(&driver) && trace_ethosu_start());
    assert(ethosu_trace_samples.header.pmu_status == ETHOSU_TRACE_PMU_BUSY);
    assert(!ethosu_trace_samples.header.pmu_count);
    assert(registers.PMEVTYPER[0].word == 0x1234U && registers.PMINTSET.word == 1U);
    trace_ethosu_stop(1U, 2U);
    assert(driver.power_request_counter == 1U && registers.PMINTSET.word == 1U);
    assert(ethosu_trace_samples.header.validation_passed == 1U);
    registers.PMINTSET.word = 0U;
    registers.PMCNTENSET.word = 1U;
    assert(trace_ethosu_start() && ethosu_trace_samples.header.pmu_status == ETHOSU_TRACE_PMU_BUSY);
    trace_ethosu_stop(1U, 1U);
    assert(registers.PMEVTYPER[0].word == 0x1234U);
    registers.PMCNTENSET.word = 0U;
    registers.PMOVSSET.word = 1U;
    assert(trace_ethosu_start());
    assert(ethosu_trace_samples.header.pmu_status == ETHOSU_TRACE_PMU_ACTIVE);
    assert(ETHOSU_PMU_Get_EVTYPER(&driver, 0U) == PROFILER_ETHOSU_PMU_EVENT0);
    assert(registers.PMINTCLR.word == 1U && registers.PMOVSCLR.word == 1U);
    assert(driver.power_request_counter == 3U);
    trace_ethosu_stop(1U, 1U);
    assert(driver.power_request_counter == 1U && registers.PMCNTENCLR.word == 1U);
    assert(registers.PMCR.word == 0U);
    return 0;
}
