# Agent guide

Start with [README.md](README.md). Use [configuration](docs/CONFIGURATION.md),
[adapter template](adapters/template/README.md) and the
[Corstone FVP example](examples/corstone300/README.md) for integration.

For new applications, follow the [3-stage checklist](docs/INTEGRATION.md): establish
timer/clocks/stack/code regions, validate PC capture, then PMU, then backtraces.
Keep settings in the application. Run [ELF preflight](host/check_profiler_elf.py)
before capture; [package reports](host/create_profiler_report.py) with exact inputs
and provenance. Do not guess bounds or ownership. Report validation limits.

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
  The decoder writes `stacks.folded`; render with external `flamegraph.pl` and use
  `stacks.note.txt` as the subtitle. `--stack-root NAME` selects the graph base.
  Unreliable/root-missing chains are excluded and counted; PC/PMU statistics remain intact.
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
