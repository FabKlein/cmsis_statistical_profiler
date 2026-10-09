# Ethos-U statistical trace

This optional companion layer samples Ethos-U55, U65, or U85 from the Cortex-M
profiler timer interrupt. It uses the public `ethosu_driver.h` and
`pmu_ethosu.h` APIs from the matching Arm core-driver pack. It has a separate
buffer and does not use Cortex-M sample capacity.

Add `ethosu_trace.clayer.yml` to the image that owns the NPU driver. Set these
application definitions in its `PROFILER_USER_CONFIG` header:

```c
#define PROFILER_ETHOSU_TRACE 1
#define PROFILER_AUX_SAMPLE_HOOK PROFILER_ETHOSU_TRACE
#define PROFILER_ETHOSU_TRACE_BUFFER_BYTES (128U * 1024U)
#define PROFILER_ETHOSU_BUFFER_ATTRIBUTES __attribute__((section(".bss.ethosu_trace"), aligned(32)))
#define PROFILER_ETHOSU_PMU_COUNT 0 /* 0..4 */
#define PROFILER_ETHOSU_MAX_STREAMS 16 /* Default; 1..64 distinct streams per capture. */
/* For PMU collection, select events using ethosu_pmu_event_type names.
 * These four names exist on U55, U65, and U85. */
#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT1 ETHOSU_PMU_MAC_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT2 ETHOSU_PMU_MAC_DPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT3 ETHOSU_PMU_CYCLE
```

Event selections are **driver enum IDs**, not TRM register encodings. The shared
[host catalog](../../host/ethosu_pmu_events.py) maps U55/U65/U85 IDs to official
symbols and hardware encodings from Arm core-driver 1.26.2, with links to the TRMs.
The decoder and inference fold use this catalog for any selected combination;
unknown IDs retain numeric labels. Captures do not identify the driver version,
so check that the catalog matches your firmware's driver.

Reserve the buffer's linker section in memory accessible to the sampling core
and debugger. Do not overlap the Cortex-M profiler buffer, stack, heap, another
core's allocation, or the NPU's scratch memory. Call `trace_ethosu_bind(drv)`
after driver setup, `trace_ethosu_start()` after `profiler_init()`, and
`trace_ethosu_stop(iterations, validation_passed)` before stopping/exporting the
CPU profiler. The adapter holds an Ethos-U power reference while active so its
register state survives inference calls. This changes power behavior during a
capture. By default, the adapter supplies `ethosu_inference_begin`, forwarding
to `trace_ethosu_inference_begin` before each command-stream submission.

Serialize bind/start/stop calls in privileged thread mode on 1 core.
`trace_ethosu_bind()` returns 1 on success or 0 while started, leaving the
original driver selected. Stop before rebinding, even when the buffer is full:
power references and PMU resources still belong to the original device until
stop releases them. Passing `NULL` detaches the driver only while stopped.
This guard does not provide locking between concurrent callers.

If the application already owns that driver callback, set this in its shared
`PROFILER_USER_CONFIG` header (so the adapter sees it too):

```c
#define PROFILER_ETHOSU_DRIVER_CALLBACK 0
```

Then forward exactly once from the existing callback:

```c
#include "ethosu_trace.h"

void ethosu_inference_begin(struct ethosu_driver *drv, void *user_arg)
{
    /* Keep existing application callback work here. */
    trace_ethosu_inference_begin(drv, user_arg);
}
```

The public trace API uses `trace_ethosu_bind/start/stop/full/inference_begin`.
The driver callback and `profiler_aux_sample` retain their required integration
names. There must be only 1 definition of the driver callback.

Streams are discovered automatically from the runtime's submitted COP1 payloads.
The application does not need their pointers or sizes. Repeated submissions of
an identical command-stream address and length reuse the same capture-local ID:

```text
runtime submits A -> ID 1 -> sample: stream 1, QREAD 128
runtime submits B -> ID 2 -> sample: stream 2, QREAD 128
runtime submits A -> ID 1 -> sample: stream 1, QREAD 256
```

**Keep command-stream memory unchanged during capture.** Addresses identify
allocations, not contents; replacing a stream in place cannot be detected. IDs
do not identify network names or individual inference runs. The table records
CPU-visible command addresses, which can differ from NPU QBASE after remapping.

The EUTR format stores little-endian 32-bit words (see `ethosu_trace.h`):

```text
128-byte header
  + fixed stream table: MAX_STREAMS x 8 bytes (command address, byte length)
  + running: timestamp, tick, STATUS, QREAD,      stream_id,  optional PMU[0..3]
  + idle:    timestamp, tick, STATUS, 0xffffffff, idle_count, optional PMU[0..3]
```

