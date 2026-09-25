# CMSIS-RTX dual-thread backtraces

Runnable secure Corstone-300 FVP test using ATfE Clang 22.1, CMSIS 6.3.0,
CMSIS-RTX 5.9.1 and SSE-300 BSP 1.5.0. No pack files are modified.

2 equal-priority workers run the [same workload](../corstone300/call_tree.c):

```text
worker  → run_once  → A  → B  → C  → D  → E  → F
worker1 → run_once1 → A1 → B1 → C1 → D1 → E1 → F1
```

The builder compiles the source twice, renaming the second copy's symbols.
Each copy has private validation state. Calls repeat 2/4/8/16/32 times at A–E,
with 100 NOPs after each call; F executes 100 NOPs. Inlining and sibling calls
are disabled. RTX preempts the workers with a 5-tick round-robin time slice.
An additional higher-priority controller captures for 2 seconds, checks both
workers completed valid iterations, then stops, suspends them and exports RAM
through semihosting. SysTick, PendSV and SVC remain owned by RTX.

## Run

From the repository root, with the packs and tools installed locally:

```sh
python3 tests/run_rtos_fvp.py \
  --cc /path/to/ATfE/bin/clang \
  --cmsis /path/to/ARM/CMSIS/6.3.0 \
  --bsp /path/to/ARM/V2M_MPS3_SSE_300_BSP/1.5.0 \
  --rtx /path/to/ARM/CMSIS-RTX/5.9.1 \
  --fvp /path/to/FVP_Corstone_SSE-300 \
  --flamegraph /path/to/FlameGraph/flamegraph.pl
```

The runner builds, runs FVP, decodes `samples.bin`, checks both call trees and
writes `result.json`. Outputs are in `build/rtos-call-tree`; open
`report/flamegraph.svg` in a browser. The runner selects `--stack-root osThreadEntry`
and adds a subtitle with included/excluded sample counts. Omit `--flamegraph` to produce folded stacks
without the external renderer. Existing output files are replaced on each run.

Acceptance requires 650–680 samples, valid timing and firmware validation,
no rejected frames, at least 100 PC hits in each workload, deep caller chains
from both workers, no chains mixing A–F with A1–F1, PSP frames and matching
folded totals matching the included samples. This is a test-specific reference, not a generic RTOS rule.

## Stack bounds and limitations

All 3 application stacks are permanent, disjoint 8 KiB allocations. The bounds
hook matches the interrupted PSP against this immutable registry; it makes no
RTOS calls in the sampling ISR. Unknown PSP allocations are rejected. TIMER0
runs at lowest priority, so kernel exception handlers finish before sampling.
This setup does not cover dynamic task stacks, task deletion or higher-priority
sampling during context switches.

Backtraces retain up to 16 callers. RTX kernel code has no unwind tables in this
example, so traces stop at `osThreadEntry` with `no_table`. Exact function-entry
samples retain PC hits but lose their caller chains unless the ELF confirms
a finish-only recipe and the first caller matches captured LR (as for F/F1). Fixed-rate aliasing affects this repetitive NOP workload; do not interpret
its hit percentages as a scheduler fairness benchmark. There are no task IDs;
the distinct function names distinguish the workers.

Observed: 665 samples, 0 rejected/unresolved, valid timing, 11 entry-filtered
samples and 654 plotted chains; excluded samples remain in PC/PMU reports. Both workers appear separately. This validates
1 RTX/FVP configuration, not arbitrary kernels or physical hardware.

Variable records use 38,372 bytes for these 665 samples, versus 61,180 bytes
with fixed 16-caller records (about 37% less). The RAM allocation remains 128 KiB.
