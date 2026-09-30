# Himax WE2 TIMER4 adapter

This adapter reserves `TIMER_ID_4` and `TIMER4INT_IRQn` exclusively for
statistical sampling on the Himax WE2/HX6538 Cortex-M55. It was validated on a
Seeed Studio Grove Vision AI Module V2 using the Himax WE2 SDK. SysTick remains
available to the application or an RTOS.

The Himax SDK is not supplied as a CMSIS software component here. Add
`profiler_timer4.c` to the application build together with the four profiler MCU
sources, and provide the SDK include paths containing `WE2_core.h`,
`WE2_device.h` and `hx_drv_timer.h`. The board initialization must call
`hx_drv_timer_init(TIMER_ID_4, HX_TIMER4_BASE)` before profiler initialization;
the standard WE2 platform initialization already does this.

## Configuration and ownership

Use an application configuration such as:

```c
#define PROFILER_DEVICE_HEADER "WE2_device.h"
#define PROFILER_SAMPLE_HZ 1000U
#define PROFILER_SAMPLE_BUFFER_BYTES (128U * 1024U)
#define PROFILER_BUFFER_ATTRIBUTES \
    __attribute__((section(".profiler_buffer"), aligned(32)))
```

Reserve `.profiler_buffer` as `NOLOAD` in SRAM. For EHABI backtraces, also retain
`.ARM.extab` and `.ARM.exidx`, compile profiled sources with `-funwind-tables
-fno-optimize-sibling-calls`, and follow the main
[unwinding guide](../../docs/UNWINDING.md).

The SDK timer period is expressed in whole milliseconds, so this adapter accepts
only sample rates that divide 1000 exactly. The tested configuration is 1 kHz.
The adapter checks the SDK ownership state and NVIC enable state before claiming
TIMER4.

## Important vector handoff

`hx_drv_timer_hw_start()` does not enable the TIMER4 interrupt when passed a null
callback. The adapter therefore supplies an unused callback so the vendor driver
performs its clock/register/NVIC setup. It then replaces the SDK vector using
`EPII_NVIC_SetVector()` and explicitly enables the IRQ. This ordering is
intentional: starting the timer after installing the profiler vector would let
the vendor driver overwrite it.

The final vector is the profiler's naked entry point. Do not install another
TIMER4 handler or call `hx_drv_timer_irq_handler()` from it; an ordinary C wrapper
would alter the exception frame before the profiler captures it.

## UART retrieval without a debugger

The Grove Vision AI Module V2 USB connection exposes the WE2 bootloader and
application UART, but did not expose a usable SWD/J-Link debug interface during
validation. Firmware was flashed through the ROM XMODEM flow, and the stopped
profiling buffer was exported through the application UART at 921600 baud.
This is a board/debug-interface limitation, not a profiler requirement; use the
normal GDB export helper when SWD is available.

After `sampling_profiler_stop()` returns, send one textual marker, the complete
binary object, then an optional trailing marker. Do not print text inside the
binary payload:

```c
xprintf("SCPF_BEGIN %lu\r\n",
        (unsigned long)statistical_samples.header.buffer_bytes);
for (uint32_t byte = 0U;
     byte < statistical_samples.header.buffer_bytes;
     ++byte) {
    console_putchar(((const volatile uint8_t *)&statistical_samples)[byte]);
}
xprintf("\r\nSCPF_END\r\n");
```

Install PySerial and capture the exact byte count declared by the firmware:

```sh
python3 -m pip install pyserial
python3 adapters/himax_we2/capture_uart.py \
  --port /dev/cu.usbmodemXXXXXXXX \
  --output samples.bin
```

Opening the serial device may reset this board, which is useful when capture and
export run once at boot. The script tolerates the doubled carriage return emitted
by the tested Himax console implementation. Increase `--timeout` for larger
buffers or slower baud rates. A 128 KiB raw payload takes at least about 1.4
seconds at 921600 baud, excluding boot and workload time.

Decode `samples.bin` with the exact unstripped ELF used to generate the flashed
secure image:

```sh
python3 host/create_profiler_report.py \
  --samples samples.bin --elf firmware.elf --output report --html
```

## Hardware validation

TIMER4 was validated at 1 kHz with a 128 KiB buffer, four requested PMU events
and 16-level EHABI backtraces. The buffer filled with 2,049 accepted samples,
zero rejected frames and zero unresolved PCs. The A/B/C test reconstructed
`app_main -> functionA -> functionB -> functionC`; 2,027 PC samples (98.93%)
landed in `functionC`. The report recorded 3,767 L1D refills, 1,776,986 backend
stalls, 514,907,619 retired instructions and 819,751,478 CPU cycles over the
capture interval. PMU totals include profiler interrupt execution and are not
per-function attribution.
