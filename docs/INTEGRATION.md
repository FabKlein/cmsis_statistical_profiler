# Integrate in 3 stages

Keep configuration in your application. Identify CPU/security mode, toolchain,
reserved timer/IRQ, actual clocks, readable stack allocations and executable
regions first. Do not guess these values. Pin the profiler revision and retain
the exact unstripped ELF for each capture.

## 1. PC sampling

1. Add the common, board and timer layers shown in the [README](../README.md#get-started).
   Manual builds need the 4 `mcu/*.c` sources, 1 timer adapter and their include paths.
   Keep the [ISR compiler restrictions](CONFIGURATION.md#build-and-ownership).
2. Set application cproject definitions, or use an application config header:

   ```yaml
   define:
     - PROFILER_SAMPLE_HZ: 1000
     - PROFILER_SAMPLE_BUFFER_BYTES: 65536
     - PROFILER_PMU_COUNT: 0
     - PROFILER_STACK_UNWIND: 0
   ```

   Supply timer clock and stack RAM definitions from the board guide. Header users
   define `PROFILER_USER_CONFIG="profiler_app_config.h"`; use `#ifndef` defaults
   inside it so command-line settings can override them without `#undef`.
3. Preserve application startup/linker placement and HAL/RTOS exceptions. The
   buffer defaults to BSS. Check that data plus MSP/task stacks fit physical RAM.
4. Call `sampling_profiler_init()`, `sampling_profiler_enable()`, run a known
   workload, then `sampling_profiler_stop(iterations, validation_passed)`.
   On init failure inspect `*sampling_profiler_diagnostics()`; see
   [failure meanings](CONFIGURATION.md#initialization-failures).
5. After stop returns, halt and export from GDB with the exact ELF loaded:

   ```gdb
   source tools/export_profiler_buffer.gdb
   export_profiler_buffer samples.bin
   ```

   From the profiler repository, create a fresh local report directory:

   ```sh
   python3 host/check_profiler_elf.py --elf firmware.elf
   python3 host/create_profiler_report.py --samples samples.bin --elf firmware.elf --output report-pc
   ```

6. Require correct workload output, complete/inactive capture, valid timing,
   no unexpected rejections/unresolved PCs and hits in the known workload.
   Missing EHABI is expected at this stage. Bad timing usually means a clock
   mismatch, lost IRQs or debugger/sleep interference; stack rejections need
   corrected RAM bounds. Do not enable more features to hide a failed PC test.

## 2. PC + PMU

Keep the same sources, linker and calls. Set `PROFILER_PMU_COUNT: 2` (up to 4),
optionally overriding event IDs. Repeat capture and report into `report-pmu`.
Require `header.pmu.status=active`, the requested count and valid event totals.
Fallback to PC sampling is intentional on unavailable/busy/unsupported PMUs;
inspect that status before interpreting counts. Model events may remain 0.
PMU intervals include other execution and are not per-function counts.

## 3. Call stacks + FlameGraph

Enable `PROFILER_STACK_UNWIND: 1`, `PROFILER_PRECISE_STACK_BOUNDS: 1` and
`PROFILER_UNWIND_MAX_DEPTH: 16`. Add the application's table and precise stack
hooks. Generate tables for profiled application **and library** sources and
retain them at link time using the [AC6/GCC/LLVM instructions](UNWINDING.md#build-and-integration).
Use the split-code example if code occupies disjoint allocations.

```sh
python3 host/check_profiler_elf.py --elf firmware.elf --require-unwind --function functionF --output preflight.json
python3 host/create_profiler_report.py --samples samples.bin --elf firmware.elf --output report-stacks --stack-root osThreadEntry --flamegraph /path/to/FlameGraph/flamegraph.pl
```

Choose a root actually present in your workload, or omit `--stack-root`.
Require the expected nested calls, then inspect depth/status distributions,
root coverage and exclusions. A missing/CANTUNWIND recipe needs a library rebuild,
assembly annotation or linker fix. Preflight checks metadata, not runtime stack
readability or every EHABI opcode. EHABI sampling remains best effort: graph
inclusion/root coverage is **not** independently verified stack accuracy.

## Budget, evidence and overhead

Estimate minimum, expected and worst-case storage before increasing depth/rate:

```sh
python3 host/estimate_profiler_buffer.py --buffer-bytes 1048576 --sample-hz 2000 --pmu-count 4 --max-depth 16 --expected-depth 8
```

The report shows average record bytes, payload occupancy, buffer exhaustion and
finalization separately. Finalization does not prove the requested duration ran.
The wrapper keeps raw data/ELF, hashes, configuration, validation and tool hashes
in `manifest.json`; pass `--producer-revision`, `--compiler-id` and
`--capture-command` to record firmware provenance. These values are caller supplied.
Add `--html` with the optional Plotly dependency for a dashboard. Open `index.html`
locally. Keep private firmware and reports outside source control.

Measure the same correctness-checked workload with profiling off, PC only, PMU,
and unwinding at several rates. Repeat runs under identical clocks/cache/input
conditions; compare elapsed time and MSP/task stack high-water marks. Report
whole-workload overhead separately from any measured ISR latency. Validate on
hardware before claiming device accuracy; FVP is a functional regression test.
