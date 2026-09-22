# Corstone-300 / SSE-300 adapter

Select `corstone300.clayer.yml` and `corstone300_timer0.clayer.yml` with the common
layer. Include CMSIS-Core and BSP `Device/Include` headers; use a secure M55 build.

- Reserves secure TIMER0 (`0x58000000`), IRQ 3, `TFM_TIMER0_IRQ_Handler`.
  Uses system-timer auto-increment mode; application SysTick stays unchanged.
- Set `PROFILER_TIMER_CLOCK_HZ` to the actual reference-counter frequency.
  The application must start that shared counter and configure access. Writing
  CNTFRQ does not set its frequency; the profiler never resets it.
- Init rejects a busy TIMER0/IRQ, disabled reference counter, missing auto-increment
  or Non-secure IRQ. Stop disables TIMER0 without stopping the shared counter.
- Stack defaults use `SSE300MPS3.h`: `DTCM0_BASE_S` and
  `DTCM_BLK_SIZE * DTCM_BLK_NUM`. Override bounds for other memory layouts.

The [runnable example](../../examples/corstone300/README.md) uses a 32 MHz CPU and
100 MHz reference timer on FVP. Use the selected FPGA image's actual clocks and
memory map. FVP is tested; FPGA execution remains unverified.
