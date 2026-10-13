# CMSIS Statistical Profiler

An unreleased profiler for Cortex-M thread PCs, with optional PMU counters,
EHABI backtraces and a separate Ethos-U55/U65/U85 trace. Capture into RAM, then
analyze with the exact ELF/AXF. Supports Cortex-M0 through M85; APIs and formats
may change. Zephyr applications should use its native
[Perf profiling tool](https://docs.zephyrproject.org/latest/samples/subsys/profiling/perf/README.html#profiling-perf).

## How it works

```text
Timer IRQ → Cortex-M backend → capture/storage → stopped RAM dump → host + ELF
```

| Layer | Responsibility | Location |
|---|---|---|
| Timer integration | Own one timer/IRQ and preserve interrupted registers | `adapters/`, `integrations/systick/` |
| Cortex-M backend | Validate frame/bounds; recover PC, PMU and callers | `mcu/profiler_backend.c` |
| Capture/storage | Append bounded records; preserve them when full | `mcu/sampling_profiler.c` |

The application owns startup, clocks, linker placement and readable stack bounds.
AMP images each need physically separate state/buffers and a reserved timer;
decode each with its own ELF. Vendor dependencies stay in adapters.

## Get started

Follow the [integration checklist](docs/INTEGRATION.md): validate PC sampling,
then PMU, then backtraces. Put settings in the application using
[configuration](docs/CONFIGURATION.md). Use one timer source; a dedicated timer
keeps HAL/RTOS SysTick available. The generic SysTick path requires exclusive
ownership. M0/M0+/M1/M23 require a custom timestamp; TCM is optional.

| Target | Guide |
|---|---|
| Corstone-300 FVP / MPS3 FPGA | [Runnable example](examples/corstone300/README.md) |
| STM32N6 | [TIM2](adapters/stm32n6/README.md) |
| Alif E8, including AMP | [UTIMER](adapters/alif_e8/README.md) |
| NXP MIMXRT685 | [CTIMER4](adapters/nxp_rt685/README.md) |
| Himax WE2 / HX6538 | [TIMER4 and UART retrieval](adapters/himax_we2/README.md) |
| Free SysTick | [Generic integration](integrations/systick/README.md) |
| Ethos-U55/U65/U85 | [Separate NPU trace](adapters/ethosu/README.md) |
| CMSIS-RTOS2 | [RTX](examples/corstone300_rtos2/CALL_TREE.md), [FreeRTOS](examples/corstone300_freertos/README.md), [integration illustration](examples/corstone300_rtos2/README.md) |
| New board | [Adapter template](adapters/template/README.md) |

For a peripheral timer, select the common, board and timer layers:

```yaml
layers:
  - layer: ../cmsis_statistical_profiler/cmsis_statistical_profiler.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300_timer0.clayer.yml
```

For generic SysTick, select the common layer and
`integrations/systick/systick.clayer.yml`. No board adapter is needed when the
application supplies device header, clock, stack bounds, startup and linker setup.

## Capture and decode

Use the public [profiler API](mcu/sampling_profiler.h) serially in privileged
thread mode on the sampled core:

```c
if (!profiler_init())
    return;
profiler_enable();
run_your_workload();
profiler_stop(1, workload_output_is_correct());
```

`profiler_enable()`/`profiler_disable()` gate recording; stop finalizes even a
full buffer. Generate the [shared build header](docs/CONFIGURATION.md#shared-build-configuration)
before building, then run ELF preflight before capture:

```sh
python3 host/check_profiler_elf.py --elf firmware.elf
```

After stop returns, halt with the same ELF loaded in GDB and export the full allocation:

```gdb
source tools/export_profiler_buffer.gdb
export_profiler_buffer samples.bin
```

Package into a new directory and open `report/index.html`:

```sh
python3 host/create_profiler_report.py \
  --samples samples.bin --elf firmware.elf --output report \
  --board "<actual board or simulator>" --application "<application name>"
```

Keep raw inputs, exact ELF, decoded reports and `REPORT.md`. Require complete,
inactive capture, valid timing, correct workload output and no unexpected rejected
frames or unresolved PCs. PC percentages estimate sampled execution time;
PMU intervals are not per-function costs.

## Reference and development

| Topic | Main reference |
|---|---|
| Settings, build identity, ownership and diagnostics | [Configuration](docs/CONFIGURATION.md) |
| Backtrace hooks, linker recipes and limits | [Unwinding](docs/UNWINDING.md) |
| Interrupt stack and timing measurements | [ISR budget](docs/ISR_BUDGET.md) |
| Host dependencies, packaging, annotation, FlameGraph, HTML and Perfetto | [Host tools](docs/HOST_TOOLS.md) |
| Repeated captures, aggregation and synchronized folds | [Repeated captures](docs/REPEATED_CAPTURES.md) |
| PTE/Vela alignment and operator charts | [Ethos-U operator reports](docs/ETHOSU_OPERATOR_REPORTS.md) |
| Binary layout | [Format](FORMAT.md) |
| Checks and validation limits | [Validation](tests/VALIDATION.md) |

Run `python3 -B -m unittest discover -s tests -v`, `ruff format --check host/`
and `python3 tests/check_c_format.py` (clang-format 22.1.0).
See [CI](.github/workflows/fvp.yml), [Doxygen](Documentation/README.md),
[agent instructions](AGENTS.md) and [TODO](TODO.md).
