# Corstone-300 capture example

Secure bare-metal example with startup, ITCM/DTCM linker script and a validated
250 ms workload. TIMER0 samples while application SysTick runs independently.
The example checks SysTick continuity and profiler stop/restart.

Requires AC6, Arm GNU GCC or ATfE Clang, CMSIS 6.x and SSE-300 BSP 1.5.0.
Add `--cc /path/to/armclang` for AC6 (scatter file and Microlib), or
`--cc /path/to/ATfE/bin/clang` for ATfE (LLD and bundled libc). GCC is the default.
From the repository root:

```sh
python3 examples/corstone300/build.py \
  --cmsis /path/to/ARM/CMSIS/6.0.0 \
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

```text
ITCM: 0x10000000 .. 0x10080000     DTCM: 0x30000000 .. 0x30080000
+---------------------------+    +---------------------------+
| Interrupt vectors         |    | .data (copied at startup) |
| .text: executable code    |    | .bss: buffer, PSP stacks, |
| .rodata: constants        |    |       other zeroed state  |
| .ARM.extab: unwind recipes|    +---------------------------+
| .ARM.exidx: recipe index  |    | Free space                |
| Initial .data image       |    +---------------------------+ 0x3007c000
| Free space                |    | MSP: 16 KiB, grows down   |
+---------------------------+    +---------------------------+ 0x30080000
```

For application integration, see the [AC6 scatter-file steps](../../docs/UNWINDING.md#ac6-scatter-file-integration)
or [GCC/LLVM linker-script steps](../../docs/UNWINDING.md#gcc--llvm-linker-script-integration).

GNU-script backtrace additions retain `.ARM.exidx`/`.ARM.extab` with `KEEP`, even during
linker garbage collection. Boundary symbols let [unwind_tables.c](unwind_tables.c)
supply the index, recipes and executable-only `.text` range to the unwinder.
`end` aliases the end of `.bss` for libc references pulled in by optional unwind
runtime code; it does not allocate a heap. The existing assertion prevents
`.data`/`.bss` from overlapping the reserved MSP region. Sizes within each region
vary with the build; see `profiler.map` for exact placement.

## MPS3 FPGA

Build without `--semihosting`, load with the board debugger and break at
`profiler_capture_complete`. Use [export_profiler_buffer.gdb](../../tools/export_profiler_buffer.gdb)
and decode with the matching ELF.

Confirm the FPGA image's clocks and memory map: this linker assumes 512 KiB secure
ITCM and 512 KiB secure DTCM. Set `--timer-clock-hz` to the actual reference frequency.
The example starts the shared reference counter unscaled; adapt this to existing
board setup. FPGA execution remains unverified.

## CI regression

[GitHub Actions](../../.github/workflows/fvp.yml) builds with AC6 6.24 and runs FVP
11.31.28 with PMU enabled. Use [the runner and reference](../../tests/VALIDATION.md#ci-reference)
for the same local pass/fail check.

CI uses `--reference-timestamp`: the low 32 bits of the free-running TIMER0
reference counter, at `--timer-clock-hz`. This avoids the functional FVP's DWT
rate mismatch while retaining the strict timing check. It measures elapsed time,
not CPU cycles, and does not reset or reconfigure the shared counter.

For a backtrace regression, add `--stack-unwind --output build/fvp-unwind` to
`tests/run_fvp.py`. It requires at least 90% of samples to recover 2 callers and
checks that folded-stack counts match the capture. The PSP example stops at its
naked stack-switch wrapper, so its traces are intentionally reported incomplete.

## A–F flamegraph workload

[call_tree.c](call_tree.c) repeats `functionA(); 100 NOPs` through the capture
harness. A calls B 2 times, B calls C 4 times, C calls D 8 times, D calls E 16
times and E calls F 32 times, each call followed by 100 NOPs. F executes 100 NOPs.
Validation requires 32,768 F calls per iteration. Functions are `noinline`;
the builder also disables inlining and sibling-call optimization for this workload
and its harness. The timeout is checked between iterations, so capture can exceed
250 ms. Most samples should land in E/F; shallow levels execute much less often.

Use the build/run commands above with `--call-tree --sample-hz 333` and an output
directory such as `build/call-tree`. The ordinary CI workload reference does not
apply. After decoding, generate an interactive SVG with a local
[FlameGraph](https://github.com/brendangregg/FlameGraph) checkout:

```sh
perl /path/to/FlameGraph/flamegraph.pl --countname samples \
  --subtitle "$(cat report/stacks.note.txt)" report/stacks.folded > report/flamegraph.svg
```

Open the SVG in a browser. A full deep sample contains
`capture;profile_workload;run_once;functionA;functionB;functionC;functionD;functionE;functionF`:
8 callers plus the sampled PC within that suffix. The 16-caller limit also
allows `main` and `Reset_Handler` to be retained, aligning the graph roots.
Traces still stop at unsupported startup boundaries; partial-stack status is
reported outside the plotted hierarchy. Samples during
entry/exit may skip callers; executable-address validation cannot detect every
plausible incorrect chain. Unreliable entry samples are excluded from the graph and counted in its subtitle.

For disjoint executable regions, add `--call-tree --split-code`. F executes in
secure code SRAM; A–E remain in ITCM. See [split linker scripts and hook](../../docs/UNWINDING.md#split-executable-regions).
Run `python3 host/check_profiler_elf.py --elf build/corstone300/profiler.elf --require-unwind --function functionF`
from the repository root before capture.
