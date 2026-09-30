# CMSIS-FreeRTOS dual-thread backtraces

[Example acronym definitions](../corstone300/README.md#acronyms-used-in-these-examples).

Corstone-300 FVP test using ATfE Clang 22.1, CMSIS 6.3.0,
[CMSIS-FreeRTOS](https://github.com/ARM-software/CMSIS-FreeRTOS) 11.2.0
and SSE-300 BSP 1.5.0. Pack files remain unchanged.

Reuses the [RTX test application and workload](../corstone300_rtos2/CALL_TREE.md)
through the pack's CMSIS-RTOS2 wrapper:

```text
worker_entry -> worker  -> run_once  -> A  -> B  -> C  -> D  -> E  -> F
             -> worker1 -> run_once1 -> A1 -> B1 -> C1 -> D1 -> E1 -> F1
```

2 equal-priority workers have separate static 8 KiB PSP stacks and task-control
blocks. A-E call the next function 2/4/8/16/32 times, with 100 NOPs after each
call; F executes 100 NOPs. Inlining and tail calls are disabled. A controller
captures for 2 seconds at 333 Hz, validates both workers, stops capture and
exports the 128 KiB buffer through semihosting.

## Run

Use the [Toolbox environment setup](../corstone300_rtos2/CALL_TREE.md#run)
(CMSIS-Toolbox 2.13.0, CMake, Ninja and ATfE 22.1). The shared
[solution](../corstone300_rtos2/call_tree.csolution.yml) selects the FreeRTOS
kernel, wrapper and heap through pack components. Install missing packs and build:

```sh
cbuild examples/corstone300_rtos2/call_tree.csolution.yml \
  --context call_tree.FreeRTOS+Corstone300 --packs --update-rte \
  --output build/rtos-toolbox
```

The ELF is `build/rtos-toolbox/out/call_tree/Corstone300/FreeRTOS/profiler.elf`.
To build, run, decode and check both workers:

```sh
python3 tests/run_rtos_fvp.py --kernel freertos \
  --fvp /path/to/FVP_Corstone_SSE-300 \
  --flamegraph /path/to/FlameGraph/flamegraph.pl
```

Outputs: `build/freertos-call-tree/{profiler.elf,samples.bin,result.json}` and
`report/{samples.csv,stacks.folded,flamegraph.svg}`. Omit `--flamegraph` if the
external renderer is unavailable. Existing outputs are replaced.

The runner checks timing, 650-680 samples, successful worker validation, no
rejected frames, PSP sampling, both deep caller chains, no mixed-worker chains
and plotted totals. Each worker needs at least 100 plotted samples and an ordered
chain reaching E/F; all plotted chains must follow the known caller sequence. It selects `--stack-root worker_entry`, an application
wrapper above both workers. Task return addresses supplied by the kernel are
not reliable caller roots.

## Configuration and limits

[FreeRTOSConfig.h](FreeRTOSConfig.h) selects the pack's Cortex-M55 NTZ port in
Secure-only mode, with privileged tasks and no MPU. FreeRTOS and its CMSIS
wrapper own SysTick, PendSV and SVC; the profiler owns TIMER0. The 1 kHz kernel
tick time-slices equal-priority workers. The sampling ISR uses a static stack
registry and makes no RTOS calls. Kernel sources are built without unwind tables.

Observed on FVP: 664 samples, valid timing, 0 rejected frames, 660 plotted
chains and 4 excluded unreliable chains. Both workers reach F/F1. Backtraces
remain best-effort; excluded chains retain their PC statistics. Fixed-rate
sampling of this repetitive workload is not a scheduler fairness measurement.

This test covers static tasks on 1 core. Dynamic task deletion, MPU isolation,
Non-secure execution, TrustZone task transitions and physical hardware are not
validated. The pack is a separate kernel integration from the FreeRTOS library
[CMSIS-Packs index](https://github.com/FreeRTOS/CMSIS-Packs).
