# Repeated Cortex-M and Ethos-U captures

Use this workflow for CPU, NPU or synchronized captures. Run commands from the
repository root; see [host dependencies](HOST_TOOLS.md#python-and-dependencies).
Keep exact ELFs, profiler revision, raw allocations and decoded reports per capture.

## 1. Stop, export and resume

1. Reserve physically separate CPU/NPU buffers and choose rate, allocation sizes,
   capture count and stop condition. Follow the [Ethos-U lifecycle](../adapters/ethosu/README.md);
   NPU-only capture still needs the CPU timer/clock setup.
2. Initialize, start and run the workload. Finalize both enabled captures when either
   buffer fills or the window ends. Expose the completion breakpoint/capture ID only
   after both stops return and before either buffer is reused.
3. Halt there; verify each header has `complete=1`, `active=0`, plausible clocks/counts,
   diagnostics and workload validation. Full does not imply finalized. A breakpoint
   before the completion assignment may be too early: trust the headers.
4. Export and decode while halted. Resume only after validating the saved capture.

Use the [CPU](../tools/export_profiler_buffer.gdb) and
[NPU](../tools/export_ethosu_trace_buffer.gdb) GDB helpers with the matching ELF.
Never read a running buffer, concatenate raw captures or count debugger pauses
as sampling time. Capture-local ticks and stream IDs must retain their boundaries.

### Ethos-U execution during debugger uploads

Stopping the profiler or halting Cortex-M does not pause Ethos-U execution.
The NPU can finish an outstanding command stream while sampling is stopped and
the buffers are exported. Restarting capture may therefore observe idle or the
remaining part of a running stream. Restart clears the stream table; an already
running stream stays unknown until a new submission callback registers a stream.
With PMU enabled, restarting while the NPU is running also causes busy fallback.
`complete=1` means the capture was finalized, not that its last inference completed.

The combined Perfetto timeline retains captured CPU/NPU observations and marks
each window boundary. Debugger pauses are omitted from presentation time;
adjacent windows do not establish continuous workload execution. Missing NPU
activity cannot be reconstructed, and boundary display zeros do not establish
hardware idle. Do not join bursts or calculate PMU deltas across captures.

For comparisons, use the [MCU/NPU folds](#6-fold-mcu-and-ethos-u-by-inference).
Both exclude the first and last observed running bursts in each capture and
retain interior periods using the same selection. This conservatively excludes
potentially partial bursts, including some that may actually be complete.
It does not identify exact driver invocations: submissions without sampled idle
can merge, and short executions can be missed. Keep full CPU/NPU reports and
Perfetto observations; the exclusions apply to folded statistics, not raw totals.
The profiler does not suspend workload execution or require application changes
to hide these discontinuities.

## 2. Reconstruct and decode full allocations

Preserve one complete allocation per enabled processor and capture. For chunked
reads, check addresses and returned byte lengths; reject gaps, overlaps and short
reads before writing chunks in address order. The required populated prefix is:

| Buffer | Prefix length |
|---|---|
| CPU | `header_bytes + bytes_used` |
| NPU | `header_bytes + 8 * stream_capacity + count * record_bytes` |

Validate headers, descriptors and prefix length against `buffer_bytes` first.
Only the unused tail may be zero-padded when reconstructing a full-sized export.
Startup clears metadata, not record storage: unused bytes can contain old data.
Padding reconstructs irrelevant tail space; it does not reproduce its original
bytes. Never pad missing headers, stream tables or committed records.

```text
run/
  firmware.axf
  capture_00/{cortex_m.bin,ethosu.bin,cortex_m_report/,ethosu_report/}
  capture_01/{cortex_m.bin,ethosu.bin,cortex_m_report/,ethosu_report/}
```

Decode each saved buffer with its matching revision and exact executable:

```sh
python3 host/analyze_profiler_buffer.py \
  --samples run/capture_00/cortex_m.bin --elf run/firmware.axf \
  --output run/capture_00/cortex_m_report
python3 host/analyze_ethosu_trace.py \
  --samples run/capture_00/ethosu.bin --elf run/firmware.axf \
  --output run/capture_00/ethosu_report
```

Repeat for each capture. Inspect decoded finalization, timing, rejected frames,
unresolved PCs, PMU status and workload validation before aggregation.

## 3. Aggregate decoded reports

```sh
python3 host/aggregate_profiler_captures.py --input-dir run --output-dir run/aggregate
```

Discovery orders numeric `capture_*` directories; use CLI pattern/explicit-input
options for other layouts. Every capture must provide the same enabled processors
and compatible format, clock, PMU-slot/event and firmware metadata. Empty finalized
captures are valid; an empty NPU stream table does not constrain later streams.
Stream aggregation requires matching IDs, CPU-visible addresses and lengths;
otherwise analyze separately rather than guessing equivalence.

Outputs include `captures.csv`, `summary.json` and combined processor sample/histogram
tables with capture indices. Totals weight NPU compressed idle records by represented
ticks. `capture_configuration` contains shared settings, not per-capture counters.
Manifest paths are relative to the aggregate directory; preserve layout on relocation.
Treat the manifest as trusted input. Use its numeric capture indices in later folds.

For CPU hotspots and optional backtrace graphs:

```sh
python3 host/generate_aggregate_mcu_report.py --run-dir run/aggregate \
  --flamegraph /path/to/FlameGraph/flamegraph.pl
```

Set `--stack-root NAME` consistently when decoding each CPU capture. Omit
`--flamegraph` for PC-only captures; when backtraces exist supply Brendan Gregg's external renderer. The all-PC view
keeps missing-root and unreliable callers separate while retaining their PC hits.
Graph widths count included recovered stacks; empty graphs are omitted. Renderer
hash/provenance is recorded.

Generation stages before replacing its owned `mcu_report/` directory; failures
preserve the previous report, with recovery paths reported if rollback fails.
Keep supplemental artifacts outside that directory. CPU/NPU-only runs generate
only applicable views; PMU-disabled runs omit PMU panels.

## 4. Match TOSA/Vela operations to QREAD

Follow the [operator report workflow](ETHOSU_OPERATOR_REPORTS.md) for exact PTE
unwrapping, Vela mapping/alignment, operator charts and optional sampled phases.
TOSA alone cannot label QREAD. Only run `summarize_tosa_operators.py` after
alignment passes. Supplied-file hashes do not establish deployed firmware identity.

## 5. Build an offline report index

Keep a human Markdown summary and generate the index after all optional artifacts.
Use the shared [index and platform schema](HOST_TOOLS.md#report-index-and-platform-metadata).
For repeated CPU captures, generate a combined timeline first:

```sh
python3 host/combine_perfetto_captures.py --run-dir run/aggregate
# Use this alternative when every capture has synchronized CPU/NPU reports:
python3 host/combine_perfetto_captures.py --run-dir run/aggregate --include-ethosu
python3 host/generate_report_index.py \
  --run-dir run/aggregate --board "<actual board or simulator>" \
  --application "<application name>"
```

CPU-only output is `cortex_m_combined.perfetto.json`; CPU/NPU output is
`combined.perfetto.json`, which the index prefers. NPU-only runs omit these CPU-based
exports. Windows are placed end-to-end by active duration, with explicit boundaries,
no debugger pauses and no cross-window PMU intervals.

Including Ethos-U requires finalized CPU/NPU reports in every capture, shared
clock metadata and identical timestamps at overlapping ticks. NPU windows must
fit within CPU epochs; unverifiable alignment rejects generation before writing.
NPU STATUS/stream/QREAD snapshots remain observations, not inference durations.
Compressed idle retains the latest snapshot and represented idle count.

NPU PMU tracks are labelled **idle-clamped**: they display zero from the first
sampled idle tick to the next running sample and at window boundaries. That first
idle time uses the CPU sample or a labelled timer-period estimate. Snapshot details
retain measured preceding-interval rates, including idle. Display zeros are not
hardware measurements; events can count while idle. Wrapped deltas require fewer
than 2^32 increments between retained snapshots. Unknown streams/QREAD stay explicit.

Serve the index through the [localhost helper](HOST_TOOLS.md#report-index-and-platform-metadata)
for its automatic Perfetto control; `file://` cannot transfer the trace. Preserve
raw buffers and decoded reports, verify every local link and regenerate when
artifacts change.

## 6. Fold MCU and Ethos-U by inference

```sh
python3 host/fold_mcu_by_ethosu.py --run-dir run/aggregate --pre-ms 0 --post-ms 40
python3 host/fold_ethosu_by_inference.py --run-dir run/aggregate
python3 host/plot_joint_mcu_ethosu.py --run-dir run/aggregate
```

The MCU fold anchors CPU PC/PMU samples on the first running NPU tick. The NPU
fold groups complete running bursts. Shared ticks/timestamps, actual
`timer_hz / timer_period`, compatible firmware metadata and observed window
overlap must validate. Tick normalization is modulo 2^32; ambiguous half-range
backward jumps and cumulative timing drift reject the fold. Retain the preceding
PMU baseline but never bridge capture boundaries or debugger pauses.

Exclude capture-edge periods and report each phase's eligible inference/sample
coverage. Shorter periods reduce later-phase populations; absent observations
remain blank, not measured zero. Approximate confidence bands do not bound
sampling error. A running burst without an observed idle gap may contain several
inferences; it cannot establish an exact invocation count.

| Fold | Main outputs/semantics |
|---|---|
| MCU | `mcu_folded_summary.json`, function/phase tables, inference windows and SVG/PNG; preserve original function mix |
| NPU | Activity SVG/PNG even without PMU; optional inference PMU table/plots |
| Joint | CPU function/activity and available CPU/NPU PMU panels on one phase axis |

MCU PMU columns are keyed by slot (`pmu0_mean`, `pmu0_ci95`, `pmu0_intervals`, etc.);
`cpu_pmu_events` identifies slots/events. Repeated events stay separate; joint
columns use `mcu_pmu0_mean`, etc. Aggregate totals are valid only when every capture
is valid; otherwise totals remain null with partial sums/statuses reported.
NPU labels use [driver enum IDs](../host/ethosu_pmu_events.py), not raw TRM codes;
unknown IDs stay numeric. Generic `*_cycles` fields can hold non-cycle events.

Non-idle PC share requires explicit platform idle functions/half-open PC ranges.
`--idle-function NAME` replaces platform function names but preserves its ranges;
put the same selection in `platform.json` for index consistency. No RTOS idle name
is assumed. Idle classification does not change displayed function names or prove
that the CPU stopped. PMU intervals stay separate from PC/QREAD attribution.

Joint plots require matching capture and per-phase inference counts, intersect
phase coverage and keep each PMU counter separate. Distinct CPU/NPU clocks are
allowed; verified fixed `npu_clock_hz` alone enables active-cycle-to-ms conversion.
Compressed-idle PMU deltas are retained-interval observations; later phase display
zeros are not measured zero counts. Unknown/invalid QREAD still contributes to
running activity/PMU, while operator timing remains unavailable.

Negative pre-context can reuse CPU samples from a previous positive phase; folded
counts are not unique raw-sample totals. Match pre-context settings when comparing
folds. Highlighted spans are sampled/inferred spans, not call entry/exit. Separated
PC segments may be one preempted call: check raw chains and scheduling context
before counting calls, preserve gaps and label inferred spans. Regenerate the
[index](HOST_TOOLS.md#report-index-and-platform-metadata) after adding folds.
