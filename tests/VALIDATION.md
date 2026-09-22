# Validation

Checked on 22 September 2026:

| Check | Coverage / result |
|---|---|
| 22 native/Python test groups | Lifecycle, rates, cache, timer stop/restart, PRIMASK, SysTick preservation, clock wraps, frame/bounds rejection, DTCM configuration and malformed/empty captures |
| PMU tests | All counts 0–4, capacity checks, availability, authentication, ownership, chaining, read retries, overflow, restart and shared cycle-counter preservation; compact records for every active count and when inactive |
| GCC 13.2.1 / AC6 6.24 | M0/M0+/M1/M3/M4/M7/M23/M33/M35P/M52/M55/M85; applicable security and custom timestamp settings |
| Alif AMP adapter | Native tests cover all 12 channel selections, shared-clock preservation, other-channel isolation, busy/security rejection and restart; GCC/AC6 check HP/HE defaults and overrides |
| Real SDK adapters | STM32N6, Corstone-300, Alif HP/HE; dedicated vectors, no SysTick/HAL ownership; GCC relocatable links |
| Corstone FVP | 125/333/2500 Hz, MSP and PSP/FP, precise bounds, restart and application SysTick continuity |
| 4-event FVP | AC6: 84 samples, 100% workload hits, valid timing, all 4 event reports decoded; functional model totals are 0 |
| PMU on/off FVP | 2 333 Hz captures each; final capture: 84 samples, validation passed, no rejected/unresolved PCs |
| PMU software-increment diagnostic | 2,020,000 events on each chained pair, crossing low-half rollovers |
| CMSIS-RTOS2 illustration | GCC/AC6 compilation and exception-symbol checks only; no kernel linked/run |
| CMSIS layers | Schema validation and generated AC6/GCC builds: application flags unchanged; core and all timer groups protected |
| Timing checks | Frozen counters, rate mismatch, mid-capture drift and stop epochs; valid wraps, coarse counters and degraded reports |
| CI regression | Workflow passes actionlint; AC6/FVP uses reference-counter timestamps and requires valid cumulative timing |

GCC 13 uses `-march=armv8.1-m.main` for M52 because it lacks that CPU name.
FVP D-cache refill/backend-stall counts are 0 for the ITCM/DTCM workload;
this says nothing about hardware stalls. Inspect ISR disassembly after compiler/LTO changes.

## SDKs used

| SDK | Version / Git revision |
|---|---|
| ARM CMSIS | 6.0.0 for board adapters; 6.3.0 for the full architecture matrix |
| ARM V2M_MPS3_SSE_300_BSP | 1.5.0 |
| ST cmsis-device-n6 | `81fe2fe8d576ec4c55be308ac4504bd580e498e6` |
| ST stm32n6xx-hal-driver | `d88071ed0adc1991a5daed6f20ab311f80bb33b7` |
| Alif alif_ensemble-cmsis-dfp | `652dd6bf6856891695dfef1f0e7f74829ec9f451` |

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
  --sample-hz 125 333 2500 --pmu
```

Run `python3 tests/check_layer_scope.py --compiler AC6 GCC` to check compiler-option
scope (requires csolution, PyYAML and the packs above). CI checks AC6.

Supply `--cc /path/to/armclang` for AC6. SDKs are not downloaded by the scripts;
omit adapter SDK options you do not have. Temporary objects are built outside
the source tree. FVP build/run instructions are in the
[Corstone example](../examples/corstone300/README.md).

Physical STM32N6, Alif and MPS3 FPGA execution, M0/non-secure runtime execution,
and RTOS scheduling/stack integration remain unverified. FVP validates capture
flow and counter integration, not cycle-accurate silicon performance.

## CI reference

[The workflow](../.github/workflows/fvp.yml) follows the
[CMSIS-NN FVP setup](https://github.com/ARM-software/CMSIS-NN/blob/main/.github/workflows/float-fvp.yml):
Arm64 runner, vcpkg tools, Arm license activation, cached packs and uploaded artifacts.
It builds with AC6 6.24, runs FVP 11.31.28 and decodes the semihosted buffer.

```sh
python3 tests/run_fvp.py --cc /path/to/armclang \
  --cmsis /path/to/ARM/CMSIS/6.3.0 \
  --bsp /path/to/ARM/V2M_MPS3_SSE_300_BSP/1.5.0 \
  --fvp FVP_Corstone_SSE-300 --output build/fvp
```

The committed [reference](fvp_reference.json) requires 80–90 samples, no rejected
or unresolved PCs, at least 95% hits in `run_once`, a completed/validated capture,
correct clocks, valid cumulative timing, restart evidence and an extended PSP frame. PMU must be active
with events `0x0003`/`0x0024`, no validity flags and consistent totals/deltas.
Observed 2-event reference-timestamp output: 84 samples, 97.62% workload hits, both event totals 0. PMU totals
are not fixed thresholds; functional-model zeros are allowed.

The runner clears stale captures, enforces timeouts and writes `result.json`.
Failures return nonzero. CI uploads logs, ELF/map, raw buffer and decoded reports.
To recheck reports: `python3 tests/check_fvp.py --report build/fvp/report`.
Local testing uses Linux x86-64; GitHub runs the Arm64 model.

The runner selects `--reference-timestamp`, using the 100 MHz reference counter
shared with TIMER0. The functional FVP's DWT rate disagrees with elapsed timer
time; reference timestamps avoid that mismatch. CI still requires
`timing_valid=true`; timestamps represent elapsed time, not CPU cycles.
