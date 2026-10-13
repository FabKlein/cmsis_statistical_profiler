# Corstone-300 capture example

Secure bare-metal example with startup, ITCM/DTCM linker script and a validated
250 ms workload. TIMER0 samples while application SysTick runs independently.
The example checks SysTick continuity and profiler stop/restart.

## AC6 with CMSIS-Toolbox

Requires CMSIS-Toolbox 2.13, AC6 6.24 and the packs pinned in
[profiler.csolution.yml](profiler.csolution.yml). Set `AC6_TOOLCHAIN_6_24_0` to
AC6's `bin` directory and put Toolbox on `PATH`. From the repository root:

```sh
python3 host/generate_profiler_build_config.py \
  --output examples/corstone300/profiler_build_config.generated.h \
  --pmu-count 2 --unwind-depth 16
cbuild examples/corstone300/profiler.csolution.yml \
  --context profiler.FVP+Corstone300 --packs --update-rte --output build/corstone300
```

The executable is `build/corstone300/out/profiler/Corstone300/FVP/profiler.axf`.
The `Unwind` context additionally enables backtraces and retains EHABI tables.
Application settings live in [profiler.cproject.yml](profiler.cproject.yml):
333 Hz, 64 KiB buffer, 2 PMU events, PSP/FP workload, 2 captures and a reference-counter timestamp.

For the complete build/run/decode pass/fail check (the CI command):

```sh
python3 tests/run_fvp.py --output build/fvp
# Add --stack-unwind for the Unwind context, or --fvp /path/to/FVP_Corstone_SSE-300.
```

The runner generates a fresh shared build header, runs ELF preflight before
capture, and copies the AXF to `build/fvp/profiler.elf` alongside the capture and
reports. It retains `profiler_build_config.h` and verifies the captured token
against the ELF. Regenerate the manual-build header before every new build and
archive it with that executable.
For a manual run of the direct cbuild output, use its `profiler.axf` path with `-a`.

## Configurable builds / GCC / ATfE

The Python wrapper preserves the options below. AC6 (`--cc /path/to/armclang`)
also uses `cbuild` and requires PyYAML; generated project overrides stay in
`OUTPUT/toolbox-source`. GCC (default) and ATfE (`--cc /path/to/ATfE/bin/clang`)
continue to compile directly. The wrapper generates its own shared header and
exports `OUTPUT/profiler.elf` and `OUTPUT/profiler_build_config.h`.

```sh
python3 examples/corstone300/build.py \
  --cmsis /path/to/ARM/CMSIS/6.3.0 \
  --bsp /path/to/ARM/V2M_MPS3_SSE_300_BSP/1.5.0 \
  --output build/corstone300 --semihosting --sample-hz 2500 --buffer-bytes 65536 \
  --timer-clock-hz 100000000 --captures 2 --reference-timestamp
```

Run the FVP from the build directory so the post-capture dump is written there:

```sh
cd build/corstone300
FVP_Corstone_SSE-300_Ethos-U55 -a profiler.elf \
  -C core_clk.mul=32000000 \
  -C mps3_board.sse300.refcounter.base_frequency=100000000 \
  -C cpu0.semihosting-enable=1 \
  -C mps3_board.visualisation.disable-visualisation=1 \
  -C mps3_board.telnetterminal0.start_telnet=0 \
  -C mps3_board.telnetterminal1.start_telnet=0 \
  -C mps3_board.telnetterminal2.start_telnet=0 \
  -C mps3_board.telnetterminal5.start_telnet=0 --simlimit 3
python3 ../../host/analyze_profiler_buffer.py --samples samples.bin --elf profiler.elf --output report
```


The commands match a 32 MHz BSP CPU and 100 MHz reference timer. FVP defaults to
25 MHz CPU; omitting the override fails the SysTick check. `--captures 2` exports
the final capture. Semihosting occurs only after capture.

Expect `validation_passed=1`, `complete=1`, `active=0`, `rejected=0`, about 625 samples
at 2500 Hz, mostly in `run_once`. A simulation-limit exit alone does not prove success.

| Build option | Purpose |
|---|---|
| `--sample-hz`, `--buffer-bytes` | Sampling rate and allocation budget |
| `--psp --float-workload` | Exercise PSP/extended frames; EXC_RETURN normally `0xFFFFFFED`, possibly `0xFFFFFFFD` before FP use |
| `--call-tree` | Non-inlined A–F NOP workload; enables backtraces and precise bounds |
| `--stack-unwind` | Enable compact EHABI backtraces and precise bounds; see [setup](../../docs/UNWINDING.md) |
| `--precise-stack-bounds` | Check linker MSP bounds and the example PSP array; still enforce the RAM whitelist |
| `--reference-timestamp` | Use the 100 MHz reference counter for FVP timing; default is DWT |
| `--pmu-count 0..4` | Select event count; `--pmu` is shorthand for 2. Defaults: cache refill, backend stall, instructions retired, CPU cycles |

