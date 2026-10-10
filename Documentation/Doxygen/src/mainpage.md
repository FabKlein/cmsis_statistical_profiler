# CMSIS Statistical Profiler {#mainpage}

**Prototype: interfaces and documentation are under construction.**

Sample running Cortex-M code into a RAM buffer, then decode it on the host using
the matching executable. Optional performance counters and backtraces add context.

## Structure

```text
Board timer adapter -> Cortex-M backend -> Capture/storage
                                               |
                                         Buffer export
                                               |
                                      Host report / flamegraph
```

The application supplies clocks, memory placement and stack bounds. Each core has
its own profiler state and buffer. Keep the operating system's interrupts intact.

## Application API

Include `sampling_profiler.h`; it requires no target configuration:

1. Call profiler_init() and check for success.
2. Use profiler_enable() / profiler_disable() to control recording.
3. Call profiler_stop() before exporting the buffer.

profiler_diagnostics() explains initialization failures. profiler_full() reports
buffer exhaustion. profiler_sample_ticks() and profiler_elapsed_ms() measure
cumulative sampling time; subtract readings to measure an interval.

The first profiler_stop() finalizes the capture; repeated stops preserve it until
profiler_init() starts a new one. Include `sampling_profiler_format.h` for capture
layout and buffer export, or `sampling_profiler_config.h` to read application
settings. `sampling_profiler_port.h` holds internal sample and backend interfaces.
Backtraces are best-effort; sampling percentages are estimates, not exact function
durations.
