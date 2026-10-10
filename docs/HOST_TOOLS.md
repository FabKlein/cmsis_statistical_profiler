# Host tools and report interpretation

Run host commands from the repository root. Keep the exact unstripped ELF/AXF
and raw allocation for every capture; decode with the matching profiler revision.
The [integration guide](INTEGRATION.md) covers the first capture, and the
[repeated-capture runbook](REPEATED_CAPTURES.md) covers synchronized MCU/Ethos-U
reports, aggregation and operator attribution.

## Python and dependencies

Use **Python 3.10 or newer** for the host toolkit. Folding and operator tools use
`itertools.pairwise`, which is unavailable in Python 3.8/3.9. Decoding, ELF
preflight, report packaging/index generation and Perfetto export use the Python
standard library; no Python package is required for those paths.

| Optional feature | Requirements |
|---|---|
| Interactive `dashboard.html` | Plotly from [requirements-visualization.txt](../host/requirements-visualization.txt) |
| MCU/Ethos-U folding CLI charts and joint charts | Matplotlib; its installation supplies NumPy. The `fold()` analysis functions need only the standard library |
| Ethos-U operator SVG charts | Standard library; no Matplotlib dependency |
| PTE register-command unwrapping | The matching `ethos-u-vela` environment used for the model build; see [operator inputs](ETHOSU_OPERATOR_REPORTS.md#inputs) |
| FlameGraph SVG | Perl and Brendan Gregg's external `FlameGraph/flamegraph.pl` |
| Instruction/source annotation | GNU Arm or LLVM `objdump`; `addr2line` plus debug information and matching sources for `--source` |
| C++ demangling | GNU/LLVM `c++filt` on `PATH`, or `--cxxfilt PATH` |
| Python formatting | Ruff (development only) |

Install only the optional packages you need, preferably in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r host/requirements-visualization.txt  # HTML dashboard
python -m pip install matplotlib                           # folding charts
```

Use the model build's Vela environment for unwrapping rather than selecting an
unrelated Vela version. Optional plotting dependencies do not affect firmware.

## Decode and package a single capture

Run preflight before capture, then stop and export the whole allocation as shown
in the [integration guide](INTEGRATION.md). Package it into a new directory:

```sh
python3 host/create_profiler_report.py \
  --samples samples.bin --elf firmware.elf --output report \
  --board "<actual board or simulator>" --application "<application name>"
```

The package contains `REPORT.md`, the shared offline `index.html`, decoded tables,
Perfetto output, raw inputs and a provenance manifest. `--board` and
`--application` are required caller-supplied labels. Add `--platform platform.json`
for verified processor identities, nominal clocks and explicit idle names/ranges;
see the [metadata schema](REPEATED_CAPTURES.md#5-build-an-offline-report-index).
Add `--producer-revision`, `--compiler-id` and `--capture-command` to retain build
and retrieval provenance. Hashes identify the archived files, not the firmware
actually deployed on a device.

Use `--html` for the optional Plotly dashboard; `--stack-root NAME --flamegraph
/path/to/FlameGraph/flamegraph.pl` adds a graph when included backtraces exist.
A failed optional renderer returns failure but retains decoded data, inputs and
an index with diagnostics. Fix the dependency/input and package into a fresh
directory. Regenerate the index after subsequently adding artifacts:

```sh
python3 host/generate_report_index.py \
  --run-dir report --board "<actual board or simulator>" --application "<application name>"
```

For a direct decode without packaging:

```sh
python3 host/analyze_profiler_buffer.py --samples samples.bin --elf firmware.elf --output report
```

Outputs are `functions.csv`, `samples.csv`, `summary.json`, and `events.csv` for PMU
requests. Function percentages estimate sampled execution time, not call counts.
Tasks are aggregated; task IDs are not recorded. Invalid timestamp timing leaves
derived time fields blank while preserving raw PC/PMU data; time-based exporters
reject such reports.

C++ names are demangled with `arm-none-eabi-c++filt`, `llvm-cxxfilt` or `c++filt`.
Use `--cxxfilt PATH` to choose a tool or `--no-demangle` to retain ELF names.
Missing/failed tools produce a warning and preserve original names. Regenerate
reports and visualizations when changing symbolization.

## Folding synchronized MCU and Ethos-U captures

Follow the [runbook](REPEATED_CAPTURES.md) to finalize, decode and aggregate each
capture. Then generate either fold, or both and the joint view:

```sh
python3 host/fold_mcu_by_ethosu.py --run-dir RUN_DIR --post-ms 40
python3 host/fold_ethosu_by_inference.py --run-dir RUN_DIR
python3 host/plot_joint_mcu_ethosu.py --run-dir RUN_DIR
```

The MCU fold keys counters by slot: `pmu0_mean`, `pmu0_ci95`, `pmu0_intervals`,
and equivalent columns for each additional slot. `cpu_pmu_events` in
`mcu_folded_summary.json` supplies slot, key, event ID and display label. Repeated
event selections remain separate. Joint output uses `mcu_pmu0_mean` etc.
Regenerate both MCU and joint folds when updating older reports to this schema.

Non-idle PC share is an estimate and appears only with explicit classification:
use `platform.json` idle functions/half-open PC ranges, or pass repeatable
`--idle-function NAME` to the MCU fold. CLI names replace the platform function
list; platform PC ranges still apply. No RTOS idle name is assumed. For the same
classification in the offline index, record the selection in `platform.json`.
Function charts retain original symbols even when a PC range classifies part of
a function as idle. Unobserved phases/PMU intervals stay blank, not measured zeros.

Both folds use shared finalized-report checks, compressed idle weights,
running-burst detection and statistical helpers. Capture-edge groups are excluded,
shared CPU/NPU ticks and timestamps must agree, and per-phase populations can
shrink as shorter periods end. Approximate confidence bands are not bounds on
sampling error. PMU intervals are not per-function or per-operator costs.

## Optional backtraces and FlameGraph

Set `PROFILER_STACK_UNWIND=1` and `PROFILER_PRECISE_STACK_BOUNDS=1` in your application
to collect caller addresses. `PROFILER_UNWIND_MAX_DEPTH` defaults to 16;
each sample stores only its recovered callers (4-byte metadata + 4 bytes/caller). This requires
compiler-generated EHABI tables, a linker-table hook and precise stack bounds.
Reserve interrupt stack space using the [stack and time budget guide](ISR_BUDGET.md);
the caller-depth limit also controls temporary RAM and ISR work.
The decoder exports `stacks.folded` and trace-status diagnostics; incomplete traces
remain visible without diagnostic frames; unreliable chains are excluded with counts.
Use `--stack-root osThreadEntry` to select the graph base. See [setup and limitations](UNWINDING.md).

Interpret `no_table` and `unsupported` at the point where unwinding **stopped**,
not necessarily at the sampled PC. A partial chain that already reached the
chosen `--stack-root` is useful even if C runtime startup above it has no
recipe. Compare `root_reached_percent`, `unwind_status_counts` and the actual
`callchain` values in `samples.csv`; raw status totals alone do not measure
FlameGraph coverage. For C++ code, `-funwind-tables` may produce a generic
personality recipe that this compact-EHABI walker cannot decode. Check required
functions in the final ELF with
`host/check_profiler_elf.py --elf firmware.axf --function NAME --require-unwind`; disabling
exceptions for an affected source is an option
only if its behavior does not depend on C++ exception propagation.

![F16 MobileNetV3 on STM32N6: sampled call stacks as a flamegraph](images/stm32n6-mobilenetv3-f16-flamegraph.svg)

*Example flamegraph: F16 MobileNetV3 on STM32N6. Frame widths represent included
sample counts, not call counts or per-function PMU totals.*

## Annotate hot instructions

Show a ranked hotspot summary of functions, source lines and instruction PCs:

```sh
python3 host/annotate_profiler_report.py --report report --elf firmware.elf --top 5 --source
```

The default `--view hotspots` ranks self-PC samples across the selected functions.
Source-line hits from different functions add together when they map to the same
file and line. `--hotspot-limit 15` controls the number of source lines and PCs.
Shares use all capture samples as the denominator; they are not measured instruction
cycle costs. Sampling bias and interrupt latency still apply. PMU counts are not
attributed to source lines or instructions.

Use `--view groups` for the detailed disassembly. Functions and their instruction
groups are shown in descending sample-share order; equal-hit groups retain address
order. Groups contain 8 instructions by default; use `--group-instructions 4` to
shrink or `1` for individual instructions. Zero-hit groups are hidden with an
omission marker; use `--show-zero-hit-groups` for the full disassembly. Group
percentages are relative to the function's samples. These are consecutive
instruction groups, not branch-delimited basic blocks.

Use `--function NAME` (or `0xADDRESS`) to select a function, and `--output annotation.txt`
to save text. The tool probes `arm-none-eabi-objdump`, then `llvm-objdump` on `PATH`;
use `--objdump /path/to/objdump` to override. The ELF must match the report's hash.
Unmatched PCs are reported explicitly, without assigning them to nearby instructions.
For Cortex-M55 MVE code, pass the architecture explicitly, for example GNU Arm
`--objdump-arg=-m --objdump-arg=armv8.1-m.main` or LLVM
`--objdump-arg=--mcpu=cortex-m55`. Without it, valid MVE opcodes can appear as
coprocessor instructions such as `cdp` or `ldc`.

Add `--source` for a source-line ranking in the hotspot view or distinct source
lines above each group in the detailed view. This needs
ELF debug information (`-g`) and matching local sources. GNU Arm/LLVM `addr2line`
is auto-detected; override with `--addr2line PATH`. For a relocated source tree,
use `--source-map /original/project=/local/project` (repeatable). Missing lines
or files are noted while disassembly remains available. Optimized source mappings
can be reordered or inlined; they do not define group boundaries.

## Visualize reports: HTML and Perfetto

[host/visualize_profiler_report.py](../host/visualize_profiler_report.py) converts a decoded report
into a Perfetto trace and, optionally, an interactive HTML dashboard. It reads
`samples.csv` and `summary.json` from the same decoder run. No connected board,
firmware rebuild or ELF is needed at this stage; symbolization is already done.
Use the matching ELF when running `analyze_profiler_buffer.py` first.

![F16 MobileNetV3 on STM32N6: sampled function shares and PMU event rates](images/stm32n6-mobilenetv3-f16.png)

*Example HTML dashboard: F16 MobileNetV3 on STM32N6, showing sampled function
shares and PMU event rates over time.*

Run these commands from the repository root. `REPORT_DIR` can be outside the
repository; keep confidential captures and generated reports out of version control.

```sh
python3 host/visualize_profiler_report.py --report REPORT_DIR
```

This writes `REPORT_DIR/samples.perfetto.json` using only the Python standard
library. To also generate HTML, install the optional visualization dependency
in your Python environment:

```sh
python3 -m pip install -r host/requirements-visualization.txt
python3 host/visualize_profiler_report.py --report REPORT_DIR --html
```

This additionally writes `REPORT_DIR/dashboard.html`. Open it in a browser, or
launch it with Python using the absolute file path:

```sh
python3 -m webbrowser "file:///absolute/path/to/report/dashboard.html"
```

| Option | Purpose |
|---|---|
| `--report PATH` | Required directory containing `samples.csv` and `summary.json` |
| `--output PATH` | Output directory; defaults to the report directory |
| `--html` | Also create `dashboard.html`; requires Plotly |
| `--symbol-max-chars N` | Limit displayed function labels (default 120, minimum 40) |
| `--help` | Show command-line usage |

Existing exports with these names are overwritten; decoded CSV/JSON inputs are
unchanged. Use `--output` to retain multiple exports.

### HTML dashboard

- Top 20 function names by exclusive PC hits, plus a full function-name table.
- Individual PC samples with function, time, PC, LR and sample index on hover.
- 0-4 valid PMU event-rate graphs sharing the PC timeline's zoomable time axis.
- Capture warnings, validation status, PMU totals and ELF/capture hashes.
- Embedded Plotly JavaScript: works offline, with no CDN or server required.

Drag to zoom, double-click a plot to reset, click legend entries to hide functions,
or double-click a legend entry to isolate a function. Function rank 0 is the hottest
name in the table. Hotspot percentages and the table always describe the whole
capture, even when the timeline is zoomed. Identical function names are aggregated.

Long demangled names retain their beginning and end plus a stable eight-digit
SHA256 prefix ID, within the label limit. Full names remain in plot hover text
(wrapped for readability) and table tooltips. Click a table name to expand its
full, copyable signature. For example, use `--html --symbol-max-chars 100` for
shorter labels. Aggregation still uses the full name; CSV inputs are unchanged.

### Perfetto trace

Open `samples.perfetto.json` with **Open trace file** in an approved Perfetto UI.
For confidential data, use your approved local/self-hosted viewer and do not use
upload or sharing features. The exporter itself performs no network requests.

The Chrome JSON trace contains 1 instant event per PC sample, named after its
function, with PC/LR/index/tick arguments. PMU rates appear as counter tracks.
Long event names use the same compact labels; select an event to see its full
name in the `function` argument. The short ID is a display aid, not a unique
symbol key; use the full argument and PC for programmatic analysis.
A capture-information event contains warnings, limitations, hashes and PMU totals.
Timestamps use microseconds in JSON; Perfetto SQL uses nanoseconds.
No call stacks, function-duration spans or inference boundaries are inferred.

### Interpretation and validation

PMU rates are `interval_delta / actual_elapsed_seconds` between consecutive
samples. A value at time T describes the interval **ending** at T, not the time
after T; viewer lines/steps are not additional measurements. The initial PMU
interval is omitted because its epoch differs from the timestamp epoch. Final
unsampled time is also omitted, so plotted intervals need not sum to the full
initialization-to-stop totals.

These are raw event-rate plots, not smoothed curves, CPI, stall percentages or
cache-miss rates. PMU intervals include interrupts and gated-off execution and
must not be attributed to the function sampled at their endpoint. PC hits estimate
exclusive execution-time share, not calls or exact cycle counts. Fixed-rate
aliasing and interrupt latency remain limitations; LR is not a call stack.

Empty captures, invalid timing, non-increasing timestamps, inconsistent sample
counts and malformed PMU deltas are rejected. Disabled/invalid PMU suppresses
rate tracks while retaining valid PC samples. Full/incomplete captures, rejected
frames, failed workload validation and unresolved PCs produce warnings.
The exporter preserves supplied hashes but cannot independently verify that the
CSV, summary and original ELF belong together.
