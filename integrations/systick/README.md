# Exclusive SysTick integration

Select `systick.clayer.yml` with the common layer, **instead of** a board timer
layer. A board adapter is not required when the application supplies the CMSIS
device header, `SystemCoreClock`, readable stack bounds, startup/vector ownership
and linker placement. It owns CPU-clocked SysTick and `SysTick_Handler` at
`PROFILER_SAMPLE_HZ`; valid periods are 2–16,777,216 CPU cycles.

Use only when SysTick is free. Init rejects an enabled timer; stop disables it;
reinitialization restarts it. HAL/RTOS tick chaining is not provided.
Use a dedicated peripheral timer when the application already owns SysTick.

Keep `PROFILER_DEFINE_IRQ_HANDLER` as the actual naked vector entry; a normal C
wrapper loses the original exception frame. Compile exactly 1 timer source.

## PSOC Edge hardware validation

This integration was exercised on an Infineon PSOC Edge E84 evaluation platform
using independent debugger-loaded Cortex-M55 r1p1 and Cortex-M33 r1p0 RAM images.
Each image owned SysTick, used a 64 KiB capture buffer, sampled at 1 kHz and
enabled 16-level EHABI backtraces. Both captures completed with zero rejected
frames and zero unresolved PCs; reconstructed chains covered the complete A–F
test workload. The M55 additionally collected four PMU events from eight hardware
event counters. The M33 has no architectural PMU and retained PC/backtrace
sampling as configured.

The test used application-local CMSIS device definitions, exact MSP bounds and
linker-provided `.ARM.exidx` ranges. It inherited clocks, power domains and
security attribution from the platform's existing boot firmware. It therefore
validates the generic SysTick profiler path, PMU fallback and backtrace capture,
not production PSOC startup or coexistence with an RTOS/HAL SysTick owner.
