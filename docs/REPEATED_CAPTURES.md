# Repeated Cortex-M and Ethos-U statistical profiling

This runbook applies to firmware using `cmsis_statistical_profiler` and its
optional Ethos-U trace adapter. It covers repeated captures, reconstruction of
each complete binary buffer, aggregation of decoded reports, and attribution
of Ethos-U QREAD samples to Vela operations. The application supplies the
timer, memory placement, workload, stop condition, and the mechanism that
starts another capture. The profiler library does not automatically iterate
captures.

Commands below assume the current directory is the profiler repository root.

## 1. Arrange the capture loop

Choose the number of captures, sampling rate, buffer sizes, and stop condition
for the target. Reserve separate memory for the Cortex-M and Ethos-U buffers;
follow the profiler's [integration guide](INTEGRATION.md)
and [Ethos-U adapter guide](../adapters/ethosu/README.md).
Keep the exact unstripped ELF/AXF and the profiler revision used to build the
firmware. The aggregator accepts Cortex-M-only, Ethos-U-only, and combined
captures. Export and decode each enabled processor's buffer.

For each capture, the application should:

1. Initialize the Cortex-M profiler if enabled, start the Ethos-U trace if enabled, and
   enable sampling. Run the workload.
2. When the requested duration passes or either enabled buffer becomes full, disable
   sampling and stop each enabled processor's profiler.
   Every enabled buffer must be finalized even if one filled first.
3. Expose a distinct **capture complete** stop point after the stop calls and
   before either enabled profiler reuses an allocation.
   A source breakpoint, explicit halt, or another debugger-visible state can
   serve as that point. Keep a capture number that increases only after both
   stops complete.
4. Halt at that point, export the enabled buffers to a new numbered directory, and
   decode them while still halted. Continue only after the export is valid;
   the application can then start the next capture. Repeat for the configured
   count.

At every stop, inspect each enabled header. Require `complete=1` and `active=0`, and
check the rate, allocation size, record count, diagnostics, and workload
validation. `full=1` can be a normal reason for stopping; it does not mean the
buffer is incomplete. A breakpoint **on** an assignment that marks completion
may halt before that assignment executes. The finalized buffer headers, not
that state variable, establish whether export is safe. If the debugger stops
elsewhere or the target resets, do not count a capture until its files have
been exported and decoded.

Use a debugger interface permitted by the host project to obtain the
addresses of `statistical_samples` and `ethosu_trace_samples` and read them
after the target stops. The supplied
[Cortex-M](../tools/export_profiler_buffer.gdb) and
[Ethos-U](../tools/export_ethosu_trace_buffer.gdb) GDB exporters are options
where direct GDB access is allowed. Other debugger interfaces may limit each
read to a smaller chunk. Preserve every chunk's start address and byte count.
If the interface returns a hex dump, convert only its byte column to binary
and verify its printed addresses. Do not read a running target.

## 2. Reconstruct one full allocation per capture

The host decoders expect one file per allocation, with length equal to that
capture's `buffer_bytes`. Reading the entire allocation is simplest. If only
the used prefix is transferred, these are the required byte ranges from the
allocation's start:

| Format | Required prefix length |
|---|---|
| Cortex-M SCPF v2, `statistical_samples` | `header_bytes + bytes_used` |
| Ethos-U EUTR v1, `ethosu_trace_samples` | `header_bytes + 8 × stream_capacity + count × record_bytes` |

The prefix includes the complete header and, for Ethos-U, the complete stream
descriptor table. Read all lengths from **this capture's** header and confirm
`0 ≤ prefix length ≤ buffer_bytes`. Reassemble read chunks in increasing
address order; reject gaps, overlaps, and short reads. For these profiler
formats the allocations are cleared at capture start, so pad only the unused
tail with zero bytes to reach `buffer_bytes`. Do not pad missing bytes inside
the required prefix. Keep the resulting files, for example:

```text
<run>/firmware.axf
<run>/capture_00/cortex_m.bin
<run>/capture_00/ethosu.bin
<run>/capture_00/cortex_m_report/
<run>/capture_00/ethosu_report/
<run>/capture_01/...
```

Decode each pair with the decoder revision matching the firmware. The
Cortex-M decoder also needs that capture's exact unstripped ELF/AXF:

```sh
RUN_DIR=/path/to/run
CAP="$RUN_DIR/capture_00"
python3 host/analyze_profiler_buffer.py \
  --samples "$CAP/cortex_m.bin" --elf "$RUN_DIR/firmware.axf" \
  --output "$CAP/cortex_m_report"
python3 host/analyze_ethosu_trace.py \
  --samples "$CAP/ethosu.bin" --output "$CAP/ethosu_report"
```

