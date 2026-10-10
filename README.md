# CMSIS Statistical Profiler

Initial prototype. APIs and capture format may change.

Sample Cortex-M thread PCs into RAM, then decode them with the matching ELF/AXF.
Optional PMU counters report hardware events. The core supports M0 through M85;
board adapters or the generic SysTick integration supply the sampling timer.

Zephyr users should use its native [Perf profiling tool](https://docs.zephyrproject.org/latest/samples/subsys/profiling/perf/README.html#profiling-perf).
This pack is intended for applications outside Zephyr; see the linked sample for
Zephyr's supported targets and requirements.

## How it works

```text
Cortex-M application
   │  periodic interrupt at PROFILER_SAMPLE_HZ
   ▼
1. Timer integration
   ├─ Board timer adapter                adapters/<board>/
   └─ Exclusive generic SysTick          integrations/systick/
      └─ Own timer + IRQ; preserve interrupted stack and EXC_RETURN
           │
           ▼
2. Cortex-M backend                      mcu/profiler_backend.c
   ├─ Acknowledge timer, read timestamp, check capture gate
   ├─ Validate exception frame and stack bounds
   └─ Extract PC/LR + optional PMU snapshots and bounded backtrace
           │  validated sample (or rejection reason)
           ▼
3. Capture core                          mcu/sampling_profiler.c
   └─ Append to RAM buffer sized by PROFILER_SAMPLE_BUFFER_BYTES
      (includes header and records; currently stops recording when full)
           │  stop capture, then dump via debugger / FVP semihosting
           ▼
Host decoder + matching ELF              host/analyze_profiler_buffer.py
   └─ Function hit percentages, sample timeline, PMU totals, diagnostics
```

For asymmetric multiprocessing (AMP), where each core runs its own firmware,
each core has its own instance of the 3 layers shown above: **Timer integration**,
**Cortex-M backend** and **Capture core**, with a separate buffer and host report.

## Get started

Follow the [3-stage integration guide](docs/INTEGRATION.md): PC sampling, PMU, then backtraces.
Every application must explicitly supply readable bounds for its actual stack RAM;
board adapters do not select or probe those bounds.

| Target | Guide |
|---|---|
| Corstone-300 FVP / MPS3 FPGA | [Runnable example](examples/corstone300/README.md) |
| STM32N6 | [TIM2 adapter](adapters/stm32n6/README.md) |
| Alif E8 | [UTIMER adapter](adapters/alif_e8/README.md) |
| Ethos-U55/U65/U85 | [Optional separate NPU trace](adapters/ethosu/README.md) |
| NXP MIMXRT685 | [CTIMER4 adapter](adapters/nxp_rt685/README.md) |
| Himax WE2 / HX6538 | [TIMER4 adapter and UART retrieval](adapters/himax_we2/README.md) |
| Free SysTick | [Generic exclusive integration](integrations/systick/README.md) |
| CMSIS-RTOS2 | [RTX](examples/corstone300_rtos2/CALL_TREE.md) / [FreeRTOS](examples/corstone300_freertos/README.md) dual-thread Toolbox/FVP tests, [integration illustration](examples/corstone300_rtos2/README.md) |
| New board | [Adapter template](adapters/template/README.md) |

Select the common layer, 1 board and 1 board timer:

```yaml
layers:
  - layer: ../cmsis_statistical_profiler/cmsis_statistical_profiler.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300_timer0.clayer.yml
```

Alternatively, select the common layer and the generic SysTick integration. A
board adapter is not required when the application directly supplies
`PROFILER_DEVICE_HEADER`, `SystemCoreClock`, readable stack bounds, startup/vector
ownership and linker placement:

```yaml
layers:
  - layer: ../cmsis_statistical_profiler/cmsis_statistical_profiler.clayer.yml
  - layer: ../cmsis_statistical_profiler/integrations/systick/systick.clayer.yml
```

The application supplies startup, clocks, linker placement and readable stack RAM.
Reserve the selected timer. The generic path requires free SysTick and owns its
handler; a board timer path leaves HAL/RTOS SysTick, PendSV and SVC ownership
unchanged. Supplied board adapters use secure M55 mappings; other targets using a
peripheral timer need an appropriate adapter.
M0/M0+/M1/M23 need a [custom timestamp](adapters/template/profiler_timestamp.c.example).
TCM is optional.

Set sampling rate, buffer size and readable stack bounds in the application;
see [configuration](docs/CONFIGURATION.md). Use one timer source. Recording stops
when the buffer is full; existing records are preserved. Start with PC sampling
and enable PMU/backtraces only after that capture passes validation.

## Capture and decode

Run lifecycle calls serially in privileged thread mode on the sampled core:

```c
if (!profiler_init())
    return;
profiler_enable();
run_your_workload();
profiler_stop(1, workload_output_is_correct());
```

The public API is in [sampling_profiler.h](mcu/sampling_profiler.h).
`profiler_enable()`/`profiler_disable()` gate recording; `profiler_stop()` finalizes
the capture and repeated stops preserve its first result. `profiler_init()` resets
metadata for the next capture. `profiler_sample_ticks()` and
`profiler_elapsed_ms()` provide cumulative timer readings; subtract two readings
for an interval.

Before capture, check the exact ELF with Python 3.10+:

```sh
python3 host/check_profiler_elf.py --elf firmware.elf
```

After stop returns, halt the target with that ELF loaded in GDB. From the
repository root, export the whole allocation:

```gdb
source tools/export_profiler_buffer.gdb
export_profiler_buffer samples.bin
```

Decode and package the first report into a new directory:

```sh
python3 host/create_profiler_report.py \
  --samples samples.bin --elf firmware.elf --output report \
  --board "<actual board or simulator>" --application "<application name>"
```

Open `report/index.html`; keep `REPORT.md`, raw inputs and the exact ELF together.
Require complete/inactive capture, valid timing, correct workload output and no
unexpected rejected frames or unresolved PCs. Keep clocks stable and avoid
sleep/debugger pauses during capture. PC percentages estimate sampled execution
time; PMU deltas are not per-function costs.

## Optional PMU

Configure 0–4 events in the application; see [PMU configuration](docs/CONFIGURATION.md).
Unavailable PMU falls back to PC sampling with a diagnostic. Counter slots retain
separate identities even when selecting the same event twice.

## Optional backtraces and FlameGraph

Backtraces require EHABI tables, precise stack bounds and both application hooks;
see [unwinding setup](docs/UNWINDING.md) and the [ISR budget](docs/ISR_BUDGET.md).
The decoder retains partial-trace diagnostics and exports folded stacks.
Render them with Brendan Gregg's external `flamegraph.pl` as described in the
[host tools guide](docs/HOST_TOOLS.md#optional-backtraces-and-flamegraph).

## Further guides

| Task | Guide |
|---|---|
| Host requirements, packaging, instruction annotation, HTML and Perfetto | [Host tools](docs/HOST_TOOLS.md) |
| Repeated or synchronized MCU/Ethos-U captures, aggregation and report index | [Repeated captures](docs/REPEATED_CAPTURES.md) |
| Exact PTE/Vela validation and operator attribution | [Ethos-U operator reports](docs/ETHOSU_OPERATOR_REPORTS.md) |
| Compile, FVP and hardware evidence and limitations | [Validation](tests/VALIDATION.md) |
| Binary layout | [Capture format](FORMAT.md) |

For AMP, reserve a distinct buffer and timer per image and decode with each core's
ELF. The [Alif guide](adapters/alif_e8/README.md) covers dual-core integration.
Ethos-U uses a separate trace buffer; see its [adapter guide](adapters/ethosu/README.md).

## Development

Run `python3 -B -m unittest discover -s tests -v` and
`ruff format --check host/`. See [validation commands](tests/VALIDATION.md),
[CI](.github/workflows/fvp.yml), [Doxygen](Documentation/README.md),
[agent guide](AGENTS.md) and [TODO](TODO.md).
