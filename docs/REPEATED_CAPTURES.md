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
firmware. This runbook and its aggregator assume both buffers are enabled;
the Cortex-M decoder also works by itself for CPU-only capture.

For each capture, the application should:

1. Initialize the Cortex-M profiler, start the Ethos-U trace if enabled, and
   enable sampling. Run the workload.
2. When the requested duration passes or either buffer becomes full, disable
   sampling and call `trace_ethosu_stop()` followed by `profiler_stop()`.
   Both buffers must be finalized even if one filled first.
3. Expose a distinct **capture complete** stop point after both calls and
   before either `profiler_init()` or `trace_ethosu_start()` reuses an allocation.
   A source breakpoint, explicit halt, or another debugger-visible state can
   serve as that point. Keep a capture number that increases only after both
   stops complete.
4. Halt at that point, export both buffers to a new numbered directory, and
   decode them while still halted. Continue only after the export is valid;
   the application can then start the next capture. Repeat for the configured
   count.

At every stop, inspect both headers. Require `complete=1` and `active=0`, and
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

After every selected capture has valid `cortex_m_report` and `ethosu_report`
directories, run:

```sh
RUN_DIR=/path/to/run
python3 host/aggregate_profiler_captures.py --input-dir "$RUN_DIR"
```

The aggregator discovers `capture_*` directories in numeric order. Use
`--pattern` for another naming scheme, or list the capture directories
explicitly with `--output-dir`. There is no fixed capture count in this host
tool. It checks finalization, matching ELF hash, sample rate, buffer formats,
Ethos-U stream descriptors, and decoded totals before writing `captures.csv`,
`cortex_m_samples.csv`, `ethosu_samples.csv`, `cortex_m_functions.csv`,
`ethosu_qread_histogram.csv`, and `summary.json`.

The combined sample files retain a `capture` column. Function hits and QREAD
histogram counts are summed across windows; compressed Ethos-U idle records
contribute their represented tick counts. Debugger pauses are **not** sampled
time. The current aggregator requires the same stream IDs, CPU-visible
addresses, and lengths in every capture before merging QREAD bins. When those
descriptors differ, analyze the streams separately or extend the aggregator
with an explicit stream equivalence check.

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
