# Validation evidence and reproduction

Results below distinguish current regression checks, earlier target runs and
unverified configurations. FVP demonstrates capture behavior, not cycle-accurate
silicon performance. Format and lifecycle contracts live in [FORMAT.md](../FORMAT.md)
and [configuration](../docs/CONFIGURATION.md); historical captures require their
original decoder and ELF.

## Current checks (13 October 2026)

| Check | Evidence |
|---|---|
| Native/host suite | 183 tests passed, no skips, Plotly installed |
| Cortex-M matrix | GCC 13.2.1 and AC6 6.24: all 12 supported cores, applicable security/timestamp modes, PMU 0/4, unwind off/depth 16, `-O2` |
| Corstone SDK compilation | CMSIS 6.3.0 / BSP 1.5.0; 125/333/2500 Hz, sampling on/off |
| Ethos-U SDK compilation/probes | Core-driver 1.26.2, U55/U65/U85, PMU 0/1/4; GCC/AC6 Cortex-M55 builds with callback on/off; native invalid-event and RAM-register ownership/readback probes |
| Fresh AC6/FVP captures at final review | PC/PMU: 83 samples; unwind: 83, 82 with two recovered callers, all partial `no_progress`; complete/inactive, valid timing/workload, zero rejected/unresolved, exact-ELF tokens match |
| Build identity | Read-only 16-byte ELF object retained with LTO/section GC; per-file layout overrides rejected; wrong-ELF decoding fails before output |
| Linked ISR inspection | Integer-only vector/backend/storage/PMU/bounds/unwind paths; frame/EXC_RETURN and callee registers preserved |
| Generated CMSIS layers | AC6/GCC/CLANG option scope preserves application flags and protects profiler/timer groups; NXP layer needs its own device pack |
| Host charts/packaging | Synchronized synthetic wrap/rounded-period inputs, MCU/NPU/joint SVG/PNG, repeated PMU slots, optional-render failure preservation; 53 offline index links verified |
| Style/docs/CI syntax | Ruff, clang-format 22.1.0, Doxygen, actionlint 1.7.12 and whitespace checks |

The suite covers bounded EHABI reads and partial prefixes, mixed-depth records,
MSP/PSP/FP/alignment frames, lifecycle restart/idempotent stop, PMU chaining and
rollover, stack-region rejection, startup rollback/PRIMASK restoration, build
identity, capture/aggregate schemas, explicit idle classification and cumulative
clock/epoch checks. Ethos-U probes cover busy counters/IRQs, invalid events,
readback failure and owned-resource cleanup. Alif probes cover all 12 channels,
shared-clock preservation and other-channel isolation. Cleanup regressions also
check inactive PMU snapshots, failure at each Ethos-U event slot, insufficient
capacity, and truncated/oversized/unsupported COP1 payloads without stale IDs.

The PC-only AC6 scatter context emits two existing empty unwind-section warnings;
the Unwind context retains and preflights nonempty tables.

**Limits:** no new silicon ISR-time/stack-high-water measurement, physical NPU
IRQ/power/W1C validation or licensed RTX/FreeRTOS runtime run. RAM-register probes
cannot establish those hardware behaviors. The corrected NXP Cortex-M33 compile
path was checked, but a fresh NXP SDK build was unavailable. Remote GitHub CI was
not triggered by the local review.

## Earlier runtime and integration evidence

| Configuration | Observed result and scope |
|---|---|
| Corstone bare-metal FVP | 125/333/2500 Hz, MSP and PSP/FP, precise bounds, stop/restart and independent application SysTick |
| AC6 four-event FVP | 84 samples, valid timing, 100% workload hits; all four events decoded, model totals zero |
| PMU software increment | 2,020,000 events per chained pair, including low-half rollover |
| ATfE 22.1 / LLD PSP/FP FVP | 84 samples, zero rejected/unresolved, 97.62% with two callers |
| ATfE A–F, 333 Hz/depth 16 | 151 samples; all ten F hits recover ten callers to Reset, no depth truncation; three unreliable entries excluded |
| RTX 5.9.1 / Toolbox 2.13 / ATfE 22.1 | 665 samples, zero rejected/unresolved, 657 plotted chains, separate static PSP worker trees; [run guide](../examples/corstone300_rtos2/CALL_TREE.md) |
| CMSIS-FreeRTOS 11.2.0, same tools | 664 samples, valid timing, zero rejects, 660 plotted chains; [run guide](../examples/corstone300_freertos/README.md) |
| CMSIS-RTOS2 illustration | GCC/AC6 compilation only; no linked kernel/runtime |
| Split ITCM/code-SRAM FVP | AC6 6.24, GCC 13.2 and ATfE 22.1: valid timing, no unresolved PCs; partial traces retained |
| STM32N6/Corstone/Alif/NXP SDK adapters | Earlier GCC/AC6 header builds and GCC relocatable links; fresh scope differs as stated above |
| System LLVM Clang 22 matrix | All 12 cores, applicable security/timestamps, PMU four/depth 16 at `-O2`; Newlib include path required; compile evidence only |