Ordinary MSP captures use EXC_RETURN `0xFFFFFFF9`. PMU events can count 0 for
this ITCM/DTCM workload/model. FVP validates capture flow, not silicon performance.

## Linker layout

[linker.ld](linker.ld) is used by GCC/ATfE and the RTX call-tree test. AC6 uses
[linker.sct](linker.sct). Both target this example's secure ITCM/DTCM mapping.

| Region | Execution range | Contents |
|---|---|---|
| ITCM | `[0x10000000, 0x10080000)` | Vectors, code/RO, EHABI and initial data image |
| DTCM | `[0x30000000, 0x30080000)` | Data/BSS, buffer and PSP stacks; final 16 KiB reserved for MSP |

[unwind_tables.c](unwind_tables.c) consumes linker-derived code/table bounds.
Adapt the [AC6](../../docs/UNWINDING.md#ac6-scatter-file-integration) or
[GCC/LLVM recipe](../../docs/UNWINDING.md#gcc--llvm-linker-script-integration)
to application maps; GNU/LLVM ordinary selectors retain live tables without
blanket KEEP. The BSS/MSP overlap assertion and libc `end` alias allocate no heap.
Check `profiler.map` for exact placement.

## MPS3 FPGA

Build without `--semihosting`, load with the board debugger and break at
`profiler_capture_complete`. Use [export_profiler_buffer.gdb](../../tools/export_profiler_buffer.gdb)
and decode with the matching ELF.

Confirm the FPGA image's clocks and memory map: this linker assumes 512 KiB secure
ITCM and 512 KiB secure DTCM. Set `--timer-clock-hz` to the actual reference frequency.
The example starts the shared reference counter unscaled; adapt this to existing
board setup. FPGA execution remains unverified.

## CI regression

Use [the runner/reference](../../tests/VALIDATION.md#ci-reference) for CI acceptance,
artifact contents and the FVP reference-timestamp rationale. Add
`--stack-unwind --output build/fvp-unwind` for backtrace checks. The PSP trace
stops at its naked stack-switch wrapper and is intentionally partial.

## A–F flamegraph workload

[call_tree.c](call_tree.c) repeats `functionA(); 100 NOPs` through the capture
harness. A calls B 2 times, B calls C 4 times, C calls D 8 times, D calls E 16
times and E calls F 32 times, each call followed by 100 NOPs. F executes 100 NOPs.
Validation requires 32,768 F calls per iteration. Functions are `noinline`;
the builder also disables inlining and sibling-call optimization for this workload
and its harness. The timeout is checked between iterations, so capture can exceed
250 ms. Most samples should land in E/F; shallow levels execute much less often.

Use the build/run commands above with `--call-tree --sample-hz 333` and an output
directory such as `build/call-tree`. The ordinary CI reference does not apply.
Follow the
[host FlameGraph workflow](../../docs/HOST_TOOLS.md#optional-backtraces-and-flamegraph).
A deep sample contains `capture;profile_workload;run_once;A;B;C;D;E;F`
(the workload symbols are `functionA`, etc.); depth 16 can also retain main/Reset.
Partial startup stops and entry/exit sampling remain best-effort limitations.

For disjoint executable regions, add `--call-tree --split-code`. F executes in
secure code SRAM; A–E remain in ITCM. See [split linker scripts and hook](../../docs/UNWINDING.md#split-executable-regions).
Run `python3 host/check_profiler_elf.py --elf build/corstone300/profiler.elf --require-unwind --function functionF`
from the repository root before capture.

## Acronyms used in these examples

| Term | Meaning |
|---|---|
| FVP / BSP | Fixed Virtual Platform (simulator) / Board Support Package (device support files) |
| RTOS / TCB | Real-Time Operating System / Task Control Block (kernel bookkeeping for a task) |
| MSP / PSP | Main Stack Pointer / Process Stack Pointer; these tests use PSP for threads and MSP for interrupts |
| IRQ / ISR / NVIC | Interrupt Request / Interrupt Service Routine / Nested Vectored Interrupt Controller |
| ITCM / DTCM | Instruction / Data Tightly Coupled Memory |
| DWT / PMU | Data Watchpoint and Trace (provides a cycle counter) / Performance Monitoring Unit |
| EHABI / ELF | Exception Handling Application Binary Interface (unwind metadata) / Executable and Linkable Format (firmware file) |
| CNTCR | System Counter Control Register; its EN bit enables the shared reference counter |

Enabling the shared counter does not enable sampling interrupts. TIMER0 controls
when the profiler interrupts the application; the counter supplies its timebase.
