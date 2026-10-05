# Alif Ensemble E8 adapter

Select `alif_e8.clayer.yml` and `alif_e8_utimer.clayer.yml` with the common layer
in each firmware image. Requires secure privileged M55 builds (`-mcmse`).

| Image | Default UTIMER channel | Overflow vector | NVIC IRQ |
|---|---|---|---|
| `RTSS_HP` | 0 | `UTIMER_IRQ7Handler` | 384 |
| `RTSS_HE` | 1 | `UTIMER_IRQ15Handler` | 392 |

Override `PROFILER_ALIF_UTIMER_CHANNEL` per image (0–11); IRQ/vector follow the
channel automatically. Reserve distinct channels across both cores and all drivers.
Route each interrupt Secure to its owning core; keep application SysTick unchanged.

## Shared timer setup

**The owning application must enable each channel clock before that core's
profiler initializes.** 1 designated core performs shared register updates and
signals readiness using the application's startup handshake. If both default
channels are reserved from startup:

```c
/* Run once in serialized board setup, before releasing the other core. */
UTIMER->UTIMER_GLB_CLOCK_ENABLE |= (1U << 0) | (1U << 1);
__DSB();
/* Publish readiness through the application's inter-core startup protocol. */
```

Other UTIMER users must join the same clock-setup policy. The adapter never writes
this shared clock register or resets the block; start/stop/clear write only the
selected channel's command bit. No cross-core locks run in the sampling ISR.

Check the application's UTIMER drivers before enabling a profiler channel. On a
DevKit-E8 application using the Ensemble 2.2.1 drivers, enabling an HP channel
early let another driver claim it during peripheral bring-up. The validated
application reserved channel 1 for HE at startup, selected channel 2 for HP,
and enabled channel 2 immediately before HP `profiler_init()`. It stopped and
cleared channel 2's counter and interrupt, then disabled and cleared
`UTIMER_IRQ23_IRQn` before initialization. Reset only a channel the application
has reserved for profiling; do not clear a channel owned by another driver.
After a debugger reload, inspect the running and counter-control bits as well
as the NVIC enable bit: a disabled IRQ alone does not make a channel free.

Set `PROFILER_TIMER_CLOCK_HZ` per image to the actual UTIMER input clock, not the
CPU frequency. Init rejects a missing clock, Non-secure IRQ, enabled local IRQ,
running channel or previously configured counter. These checks do not arbitrate
another core: channel ownership is static. Stop retains ownership for repeated captures.

## Memory and SDK

Each image links its own profiler state and `statistical_samples` buffer into
physically separate readable memory. DTCM is optional; larger SRAM regions work
when the linker reserves them and the debugger can read them. The symbol names and
local addresses may match; the allocations must not share physical storage.
PMU and DWT are local to each core. Keep each `SystemCoreClock` accurate and clocks
stable during capture; different fixed CPU speeds and sampling rates are supported.

On HP, a debugger reload left PMU event counters enabled (`CNTENSET=0xff`), so
`profiler_init()` recorded PMU status `busy`. The application explicitly stopped
those event counters and disabled their interrupts before handing the HP PMU to
the profiler. Do this only after confirming that no other application component
owns them; the adapter deliberately does not take over an occupied PMU. HE
initialized its four counters independently.

Each application image must supply explicit bounds for its CPU-local stack RAM.
The application supplies boot, RAM/MPU/security and DWT access.
For the Ensemble 2.x DFP's AE822FA0E5597, include:

```text
<CMSIS>/CMSIS/Core/Include
<DFP>/Device/core/common/include
<DFP>/Device/soc/AE822FA0E5597/include
<DFP>/Device/soc/AE822FA0E5597/include/rtss_hp   # or rtss_he
```

Select matching `RTSS_HP` or `RTSS_HE`. Preserve the device wrapper's include order:
`soc.h`, `core_defines.h`, then `system.h`.

## Retrieve both captures

Stop both captures before halting either core. Normally use separate debugger
contexts with matching ELFs so each resolves its own buffer symbol. If both
buffers are in shared SRAM and the HP debugger can read that SRAM, it may dump
the HE buffer by its linker address instead; still decode that dump with the
matching HE ELF. From the repository root:

```gdb
# HP debugger context, HP ELF loaded:
source tools/export_profiler_buffer.gdb
export_profiler_buffer hp_samples.bin

# HE debugger context, HE ELF loaded:
source tools/export_profiler_buffer.gdb
export_profiler_buffer he_samples.bin
```

