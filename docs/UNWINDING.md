# Optional backtraces

Set these definitions project-wide in your application:

```yaml
- PROFILER_STACK_UNWIND: 1
- PROFILER_PRECISE_STACK_BOUNDS: 1
- PROFILER_UNWIND_MAX_DEPTH: 16
```

Disabled by default. Each enabled record adds 4 bytes for depth/status plus
4 bytes per recovered caller. `PROFILER_UNWIND_MAX_DEPTH` (1-255, default 16)
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
   executable region list and linker-derived table ranges. Initialization fails for
   missing or structurally invalid ranges. Supply 1-8 sorted, nonoverlapping code
   regions and 1 sorted index table per image. Gaps are never executable, and an
   index recipe cannot extend from 1 region into another.
4. Implement `profiler_stack_bounds()` for the interrupted MSP/PSP allocation.
   Bounds are intersected with the existing RAM whitelist. With an RTOS, identify
   the interrupted task, validate that its frame belongs to that stack, and reject
   ambiguous context-switch states. Do not use the handler's current MSP as PSP bounds.

The [Corstone example](../examples/corstone300/README.md) implements both hooks:
add `--stack-unwind` to its build command. This also enables precise bounds and
compiler metadata generation. The [RTX dual-thread test](../examples/corstone300_rtos2/CALL_TREE.md)
validates static PSP stack bounds and separate call trees on FVP.
No board-specific logic belongs in the unwinder.

### AC6 scatter-file integration

Inside the existing load region, add these execution regions **after the code/RO
region and before the RAM regions**, as in [linker.sct](../examples/corstone300/linker.sct):

```text
    ER_EXIDX +0 { *(.ARM.exidx*) }
    ER_EXTAB +0 { *(.ARM.extab*) }
```

`+0` places each region immediately after the preceding execution region.
`ER_EXIDX` holds the code-to-recipe index; `ER_EXTAB` holds recipes too large for
an inline index entry. Both must remain readable during capture. Allow room for
them in the load region; these additions do not increase its configured size.

Compile profiled sources with `-funwind-tables` and add the armlink option
`--keep=*(.ARM.exidx*)` (quote it when invoking through a shell) and
`--no_compressexidx` to retain entries at disjoint code-region boundaries. Placement alone
does not generate tables or guarantee retention. Prebuilt libraries need their
own unwind metadata; missing metadata stops the trace.

Add [unwind_tables.c](../examples/corstone300/unwind_tables.c) to the application,
or implement its hook using these linker symbols:

| Hook range | AC6 boundary symbols |
|---|---|
| Code | `Image$$ER_ITCM$$Base` / `Image$$ER_ITCM$$Limit` |
| Index | `Image$$ER_EXIDX$$Base` / `Image$$ER_EXIDX$$Limit` |
| Recipes | `Image$$ER_EXTAB$$Base` / `Image$$ER_EXTAB$$Limit` |

`ER_ITCM` is the example's code-region name, not a TCM requirement. Substitute
your code region's name in the hook. If you rename the table regions, update
their symbol references too. For split code placement, add each execution region
to the hook; do not enclose ITCM and SRAM in 1 broad range.

Check the map file for the regions and resolved boundary symbols. The index must
be nonempty; `.ARM.extab` may be empty when all recipes fit inline. Finally,
confirm `sampling_profiler_init()` succeeds. The precise stack-bounds hook from
step 4 is still required; scatter-file changes alone do not enable backtraces.

### GCC / LLVM linker-script integration

GCC with GNU ld and ATfE Clang with LLD use the same example
[linker.ld](../examples/corstone300/linker.ld). Adapt the sections below inside
your existing `SECTIONS` block; `CODE` means your CPU-readable code memory region,
not necessarily TCM. Merge with existing sections instead of defining duplicates.

```text
.text :
{
    __profiler_code_start = .;
    *(.text*)
    __profiler_code_end = .;
    *(.rodata*)
} > CODE
.ARM.extab :
{
    __profiler_extab_start = .;
    KEEP(*(.ARM.extab*))
    __profiler_extab_end = .;
} > CODE
.ARM.exidx :
{
    __exidx_start = .;
    KEEP(*(.ARM.exidx*))
    __exidx_end = .;
} > CODE
```

Preserve your startup/vector selectors, alignment, memory limits and data/stack
placement. The code bounds must cover the executable span being unwound; adapt
for custom code sections. Keep unwind tables separate from `.text`/`.rodata`
and remove any rule that discards them. `KEEP` retains them with `--gc-sections`.
The linker orders the EHABI index; do not sort its input sections by name.

