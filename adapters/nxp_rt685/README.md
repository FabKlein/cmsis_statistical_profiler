# NXP MIMXRT685 CTIMER4 adapter

This adapter reserves CTIMER4, match channel 0 and `CTIMER4_IRQn` exclusively
for statistical sampling. It selects `MAIN_CLK`, uses no prescaler and programs
a periodic match/reset interrupt at `PROFILER_SAMPLE_HZ`. SysTick remains free
for an RTOS or application tick.

Add the common profiler layer and this timer layer:

```yaml
layers:
  - layer: path/to/cmsis_statistical_profiler/cmsis_statistical_profiler.clayer.yml
  - layer: path/to/cmsis_statistical_profiler/adapters/nxp_rt685/nxp_rt685_ctimer4.clayer.yml
```

The timer layer selects these NXP DFP components automatically:

```yaml
components:
  - component: NXP::Device:SDK Drivers:common
  - component: NXP::Device:SDK Drivers:clock
  - component: NXP::Device:SDK Drivers:reset
```

Manual, non-CMSIS builds must compile and link the equivalent NXP SDK common,
clock and reset driver sources and add the device, `periph` and driver include
directories.

Do not select the NXP CTIMER driver for CTIMER4 or install another
`CTIMER4_IRQHandler`. The adapter provides the actual naked vector entry so the
original exception frame reaches the profiler unchanged. Initialization rejects
an enabled CTIMER4 clock gate or IRQ as busy.

## Hardware validation

Validated on MIMXRT685-EVK Cortex-M33 at 48 MHz with a 1 kHz sample rate,
128 KiB buffer and 16-level EHABI backtraces. The capture filled with 2,253
accepted samples, zero rejected frames, zero unresolved PCs and no CFSR/HFSR
faults. Metadata reported `timer_hz=48000000` and `timer_period=48000`.
