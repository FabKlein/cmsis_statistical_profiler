# Agent guide

Start with [README.md](README.md). Use [configuration](docs/CONFIGURATION.md),
[adapter template](adapters/template/README.md) and the
[Corstone FVP example](examples/corstone300/README.md) for integration.

For new applications, follow the [3-stage checklist](docs/INTEGRATION.md): establish
timer/clocks/stack/code regions, validate PC capture, then PMU, then backtraces.
Keep settings in the application. Run [ELF preflight](host/check_profiler_elf.py)
before capture; [package reports](host/create_profiler_report.py) with exact inputs
and provenance. Do not guess bounds or ownership. Report validation limits.

- Keep a 3 layers SW structure: capture/storage, Cortex-M backend, board timer adapter.
  Vendor dependencies belong in adapters, not the capture core.
- Use 1 dedicated timer. Preserve HAL/RTOS interrupt ownership. The application
  supplies clocks, startup, linker placement and readable stack bounds; TCM is optional.
- For AMP, keep buffers/state physically separate per image and reserve distinct
  timer channels. Serialize shared peripheral clock setup; decode with each core's ELF.
- Run lifecycle calls serially in privileged thread mode on 1 core. Always stop
  before dumping the whole buffer with [export_profiler_buffer.gdb](tools/export_profiler_buffer.gdb);
  decode with [analyze_profiler_buffer.py](host/analyze_profiler_buffer.py) and the exact
  unstripped executable. Plot reports with [visualize_profiler_report.py](host/visualize_profiler_report.py).
- Keep ISR code bounded and integer-only: no allocation, blocking, logging, FP or
  vector instructions. Preserve the original exception frame.
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
  Adapt the existing memory map; verify final ELF recipes and known caller chains.
  The decoder writes `stacks.folded`; render with external `flamegraph.pl` and use
  `stacks.note.txt` as the subtitle. `--stack-root NAME` selects the graph base.
  Unreliable/root-missing chains are excluded and counted; PC/PMU statistics remain intact.
  See the [RTX dual-thread FVP test](examples/corstone300_rtos2/CALL_TREE.md).
- Preserve SPDX/project headers and Doxygen contracts. Use `.clang-format` for C/H;
  preserve protected device include order.
- For behavior changes, run `python3 -B -m unittest discover -s tests -v`.
  For backend/adapter changes, also use the relevant [compile/FVP checks](tests/VALIDATION.md).
  State hardware validation limits accurately.
