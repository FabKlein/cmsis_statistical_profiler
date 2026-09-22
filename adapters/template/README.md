# Add a board adapter

Copy and rename the template layers:

```sh
cp -R adapters/template adapters/my_board
mv adapters/my_board/template.clayer.yml adapters/my_board/my_board.clayer.yml
mv adapters/my_board/template_timer.clayer.yml adapters/my_board/my_board_timer.clayer.yml
```

## Board settings

Set `PROFILER_DEVICE_HEADER` to the quoted CMSIS device header. Supply SDK include
paths and device defines. Keep the shared `mcu/profiler_board_config.h`.

Set SDK-derived `PROFILER_DEFAULT_STACK_BASE` and `PROFILER_DEFAULT_STACK_BYTES`,
or supply application bounds through `profiler_app_config.h.example`.
For several ranges, use `PROFILER_STACK_REGIONS`. Bounds must describe initialized,
CPU-readable stack RAM, including all task stacks. Never guess sizes.

`PROFILER_DEFAULT_DTCM_BASE` explicitly opts into MEMSYSCTL size detection on
supported cores; TCM is otherwise optional. Application bounds override defaults.
Define `PROFILER_USER_CONFIG` to the quoted application header and add its include
path. Set rate and buffer size consistently across all profiler sources.

## Timer hooks

Complete `profiler_timer.c` by replacing `YOUR_` and `TODO(timer)` placeholders,
then remove its deliberate `#error`.

| Item | Requirement |
|---|---|
| IRQ/vector | Exact startup handler, routed to the sampled core/security domain |
| Init | Reject busy resources; configure a stopped periodic timer |
| Clock/period | Actual count frequency after prescaling; use `profiler_timer_period()` |
| Start | Clear stale events, enable IRQ and counting |
| Stop | Mask IRQ, stop and clear; safe before init and on repeated captures |
| Ack | Clear a real sample event and return 1; return 0 for spurious IRQs |

Store actual `timer_hz` and `timer_period` in `ProfilerClock`; preserve
`timestamp_hz`. Convert period to hardware reload values only at register writes.
Init/start/stop run with local interrupts masked. Reserve the timer for the firmware
lifetime, including across cores; avoid changing shared clocks or resetting blocks.

Use `PROFILER_DEFINE_IRQ_HANDLER` as the actual vector entry, without a C/HAL
wrapper. Ack runs even while gated off/full. Keep it bounded and integer-only;
never advance HAL time. See [hook contracts](../../mcu/sampling_profiler_cortex_m.h)
and the [STM32](../stm32n6/profiler_tim2.c),
[Corstone](../corstone300/profiler_timer0.c) or [Alif](../alif_e8/profiler_utimer.c) adapters.

## Optional hooks

- Without accessible CYCCNT, implement [timestamp hooks](profiler_timestamp.c.example)
  and set `PROFILER_TIMESTAMP_CUSTOM=1`. Use a coherent free-running 32-bit upcounter
  at a fixed frequency; sampling must not reset it. Narrow counters need safe extension.
- For exact stack bounds, implement [the bounds hook](profiler_stack_bounds.c.example)
  and set `PROFILER_PRECISE_STACK_BOUNDS=1`. Failed lookups reject samples; bounds
  only narrow the RAM whitelist. RTOS ports need an ISR-safe interrupted-task lookup.

## Build and check

Select the common layer, your board layer and 1 timer layer. For non-CMSIS builds,
see [configuration](../../docs/CONFIGURATION.md). Exclusive
[SysTick](../../integrations/systick/README.md) is an option only when unused by the application.

Use [profile_workload](../../examples/profile_workload.c) and the root
[capture/decode steps](../../README.md). Check busy/invalid-rate rejection, actual
interrupt cadence, resolved PCs, frame rejection counts, stop/restart and unchanged
application ticks. Exercise MSP/PSP and FP frames when used. Inspect ISR disassembly
for FP/vector instructions. Native tests do not replace SDK and hardware/model checks.
