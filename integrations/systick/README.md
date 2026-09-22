# Exclusive SysTick integration

Select `systick.clayer.yml` with the common and board layers, **instead of** a
board timer layer. It owns CPU-clocked SysTick and `SysTick_Handler` at
`PROFILER_SAMPLE_HZ`; valid periods are 2–16,777,216 CPU cycles.

Use only when SysTick is free. Init rejects an enabled timer; stop disables it;
reinitialization restarts it. HAL/RTOS tick chaining is not provided.
Use a dedicated peripheral timer when the application already owns SysTick.

Keep `PROFILER_DEFINE_IRQ_HANDLER` as the actual naked vector entry; a normal C
wrapper loses the original exception frame. Compile exactly 1 timer source.
