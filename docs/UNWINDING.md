# Optional backtraces

Set these project-wide definitions in `cmsis_statistical_profiler.clayer.yml`:

```yaml
- PROFILER_STACK_UNWIND: 1
- PROFILER_PRECISE_STACK_BOUNDS: 1
- PROFILER_UNWIND_MAX_DEPTH: 16
```

Disabled by default. Each enabled record adds 4 bytes for depth/status plus
4 bytes per recovered caller. `PROFILER_UNWIND_MAX_DEPTH` (1–255, default 16)
bounds ISR work and temporary caller storage; unused slots are never exported.
The existing PC identifies the current function. Header `unwind_max_depth=0`
means no backtraces; a nonzero value identifies EHABI and the compiled limit.
Rebuild firmware and use the matching decoder after this format change.

## Build and integration

1. Generate unwind tables for application and library code, for example with
   `-funwind-tables` on AC6/GCC/ATfE Clang. Apply this to the code being profiled, including
   C++ sources, rather than only the profiler group. Frame pointers are not required.
   Assembly functions need unwind annotations; missing metadata stops the trace.
2. Retain `.ARM.exidx` and `.ARM.extab` in CPU-readable, immutable memory. GNU
   linker scripts can use `KEEP`; AC6 may need `--keep=*(.ARM.exidx*)`.
   Toolchains may pull in their exception runtime through table references,
   increasing image size even though this profiler never calls that runtime.
3. Implement `profiler_unwind_tables()` from
   [sampling_profiler_unwind.h](../mcu/sampling_profiler_unwind.h), supplying the
   executable span and linker-derived table ranges. Initialization fails for
   missing or structurally invalid ranges. This initial implementation supports
   1 contiguous code span and 1 sorted index table per image.
4. Implement `profiler_stack_bounds()` for the interrupted MSP/PSP allocation.
   Bounds are intersected with the existing RAM whitelist. With an RTOS, identify
   the interrupted task, validate that its frame belongs to that stack, and reject
   ambiguous context-switch states. Do not use the handler's current MSP as PSP bounds.

The [Corstone example](../examples/corstone300/README.md) implements both hooks:
add `--stack-unwind` to its build command. This also enables precise bounds and
compiler metadata generation. The [RTX dual-thread test](../examples/corstone300_rtos2/CALL_TREE.md)
validates static PSP stack bounds and separate call trees on FVP.
No board-specific logic belongs in the unwinder.

## Execution and limits

The naked IRQ entry preserves interrupted r4-r11 before calling C. The backend
combines them with the hardware frame and reconstructs the pre-exception SP,
including FP-frame reservation and alignment padding. No raw frame pointers or
stack bytes are added to the exported records.

The integer-only walker supports compact EHABI personalities 0/1/2, common core
register recipes and VFP stack-size adjustments. It never calls a personality
routine or restores FP registers. Generic personalities, PAC, other unsupported
opcodes, missing metadata and invalid reads stop the trace with a status.

Each sample is limited to `PROFILER_UNWIND_MAX_DEPTH` callers and 32 recipe bytes
per frame, with
binary-search table lookup and bounds checks before stack/table dereferences.
This bounds work but is not a measured latency guarantee: benchmark ISR overhead
on the target at the intended sample rate. It adds 40 bytes to the IRQ entry's
stack use plus C unwinder workspace.

This is best-effort sampling. Ordinary EHABI tables describe call-site state;
interrupting function entry/exit can yield plausible but incorrect traces.
Tail calls, inlining and unannotated assembly can hide callers. Exception/security
boundaries are not unwound. Task IDs are not recorded; RTOS traces aggregate tasks.

## Host output and FlameGraph

Run `host/analyze_profiler_buffer.py` normally. With backtraces present it adds:

- `stacks.folded`: root-to-leaf stacks with sample counts, ready for FlameGraph.
- `stacks.note.txt`: inclusion counts and partial-stack note for the SVG subtitle.
- `samples.csv`: `unwind_status`, `callers_raw`, `callchain` and `flamegraph_status`.
- `summary.json`: `unwind_status_counts` and `flamegraph` inclusion/exclusion totals.

The host checks record lengths, depth/status and executable address ranges in the
matching ELF. Caller addresses are symbolized at `(return_address & ~1) - 2`,
so a return address at the next function boundary belongs to the preceding call.
Recursion is permitted. Unresolved executable addresses remain explicit.
Samples exactly at an ELF function entry receive host status `function_entry`:
the caller chain is excluded from the flamegraph. Raw callers and PC/PMU statistics remain
available. An entry is retained when the ELF confirms the exact inline EHABI
finish-only recipe (`0x80b0b0b0`) and its first recovered caller equals the
captured LR: this recipe does not touch the stack and is valid at entry too.
Other recipes remain conservative. The filter does not detect later prologue
instructions, epilogues or entries missing from the ELF.

Valid partial chains remain without diagnostic frames. Unreliable chains
(`invalid_trace` and `function_entry`) are excluded, with counts in the subtitle
and summary. Widths use included samples only; PC/PMU statistics use all samples.
`complete` means a zero return address, not proof of a correct logical root.

Use `--stack-root osThreadEntry` to select the graph base. It matches an exact
displayed symbol name (including the address suffix for duplicate names), keeps
the outermost occurrence for recursion and trims older frames. Chains without
that root are excluded and counted as `root_missing`; no frames are invented.
An unmatched root produces an empty folded file and reports 0 included samples.
Full decoded chains and unwind statuses remain in CSV. Omit the option to retain
all recovered outer frames. This display choice does not change unwind validity.

With [FlameGraph](https://github.com/brendangregg/FlameGraph) installed locally:

```sh
perl /path/to/FlameGraph/flamegraph.pl --countname samples --subtitle "$(cat report/stacks.note.txt)" report/stacks.folded > report/flamegraph.svg
```

The existing HTML/Perfetto visualization remains a PC/PMU view. Flamegraph widths
represent sample counts, not per-function PMU counts. See the
[Arm EHABI frame unwinding instructions](https://github.com/ARM-software/abi-aa/blob/main/ehabi32/ehabi32.rst#103-frame-unwinding-instructions)
for how unwind recipes describe stack-pointer adjustments and register recovery
to reconstruct caller frames.
