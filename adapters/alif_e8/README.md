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

Dual-core captures used HP channel 2 and HE channel 1, separate SRAM buffers,
four PMU events and matching Release AXFs. See the [hardware evidence](../../tests/VALIDATION.md#physical-hardware)
for counts and scope. Larger backtrace buffers still fill according to actual
variable-length records; a full HE buffer must be stopped before export.

Application-specific findings:

- Broad startup `(+RO)` selectors can consume EXIDX before dedicated scatter
  regions. Follow [selective AC6 retention](../../docs/UNWINDING.md#ac6-table-retention),
  check the actual `--via` path and preflight each final AXF after changes.
- HP `app_main` initially used an unsupported generic C++ recipe. Compiling only
  that source with `-fno-exceptions` reduced unsupported traces from 6,644 to 4;
  this is valid only when exception propagation is unnecessary. Root coverage
  remained near 80% because vendor/runtime calls had CANTUNWIND. On HE, 4,951 of
  5,095 samples reached `tiling::worker_main()`; stops above the application root
  in `__rt_entry_main` remained useful partial chains. See [host interpretation](../../docs/HOST_TOOLS.md#optional-backtraces-and-flamegraph).
- Camera I2C initialization dominated the initial HP capture and delayed its
  thread-mode stop check. A generated-texture renderer isolated the intended
  workload. Verify both headers are complete before export.
- HP could read both buffers in shared SRAM. Use each current map/symbol and
  allocation length; application addresses are not adapter defaults. For 4 KiB
  debugger read limits follow [chunk reconstruction](../../docs/REPEATED_CAPTURES.md#2-reconstruct-and-decode-full-allocations).
- Keep CMSIS Load and debug launch on the same physical probe. A Load task selecting
  `cmsisdap:` while launch selected J-Link waited for the wrong probe. Confirm
  loading completed on both images before treating debug responsiveness as new firmware.

Native channel isolation and GCC/AC6 SDK builds cover defaults/overrides.
Hardware runs do not establish synchronized cross-core timestamps or complete
unwinding of every library function.
