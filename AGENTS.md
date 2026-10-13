# Agent guide

## Start here

1. Read [README.md](README.md) for the project overview and public workflow.
2. Run `git status --short` and inspect existing changes before editing. Preserve
   unrelated work; do not assume the working tree is clean.
3. Identify the affected component below, then read its guide before editing.
4. Make the change, run the applicable checks at the end of this file, and report
   what passed and what remains unverified.

| Component / task | Files | Guide |
|---|---|---|
| Capture/storage and binary layout | `mcu/sampling_profiler.c`, `mcu/sampling_profiler_format.h` | [Format](FORMAT.md) |
| Cortex-M backend, PMU and unwinding | `mcu/profiler_backend.c`, `mcu/sampling_profiler_pmu.c`, `mcu/sampling_profiler_unwind.c` | [Configuration](docs/CONFIGURATION.md), [unwinding](docs/UNWINDING.md) |
| Timer integration / new board | `adapters/`, `integrations/systick/` | Relevant adapter README, [adapter template](adapters/template/README.md) |
| Ethos-U capture | `adapters/ethosu/` | [Ethos-U adapter](adapters/ethosu/README.md) |
| New application | `examples/`, application-owned settings | [Integration checklist](docs/INTEGRATION.md), [Corstone example](examples/corstone300/README.md) |
| Decode, capture or report | `host/`, `tools/` | [Host tools](docs/HOST_TOOLS.md), [repeated captures](docs/REPEATED_CAPTURES.md), [operator reports](docs/ETHOSU_OPERATOR_REPORTS.md) as applicable |

For new integrations, establish timer, clocks, stack and code regions first.
Validate PC capture, then PMU, then backtraces. Keep settings in the application.
Never guess bounds, clocks or ownership.

## Architecture and embedded code

- Keep three layers: capture/storage, Cortex-M backend, timer integration.
  Use the paths above. Vendor dependencies belong in adapters.
- Generic SysTick needs no board adapter
  when the application supplies device, clocks, stacks, startup and linker setup.
- Compile one timer source; prefer a dedicated timer when HAL/RTOS owns SysTick.
- For AMP, separate state/buffers physically per image, reserve distinct channels,
  serialize shared clock setup and decode with each core's ELF. TCM is optional.
- Applications use `profiler_*` from `sampling_profiler.h`, including
  `profiler_sample_ticks()` and `profiler_elapsed_ms()`. Keep `profiler_port_*`
  internal and `profiler_timer_*` in timer adapters.
- Run lifecycle calls serially in privileged thread mode on one core.
  Stop before exporting the whole buffer; a full buffer still requires stop.
- Preserve the exception frame. ISR code must be bounded and integer-only:
  no allocation, blocking, logging, FP/vector instructions or personality calls.
- On Armv8-M, use captured `EXC_RETURN` to determine frame security; compile
  backend/ISR sources with `-mcmse` for Secure frames. Apply it globally only for
  an intentionally CMSE application.
- Follow [FORMAT.md](FORMAT.md): one current version-1 layout, no legacy branches.
  CPU records have six base words, 0–4 PMU words and optional depth/status plus
  only recovered callers. Default unwind depth is 16. Use `bytes_used` and each
  record's depth, never fixed backtrace stride/capacity. Change firmware, decoder
  and tests together; after release bump incompatible format identifiers.
- Follow [unwinding](docs/UNWINDING.md): bound every read, retain partial status,
  and never call exception personality routines.
- When enabling backtraces, supply precise task-stack bounds and both table-range
  and stack-bounds hooks. Defines alone are insufficient.
  Apply `-funwind-tables` to profiled sources, retain tables
  using the documented AC6 or GCC/LLVM recipe and check the final ELF. For large
  AC6 images use fresh selective two-pass retention, then recheck the final link.
- Ethos-U uses a separate [EUTR buffer](adapters/ethosu/README.md) and
  `trace_ethosu_*` API. Discover immutable streams in the driver callback; no
  application registration.
- When the application already implements the driver callback, forward exactly
  once to `trace_ethosu_inference_begin` and set
  `PROFILER_ETHOSU_DRIVER_CALLBACK=0` project-wide.
- Ethos-U PMU ownership lasts until stop returns, including after buffer full.
  Set `PROFILER_ETHOSU_PMU_COUNT=0` when the application owns the PMU.
