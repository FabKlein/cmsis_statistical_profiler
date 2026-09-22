# Corstone-300 capture example

Secure bare-metal example with startup, ITCM/DTCM linker script and a validated
250 ms workload. TIMER0 samples while application SysTick runs independently.
The example checks SysTick continuity and profiler stop/restart.

Requires AC6 or Arm GNU GCC, CMSIS 6.x and SSE-300 BSP 1.5.0.
Add `--cc /path/to/armclang` for AC6 (scatter file and Microlib); GCC is the default.
From the repository root:

```sh
python3 examples/corstone300/build.py \
  --cmsis /path/to/ARM/CMSIS/6.0.0 \
  --bsp /path/to/ARM/V2M_MPS3_SSE_300_BSP/1.5.0 \
  --output build/corstone300 --semihosting --sample-hz 2500 --buffer-bytes 65536 \
  --timer-clock-hz 100000000 --captures 2 --reference-timestamp
```

Run the FVP from the build directory so the post-capture dump is written there:

```sh
cd build/corstone300
FVP_Corstone_SSE-300_Ethos-U55 -a profiler.elf \
  -C core_clk.mul=32000000 \
  -C mps3_board.sse300.refcounter.base_frequency=100000000 \
  -C cpu0.semihosting-enable=1 \
  -C mps3_board.visualisation.disable-visualisation=1 \
  -C mps3_board.telnetterminal0.start_telnet=0 \
  -C mps3_board.telnetterminal1.start_telnet=0 \
  -C mps3_board.telnetterminal2.start_telnet=0 \
  -C mps3_board.telnetterminal5.start_telnet=0 --simlimit 3
python3 ../../host/analyze_samples.py --samples samples.bin --elf profiler.elf --output report
```


The commands match a 32 MHz BSP CPU and 100 MHz reference timer. FVP defaults to
25 MHz CPU; omitting the override fails the SysTick check. `--captures 2` exports
the final capture. Semihosting occurs only after capture.

Expect `validation_passed=1`, `complete=1`, `active=0`, `rejected=0`, about 625 samples
at 2500 Hz, mostly in `run_once`. A simulation-limit exit alone does not prove success.

| Build option | Purpose |
|---|---|
| `--sample-hz`, `--buffer-bytes` | Sampling rate and allocation budget |
| `--psp --float-workload` | Exercise PSP/extended frames; EXC_RETURN normally `0xFFFFFFED`, possibly `0xFFFFFFFD` before FP use |
| `--precise-stack-bounds` | Check linker MSP bounds and the example PSP array; still enforce the RAM whitelist |
| `--reference-timestamp` | Use the 100 MHz reference counter for FVP timing; default is DWT |
| `--pmu` | Request D-cache refill/backend-stall counters; adds event reports and timeline deltas |

Ordinary MSP captures use EXC_RETURN `0xFFFFFFF9`. PMU events can count 0 for
this ITCM/DTCM workload/model. FVP validates capture flow, not silicon performance.

## MPS3 FPGA

Build without `--semihosting`, load with the board debugger and break at
`profiler_capture_complete`. Use [dump_samples.gdb](../../tools/dump_samples.gdb)
and decode with the matching ELF.

Confirm the FPGA image's clocks and memory map: this linker assumes 512 KiB secure
ITCM and 512 KiB secure DTCM. Set `--timer-clock-hz` to the actual reference frequency.
The example starts the shared reference counter unscaled; adapt this to existing
board setup. FPGA execution remains unverified.

## CI regression

[GitHub Actions](../../.github/workflows/fvp.yml) builds with AC6 6.24 and runs FVP
11.31.28 with PMU enabled. Use [the runner and reference](../../tests/VALIDATION.md#ci-reference)
for the same local pass/fail check.

CI uses `--reference-timestamp`: the low 32 bits of the free-running TIMER0
reference counter, at `--timer-clock-hz`. This avoids the functional FVP's DWT
rate mismatch while retaining the strict timing check. It measures elapsed time,
not CPU cycles, and does not reset or reconfigure the shared counter.
