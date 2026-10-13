# Corstone-300 RTOS: inside the first sampling interrupt

This historical [RTX call-tree](../examples/corstone300_rtos2/CALL_TREE.md)
Tarmac example follows one TIMER0 interrupt from `269081 clk` until the worker
resumes at `273599 clk`. `functionE` has called `functionF`, but F's first
instruction has not executed: the saved PC is F, while the saved LR returns to E.

The [annotated trace](traces/corstone300-rtos-first-sample.tarmac) preserves the
first two caller-recovery steps and the final caller, storage and return events.
A marked gap at `270110..273286 clk` omits repetitive recovery. There is no nested
interrupt or task switch. The full trace and matching executable are not bundled.
Addresses illustrate this build; do not use them as application configuration.

**This trace predates the current implementation.** It uses a 176-byte header and
an append-time DMB. Current captures use the [192-byte SCPF layout](../FORMAT.md);
publication and export follow the [current ownership contract](CONFIGURATION.md#build-and-ownership).
The trace remains useful for understanding exception frames and virtual unwinding.

## Context and trace notation

Two equal-priority workers run distinct A–F and A1–F1 call trees on permanent
8 KiB PSP stacks. A controller starts, stops and exports capture. The profiler
uses TIMER0, IRQ 3; RTX owns SysTick, PendSV and SVC.

| Capture setting | This build |
|---|---|
| Requested sample rate / period | 333 Hz / 300,300 reference ticks |
| Timer and timestamp frequency | 100 MHz |
| Allocation / maximum callers | 128 KiB / 16 |
| PMU | Disabled |
| State before the sample | Active, incomplete, zero records |

In Tarmac, `IT` means an executed instruction, `IS` a failed conditional
instruction, `R` a register change, and `MR4`/`MW4` a four-byte memory read/write.
`thread_s` and `handler_s` denote Secure Thread and Handler modes. Appended
`[function+offset]` labels describe instruction addresses, not branch destinations.
See the [Tarmac format](https://github.com/ARM-software/tarmac-trace-utilities/blob/main/doc/index.rst).
The trace's `clk` coordinate is separate from stored sample timestamps and is
not a calibrated physical CPU cycle measurement.

## Hardware entry and the two stacks

The call at `0x10001182` sets LR to `0x10001187` (Thumb-tagged return address) and
PC to `0x10000b14`, F's entry. Hardware then saves the basic exception frame on
PSP; the handler's own workspace uses MSP.

| Item | Address/value in this trace |
|---|---|
| Worker allocation | `[0x300000c0, 0x300020c0)` |
| PSP before IRQ / after hardware save | `0x30002080` / `0x30002060` |
| Saved PC / LR / xPSR | `0x10000b14` / `0x10001187` / `0x01000000` |
| Handler MSP before IRQ | `0x3007ff98` |
| EXC_RETURN | `0xfffffffd`, basic Thread frame on PSP |

The naked [IRQ wrapper](../mcu/profiler_backend.h) preserves r4–r11 and
EXC_RETURN, then passes the hardware frame and saved registers to the
[backend](../mcu/profiler_backend.c). The backend acknowledges TIMER0, reads the
timestamp, checks the gate and validates the frame against the interrupted
worker's allocation. Readable surrounding RAM is insufficient evidence of stack
ownership. FP frames, alignment padding and security-state handling are covered
by [integration](INTEGRATION.md) and [unwinding](UNWINDING.md).

## Recovering callers without changing the worker stack

The [unwinder](../mcu/sampling_profiler_unwind.c) operates on virtual registers.
It binary-searches `.ARM.exidx` by decoded code-range start, interprets the
selected compact recipe, bounds every table/stack read and recovers a caller.
It never calls exception personality routines or pops the live application stack.

This ELF has 154 eight-byte index entries and no out-of-line `.ARM.extab`
recipes. F's entry is at `0x1000a210`: PREL31 word `0x7fff6904` points back to
`0x10000b14`, and recipe `0x80b0b0b0` means finish using LR. F is a leaf, so its
virtual SP stays unchanged. An unchanged SP alone is not a failed unwind step.

Caller lookup uses `(return_address & ~1) - 2`; for `0x10001187`, lookup
`0x10001184` lies inside the preceding four-byte BL. This does not assume all
calls are two bytes long. E's recipe `0x808408b0` restores r7 and LR from
`0x30002080` and `0x30002084`, then advances virtual SP by eight bytes.

| Function unwound | Virtual SP before → after | Recovered caller |
|---|---|---|
| F | `0x30002080 → 0x30002080` | E, `0x10001187` |
| E | `0x30002080 → 0x30002088` | D, `0x1000309f` |
| D | `0x30002088 → 0x30002090` | C, `0x1000323b` |
| C | `0x30002090 → 0x30002098` | B, `0x1000389f` |
| B | `0x30002098 → 0x300020a0` | A, `0x10003bd3` |
| A | `0x300020a0 → 0x300020a8` | `run_once`, `0x10003d7b` |
| `run_once` | `0x300020a8 → 0x300020b0` | `worker`, `0x100009ed` |
| `worker` | `0x300020b0 → 0x300020c0` | `osThreadEntry`, `0x1000993f` |

`osThreadEntry` has `CANTUNWIND`; recovery stops with `NO_TABLE`, retaining eight
callers. Metadata `0x00000108` encodes depth 8 and status 1. The sampled PC is
separate, giving nine displayed function levels. See the
[EHABI specification](https://github.com/ARM-software/abi-aa/blob/main/ehabi32/ehabi32.rst#103-frame-unwinding-instructions)
and [opcode definitions](../mcu/profiler_ehabi.h).

## Storage and exception return

The historical record at `0x300061d0` occupies `24 + 4 + 8*4 = 60` bytes:
six base words, depth/status and eight nearest-first callers. No unused caller
slots are exported. Its timestamp is 841,000 and tick is 1; LR also appears as
the first caller because F's finish-only recipe uses LR.

The trace publishes `bytes_used=60` and `count=1` after a DMB. That ordering is
historical; use the current lifecycle contract for new integrations. The wrapper
restores r4–r11 and EXC_RETURN, then `BX` with the exception-return token lets
hardware restore the PSP frame. PSP returns to `0x30002080`, MSP to
`0x3007ff98`, and F's first instruction executes. No scheduler call occurs.

## What this example establishes

| Handler phase | Instruction-event positions |
|---|---:|
| Assembly entry | 16 |
| Backend and hooks before unwinding | 166 |
| Unwinder | 4,232 |
| Storage call setup and storage | 92 |
| Backend and assembly return | 11 |
| Total | 4,517 |

The total includes 4,018 executed and 499 condition-failed instructions;
unwinding accounts for 93.7% of these positions. This is model instruction work,
not physical latency or WCET. Use the [ISR budget guide](ISR_BUDGET.md) for target
measurement. The first stored timestamp is 300,478 reference ticks (3.00478 ms)
after the capture epoch, which includes setup/read offsets and does not measure
unwinder duration.

The host reverses callers and appends F:

```text
osThreadEntry;worker;run_once;functionA;functionB;functionC;functionD;functionE;functionF 1
```

The `1` counts a sample, not an invocation. The partial chain is usable at the
selected root. Entry filtering permits this F sample because the exact finish-only
recipe is safe at entry and its first caller matches LR; other prologues may be
unreliable. See [host inclusion rules](HOST_TOOLS.md#optional-backtraces-and-flamegraph).

## Inspect your own build

Follow the [RTX run guide](../examples/corstone300_rtos2/CALL_TREE.md#run), keep the
exact ELF with the capture, and compare handler stages rather than addresses:

```sh
arm-none-eabi-objdump -d path/to/profiler.elf | less
arm-none-eabi-readelf --unwind path/to/profiler.elf | less
arm-none-eabi-readelf --sections path/to/profiler.elf | less
```

Export only after stop returns and the header is complete/inactive. A snapshot
immediately after the first interrupt is still incomplete.
