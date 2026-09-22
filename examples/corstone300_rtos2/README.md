# Corstone-300 CMSIS-RTOS2 illustration

Add this example to a working secure, single-core M55 CMSIS-RTOS2 BSP project.
It supplies application code, not a kernel, startup or linker script.
2 workers run deterministic workloads and yield; a privileged controller captures
for about 250 ms, validates progress and checks timer stop while RTOS time continues.
Workers stay ready to avoid idle sleep stopping DWT.

## Integrate

1. Use this `main.c` with your kernel/startup. Omit the bare-metal example's main,
   startup and `examples/profile_workload.c`. Supply kernel control-block storage
   for 3 application threads plus kernel threads. 3 2 KiB stacks are supplied;
   check actual stack use.
2. Select the common, Corstone board and TIMER0 layers. Reserve IRQ 3 and bind
   `TFM_TIMER0_IRQ_Handler`. Keep SysTick, PendSV and SVC owned by the RTOS;
   leave sampling at the lowest IRQ priority.
3. Add this directory to the include path. Set `PROFILER_USER_CONFIG="profiler_config.h"`
   for all profiler sources, `PROFILER_SAMPLE_HZ=333`, buffer bytes=65536 and
   `PROFILER_TIMER_CLOCK_HZ` to the actual reference frequency. Avoid conflicting defines.
4. Cover every application/kernel stack in the RAM whitelist. Use initialized,
   accessible RAM for the buffer. Keep vectorization disabled in profiler code.
5. Adapt the reference-counter initialization to your board setup; do not reprogram
   a shared counter already in use. Keep clocks stable and avoid halts/low-power modes.

For FVP with BSP 1.5.0, use:

```text
-C core_clk.mul=32000000
-C mps3_board.sse300.refcounter.base_frequency=100000000
```

Load the RTOS project's ELF normally. FPGA needs its own image's clocks/memory map.

## Check and decode

Break at `profiler_rtos_capture_complete`. Success: `profiler_rtos_example_result=1`,
`header.complete=1`, `header.validation_passed=1`, and nonzero samples. Result 2
means initialization, workload or timer-continuity failure. Handler-mode rejections
can occur when TIMER0 preempts a kernel handler.

Dump with [dump_samples.gdb](../../tools/dump_samples.gdb), then run:

```sh
python3 host/analyze_samples.py --samples samples.bin --elf rtos_application.elf --output report
```

Samples aggregate all tasks, including kernel/controller thread-mode execution;
there are no task IDs. Sampling rate is independent of the RTOS tick rate.

Leave precise stack bounds disabled: CMSIS-RTOS2 has no portable ISR-safe stack
base/size query. Enabling it requires a kernel adapter or synchronized allocation
registry covering task lifetimes, kernel tasks and interrupted-context selection.

GCC/AC6 compile-checked against CMSIS 6.3.0 and BSP 1.5.0. No RTOS kernel has been
linked or run. Use the [bare-metal example](../corstone300/README.md) for tested FVP capture.