```sh
python3 host/analyze_profiler_buffer.py --samples hp_samples.bin --elf hp.elf --output report/hp
python3 host/analyze_profiler_buffer.py --samples he_samples.bin --elf he.elf --output report/he
```

Reports and percentages are per core. Independent DWT timestamps do not share an
epoch; do not merge timelines without a shared clock or synchronization markers.
This is AMP support, not a shared-buffer/SMP collector.

## DevKit-E8 validation notes

Dual-core capture was validated on DevKit-E8 with the HP profiler on UTIMER
channel 2 and HE on channel 1. Each image had its own fixed SRAM region, stack
bounds, four PMU events and an exact matching Release AXF. HP collected 8,039
samples over approximately four seconds; the smaller HE buffer filled after
4,306 samples. Both captures finalized with zero rejected samples and active
four-event PMU metadata. The HE buffer filling early is expected with
variable-length backtrace records; size from the actual record stream, not a
fixed samples-per-byte estimate.

In a later run, a 304 KiB HE buffer held 5,095 samples before filling; the
512 KiB HP buffer held 8,136 samples without filling. The completed HE trace,
decoded with its matching AXF, reached `tiling::worker_main()` in 4,951 samples
(97.2%). Most `no_table` outcomes occurred only after unwinding through
`worker_main` and `main` into AC6 runtime `__rt_entry_main`. Reaching the
selected application root matters more than a raw `no_table` count: unwinding
beyond that root is not needed for its FlameGraph. The matching-AXF decode had
zero rejected frames and zero unresolved PCs.

Practical integration issues:

- For AC6 flamegraphs, compile profiled code with `-funwind-tables`, put
  `.ARM.exidx` and `.ARM.extab` into contiguous dedicated scatter regions, and
  use [selective two-pass retention](../../docs/UNWINDING.md#ac6-table-retention)
  for large images. Broad startup `(+RO)` selectors can consume `.ARM.exidx`
  before its dedicated region does. Regenerate retention rules from the current
  map and rebuild both images whenever their code changes. Check that each
  project's `--via` response-file path resolves to the generated file in the
  actual linker invocation, then check the final AXFs. Valid PC and PMU samples
  do not imply complete call stacks: this run still contained partial traces
  and missing/unsupported unwind recipes.
- On HP, the original AXF gave `app_main` a generic C++ personality recipe,
  which the bounded compact-EHABI walker does not interpret. Compiling only
  that source with `-fno-exceptions` produced a compact recipe and reduced
  `unsupported` outcomes from 6,644 to 4 in the next capture. Use this only
  when the affected code does not require C++ exception propagation; check
  the final AXF with `host/check_profiler_elf.py --elf firmware.axf --function app_main --require-unwind`
  and validate on hardware. HP root coverage remained near 80% because
  vendor/runtime functions such as `display_wait_frame`, `__rt_memcpy_w`, and
  `ethosu_semaphore_take` have `cantunwind` metadata. Do not treat these
  rootless samples as an `app_main` failure.
- A slow or stuck peripheral call can dominate a short capture and prevent a
  thread-mode `profiler_stop()` check from running. In the validated workload,
  camera I2C initialization dominated the first HP run. A generated texture
  was selected for the renderer profiling run. Scope the workload deliberately
  and confirm `complete=1` on both headers before export.
- Allocate separate host dumps for the two buffers and decode each against its
  own AXF. The HP debugger could read both shared-SRAM ranges: initially
  `0x02340000`/512 KiB for HP and `0x023C0000`/256 KiB for HE; after enlarging
  HE, `0x02334000`/512 KiB for HP and `0x023B4000`/304 KiB for HE. These are
  application linker addresses, not adapter defaults; read the current map or
  symbol before each export. With a 4 KiB debugger read limit, assemble chunks
  in address order and export the entire allocated buffer, including unused
  tail bytes. `create_profiler_report.py --html` needs
  `host/requirements-visualization.txt`; FlameGraph SVG generation needs a
  separate `flamegraph.pl` installation.
- Keep the CMSIS Load task and debug launch on the same physical probe. A
  generated Load task selecting `cmsisdap:` while the launch selected J-Link
  waited for the wrong probe. Confirm Load completed for both images before
  treating a briefly responsive debug session as evidence of new firmware.

Native isolation tests and GCC/AC6 SDK builds also cover the adapter defaults
and channel overrides. Hardware validation establishes capture and export on
this application; it does not establish synchronized cross-core timestamps or
complete EHABI unwinding of every library function.
