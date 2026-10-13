# Integrate in 3 stages

Before integration identify the CPU/security mode, toolchain, reserved timer/IRQ,
actual clocks, initialized stack allocations and executable regions. Keep settings
in the application, pin the profiler revision and retain each exact unstripped ELF.
Never infer bounds or ownership from device capacity.

## Confirm the Armv8-M exception frame security state

Inspect the first real `EXC_RETURN` passed to `statistical_sampling_tick()`;
debugger SCS visibility and project labels do not establish frame security.
Secure frames require `-mcmse` on backend/ISR sources. Apply it globally only for
an intentionally CMSE application; it does not configure SAU/IDAU or routing.
If nearly every frame is `unsupported_frame`, check this before changing bounds.
The [NXP case](../integrations/systick/README.md#nxp-mimxrt685-evk-hardware-validation)
observed Secure MSP `0xFFFFFFE9` through a Non-secure debugger view. Repeat PC-only
validation after correcting flags; never weaken frame validation to hide failures.

## 1. PC sampling

1. Select the [common and timer layers](../README.md#get-started). Manual builds
   need four `mcu/*.c` sources, one timer and the [build restrictions](CONFIGURATION.md#build-and-ownership).
2. Set application configuration consistently across translation units:

   ```yaml
   define:
     - PROFILER_SAMPLE_HZ: 1000
     - PROFILER_SAMPLE_BUFFER_BYTES: 65536
     - PROFILER_PMU_COUNT: 0
     - PROFILER_STACK_UNWIND: 0
   ```

   Supply actual timer clocks and readable MSP/task-stack regions; preserve
   startup, linker placement and HAL/RTOS exceptions. Check total RAM capacity.
   See [settings and build identity](CONFIGURATION.md) for the user/generated headers.
3. Run `host/check_profiler_elf.py --elf firmware.elf` **before capture**.
   Initialize, enable, run a correctness-checked known workload and stop. On init
   failure inspect [diagnostics](CONFIGURATION.md#initialization-failures).
4. After stop returns, export the whole allocation using the
   [capture commands](../README.md#capture-and-decode), then
   [package a fresh report](HOST_TOOLS.md#decode-and-package-a-single-capture).
5. Require correct workload output, complete/inactive state, valid timing, known
   workload hits and zero unexpected rejections/unresolved PCs. Missing EHABI is
   expected here. Clock mismatch, lost IRQs, halts or sleep can break timing;
   invalid stack bounds need correction before adding features.

## 2. PC + PMU

Set `PROFILER_PMU_COUNT=2` (up to 4), optionally choose event IDs, and repeat into
a new report directory. Require active PMU, requested count and valid totals.
Unavailable/busy/unsupported PMU intentionally falls back to PC sampling; inspect
status before interpreting events. Model totals can be zero. PMU intervals include
other execution and are not per-function counts.

## 3. Call stacks + FlameGraph

Follow [unwinding setup](UNWINDING.md#integration-checklist-and-examples): enable
unwinding and precise bounds, add both application hooks, generate tables for
profiled sources/libraries and retain them with the toolchain's linker recipe.
Adapt the existing memory map; supply separate regions for split executable code.

Before capture, require coverage for a known nested workload function:

```sh
python3 host/check_profiler_elf.py \
  --elf firmware.elf --require-unwind --function functionF --output preflight.json
```

Preflight checks metadata, not every opcode or runtime stack readability.
After capture, require the expected nested chains and inspect depths, stop statuses,
root coverage and exclusions. Missing/CANTUNWIND recipes may require library
rebuilds or assembly/linker fixes. Choose an actual workload root and render with
[external FlameGraph](HOST_TOOLS.md#optional-backtraces-and-flamegraph).
Graph inclusion/root coverage does not independently verify asynchronous EHABI accuracy.

## Budget, evidence and overhead

Estimate storage before increasing depth/rate:

```sh
python3 host/estimate_profiler_buffer.py \
  --buffer-bytes 1048576 --sample-hz 2000 --pmu-count 4 \
  --max-depth 16 --expected-depth 8
```

Inspect actual record size, occupancy, exhaustion and finalization separately;
a complete buffer does not prove the requested duration ran. Keep exact inputs
and provenance in the [report package](HOST_TOOLS.md), including human Markdown
and offline index. Use actual board/application labels and verified metadata.

Compare correctness-checked workloads with profiling off, PC, PMU and unwinding
at several rates under identical clocks/cache/inputs. Measure workload overhead
separately from ISR duration and MSP/task high-water marks. The
[ISR budget guide](ISR_BUDGET.md) accounts for complete call paths, hardware frames,
nesting and maximum observed time. FVP is functional evidence; device performance
claims require hardware measurement.