The decoders validate header flags, format, allocation length, records, and
stream descriptors. Review their `summary.json` files before resuming the
target. Preserve each raw binary separately: every capture has its own header,
local timestamps and stream IDs, and the debugger can pause between captures.
Concatenating raw captures does not make one valid larger profiler buffer.

## 3. Aggregate decoded captures

After every selected capture has its enabled processor reports decoded and
validated, run:

```sh
RUN_DIR=/path/to/run
python3 host/aggregate_profiler_captures.py --input-dir "$RUN_DIR"
```

The aggregator discovers `capture_*` directories in numeric order. Use
`--pattern` for another naming scheme, or list the capture directories
explicitly with `--output-dir`. There is no fixed capture count in this host
tool. It accepts CPU-only, Ethos-U-only, and combined captures. The same
processors and PMU event IDs must be present in every capture. It checks
finalization, matching ELF hash when there is a CPU report, sample rate,
buffer formats, Ethos-U stream descriptors when present, and decoded totals.
It writes `captures.csv` and `summary.json` plus processor-specific combined
sample and histogram files for the processors that were captured.

The combined sample files retain a `capture` column. Function hits and QREAD
histogram counts are summed across windows; compressed Ethos-U idle records
contribute their represented tick counts. Debugger pauses are **not** sampled
time. The current aggregator requires the same stream IDs, CPU-visible
addresses, and lengths in every capture before merging QREAD bins. When those
descriptors differ, analyze the streams separately or extend the aggregator
with an explicit stream equivalence check.

| Capture configuration | Aggregate and optional views |
| --- | --- |
| Cortex-M only | CPU samples, hotspots, and one combined Perfetto timeline |
| Ethos-U only | QREAD samples and complete-period activity fold |
| Both, shared sample ticks | Separate folds plus the joint phase chart |
| Cortex-M PMU off/on | PC views in both cases; event panels only when enabled |
| Cortex-M backtrace off/on | Hotspots in both cases; Gregg flamegraphs only with backtraces |
| Ethos-U PMU off/on | Running activity fold in both cases; PMU panels only when enabled |

The synchronized MCU fold needs both processors; an Ethos-U-only or CPU-only
run cannot produce a joint phase chart. Operator labels additionally need an
exact match between the deployed PTE stream and Vela debug artifacts.

For Cortex-M captures, create the aggregate hotspot chart and optional
backtrace flamegraphs with:

```sh
python3 host/generate_aggregate_mcu_report.py --run-dir "$RUN_DIR" \
  --flamegraph /path/to/FlameGraph/flamegraph.pl
```

Omit `--flamegraph` when backtraces were disabled; the script still produces
the combined PC hotspot chart and summary. When backtraces exist, supply
Brendan Gregg's `flamegraph.pl`; the script reconciles all-PC flamegraph
leaves with the hotspot counts. CPU PMU totals are included when available.

## 4. Match TOSA/Vela operations to QREAD

A TOSA graph describes the model handed to Vela. **TOSA alone cannot label a
QREAD offset in a firmware PTE.** Preserve these artifacts for the exact
model build:

| Artifact | Purpose |
|---|---|
| TOSA flatbuffer and optional source debug data | Model graph and source-node provenance |
| Vela version, accelerator choice, system configuration, memory mode, and config file | Reproduce the compilation settings |
| Vela debug database, including `queue`, `perf`, source, and shape tables | Locate and describe scheduled NPU operations |
| Decoded register command listing from the firmware PTE | Provide the exact command words and compute-kick offsets |
| `qread_ops.csv` derived from the database and listing | Give each kick a QREAD interval and operator metadata |
| The exact firmware PTE | Prove the debug artifacts correspond to the deployed stream |

When producing a new debug database, compile the retained TOSA with the
**same** Vela settings used for the firmware and enable `--enable-debug-db`.
Vela's verbose high-level and register streams can help inspect the result.
The output format required for debug database generation depends on the Vela
version; verify it for that version. A new compile may change the command
stream even when the graph looks equivalent. Decode the **firmware PTE's**
register stream for the file-offset listing and compare command bytes before
using its database. A Vela verbose log is not necessarily the listing format
expected by the map generator.

The Vela `queue` table records byte offsets for NPU compute kicks.
[`build_vela_qread_map.py`](../host/build_vela_qread_map.py) joins those
offsets and the performance and shape tables to the decoded listing,
producing `qread_ops.csv`:

```sh
DEBUG_DIR=/path/to/vela-debug
python3 host/build_vela_qread_map.py \
  --debug-db "$DEBUG_DIR/out_debug.xml" \
  --listing "$DEBUG_DIR/cmdstream_listing.txt" \
  --command-file-offset "$COMMAND_FILE_OFFSET" \
  --output "$DEBUG_DIR/qread_ops.csv"
```

