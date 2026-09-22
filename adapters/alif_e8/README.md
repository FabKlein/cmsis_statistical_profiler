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

**Board startup must enable channel clocks before either profiler initializes.**
1 designated core performs the shared register update, then signals readiness
using the application's startup handshake. For the defaults:

```c
/* Run once in serialized board setup, before releasing the other core. */
UTIMER->UTIMER_GLB_CLOCK_ENABLE |= (1U << 0) | (1U << 1);
__DSB();
/* Publish readiness through the application's inter-core startup protocol. */
```

Other UTIMER users must join the same clock-setup policy. The adapter never writes
this shared clock register or resets the block; start/stop/clear write only the
selected channel's command bit. No cross-core locks run in the sampling ISR.

Set `PROFILER_TIMER_CLOCK_HZ` per image to the actual UTIMER input clock, not the
CPU frequency. Init rejects a missing clock, Non-secure IRQ, enabled local IRQ,
running channel or previously configured counter. These checks do not arbitrate
another core: channel ownership is static. Stop retains ownership for repeated captures.

## Memory and SDK

Each image links its own profiler state and `statistical_samples` buffer into
physically separate memory, preferably its core-local DTCM. The symbol names and
local addresses may match; the allocations must not share physical storage.
PMU and DWT are local to each core. Keep each `SystemCoreClock` accurate and clocks
stable during capture; different fixed CPU speeds and sampling rates are supported.

Stack bounds default to SDK `DTCM_BASE`/`DTCM_SIZE`. Use CPU-local addresses for
application overrides. The application supplies boot, RAM/MPU/security and DWT access.
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

Stop both captures before halting either core. Use separate debugger contexts with
the matching ELF loaded; each resolves its own buffer symbol. From the repository root:

```gdb
# HP debugger context, HP ELF loaded:
source tools/export_profiler_buffer.gdb
export_profiler_buffer hp_samples.bin

# HE debugger context, HE ELF loaded:
source tools/export_profiler_buffer.gdb
export_profiler_buffer he_samples.bin
```

```sh
python3 host/analyze_samples.py --samples hp_samples.bin --elf hp.elf --output report/hp
python3 host/analyze_samples.py --samples he_samples.bin --elf he.elf --output report/he
```

Reports and percentages are per core. Independent DWT timestamps do not share an
epoch; do not merge timelines without a shared clock or synchronization markers.
This is AMP support, not a shared-buffer/SMP collector.

Native isolation tests and GCC/AC6 SDK builds cover both defaults and overrides.
Dual-core hardware capture and debugger retrieval remain unverified.
