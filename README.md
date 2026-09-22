# CMSIS Statistical Profiler

Initial prototype — APIs and capture format may change.

Sample Cortex-M thread PCs into RAM, then decode them with the matching ELF/AXF.
Optional PMU counters report hardware events. The core supports M0 through M85;
board adapters supply the timer and device settings.

## How it works

```text
Cortex-M application
   │  periodic interrupt at PROFILER_SAMPLE_HZ
   ▼
1. Board adapter                         adapters/<board>/
   └─ Own timer + IRQ; preserve interrupted stack and EXC_RETURN
           │
           ▼
2. Cortex-M backend                      mcu/sampling_profiler_cortex_m.c
   ├─ Acknowledge timer, read timestamp, check capture gate
   ├─ Validate exception frame and stack bounds
   └─ Extract PC/LR + optional PMU snapshots
           │  validated sample (or rejection reason)
           ▼
3. Capture core                          mcu/sampling_profiler.c
   └─ Append to RAM buffer sized by PROFILER_SAMPLE_BUFFER_BYTES
      (includes header and records; never overwrite)
           │  stop capture, then dump via debugger / FVP semihosting
           ▼
Host decoder + matching ELF              host/analyze_samples.py
   └─ Function hit percentages, sample timeline, PMU totals, diagnostics
```

For AMP, each core has its own 3 layers, buffer and report.

## Get started

| Target | Guide |
|---|---|
| Corstone-300 FVP / MPS3 FPGA | [Runnable example](examples/corstone300/README.md) |
| STM32N6 | [TIM2 adapter](adapters/stm32n6/README.md) |
| Alif E8 | [UTIMER adapter](adapters/alif_e8/README.md) |
| CMSIS-RTOS2 | [Corstone illustration](examples/corstone300_rtos2/README.md) |
| New board | [Adapter template](adapters/template/README.md) |

Select the common layer, 1 board and 1 timer:

```yaml
layers:
  - layer: ../cmsis_statistical_profiler/cmsis_statistical_profiler.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300.clayer.yml
  - layer: ../cmsis_statistical_profiler/adapters/corstone300/corstone300_timer0.clayer.yml
```

The application supplies startup, clocks, linker placement and readable stack RAM.
Reserve the timer; leave HAL/RTOS SysTick, PendSV and SVC ownership unchanged.
Supplied adapters use secure M55 mappings; other CPUs need an appropriate adapter.
M0/M0+/M1/M23 need a [custom timestamp](adapters/template/profiler_timestamp.c.example).
TCM is optional.

Set `PROFILER_SAMPLE_HZ` and `PROFILER_SAMPLE_BUFFER_BYTES` in the
[common layer](cmsis_statistical_profiler.clayer.yml). A 64 KiB buffer holds 2,723
samples without PMU, 2,042 with 2 events or 1,634 with 4 events. Records never overwrite.
See [configuration](docs/CONFIGURATION.md) for clocks, bounds and build options.

## Capture and decode

Call from privileged thread mode on the sampled core:

```c
if (!sampling_profiler_init())
    return;
sampling_profiler_enable();
run_your_workload();
sampling_profiler_stop(1, workload_output_is_correct());
```

The workload functions are placeholders. Always stop, even when full. Keep clocks
stable; avoid sleep, debugger halts and long interrupt masking during capture.
After `sampling_profiler_stop()` returns, halt the target. With the matching ELF
loaded in GDB, use [tools/export_profiler_buffer.gdb](tools/export_profiler_buffer.gdb) from the
repository root:

```gdb
source tools/export_profiler_buffer.gdb
export_profiler_buffer samples.bin
```

The helper checks that capture is complete and inactive, prints the header, and
dumps the whole buffer, including unused space. For AMP, stop all captures before
halting, then run it in each core's debugger context with its own ELF and filename.

Decode with Python 3.8+ and the exact unstripped executable:

```sh
python3 host/analyze_samples.py --samples samples.bin --elf firmware.elf --output report
```

Outputs: `functions.csv`, `samples.csv`, `summary.json`, and `events.csv` for PMU
requests. Function percentages estimate sampled execution time, not call counts.
Samples aggregate tasks; call-stack tracing and task IDs are not implemented.
If timestamp clocks disagree, the host warns and marks `timing_valid=false`;
derived time fields are blank, while raw timestamps and PC/PMU reports remain available.

For AMP, use 1 profiler instance, buffer, timer channel and ELF per core.
See [Alif dual-core setup and retrieval](adapters/alif_e8/README.md). Reports stay
separate; independent timestamps are not automatically synchronized.

## Optional PMU

Set `PROFILER_PMU_COUNT` to 0–4 in the common layer (default 0). Each 32-bit
event uses 2 hardware counters. Default events, in order: D-cache refill (`0x0003`),
backend stall (`0x0024`), instructions retired (`0x0008`) and CPU cycles (`0x0011`).
Override `PROFILER_PMU_EVENT0` through `PROFILER_PMU_EVENT3` as needed. Records
use 24, 28, 32, 36 or 40 bytes for 0–4 active events.
Unavailable PMU collection falls back to PC sampling with a diagnostic status.

PMU counts cover init through stop, including interrupts and gated-off execution.
The host reports totals and interval deltas, without per-function attribution.
Overflow or incoherent reads invalidate derived counts.

## Development

Run `python3 -B -m unittest discover -s tests -v`.
[GitHub Actions](.github/workflows/fvp.yml) builds with AC6 and checks an FVP PMU
capture against the [acceptance reference](tests/fvp_reference.json).
See [validation](tests/VALIDATION.md), [capture format](FORMAT.md),
[agent guide](AGENTS.md) and [TODO](TODO.md).