The table consumes 128 bytes at the default 16-stream limit, inside the configured
buffer allocation. Each record costs 20..36 bytes. IDs are 1-based table indices;
unused descriptors are zero. This is the initial EUTR format (identifier 1);
firmware and decoder use the same layout.

Consecutive idle samples always share 1 record. STATUS bit 0 selects the meaning
of word 4: stream ID when running, nonzero idle count otherwise. Every idle tick
updates the last record with the latest timestamp, tick, STATUS and PMU values.
A count of `UINT32_MAX` starts a new record on the next idle tick. An idle run
can grow in the final buffer slot; capture becomes full when a new record is
needed and cannot fit.

The timer still samples at the configured rate. Intermediate idle snapshots are
discarded, including PMU values; multiple counter wraps across a long idle run
cannot be recovered from its final snapshot. A short inference entirely between
sampling ticks can still be missed. Stop before exporting the mutable buffer.

`header.count` counts stored records, not sampling ticks. The host keeps 1 CSV
row per record, with `idle_count` (0 when running) and `sample_count` (1 when
running, otherwise the idle count). Summary fields `total_samples`,
`idle_samples` and `running_samples` count represented ticks; utilization and
histogram percentages use those weights. For example, 80 idle ticks followed by
20 running ticks use 21 records and report 20% running.

For running records, `stream_id=0` means unknown: capture began mid-inference, payload parsing
failed, the table filled, or submission changed during the register snapshot.
Unknown running samples are counted in `unknown_stream_samples` and excluded
from QREAD hotspots. `unregistered_streams` counts submissions that could not be
registered. Existing IDs remain usable when the table fills; capture restart
clears the table. Lookup and registration run in the driver callback, not the
sampling ISR; sampling reads an already published ID and its descriptor.

`timestamp` uses the CPU profiler timestamp source; `tick` is the timer tick count.
QREAD is a command-stream byte offset, not a program counter or operator ID.
It may pass the faulting command before an error is reported. `0xffffffff` means
idle or invalid QREAD. Known IDs allow validation against that stream's length;
aligned raw QREAD is retained for unknown IDs without an inferred upper bound.
The header records the device type (55/65/85) because event enum values differ.
PMU snapshots are cumulative 32-bit counters; wrapped interval deltas cover all
execution between samples and must not be attributed to a single operator.

When PMU collection is requested, the adapter leaves it disabled if another
counter is enabled or the NPU is running at start. Read `pmu_status` and
`pmu_count` before interpreting records.

**PMU collection requires exclusive ownership until `trace_ethosu_stop()` returns,**
even if the buffer fills earlier. The application and other tools must not
reconfigure, reset, enable or disable the Ethos-U PMU during that interval.
The adapter checks availability only at start; later changes are not detected.
They can leave counts labelled with the wrong events or make resets look like
large wraparound deltas. Stop disables the counters acquired by the profiler;
it does not preserve an application's intervening configuration.

If the application needs PMU ownership, set `PROFILER_ETHOSU_PMU_COUNT=0`.
STATUS/QREAD sampling remains available without configuring or disabling PMU
counters.

Driver debug logging must be disabled for ISR-safe sampling (the core driver's default severity is WARN). Stop
profiling before exporting the entire `ethosu_trace_samples` symbol through the
supported CMSIS debugger interface:

```gdb
source tools/export_ethosu_trace_buffer.gdb
export_ethosu_trace_buffer ethosu_trace.bin
```

Then run:

```sh
python3 host/analyze_ethosu_trace.py --samples ethosu_trace.bin --output ethosu_report
```

The decoder requires a stopped, complete capture and validates flags, clocks,
PMU metadata, allocation/count consistency and QREAD alignment/state. Invalid
dumps fail before reports are written. Finalized full buffers and failed workload
validation remain inspectable. Stream IDs, descriptor bounds and diagnostic
counts are checked before output is written.

The decoder creates `summary.json`, `streams.csv`, `samples.csv`, and
`qread_histogram.csv`. The histogram groups by `(stream_id, qread_bytes)` and
sorts by sample count, keeping identical offsets in different streams separate.
Idle samples, unknown streams and invalid QREAD values are excluded. Percentages
use all running samples or all samples as denominators, including excluded ones.
Sampling percentages approximate time at a steady timer rate,
but QREAD is a command-stream position, not an operator name. `complete=1`,
`active=0`, `full=0`, and `invalid_qread=0` indicate a well-formed complete
capture; they do not establish that the requested duration ran or that the
sampled offsets identify operators. Match the dump to the exact firmware image
and use the Vela command-stream metadata separately when correlating offsets
with operators.
