# Sampling interrupt stack and time budgets

The capture buffer and the sampling interrupt's stack are separate RAM budgets.
Backtraces use the interrupt stack for a staged sample, a virtual register set
and unwind workspace. The unwinder reads the interrupted application's stack;
it does not modify it or recursively allocate a frame for every recovered caller.

## Compiler stack measurements

Measured on 10 October 2026 with GCC 13.2.1, CMSIS 6.3.0, `-Os -mfloat-abi=soft
-ffunction-sections -fdata-sections -fstack-usage`, vectorization disabled and
FPU disabled. These are **local C-function frames**, excluding their callees,
the assembly wrapper and hardware exception entry. Values are maxima across the
architecture check's applicable security and timestamp modes.

| GCC: Cortex-M cores | PC handler | PC + 4 PMU handler | Backtrace handler, depth 16 | Backtrace + 4 PMU handler, depth 16 | Unwinder |
|---|---:|---:|---:|---:|---:|
| M0 / M0+ / M1 | 56 B | — | 200 B | — | 104 B |
| M23 | 56 B | — | 200 B | — | 104 B |
| M3 / M4 / M7 / M33 / M35P | 48 B | — | 200 B | — | 112 B |
| M52 / M55 / M85 | 48 B | 64 B | 200 B | 216 B | 112 B |

AC6 6.24 gives different frames under the same settings:

| AC6: Cortex-M cores | PC handler | PC + 4 PMU handler | Backtrace handler, depth 16 | Backtrace + 4 PMU handler, depth 16 | Unwinder |
|---|---:|---:|---:|---:|---:|
| M0 / M0+ / M1 | 56 B | — | 208 B | — | 136 B |
| M23 | 56 B | — | 208 B | — | 120 B |
| M3 / M4 / M7 / M33 / M35P | 48 B | — | 192 B | — | 104 B |
| M52 / M55 / M85 | 48 B | 72 B | 192 B | 216 B | 104 B |

PMU columns apply to the PMU-capable cores in the generated device headers.
Use `PROFILER_PMU_COUNT=0` on other cores. Configuring four slots on a core with
no PMU still reserves staging space; it does not provide hardware events.

For GCC Cortex-M55, reducing the caller limit gives a useful RAM tradeoff:

| Caller limit | Handler, PMU off | Handler, 4 PMU | Unwinder |
|---|---:|---:|---:|
| 4 | 152 B | 168 B | 112 B |
| 16 (default) | 200 B | 216 B | 112 B |
| 32 | 264 B | 280 B | 112 B |

The caller array costs four bytes per configured slot, plus compiler alignment
and spills. The unwinder workspace is reused as the trace grows. Lowering the
limit also bounds the number of frames attempted, but can truncate useful chains.

Reproduce the all-core report with [compile_cortex_m.py](../tests/compile_cortex_m.py):

```sh
python3 -B tests/compile_cortex_m.py \
  --cmsis /path/to/ARM/CMSIS/6.3.0 --optimization Os \
  --pmu-count 0 4 --unwind-depth 0 16 --stack-usage build/stack-gcc
```

Use a new output directory. `frames.csv` preserves each emitted function's
byte count and compiler qualifier; `provenance.json` records compiler identity,
flags, source/header hashes and generated device headers. Depth zero disables
backtraces. Use `--cpu m55 --pmu-count 0 1 2 3 4 --unwind-depth 4 16 32` for a
depth/PMU comparison. Repeat with `--cc /path/to/armclang` or embedded Clang;
change `--optimization` to match the application's build.

These checks compile a device stub, not the application's linked image or
application hooks. Rebuild the actual IRQ sources with `-fstack-usage` and the
production options, including security, optimization and LTO settings. Inspect
the final disassembly/linker call graph: a local `.su` frame is not a complete
call-chain bound, and a zero for a naked assembly handler omits its explicit pushes.
Dynamic stack qualifiers require additional analysis.

## Reserve the complete interrupt stack

For each possible call path, add the local frames that are simultaneously live.
Take the largest path; sequential hooks and the unwinder do not all overlap.
Then account for:

- The entry wrapper: 40 B with backtraces, zero explicit stack allocation without.
- Actual timer/timestamp, stack-bounds and auxiliary hooks, PMU collection,
  storage and out-of-line compiler/library helpers.
- Hardware exception frames on the stack that actually receives them, including
  applicable FP/MVE, alignment and security state.
- Higher-priority interrupts that can nest, and the application's chosen margin.

For example, the GCC M55 four-PMU/depth-16 objects contain this unwind path:

```text
Entry wrapper                              40 B
  statistical_sampling_tick               216 B
    profiler_unwind_capture                112 B
      code_region                           24 B
        contains                            12 B
                                         -----
This software call path                    404 B
```

The object disassembly confirms those calls and frame allocations. **404 B is
not a recommended stack allocation**: other application paths and exception
frames must be accounted for. With PSP-based tasks, the initial hardware frame
is on PSP while the handler and wrapper use MSP. With MSP-based thread execution,
the application and interrupt share the allocation. Validate both MSP and task
stack high-water marks under the actual interrupt priorities and workload;
high-water observations supplement, rather than replace, call-path analysis.

## Measure interrupt time on the target

No silicon ISR-time or worst-case execution-time bound has been measured for
the configurations above. Corstone FVP validates behavior, not cycle-accurate
silicon timing. Compiler frame sizes and bounded loop counts cannot establish
an execution-time bound.

Keep timing probes in application/test integration. Use an independently owned
counter, hardware trace or GPIO/scope measurement. Measure from actual vector
entry through exception return; a C-body probe omits entry/return costs and must
be labeled accordingly. Preserve registers and EXC_RETURN. Keep probes bounded
and integer-only; avoid logging or allocation, and do not reset the profiler's
timestamp or PMU counters. Record probe overhead and the interval covered.

Exercise PC-only, PMU and backtrace configurations separately, including:

- Maximum selected depth, long EXTAB recipes, large EXIDX tables and code-region
  lists, and representative deep/recursive application chains.
- Partial/rejected traces, PMU rollover/error paths, full-buffer closure,
  disabled recording and spurious interrupts.
- Real hooks, cache/memory placement and contention, interrupted FP/MVE code
  where applicable, and allowed higher-priority interrupt nesting.

Publish the ELF/hash, compiler/options, board/core, independently verified CPU
clock, memory/cache state, sample rate, depth/PMU settings, workload and test
coverage. Record invocation count, largest observed duration, MSP/task high-water
marks and allocated stack sizes. Distinguish profiler execution time from time
spent preempted by other interrupts and whole-workload profiling overhead.

Call the result **maximum observed ISR time** unless a separate worst-case
analysis establishes a bound. At sample rate `f`, average ISR duration `t`
gives an observed overhead estimate `f * t`; keep sufficient room before the
next timer period and for the application's deadlines. Repeat after changing
the target, compiler, hooks, depth, PMU settings or memory placement.