Set `COMMAND_FILE_OFFSET` to the **file offset of the first command word in
this PTE**, expressed in decimal or with a `0x` prefix. QREAD and map
`kick_offset` values are relative to that word. Determine the base from the
actual PTE, not from another model. Build one map per command stream. A TOSA
operation can lower to several NPU kicks, and several operations can be fused,
so output tensor names are not guaranteed to be unique.

Once `<debug-dir>` contains `out_debug.xml`, `cmdstream_listing.txt`, and
`qread_ops.csv`, verify it and annotate the aggregate histogram:

```sh
RUN_DIR=/path/to/run
MODEL_PTE=/path/to/firmware-model.pte
DEBUG_DIR=/path/to/vela-debug
python3 host/align_vela_qread.py \
  --pte "$MODEL_PTE" \
  --debug-dir "$DEBUG_DIR" \
  --histogram "$RUN_DIR/ethosu_qread_histogram.csv" \
  --output-dir "$RUN_DIR"
```

The aligner reconstructs every command word from the listing and requires a
byte-for-byte match at the stated PTE file offset. It checks that the map's
compute kicks match the listing and Vela queue. When the aggregated
`summary.json` is beside the histogram, it also checks the captured stream
length. A mismatch means the operator labels must not be applied to
that capture. The current implementation accepts one histogram stream ID per
invocation; analyze multiple distinct streams separately.

The outputs are `ethosu_operator_samples.csv`,
`ethosu_unmatched_qread.csv`, and `vela_alignment.json`. A sampled QREAD in
`[kick_offset, next_kick_offset)` is assigned to that kick's row. The interval
may contain DMA and register setup for the next operation, and samples before
the first kick remain unmatched. These counts are **sampled command-position
attribution**, not direct measurements of individual register commands or
operator execution time. `est_cycles` is Vela's separate static estimate.

Group exact-PTE-aligned queue rows by TOSA operation with
`python3 host/summarize_tosa_operators.py --run-dir "$RUN_DIR"`.
The [operator report guide](ETHOSU_OPERATOR_REPORTS.md) explains how to
unwrap a Vela `COP1` register stream from the exact PTE, build the mapping,
and render operator hotspot charts.

## 5. Build an offline report index

After writing the human `REPORT.md` and all optional charts and annotations,
combine decoded Cortex-M windows into one Perfetto timeline when CPU samples
are available, then generate
the companion HTML index. Supply the actual board or simulator identity; the
board is deliberately not inferred from an ELF name.

```sh
RUN_DIR=/path/to/run
# Run this line only when Cortex-M samples were captured:
python3 host/combine_perfetto_captures.py --run-dir "$RUN_DIR"
python3 host/generate_report_index.py \
  --run-dir "$RUN_DIR" --board "<board or simulator>" \
  --application "<application name>"
```

`$RUN_DIR/index.html` summarizes the capture count, sample frequency, CPU and
Ethos-U counts, PMU configuration, validation status, and ELF hash from
`summary.json`. The main sections link only aggregate artifacts present in the
run, including the single `cortex_m_combined.perfetto.json`, flamegraphs,
instruction annotations, operator charts, command listings, and PMU views.

For optional platform details and Cortex-M activity, place `platform.json`
beside `summary.json` before generating the index. For example:

```json
{
  "schema_version": 1,
  "soc": "Example SoC",
  "cpu": {
    "name": "Cortex-M55",
    "role": "application core",
    "idle_functions": ["application_idle"],
    "idle_pc_ranges": [{"start": "0x08001230", "end": "0x0800123A"}]
  },
  "ethosu": {"name": "Ethos-U55"}
}
```

All fields except `schema_version` are optional. Add `frequency_hz` to `cpu`
or `ethosu` only when its nominal clock is known, and optionally describe its
evidence in `clock_basis`. The `role` field can describe HP/HE or another
platform's core role. The index does not infer core or NPU clocks from the
sampling timer or timestamp clock.

For CPU activity, name the exact idle function(s) shown in `samples.csv`, or
give half-open idle PC ranges (`start` inclusive, `end` exclusive). They can
describe an RTOS idle task, a FreeRTOS idle task, or a bare-metal idle loop;
the report code has no built-in RTOS idle name. The index reports the share of
sampled PCs **outside** those locations. This is a sampled non-idle estimate,
not CPU cycle utilization; it includes unresolved PCs unless their addresses
are in an idle range. Without an explicit idle classification or CPU samples,
the CPU activity card is omitted.

