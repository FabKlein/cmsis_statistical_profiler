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

Include `sampling_profiler.h`:

1. Call profiler_init() and check for success.
2. Use profiler_enable() / profiler_disable() to control recording.
3. Call profiler_stop() before exporting the buffer.

profiler_diagnostics() explains initialization failures. profiler_full() reports
buffer exhaustion. profiler_sample_ticks() and profiler_elapsed_ms() measure
cumulative sampling time; subtract readings to measure an interval.

The remaining headers describe backend and adapter interfaces. Backtraces are
best-effort; sampling percentages are estimates, not exact function durations.
