# Ethos-U command streams and operator charts

Process one stream at a time from the repository root, after
[capture/aggregation](REPEATED_CAPTURES.md). See [host dependencies](HOST_TOOLS.md#python-and-dependencies).

## Inputs

Keep the exact deployed PTE, matching Vela debug database (`out_debug.xml` with
queue/perf/source tables), command listing and model-build Vela environment.
Retain build settings: Vela version, accelerator, system configuration, memory
mode, configuration files and compiler flags; TOSA is optional.

TOSA alone cannot label QREAD. Recompiling with similar settings does not establish
identity with the deployed stream. Capture-to-PTE and database-to-model-build
associations remain caller supplied; the tools validate the supplied files.

## 1. Unwrap the PTE command stream

```sh
VENV_PYTHON=/path/to/model-build-venv/bin/python
PTE=/path/to/deployed-model.pte
DEBUG_DIR=/path/to/matching-vela-debug
"$VENV_PYTHON" host/unwrap_ethosu_pte.py \
  --pte "$PTE" --listing "$DEBUG_DIR/cmdstream_listing.txt" \
  --raw "$DEBUG_DIR/command_stream.bin"
```

The tool extracts Vela COP1 register commands with PTE file offsets/opcode names
and prints the first command word's offset. QREAD zero refers to that word.
Use `--stream-index N` for multiple streams. Current opcode definitions are U55/U65;
unsupported actions/opcodes fail. Extraction cannot recreate scheduling decisions,
operator comments or the debug database.

## 2. Match Vela operators to the deployed stream

```sh
COMMAND_FILE_OFFSET=0x...  # first command word's PTE offset, printed above
RUN_DIR=/path/to/aggregated-run
python3 host/build_vela_qread_map.py \
  --debug-db "$DEBUG_DIR/out_debug.xml" \
  --listing "$DEBUG_DIR/cmdstream_listing.txt" \
  --command-file-offset "$COMMAND_FILE_OFFSET" \
  --output "$DEBUG_DIR/qread_ops.csv"
python3 host/align_vela_qread.py \
  --pte "$PTE" --debug-dir "$DEBUG_DIR" \
  --histogram "$RUN_DIR/ethosu_qread_histogram.csv" --output-dir "$RUN_DIR"
```

Aggregate even a single capture to provide the histogram and `summary.json`.
The aligner requires one histogram stream ID. It compares listing bytes against
the exact PTE, validates kick/queue alignment, regenerated labels/shapes/estimates
against the database and captured stream length against the supplied stream.
A matching length/offset is not deployed-content identity. Proceed only with
`listing_matches_pte=true`.

Outputs are `ethosu_operator_samples.csv`, `ethosu_unmatched_qread.csv` and
`vela_alignment.json`. The latter records input hashes and
`capture_pte_identity_verified=false`: no captured command-stream content hash
proves the deployment association. Preserve exact inputs and caller evidence.

Each interval `[kick, next_kick)` includes setup/DMA positions; offsets before
the first kick remain unmatched. Fused operators can have several kicks.
Percentages use all running ticks, including unknown streams/invalid QREAD,
not only histogram hits. Distinguish assigned, unmatched and excluded counts:
20 assigned out of 100 running ticks means 20%, even with only 20 histogram hits.
Without aggregate metadata no running-sample percentage can be established.

## 3. Render the operator charts

```sh
python3 host/plot_ethosu_operators.py \
  --samples "$RUN_DIR/ethosu_operator_samples.csv" \
  --alignment "$RUN_DIR/vela_alignment.json" \
  --output-dir "$RUN_DIR" --top 30 --timing-run-dir "$RUN_DIR"
```

Outputs: interactive `ethosu_operator_hotspots.svg`, static chronological view
and compact `ethosu_operator_hotspots_top30.svg`. Change `--top` for another size.
Bars show percent of running samples; rows/hover show QREAD intervals, TOSA types,
counts, shapes, memory accesses and **Vela estimates** for cycles/MACs. Open the
interactive SVG in a browser; IDE previews may disable its sort buttons.

Optional `--timing-run-dir` needs capture-local `ethosu_samples.csv`, complete
`ethosu_inference_windows.csv` and `folded_summary.json`. It checks the validated
rate and every raw per-operator QREAD count against the aligned histogram,
excludes edge periods and writes `ethosu_operator_timing.csv`. Charts add median
sampled phase, with 10th–90th percentiles/counts on hover; blank means no complete-period
observation. Omit the option when inputs are missing.

Phases are sampled command positions, not exact operator start/end/duration.
A median can fall between ticks without recovering a sub-tick boundary; finer
measurements need higher sampling rate or independent operator markers.
QREAD may include setup/DMA while earlier work executes. `est_cycles` and `macs`
are compiler estimates, not live PMU counts or measured MAC efficiency.

After successful alignment, optionally group by TOSA type:

```sh
python3 host/summarize_tosa_operators.py --run-dir "$RUN_DIR"
```

Regenerate the [report index](HOST_TOOLS.md#report-index-and-platform-metadata)
after adding artifacts. CPU FlameGraph has its own
[host workflow](HOST_TOOLS.md#optional-backtraces-and-flamegraph).