The combined trace places windows end to end by their active capture durations,
marks every boundary, and omits debugger pause time. PMU rates are calculated
only within each window; no cross-window interval is invented. Keep the raw
capture buffers and decoded reports for validation and reproducibility, even
though the index does not present individual windows. Open the index in a
browser. Re-run the generator after adding any optional artifact; links are
relative, so keep the index with its run directory when sharing it.

To use **Open combined trace in Perfetto** in the index, serve the report on
localhost and open the URL printed by this command:

```sh
python3 host/serve_report.py --run-dir "$RUN_DIR"
```

The link opens `ui.perfetto.dev` and transfers the local trace through
Perfetto's supported browser message API. The report server listens only on
`127.0.0.1`; the trace stays in browser memory. Browser security prevents this
handoff when `index.html` is opened directly as a `file://` page. The JSON link
still permits manual loading through Perfetto's **Open trace file** control.

## 6. Fold MCU activity around Ethos-U starts

When both decoders record the same sampling tick, align MCU PC and optional PMU samples
to the first running Ethos-U tick of each complete period:

```sh
python3 host/fold_mcu_by_ethosu.py --run-dir "$RUN_DIR" \
  --pre-ms 0 --post-ms 40 --idle-function osRtxIdleThread
python3 host/generate_report_index.py \
  --run-dir "$RUN_DIR" --board "<board or simulator>" \
  --application "<application name>"
```

The tool validates capture clocks and matching timestamps, discards the first
and last running group of every buffer, and calculates phase from the shared
tick: `(MCU tick - first NPU running tick) / sample_hz`. It does not join PMU
intervals across capture boundaries or count debugger pauses. By default one
period starts at phase zero, so no sample from the previous period is shown.
An optional `--pre-ms` lead-in appears at negative phases and may reuse MCU
samples also assigned to the previous period's positive phases. This is
deliberate context, not an additional unique-sample count. The optional
`--highlight-function` and `--highlight-label` bracket a sampled function's
span while preserving gaps where the CPU executed other work. Such a bracket
is an interpretation of sampled PCs, not a measured call entry/exit pair.

Outputs are `mcu_folded.svg`/`.png`, `mcu_folded.csv`,
`mcu_folded_functions.csv`, `mcu_inference_windows.csv`, and
`mcu_folded_summary.json`. Each phase's `inferences_eligible` and
`cpu_samples` show its coverage. CPU PC percentages describe sampled function
locations; PMU values are event counts over the preceding interval and must
not be attributed to the sampled function. The configured idle function is a
classification of PC samples, not proof that the core stopped executing.
Back-to-back NPU submissions without a sampled idle gap appear as one running
group; a workload-specific inference marker is needed to separate them.

First fold Ethos-U running activity and any configured Ethos-U PMU events:

```sh
python3 host/fold_ethosu_by_inference.py --run-dir "$RUN_DIR"
```

This produces `ethosu_inference_windows.csv`, `ethosu_folded.csv`,
`ethosu_activity_folded.svg`/`.png`, and `folded_summary.json` even when PMU is
disabled. With PMU enabled it also produces `inference_pmu.csv`,
`folded_pmu.csv`, and `ethosu_pmu_folded.svg`/`.png`. The fold excludes the
first and last running group in each capture, because either can be cut by the
buffer boundary. Running groups without a sampled idle gap cannot be separated
into distinct inferences. PMU phase values are interval deltas; compressed
idle runs place the accumulated idle delta at the first idle phase.

If the MCU fold was also generated from the same captures, make a combined graph:

```sh
python3 host/plot_joint_mcu_ethosu.py --run-dir "$RUN_DIR"
python3 host/generate_report_index.py \
  --run-dir "$RUN_DIR" --board "<board or simulator>" \
  --application "<application name>"
```

`joint_folded.svg`/`.png` retain the MCU function mix and non-idle share,
add Ethos-U running share, and include panels only for configured CPU and
Ethos-U PMU events. All panels use one horizontal phase scale set by the
capture sampling rate, so corresponding peaks and
idle spans line up vertically. `joint_folded.csv` records the paired values,
including Ethos-U running share for numerical inspection. The tool requires matching
capture count, sample rate, complete-period count, and per-phase inference
coverage. It keeps only phases present in both folds; a trailing NPU-only
phase is omitted when the MCU window ends first. The running share is counted
from Ethos-U running samples at each tick, including the ticks represented by
compressed idle runs. PMU values are interval means and may have less precise
phase placement around compressed Ethos-U idle runs; they are not event counts
for the sampled PC or QREAD command. CPU and NPU cycle counters use separate
clock domains.

The index can link older `ethosu_pmu_timeline.svg` and `ethosu_pmu_zoom.svg`
files when a run already contains them. Their one-off generator has not yet
been moved into this repository; the complete-period PMU fold above is the
reusable PMU chart workflow.
