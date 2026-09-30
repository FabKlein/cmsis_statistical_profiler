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

## NXP MIMXRT685-EVK hardware validation

The integration was also exercised on the MIMXRT685-EVK Cortex-M33 r0p3 using a
debugger-loaded RAM image. The application supplied startup, a 48 MHz
`SystemCoreClock`, exact 8 KiB MSP bounds and linker-retained AC6 EHABI tables.
SysTick sampled at 1 kHz into a 128 KiB buffer with 16-level backtraces and
`PROFILER_PMU_COUNT=0`, because Cortex-M33 has no architectural PMU.

The buffer filled after 2,316 ticks and contained 2,248 accepted samples with zero
rejected frames and zero unresolved PCs. Of those, 2,247 reconstructed trustworthy
chains rooted in the A-F test workload; one function-entry sample was excluded.
Reaching the selected application root before reporting `no_table` beyond it was
expected and retained a useful partial trace.

Initial testing rejected every sample as `unsupported_frame`. The debugger could
access only the Non-secure SCS alias, but the first profiler IRQ delivered
`EXC_RETURN=0xFFFFFFE9`, identifying a Secure basic frame on MSP. Compiling only
the profiler backend/ISR sources with AC6 `-mcmse` selected the matching frame
handling and produced the clean capture above. Startup and application sources
remained non-CMSE. This demonstrates that debugger-visible SCS access is not a
reliable proxy for the interrupted frame's security state; inspect the runtime
`EXC_RETURN` before choosing backend build flags.