- Weight compressed Ethos-U idle records by represented ticks. Group hotspots by
  `(stream_id, QREAD)`; keep unknown streams separate.
- Reuse [the event catalog](host/ethosu_pmu_events.py): driver 1.26.2 enum IDs differ
  from TRM codes, unknown IDs stay numeric and repeated counter slots stay distinct.

## Capture and reporting

Apply this section when producing captures/reports or changing host tools.
Use the task guides above for commands and detailed validation.

- Run ELF preflight before capture; retain exact ELF/AXF, revision, raw buffers,
  decoded reports and provenance. Finalize every enabled capture, verify `complete=1`
  and `active=0`, and export before reuse. Check chunk addresses/lengths; pad only
  the unused tail. Never concatenate raw captures or count debugger pauses as time.
- Package every completed report with human Markdown and an offline `index.html`
  generated after optional artifacts. Supply actual board/application and verified
  platform metadata. Verify local links and regenerate when artifacts change.
  Preserve aggregate manifest-relative paths; owned `mcu_report/` replacement
  must succeed through staging. Include available artifacts; omit missing outputs.
- Use Brendan Gregg's external `flamegraph.pl`, with `stacks.note.txt` subtitle
  and one stack-root selection across captures. State included-stack denominators;
  keep missing roots/unreliable callers separate in the all-PC view. Annotate
  hotspots with the exact ELF, `--top 5 --group-instructions 8`, and report
  unmatched PCs; source/tool overrides are documented in the host guide.
- For repeated captures generate a combined Perfetto timeline with window boundaries
  and pauses omitted; include Ethos-U only when every capture synchronizes both
  reports. Keep the index's automatic Perfetto control and localhost instructions.
- Validate shared ticks/timestamps before MCU/NPU folds; exclude capture-edge
  periods and report phase coverage. Joint plots require matching captures and
  per-phase inference counts, preserve the CPU function mix and separate PMU slots.
  Check chains/scheduling before counting separated PC segments as calls; preserve
  gaps and label inferred spans.
- Exact PTE/listing bytes and matching Vela debug metadata must align before TOSA
  summaries or operator charts. Capture-to-PTE and database-to-build associations
  are caller supplied; hashes do not prove deployment. Check raw operator QREAD
  counts before optional median-phase charts. QREAD phases and idle snapshots
  are observations, not exact operator boundaries or inference durations.
- Never infer CPU/NPU frequency from the profiler timer. Non-idle PC share needs
  explicit idle classification and is an estimate, not cycle utilization. Take
  rates, totals and validation from decoded metadata. PMU intervals are separate
  from PC/QREAD attribution; idle display zeros are not measured counter zeros.

## Checks and style

Preserve SPDX/project headers and Doxygen contracts. Use `.clang-format` for C/H
and preserve protected device include order. Format host Python with
`ruff format host/`; check with `ruff format --check host/`. Comments should
explain binary layouts and validation decisions.

Use every applicable row below. Commands run from the repository root.

| Change | Required checks |
|---|---|
| Behavior in firmware or host tools | `python3 -B -m unittest discover -s tests -v` |
| Cortex-M backend, PMU or unwinding | Unit suite plus relevant Cortex-M compile matrix and FVP checks from [validation](tests/VALIDATION.md) |
| Timer integration or board adapter | Unit suite plus relevant adapter compilation and available target/FVP checks from [validation](tests/VALIDATION.md) |
| Ethos-U adapter | Unit suite plus `tests/compile_ethosu.py` with the matching driver SDK; see [validation](tests/VALIDATION.md) for options and limits |
| C/H files | `python3 tests/check_c_format.py` (clang-format 22.1.0) |
| Host Python | `ruff format --check host/` |
| Markdown only | Check local links, command names/options and agreement with the referenced code; behavior tests are unnecessary |

The bare-metal AC6 solution uses `profiler.FVP+Corstone300` or
`profiler.Unwind+Corstone300`, configured packs and `AC6_TOOLCHAIN_6_24_0`.
Use `tests/run_fvp.py`. RTOS tests use their shared Toolbox solution through
`tests/run_rtos_fvp.py --kernel rtx` or `--kernel freertos`.
If a required check cannot run, state which check and why. Distinguish native
tests, compilation, FVP execution and physical hardware evidence.