Compile profiled C/C++ sources with `-funwind-tables`, then link with your script
using `-T firmware.ld -Wl,--no-merge-exidx-entries`. Retaining individual index
entries prevents equal recipes being merged across separate code regions. For Clang, select the embedded target, for example
`--target=arm-none-eabi -mcpu=cortex-m55 -mthumb`, and use the matching runtime
and linker. ATfE supplies these; a host LLVM installation alone may not.
See [build.py](../examples/corstone300/build.py) for the tested GCC/ATfE commands.

Add [unwind_tables.c](../examples/corstone300/unwind_tables.c), or adapt its
non-AC6 branch. It consumes the 6 boundary symbols above; renaming a symbol
requires updating the hook. Addresses are execution addresses, not load-image
addresses. The example's `PROVIDE(end = __bss_end__)` satisfies optional libc
references; it is not a profiler requirement or a heap allocator.

### Integration checklist and examples

1. Enable `PROFILER_STACK_UNWIND=1`, `PROFILER_PRECISE_STACK_BOUNDS=1` and
   `PROFILER_UNWIND_MAX_DEPTH=16` consistently across application/profiler sources.
   The common clayer includes `mcu/sampling_profiler_unwind.c`; manual builds must
   add it. Keep the layer's ISR compiler restrictions.
2. Generate/retain the tables using the toolchain instructions above. Link exactly
   1 `profiler_unwind_tables()` and 1 precise `profiler_stack_bounds()` implementation.
   The board timer must use `PROFILER_DEFINE_IRQ_HANDLER` to preserve registers.
3. Inspect the final ELF/map: a nonempty `.ARM.exidx`, resolved hook boundaries,
   and unwind recipes for the workload. With GCC use `arm-none-eabi-readelf --unwind firmware.elf`; with LLVM use `llvm-readelf --unwind firmware.elf`. Table presence
   alone is insufficient if the workload entries are all `CANTUNWIND`.
4. Confirm initialization succeeds, capture known nested calls, stop and export.
   Decode with the exact ELF; check recovered chains and `unwind_status_counts`,
   not just PC hits. Render `stacks.folded` with its inclusion-count subtitle.

| Example | Integration reference |
|---|---|
| Bare-metal GCC/AC6/ATfE | [Build/run guide](../examples/corstone300/README.md): add `--stack-unwind`; [main.c](../examples/corstone300/main.c) supplies MSP/PSP bounds |
| Known A-F call tree | Same builder with `--call-tree`; enables unwinding and disables workload inlining/sibling calls |
| CMSIS-RTX / ATfE | [2-thread FVP guide](../examples/corstone300_rtos2/CALL_TREE.md), [builder](../examples/corstone300_rtos2/build_call_tree.py), [static stack registry](../examples/corstone300_rtos2/call_tree_main.c) |

Use these as integration patterns; retain the target application's memory map,
startup, interrupt ownership and stack allocations.

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

## Split executable regions

Use `build.py --call-tree --split-code` in the Corstone example. It places A-E in
ITCM and F in separate code SRAM, with 1 sorted index and 2 regions in
[unwind_tables.c](../examples/corstone300/unwind_tables.c):

```text
ITCM: 0x10000000 [vectors, A-E, tables] ... gap ... SRAM: 0x11000000 [F]
                  code[0]                                     code[1]
```

[GCC/LLD linker_split.ld](../examples/corstone300/linker_split.ld) exports SRAM
bounds and a load address; [startup.c](../examples/corstone300/startup.c) copies
the code before use. [AC6 linker_split.sct](../examples/corstone300/linker_split.sct)
uses `ER_SRAM`, copied by scatter loading. Adapt addresses and startup/cache
maintenance to your board. Code regions use execution addresses and exclude gaps;
no hand-written CANTUNWIND sentinel is needed. Keep the region array alive and
immutable throughout capture. An absent recipe at a new region stops unwinding.

## Check the ELF before capture

[ELF preflight](../host/check_profiler_elf.py) checks the compiled firmware without
running it. **1 command checks the unwind tables and coverage of all sized function
symbols in executable sections. You do not need to list functions individually.**

```sh
python3 host/check_profiler_elf.py --elf firmware.elf --require-unwind --output preflight.json
```

- Invalid table structure, missing tables or missing integration hooks cause failure.
- Functions with missing or unsupported metadata produce a warning summary.
- `preflight.json` contains the result for each function, including those that pass.

Optionally add `--function functionF` to the same command to make missing or
unsupported coverage for that function cause failure too. Repeat `--function`
for other required functions; the checker still examines the whole ELF.

If a needed library function lacks metadata, rebuild that library with
`-funwind-tables` and retain its tables at link time. Enabling tables only for
application sources cannot repair a prebuilt library.

A pass confirms the checked metadata structure, not correct runtime backtraces.
The checker does not validate every unwind instruction or runtime stack access;
follow it with a capture of known nested calls.