GCC 13 uses `-march=armv8.1-m.main` for M52 because it lacks that CPU name.
Inspect ISR disassembly after compiler/LTO changes. FVP zero refill/stall events
for ITCM/DTCM workloads do not predict silicon stalls. Clean Toolbox builds and
stale-output rejection are tested for both RTOS contexts; dynamic task allocation,
deleting tasks and sampling during context switches are outside those runtime tests.

### Physical hardware

| Target/path | Evidence | Detailed integration limits |
|---|---|---|
| NXP MIMXRT685-EVK CTIMER4 | M33, 48 MHz, 1 kHz, 128 KiB, depth 16, PMU off; 2,253 accepted, zero rejected/unresolved/faults, 2,252 rooted A–F stacks | [Adapter](../adapters/nxp_rt685/README.md) |
| NXP MIMXRT685-EVK SysTick | M33 RAM image, 1 kHz, 128 KiB; 2,248 accepted, zero rejected/unresolved, 2,247 rooted stacks | [EXC_RETURN/security finding](../integrations/systick/README.md#nxp-mimxrt685-evk-hardware-validation) |
| PSOC Edge E84 SysTick | Independent M55/M33 RAM images, 64 KiB, 1 kHz/depth 16; zero rejected/unresolved, A–F chains; M55 four PMU events, M33 none | [Inherited boot configuration](../integrations/systick/README.md#psoc-edge-hardware-validation) |
| Himax WE2 TIMER4 | M55, 1 kHz, 128 KiB/four PMU/depth 16; 2,049 accepted, zero rejected/unresolved; expected A/B/C chain | [SDK vector handoff and UART](../adapters/himax_we2/README.md) |
| Alif DevKit-E8 AMP | HP channel 2/HE channel 1, separate SRAM/four PMU/exact AXFs; first run 8,039/4,306 samples, zero rejected; later HE 5,095 samples, 97.2% reach application root | [Clock/probe/retention findings](../adapters/alif_e8/README.md) |

STM32N6 and MPS3 FPGA execution are unverified. Hardware results establish the
listed applications, not arbitrary startup, interrupt ownership or complete
library unwinding. Other physical targets, M0/Non-secure runtime, other kernels,
dynamic stacks and macOS portability remain unverified.

## ISR size and stack evidence

[ISR_BUDGET.md](../docs/ISR_BUDGET.md) is the reference for compiler frame tables,
complete-path accounting and target measurement. On 10 October, GCC/AC6 each
checked 124 `-Os` configurations; 40 additional GCC M55 cases compared depths 4/32
and PMU 0–4. Frames were static. These differ from the current `-O2` matrix.

Historical metadata/gate cleanup reduced GCC M55 object code/RO sizes under
identical `-Os -mcmse -mfloat-abi=soft` section/vectorization settings:

| Features | Record writer bytes, before → after | CPU + SysTick bytes, before → after |
|---|---|---|
| PC | 120 → 96 | 1,454 → 1,422 |
| PC + four PMU | 152 → 132 | 2,026 → 1,998 |
| PC + backtraces | 168 → 152 | 3,150 → 3,126 |
| PC + four PMU + backtraces | 208 → 196 | 3,734 → 3,714 |

Writer PC-only frame fell from 32 to 20 bytes; rejection helper from 40 to 32
code bytes. A later bounded-pop cleanup reduced unwind object size 1,436→1,424
bytes, keeping handler/walker frames at 216/112 bytes. Object totals exclude
library helpers and application tables. These measurements are historical size
comparisons, not current image sizes, latency or recommended stack allocations.

## SDKs used

| SDK | Version / revision |
|---|---|
| CMSIS | 6.0.0 in earlier board checks; 6.3.0 architecture/current Corstone checks |
| V2M_MPS3_SSE_300_BSP | 1.5.0 |
| Ethos-U core-driver | 1.26.2 |
| ST cmsis-device-n6 | `81fe2fe8d576ec4c55be308ac4504bd580e498e6` |
| ST stm32n6xx-hal-driver | `d88071ed0adc1991a5daed6f20ab311f80bb33b7` |
| Alif alif_ensemble-cmsis-dfp | `652dd6bf6856891695dfef1f0e7f74829ec9f451` |
| NXP MIMXRT685S DFP | 26.06.00 |

## Reproduce

```sh
python3 -B -m unittest discover -s tests -v
python3 tests/compile_cortex_m.py --cmsis /path/to/ARM/CMSIS/6.3.0
python3 tests/compile_adapters.py \
  --cmsis /path/to/ARM/CMSIS/6.0.0 \
  --corstone-bsp /path/to/ARM/V2M_MPS3_SSE_300_BSP/1.5.0 \
  --stm32-cmsis /path/to/cmsis-device-n6 \
  --stm32-hal /path/to/stm32n6xx-hal-driver \
  --alif-dfp /path/to/alif_ensemble-cmsis-dfp \
  --nxp-rt685-dfp /path/to/NXP/MIMXRT685S_DFP/26.06.00 \
  --sample-hz 125 333 2500 --pmu
python3 tests/check_layer_scope.py --compiler AC6 GCC CLANG
```

SDKs are not downloaded; omit unavailable adapter options. Scope checks need
csolution, PyYAML and packs; NXP is excluded from the Corstone scope harness.
Supply `--cc /path/to/armclang` for AC6 or ATfE Clang for the architecture check.
The AC6 example builder delegates to cbuild; `run_fvp.py` accepts `--cbuild`,
not `--cc`. See each script's `--help` for matrix/output options.

## CI reference

[CI](../.github/workflows/fvp.yml) uses an Arm64 runner, vcpkg tools, Arm licensing,
cached packs and uploaded logs/ELF/map/raw/decoded artifacts. CMSIS-Toolbox builds
the [AC6 6.24 solution](../examples/corstone300/profiler.csolution.yml) and runs
FVP 11.31.28. It runs on pull requests, main pushes and manual dispatch; there is
no scheduled trigger. Optional manual RTX/FreeRTOS checks need
`PROFILER_RTOS_CI=true` and a licensed self-hosted runner.

Put Toolbox on PATH, configure packs and set `AC6_TOOLCHAIN_6_24_0` to its bin directory:

```sh
python3 tests/run_fvp.py --fvp FVP_Corstone_SSE-300 --output build/fvp
python3 tests/check_fvp.py --report build/fvp/report
```

Add `--stack-unwind --output build/fvp-unwind` to the runner for at least 90%
two-caller coverage and folded-total checks. The [reference](fvp_reference.json)
requires 80–90 samples, zero rejected/unresolved, at least 95% `run_once` hits,
complete/validated capture, correct clocks, cumulative timing, restart evidence,
an extended PSP frame and active PMU events `0x0003`/`0x0024` with no validity flags.
Model-zero totals are allowed. The runner clears stale outputs, enforces timeouts,
returns nonzero on failure and writes `result.json`.

Reference timestamps use the 100 MHz counter shared with TIMER0 because this
FVP's DWT rate disagrees with elapsed timer time. They measure elapsed time,
not CPU cycles. Local tests used Linux x86-64; GitHub uses the Arm64 model.

## Selective AC6 retention

AC6 6.24 split-code link/preflight checks used a first link without blanket
retention, fresh `select_profiler_unwind.py --code-section .sram_text` rules and a
second link through `--via` with `--no_compressexidx`. E/F passed final preflight.
An unreferenced function stayed absent in both passes but survived blanket EXIDX
retention. This was not a new runtime run.

`test_select_unwind.py` covers sanitized MobileNet rows, populated `E`, duplicate/
custom sections, discarded/non-code rows, malformed input, literal `$` names and
failures. Object/archive associations remain unverified. Follow the
[AC6 integration recipe](../docs/UNWINDING.md#ac6-table-retention).

## GCC/LLVM retention

GCC 13.2.1/GNU ld 2.42 and ATfE 22.1/LLD 22.1 split-code link tests used unwind
and per-function/data sections, GC and `--no-merge-exidx-entries`. Probes included
live/dead inline and EXTAB recipes in direct objects and selected archive members;
an entirely unreferenced archive member remained absent.

| Selectors | GNU ld dead functions retained | LLD dead functions retained |
|---|---|---|
| No KEEP | 0/4 | 0/4 |
| EXIDX KEEP | 4/4 | 0/4 |
| EXTAB KEEP | 0/4 | 0/4 |
| Both KEEP | 4/4 | 0/4 |

All variants passed preflight for live probes and E/F. Ordinary selectors worked
in one pass; blanket EXIDX KEEP retained dead code with GNU ld. This does not
validate LTO, arbitrary libraries/assembly or physical hardware.

Build the [Corstone example](../examples/corstone300/README.md) with
`--call-tree --split-code`, then use the same compiler and an empty output directory:

```sh
python3 tests/check_unwind_retention.py \
  --cc arm-none-eabi-gcc --objects build/corstone300 --output build/retention-gcc
```

Repeat with ATfE and its own build directory. Each run retains four ELFs/maps,
logs, preflight reports and `results.json`. The [linker recipe](../docs/UNWINDING.md#gcc--llvm-linker-script-integration)
is the integration reference.
