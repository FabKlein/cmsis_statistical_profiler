# Agent guide

Start with [README.md](README.md). Use [configuration](docs/CONFIGURATION.md),
[adapter template](adapters/template/README.md) and the
[Corstone FVP example](examples/corstone300/README.md) for integration.

For new applications, follow the [3-stage checklist](docs/INTEGRATION.md): establish
timer/clocks/stack/code regions, validate PC capture, then PMU, then backtraces.
Keep settings in the application. Run [ELF preflight](host/check_profiler_elf.py)
before capture; [package reports](host/create_profiler_report.py) with exact inputs
and provenance. Do not guess bounds or ownership. Report validation limits.

For repeated Cortex-M and/or Ethos-U captures, follow the
[repeated-capture runbook](docs/REPEATED_CAPTURES.md). Stop after both buffers
are finalized and before either is reused; verify `complete=1`, `active=0`
in each enabled processor's header. Preserve one full allocation per processor and capture, with
chunk addresses and lengths checked before zero-padding only the unused tail.
Decode each capture with the matching profiler revision and exact ELF/AXF,
then combine decoded reports with [aggregate_profiler_captures.py](host/aggregate_profiler_captures.py).
Never concatenate raw captures or count debugger pauses as sample time.
Use [generate_aggregate_mcu_report.py](host/generate_aggregate_mcu_report.py)
for aggregate CPU hotspots and optional backtrace flamegraphs. Supply Brendan
Gregg's `flamegraph.pl` when backtraces exist; never substitute a homegrown
flamegraph renderer. Use
[summarize_tosa_operators.py](host/summarize_tosa_operators.py) only after
exact PTE/Vela alignment has passed.
For NPU attribution, build a map from a matching Vela debug database and
command listing with [build_vela_qread_map.py](host/build_vela_qread_map.py),
then use [align_vela_qread.py](host/align_vela_qread.py) to check listing bytes
against the supplied PTE and map metadata against the supplied database.
Capture-to-PTE and database-to-model-build associations remain caller supplied;
recorded input hashes identify files, not deployed firmware. TOSA alone cannot label QREAD;
operator sample counts are sampled command positions, while `est_cycles` is
Vela's estimate.
For every completed profiling report, keep the human Markdown summary and
generate a companion offline `index.html` with
[generate_report_index.py](host/generate_report_index.py) after the optional
artifacts are written. Supply the actual board/target and application name;
use an optional run-local `platform.json` for verified core identity, role,
nominal clocks, and explicit idle function or PC ranges. Never equate the
profiler timer or timestamp frequency with the CPU or NPU clock without
separate evidence. Label sampled non-idle PC share as an estimate, not cycle
utilization; omit it without an explicit idle classification. Take capture
count, sampling frequency, sample totals, and validation from
the decoded/aggregate metadata. For repeated captures, generate one combined
Perfetto timeline with explicit window boundaries and debugger pauses omitted;
show aggregate results in the index. Include available MCU hotspots,
flamegraphs, instruction reports, Ethos-U operator/command-stream views, PMU
charts, and combined tables. Preserve raw capture buffers and decoded reports
for verification. Omit missing outputs,
verify every local link, and rerun the index generator when artifacts change.
When a combined Perfetto trace exists, keep the index's automatic Perfetto
control and document the localhost server needed to use it; `file://` cannot
transfer the trace to Perfetto through the browser message API.
For synchronized MCU and Ethos-U captures, use
[fold_mcu_by_ethosu.py](host/fold_mcu_by_ethosu.py) to fold CPU PC and PMU
samples against the first running Ethos-U tick. Validate shared ticks and
timestamps, exclude capture-edge periods, and report per-phase coverage.
Use [fold_ethosu_by_inference.py](host/fold_ethosu_by_inference.py) for
complete-period Ethos-U activity and optional PMU events. When both processor
folds are available, use
[plot_joint_mcu_ethosu.py](host/plot_joint_mcu_ethosu.py) to stack the MCU
function/activity panels and optional PMU panels for both processors on one shared horizontal phase
scale. Preserve the original function mix and separate PMU counters; require
matching capture and per-phase inference counts. Keep PMU interval values
separate from sampled PC/QREAD attribution.
Separated PC segments can be one function call interrupted by a higher-priority
thread. Check raw call chains and scheduling context before counting calls;
preserve the gap in CPU activity charts and label any inferred call span.
Use [unwrap_ethosu_pte.py](host/unwrap_ethosu_pte.py) to extract a register
listing from the exact PTE, then
[plot_ethosu_operators.py](host/plot_ethosu_operators.py) on the aligner's
CSV and `vela_alignment.json`. Follow the human-facing
[operator report guide](docs/ETHOSU_OPERATOR_REPORTS.md). Do not infer
operator boundaries from a different PTE or an unverified Vela compile.
If capture-local Ethos-U samples and complete inference windows are available,
pass `--timing-run-dir` to add each operator's median sampled phase and keep
`ethosu_operator_timing.csv`. Check raw per-operator QREAD counts against the
aligned histogram; label these phases as sampled positions, not exact operator
start or end times.

- Keep a 3 layers SW structure: capture/storage, Cortex-M backend, timer integration.
  Vendor dependencies belong in adapters, not the capture core. The generic
  SysTick integration needs no board adapter when the application supplies the
  device header, clock and stack configuration.
- Use 1 timer source. Prefer a dedicated timer when HAL/RTOS code owns SysTick.
  The application supplies clocks, startup, linker placement and readable stack
  bounds; TCM is optional.
- For AMP, keep buffers/state physically separate per image and reserve distinct
  timer channels. Serialize shared peripheral clock setup; decode with each core's ELF.
