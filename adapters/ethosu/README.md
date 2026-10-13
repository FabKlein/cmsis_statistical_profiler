# Ethos-U statistical trace

Optional U55/U65/U85 sampling from the Cortex-M profiler timer, using the matching
Arm core-driver's `ethosu_driver.h`/`pmu_ethosu.h`. Add `ethosu_trace.clayer.yml`
to the NPU-owning image. The trace has a separate buffer and CPU capacity.

## Configuration

Set definitions project-wide in the application's `PROFILER_USER_CONFIG`:

```c
#define PROFILER_ETHOSU_TRACE 1
#define PROFILER_AUX_SAMPLE_HOOK PROFILER_ETHOSU_TRACE
#define PROFILER_ETHOSU_TRACE_BUFFER_BYTES (128U * 1024U)
#define PROFILER_ETHOSU_BUFFER_ATTRIBUTES __attribute__((section(".bss.ethosu_trace"), aligned(32)))
#define PROFILER_ETHOSU_PMU_COUNT 0 /* 0..4 */
#define PROFILER_ETHOSU_MAX_STREAMS 16 /* 1..64 */
#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT1 ETHOSU_PMU_MAC_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT2 ETHOSU_PMU_MAC_DPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT3 ETHOSU_PMU_CYCLE
```

Events are device-specific **driver enum IDs**, not TRM encodings. Reuse the
[host catalog](../../host/ethosu_pmu_events.py), based on core-driver 1.26.2;
headers do not verify driver version. Unknown IDs remain numeric and repeated
counter slots remain distinct. Build the driver with `ETHOSU_LOG_ENABLE=0`
project-wide: its PMU getters run in the sampling ISR.

Reserve accessible, debugger-readable linker storage separate from CPU buffers,
stacks, heap, other cores and NPU scratch memory. Generate the shared
[build header](../../docs/CONFIGURATION.md#shared-build-configuration) for CPU/NPU identity.

## Lifecycle and callback

In privileged thread mode on one core, serially:

1. Set up the driver, then `trace_ethosu_bind(drv)`.
2. Call `profiler_init()`, `trace_ethosu_start()`, then enable sampling.
3. Run the workload, call `trace_ethosu_stop(iterations, validation_passed)`,
   then stop the CPU profiler before export.

The active adapter holds a power reference, changing capture power behavior.
Bind returns 0 while started, preserving the original driver. Full does not
release resources; stop before rebinding. Bind `NULL` detaches only while stopped.
These guards do not synchronize concurrent callers.

Stop finalizes sampling; it does not stop NPU execution. For debugger uploads
and capture restarts, see [capture-boundary limitations](../../docs/REPEATED_CAPTURES.md#ethos-u-execution-during-debugger-uploads).

By default the adapter defines `ethosu_inference_begin`. If an application already
owns it, set `PROFILER_ETHOSU_DRIVER_CALLBACK=0` project-wide and forward once:

```c
#include "ethosu_trace.h"
void ethosu_inference_begin(struct ethosu_driver *drv, void *user_arg)
{
    /* Existing application callback work. */
    trace_ethosu_inference_begin(drv, user_arg);
}
```

Use `trace_ethosu_*`; driver callback/auxiliary-hook integration names remain fixed.
There must be exactly one callback definition. Callback-time COP1 discovery
registers immutable command addresses/lengths automatically; no application
registration. Repeated address/length pairs reuse capture-local IDs. Never replace
stream contents in place: addresses identify allocations, not contents, models or
inference invocations. CPU-visible addresses can differ from remapped NPU QBASE.

## EUTR format and interpretation

Little-endian words; current version 1 is the sole supported layout:

```text
144-byte header
  + stream table: MAX_STREAMS * 8 bytes (command address, length)
  + running record: timestamp, tick, STATUS, QREAD,      stream_id,  optional PMU
  + idle record:    timestamp, tick, STATUS, 0xffffffff, idle_count, optional PMU
```

The default table costs 128 bytes within the allocation. Records cost 20–36 bytes;
IDs are one-based indices, unused descriptors zero. Header words 30/31 hold actual
timer Hz/period; words 32–35 hold the build token. Startup clears header/table only;
old record tails remain undefined. Export the full allocation after stop; `count`
and `record_bytes` bound committed records. See [ethosu_trace.h](ethosu_trace.h).

STATUS bit 0 selects running/idle. Consecutive idle ticks share one record updated
to the latest timestamp/tick/PMU snapshot; `idle_count=UINT32_MAX` starts another.
Idle can grow in the final slot; full occurs when a new record cannot fit.
`count` counts records, not ticks. CSV has `idle_count` and represented
`sample_count`; totals/percentages weight represented ticks. Eighty idle ticks
plus twenty running ticks use 21 records and report 20% running.

Sampling uses actual `timer_hz / timer_period`. Intermediate idle snapshots are
lost; multiple PMU wraps cannot be recovered. Entire short inferences between
ticks can be missed. Timestamp/tick share the CPU profiler sources. QREAD is a
command byte position, not a PC/operator; it can pass a faulting command.
`0xffffffff` denotes idle/invalid QREAD.

Running stream ID 0 means unknown: mid-inference start, payload failure, full table
or changed submission during the snapshot. Unknown samples stay in totals but
not hotspots. `unregistered_streams` counts failed registrations; existing IDs
remain usable until restart clears the table. Registration runs in the callback,
not ISR. Known stream lengths bound QREAD; unknown offsets retain alignment
validation without an invented upper bound.

## PMU ownership

Collection needs exclusive ownership until `trace_ethosu_stop()` returns, including
after full. Do not reconfigure/reset/enable/disable the PMU during that interval;
later interference is undetected and can mislabel events or resemble huge wraps.
Set `PROFILER_ETHOSU_PMU_COUNT=0` when application-owned; QREAD remains available.

Enabled counters, armed PMU IRQs or a running NPU cause busy fallback without
altering existing configuration. Invalid event constants fail compilation.
Acquisition checks capacity, stops the owned mask, disables its IRQs, clears
its overflows and checks event readback. Failure closes the gate and releases
power references. Stop cleans up according to internal ownership, independent
of exported header fields; it does not preserve intervening application changes.
Inspect `pmu_status`/`pmu_count` before interpreting cumulative 32-bit snapshots.
Deltas cover all intervening execution, not individual operators.

## Export and decode

After both CPU/NPU captures are finalized, export the entire allocation:

```gdb
source tools/export_ethosu_trace_buffer.gdb
export_ethosu_trace_buffer ethosu_trace.bin
```

```sh
python3 host/analyze_ethosu_trace.py \
  --samples ethosu_trace.bin --elf firmware.elf --output ethosu_report
```

The decoder checks stopped/complete state, clocks/flags, PMU metadata,
allocation/count consistency, streams and QREAD before output. Full buffers and
failed workload validation remain inspectable. `--elf` verifies the shared token;
omitting it records a nonzero token as unverified, zero as unavailable.

Outputs: `summary.json`, `streams.csv`, `samples.csv`, `qread_histogram.csv`.
Histograms group by `(stream_id, qread_bytes)`, keeping identical offsets in
different streams separate; idle/unknown/invalid QREAD is excluded while all
running/all ticks remain percentage denominators. Finalization and valid offsets
do not prove duration or operator identity. Follow
[repeated captures](../../docs/REPEATED_CAPTURES.md) and
[exact PTE/Vela alignment](../../docs/ETHOSU_OPERATOR_REPORTS.md) for attribution.
