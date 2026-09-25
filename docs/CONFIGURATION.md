# Configuration

Set options project-wide through the clayer or compiler definitions. For an
application header, define `PROFILER_USER_CONFIG="profiler_app_config.h"` and add
its include directory. Application definitions override C defaults.

| Setting | Default | Meaning |
|---|---|---|
| `PROFILER_PMU_COUNT` | 0 | Request 0–4 chained 32-bit events; 0 disables collection; skip if unavailable or hardware capacity is insufficient |
| `PROFILER_PMU_EVENT0`, `PROFILER_PMU_EVENT1` | `0x0003`, `0x0024` | Architectural event IDs: L1D cache refill and backend stall |
| `PROFILER_PMU_EVENT2`, `PROFILER_PMU_EVENT3` | `0x0008`, `0x0011` | Instructions retired and CPU cycles; used for counts 3 and 4 respectively |
| `PROFILER_TIMESTAMP_CUSTOM` | 0: DWT | 1 selects adapter-provided timestamp hooks |
| `PROFILER_TIMER_CLOCK_HZ` | Required for Corstone/Alif | Actual timer input clock in Hz |
| `PROFILER_ALIF_UTIMER_CHANNEL` | HP: 0; HE: 1 | Alif per-image channel, 0–11; startup enables shared clocks |
| `PROFILER_IRQ_PRIORITY` | Lowest | CMSIS unshifted sampling interrupt priority |
| `PROFILER_SAMPLE_HZ` | 1000 | Requested sampling interrupt frequency in Hz |
| `PROFILER_SAMPLE_BUFFER_BYTES` | Layer: 64 KiB; C fallback: 32 KiB | Allocation budget including the 168-byte header |
| `PROFILER_SAMPLING_ENABLED` | 1 | Supplied handler/example switch; 0 still maintains ticks |
| `PROFILER_STACK_BASE`, `PROFILER_STACK_BYTES` | Board RAM defaults | Application override for 1 readable stack RAM range |
| `PROFILER_UNWIND_MAX_DEPTH` | 16 | Maximum recovered callers (1–255); bounds ISR work and temporary storage, not each stored record |
| `PROFILER_STACK_UNWIND` | 0 | 1 enables EHABI backtraces (4 bytes + 4 bytes/recovered caller); requires precise bounds and linker-table hook. See [unwinding](UNWINDING.md) |
| `PROFILER_PRECISE_STACK_BOUNDS` | 0 | Enable an ISR-safe adapter hook that narrows RAM bounds to the interrupted stack |
| `PROFILER_STACK_REGIONS` | Alternative to BASE/BYTES | Array initializer of `{CPU address, bytes}` readable stack regions |
| `PROFILER_BUFFER_ATTRIBUTES` | 32-byte alignment | Optional application-defined section placement |
| `PROFILER_SRAM_REGION_BYTES` | Unset | Optional extra allocation limit for a dedicated region |
| `PROFILER_DEVICE_HEADER` | Selected by board layer | CMSIS device include for backend/timer code |
| `PROFILER_SAMPLE_DURATION_MS` | Example only: 30000 | Callback-loop timeout; core has no duration policy |

## Build and ownership

Non-CMSIS builds compile the 3 `mcu/*.c` files and exactly 1 adapter timer.
Include `mcu/`, the adapter, CMSIS-Core and SDK headers; use C11, the correct CPU,
and `-mcmse` only for secure builds. Supply device/RAM definitions from the board layer.

The common and timer layers restrict vectorization flags to their own source groups.
For manual builds, apply them only to profiler/ISR sources.
Disable ISR vectorization: GCC `-fno-tree-vectorize`; AC6/Clang
`-fno-vectorize -fno-slp-vectorize`. No explicit FP/MVE, logging or instrumentation
in the IRQ path. Inspect disassembly after compiler/LTO changes.

Reserve the timer/vector for the firmware lifetime. On Alif, reserve a distinct
channel per core and enable shared clocks in serialized board startup.
Keep HAL/RTOS handlers unchanged. Use `PROFILER_DEFINE_IRQ_HANDLER` as the actual
vector entry. See [timer contracts](../mcu/sampling_profiler_cortex_m.h).
Startup, clocks, security routing and linker placement belong to the application.

## Memory and timestamps

TCM is optional. Configure initialized, CPU-readable stack RAM with BASE/BYTES or
REGIONS, never both. Cover all task stacks. Explicit bounds override SDK defaults
and STM32N6 DTCM detection. The capture buffer defaults to aligned BSS.

`PROFILER_PRECISE_STACK_BOUNDS=1` requires an ISR-safe [bounds hook](../adapters/template/profiler_stack_bounds.c.example).
It only narrows the whitelist; a failed lookup rejects the sample.

DWT needs accurate `SystemCoreClock` and accessible, running CYCCNT. A
[custom timestamp](../adapters/template/profiler_timestamp.c.example) must be a
coherent free-running modulo-2^32 upcounter at fixed nonzero frequency.
Narrower counters need a race-safe extension. Timer and timestamp clocks may differ;
keep both stable. Avoid sleep, debugger halts and long interrupt masking.

## PMU and diagnostics

PMU collection needs 4 16-bit counters chained into 2 32-bit counters.
The backend reserves the event bank, preserves the shared cycle counter and uses
no PMU IRQ. Busy configuration, event IRQs or legacy DWT profiling prevent collection.
Startup must permit privileged register access; failure leaves PC sampling available.

Counts cover init through stop, including all tasks, interrupts and gated-off time.
Sequential reads are not atomic with the sampled PC. Overflow or incoherent reads
invalidate derived totals/deltas. 0 counts can also reflect unsupported model/events.
See [FORMAT.md](../FORMAT.md) for record sizes and decoding rules.

The host reports invalid EXC_RETURN, unsupported frame, stack bounds or invalid
xPSR as the first rejection reason. Gated-off/full/spurious events are excluded.
Always call stop to finalize a capture, including when full.

## Multiple cores (AMP)

Link an independent profiler and physically separate buffer into each firmware.
Each core owns its sampling IRQ, timestamps and PMU. Decode each dump with its own
ELF; percentages are per core. Different fixed clocks work with per-capture metadata,
but timestamps have independent epochs. No shared-buffer writes or SMP are supported.
See [Alif setup and debugger retrieval](../adapters/alif_e8/README.md).