- Use the public `profiler_*` API from `sampling_profiler.h`; application timing
  queries are `profiler_sample_ticks()` and `profiler_elapsed_ms()`. Keep
  `profiler_port_*` internal and `profiler_timer_*` in timer adapters.
- Run lifecycle calls serially in privileged thread mode on 1 core. Always stop
  before dumping the whole buffer with [export_profiler_buffer.gdb](tools/export_profiler_buffer.gdb);
  decode with [analyze_profiler_buffer.py](host/analyze_profiler_buffer.py) and the exact
  unstripped executable. Plot reports with [visualize_profiler_report.py](host/visualize_profiler_report.py).
- Annotate decoded PC hotspots with [annotate_profiler_report.py](host/annotate_profiler_report.py):
  `--report report --elf firmware.elf --top 5 --group-instructions 8`.
  GNU Arm/LLVM objdump is auto-detected; `--objdump PATH` overrides. Groups count
  instructions, not bytes or basic blocks; use the exact ELF and report unmatched PCs.
  Add `--source` for debug-mapped source snippets; `--addr2line PATH` and
  `--source-map OLD=NEW` support custom tools and relocated source trees.
- Ethos-U uses a separate [EUTR buffer](adapters/ethosu/README.md). Discover immutable
  command streams in the inference callback; records reference a bounded stream table.
  Keep decoder/firmware formats synchronized and histogram by `(stream_id, QREAD)`;
  unknown stream IDs must not be merged into hotspots. No application registration.
  Consecutive idle ticks share 1 EUTR record: word 4 is idle_count when STATUS
  running=0, otherwise stream_id. Weight host statistics by represented ticks;
  idle runs retain only their latest timestamp/tick/PMU snapshot.
  Use the `trace_ethosu_*` API. Existing driver callbacks must forward once to
  `trace_ethosu_inference_begin`; set `PROFILER_ETHOSU_DRIVER_CALLBACK=0` project-wide.
  Ethos-U PMU collection requires exclusive ownership until stop returns, even
  after buffer full. Use `PROFILER_ETHOSU_PMU_COUNT=0` if the application owns it;
  later PMU reconfiguration is not detected.
- Keep ISR code bounded and integer-only: no allocation, blocking, logging, FP or
  vector instructions. Preserve the original exception frame.
- On Armv8-M, determine the interrupted frame security state from the captured
  `EXC_RETURN`, not from debugger SCS visibility or project labels. If secure
  frames are observed, compile the profiler backend/ISR sources with `-mcmse`;
  do not apply it globally unless the application itself is a CMSE build.
- Maintain 1 [format](FORMAT.md): 6 base words plus `pmu_count` words, 24–40
  bytes for 0–4 events, plus optional EHABI depth/status and only the recovered caller words.
  `PROFILER_UNWIND_MAX_DEPTH` defaults to 16; use header `bytes_used` and each
  record's depth, never assume a fixed stride/capacity with backtraces. Change firmware, decoder and tests together; bump the format identifier for incompatible changes, without legacy compatibility branches.
  PMU deltas are not per-function counts.
- For [backtraces](docs/UNWINDING.md), bound every read and retain partial-trace status.
  Require precise task-stack bounds; never call exception personality routines.
- For FlameGraph, enable `PROFILER_STACK_UNWIND` and `PROFILER_PRECISE_STACK_BOUNDS`;
  follow the [integration checklist and examples](docs/UNWINDING.md#integration-checklist-and-examples).
  Apply `-funwind-tables` to profiled sources, retain tables using the
  [AC6](docs/UNWINDING.md#ac6-scatter-file-integration) or
  [GCC/LLVM](docs/UNWINDING.md#gcc--llvm-linker-script-integration) instructions,
  and supply both table-range and precise stack-bounds hooks. Defines alone are insufficient.
  For large AC6 images, use [selective 2-pass retention](docs/UNWINDING.md#ac6-table-retention)
  to avoid retaining unused code; recheck the final ELF after the second link.
  Adapt the existing memory map; verify final ELF recipes and known caller chains.
  The decoder writes `stacks.folded`; render with Brendan Gregg's external
  `FlameGraph/flamegraph.pl` rather than writing another flamegraph SVG renderer. Use
  `stacks.note.txt` as the subtitle. `--stack-root NAME` selects the graph base.
  Unreliable/root-missing chains are excluded and counted; PC/PMU statistics remain intact.
  State the included-stack denominator and reconcile flamegraph PC counts with
  all-sample hotspots, especially idle-thread samples that may lack callers.
  See the [RTX](examples/corstone300_rtos2/CALL_TREE.md) and
  [FreeRTOS](examples/corstone300_freertos/README.md) dual-thread FVP tests.
  Build their shared `call_tree.csolution.yml` with CMSIS-Toolbox;
  `tests/run_rtos_fvp.py --kernel rtx|freertos` builds, checks and runs the capture.
- Preserve SPDX/project headers and Doxygen contracts. Use `.clang-format` for C/H;
  preserve protected device include order.
- Format host Python with `ruff format host/` (`python3 -m pip install ruff`).
  Check with `ruff format --check host/`; explain binary layouts and validation
  decisions in comments, rather than paraphrasing individual statements.
- Build the bare-metal AC6 FVP example with
  [its csolution](examples/corstone300/profiler.csolution.yml), contexts
  `profiler.FVP+Corstone300` or `profiler.Unwind+Corstone300`.
  `tests/run_fvp.py` uses `cbuild`, exports the buffer and checks the decoded report.
  Configure `AC6_TOOLCHAIN_6_24_0` and installed packs; see the example README.
- For behavior changes, run `python3 -B -m unittest discover -s tests -v`.
  For backend/adapter changes, also use the relevant [compile/FVP checks](tests/VALIDATION.md).
  State hardware validation limits accurately.
