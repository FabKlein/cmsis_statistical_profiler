# Ethos-U command streams and operator charts

This workflow turns a captured QREAD histogram and matching Vela debug data
into operator counts and SVG charts. It applies to one Ethos-U command stream
at a time. Run these commands from the profiler repository root. The
[repeated-capture runbook](REPEATED_CAPTURES.md) explains how to obtain and
aggregate the histogram.

## Inputs

- The exact PTE deployed in firmware, or a byte-identical copy of it.
- A QREAD histogram from `analyze_ethosu_trace.py` or
  `aggregate_profiler_captures.py`.
- The matching Vela `out_debug.xml`, with queue, perf, and source tables.
- The Vela Python package used for the model build, so the command opcode
  names match the stream. The unwrapping tool reports unknown opcodes.

TOSA alone does not map QREAD to operators. A Vela debug database from a
different compile can assign plausible but wrong labels. The alignment step
below requires an exact register-stream byte match to the PTE.

## 1. Unwrap the PTE command stream

```sh
VENV_PYTHON=/path/to/venv/bin/python
PTE=/path/to/deployed-model.pte
DEBUG_DIR=/path/to/matching-vela-debug

"$VENV_PYTHON" host/unwrap_ethosu_pte.py \
  --pte "$PTE" --listing "$DEBUG_DIR/cmdstream_listing.txt" \
  --raw "$DEBUG_DIR/command_stream.bin"
```

The tool locates Vela `COP1` driver actions, reads the embedded command-stream
length, and writes each register command with its **PTE file offset** and
Vela opcode name. It prints the first command word's PTE file offset; this is
`COMMAND_FILE_OFFSET` in the next command. QREAD offsets start at zero at
that word. The optional `--raw` file contains only the register stream. If
the PTE has several streams, use `--stream-index N` and process each one
separately. The current decoder uses Vela's U55/U65 opcode definitions;
unsupported driver actions or opcodes fail explicitly.

This reconstructs the register listing; it cannot recreate Vela's high-level
operator comments, scheduling decisions, or debug database from the PTE.

## 2. Match Vela operators to the deployed stream

```sh
COMMAND_FILE_OFFSET=0x...  # offset printed by unwrap_ethosu_pte.py
RUN_DIR=/path/to/decoded-or-aggregated-run

python3 host/build_vela_qread_map.py \
  --debug-db "$DEBUG_DIR/out_debug.xml" \
  --listing "$DEBUG_DIR/cmdstream_listing.txt" \
  --command-file-offset "$COMMAND_FILE_OFFSET" \
  --output "$DEBUG_DIR/qread_ops.csv"

python3 host/align_vela_qread.py \
  --pte "$PTE" --debug-dir "$DEBUG_DIR" \
  --histogram "$RUN_DIR/ethosu_qread_histogram.csv" \
  --output-dir "$RUN_DIR"
```

For a single decoded capture, use its `ethosu_report/qread_histogram.csv`
instead of the aggregate histogram. The aligner writes
`ethosu_operator_samples.csv`, `ethosu_unmatched_qread.csv`, and
`vela_alignment.json`. Proceed only when `command_stream_exact_match` is
true. The aligner also requires exactly one stream ID in the histogram;
separate different streams before attribution.

## 3. Render the operator charts

```sh
python3 host/plot_ethosu_operators.py \
  --samples "$RUN_DIR/ethosu_operator_samples.csv" \
  --alignment "$RUN_DIR/vela_alignment.json" \
  --output-dir "$RUN_DIR" --top 30 \
  --timing-run-dir "$RUN_DIR"
```

Outputs are `ethosu_operator_hotspots.svg` (interactive sort buttons),
`ethosu_operator_hotspots_chronological.svg` (QREAD order), and
`ethosu_operator_hotspots_top30.svg`. Change `--top` to choose the compact
chart's row count. The bar length is `percent_of_running_samples`; columns
show QREAD kick offset, TOSA type, sampled counts, and Vela cycle/MAC
estimates. Hover over a row for shapes, QREAD interval, and memory accesses.
When the run also has `ethosu_samples.csv`, `ethosu_inference_windows.csv`, and
`folded_summary.json`, `--timing-run-dir` adds **Median +ms** to each chart and
writes `ethosu_operator_timing.csv`. The script checks the validated capture
rate and that every raw QREAD operator count matches the aligned histogram.
It excludes capture-edge periods, computes each sample's offset from its
capture-local inference start tick, and shows the median of those offsets for
each queue operator. Hover for the 10th–90th percentile and contributing
sample count. A blank means no sample from a complete period. This is a
sampled QREAD phase, not a measured operator start, end, or duration.
Each offset comes from ticks spaced `1000 / sample_hz` ms apart. A median over
many ticks can be more stable and can numerically fall between two tick values,
but it does not recover a sub-tick operator boundary. Obtaining finer measured
phase detail requires a higher sampling rate or an independent timestamped
operator marker. The chart labels cycle and MAC figures as **Vela estimates**;
they are static compiler estimates, not live Ethos-U PMU counts.
Omit `--timing-run-dir` if these timing inputs are unavailable.
Open the interactive SVG in a browser for its sort buttons; some IDE image
previews disable embedded SVG scripts. The static chronological view works
without scripts.

QREAD is a command-reader position. Register setup and DMA commands can fall
inside a kick interval while earlier work runs. Operator counts are approximate
sample attribution, not exact execution time or MAC efficiency. `est_cycles`
and `macs` are Vela estimates, not live PMU measurements.

## Cortex-M flamegraphs

The Cortex-M decoder writes `stacks.folded`. Render it with
[Brendan Gregg's FlameGraph](https://github.com/brendangregg/FlameGraph):

```sh
perl /path/to/FlameGraph/flamegraph.pl \
  --countname samples report/stacks.folded > report/flamegraph.svg
```

Use the external renderer for flamegraphs instead of creating another SVG
flamegraph implementation. Check `summary.json` for excluded or unreliable
caller chains and state the included-sample denominator. A separate PC hotspot
chart can include all CPU samples even when some stacks cannot be recovered.
The [unwinding guide](UNWINDING.md) covers folded-stack validation and notes.
