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
/* For PMU collection, select events using ethosu_pmu_event_type names.
 * These four names exist on U55, U65, and U85. */
#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT1 ETHOSU_PMU_MAC_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT2 ETHOSU_PMU_MAC_DPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT3 ETHOSU_PMU_CYCLE
```

Reserve the buffer's linker section in memory accessible to the sampling core
and debugger. Do not overlap the Cortex-M profiler buffer, stack, heap, another
core's allocation, or the NPU's scratch memory. Call `ethosu_trace_bind(drv)`
after driver setup, `ethosu_trace_start()` after `profiler_init()`, and
`ethosu_trace_stop(iterations, validation_passed)` before stopping/exporting the
CPU profiler. The adapter holds an Ethos-U power reference while active so its
register state survives inference calls. This changes power behavior during a
capture. The driver calls the adapter's `ethosu_inference_begin` callback just
before each inference to identify the submitted COP1 command-stream length.
Applications that already override this weak driver callback must forward the
notification or supply an equivalent bound; only one callback definition can
link.

The EUTR v1 buffer starts with a 128-byte header of little-endian `uint32_t`
fields (see `ethosu_trace.h`). Records contain `timestamp`, `tick`, `STATUS`,
`QREAD`, then zero to four 32-bit NPU PMU counters. `timestamp` shares the CPU
profiler's DWT clock; `tick` is the timer tick count. QREAD is a byte offset
within the command stream, not a program counter or operator ID. It may pass
the faulting command before an error is reported. `0xffffffff` means QREAD was
not read because the NPU was idle or its value was invalid. `stream_bytes=0`
means the COP1 stream length could not be established; aligned raw QREAD is
still captured. The header stores the driver device type (55/65/85) because
event enum numbers differ by variant. PMU counters are cumulative 32-bit
snapshots; compute wrapped deltas to inspect intervals. They can count work
between samples and must not be attributed to a single operator.

When PMU collection is requested, the adapter leaves it disabled if another
counter is enabled or the NPU is running at start. Read `pmu_status` and
`pmu_count` before interpreting records. Driver debug logging must be disabled
for ISR-safe sampling (the core driver's default severity is WARN). Stop
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

The decoder creates `summary.json`, `samples.csv`, and `qread_histogram.csv`.
The histogram groups valid running samples by exact QREAD byte offset and sorts
by sample count. Idle samples and unavailable/invalid QREAD values have no
offset and are excluded; the CSV reports percentages of both running samples
and all samples. Sampling percentages approximate time at a steady timer rate,
but QREAD is a command-stream position, not an operator name. `complete=1`,
`active=0`, `full=0`, and `invalid_qread=0` indicate a well-formed complete
capture; they do not establish that the requested duration ran or that the
sampled offsets identify operators. Match the dump to the exact firmware image
and use the Vela command-stream metadata separately when correlating offsets
with operators.
