# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        build_call_tree.py
# Description:  Build a dual-thread CMSIS-RTOS2 backtrace example
#
# $Date:        1 October 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Direct compiler regression helper; use call_tree.csolution.yml for integration."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", required=True, help="ATfE clang executable")
    parser.add_argument("--cmsis", type=Path, required=True)
    parser.add_argument("--bsp", type=Path, required=True)
    kernel = parser.add_mutually_exclusive_group(required=True)
    kernel.add_argument("--rtx", type=Path, help="ARM.CMSIS-RTX 5.9.1 pack root")
    kernel.add_argument("--freertos", type=Path, help="ARM.CMSIS-FreeRTOS 11.2.0 pack root")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = (args.output or Path("build/freertos-call-tree" if args.freertos else "build/rtos-call-tree")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "RTE_Components.h").write_text('#define CMSIS_device_header "SSE300MPS3.h"\n')
    common = root / "examples/corstone300"
    example = root / "examples/corstone300_rtos2"
    flags = ["--target=arm-none-eabi", "-mcpu=cortex-m55", "-mthumb", "-mcmse", "-mfloat-abi=hard",
             "-O2", "-g", "-ffunction-sections", "-fdata-sections",
             "-fno-vectorize", "-fno-slp-vectorize",
             '-DCMSIS_device_header="SSE300MPS3.h"', '-DPROFILER_USER_CONFIG="profiler_config.h"',
             "-DPROFILER_SAMPLE_HZ=333", "-DPROFILER_SAMPLE_BUFFER_BYTES=131072",
             "-DPROFILER_TIMER_CLOCK_HZ=100000000", "-DPROFILER_TIMESTAMP_CUSTOM=1",
             "-DPROFILER_STACK_UNWIND=1", "-DPROFILER_PRECISE_STACK_BOUNDS=1"]
    if args.freertos:
        flags += ["-DPROFILER_EXAMPLE_FREERTOS=1"]
        kernel = args.freertos.resolve()
        port = kernel / "Source/portable/GCC/ARM_CM55_NTZ/non_secure"
        kernel_includes = [root / "examples/corstone300_freertos", kernel / "Source/include", port,
                           kernel / "CMSIS/RTOS2/FreeRTOS/Include"]
    else:
        flags += ["-DOS_TIMER_THREAD_STACK_SIZE=0", "-DOS_THREAD_WATCHDOG=0"]
        kernel_includes = [args.rtx / "Include", args.rtx / "Config"]
    for directory in [out, root / "mcu", root / "adapters/corstone300", common,
                      args.cmsis / "CMSIS/Core/Include", args.cmsis / "CMSIS/RTOS2/Include",
                      args.bsp / "Device/Include"] + kernel_includes:
        flags += ["-I", str(directory.resolve())]
    sources = [root / "mcu" / name for name in ("sampling_profiler.c", "profiler_backend.c",
               "sampling_profiler_pmu.c", "sampling_profiler_unwind.c")]
    sources += [root / "adapters/corstone300/profiler_timer0.c", common / "reference_timestamp.c",
                common / "unwind_tables.c", example / "call_tree_main.c", example / "call_tree_startup.c",
                args.bsp / "Device/Source/system_SSE300MPS3.c"]
    if args.freertos:
        sources += [kernel / "Source" / name for name in ("tasks.c", "queue.c", "list.c", "timers.c", "event_groups.c")]
        sources += [port / "port.c", port / "portasm.c", kernel / "Source/portable/MemMang/heap_4.c",
                    kernel / "CMSIS/RTOS2/FreeRTOS/Source/cmsis_os2.c"]
    else:
        sources += [args.cmsis / "CMSIS/RTOS2/Source/os_systick.c", args.rtx / "Config/RTX_Config.c"]
        sources += sorted((args.rtx / "Source").glob("*.c"))
        sources += [args.rtx / "Source/GCC/irq_armv8mml.S"]
    objects = []

    def compile_source(source, stem, extra):
        obj = out / (stem + ".o")
        subprocess.run([args.cc] + flags + extra + ["-c", str(source), "-o", str(obj)], check=True)
        objects.append(str(obj))

    for source in sources:
        extra = [] if source.suffix == ".S" else ["-std=c11", "-Wall", "-Wextra"]
        if source.parent == example:
            extra += ["-Werror", "-funwind-tables", "-fno-inline", "-fno-optimize-sibling-calls"]
        compile_source(source, source.stem, extra)
    for suffix in ("", "1"):
        extra = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-funwind-tables", "-fno-inline", "-fno-optimize-sibling-calls"]
        if suffix:
            extra += [f"-D{name}={name}1" for name in ["function" + c for c in "ABCDEF"] + ["run_once", "validate"]]
        compile_source(common / "call_tree.c", "call_tree" + suffix, extra)
    subprocess.run([args.cc] + flags + ["-nostartfiles", "-T", str(common / "linker.ld"),
                   "-Wl,--gc-sections", "-Wl,--no-merge-exidx-entries", "-Wl,-Map=" + str(out / "profiler.map")] + objects +
                   ["-o", str(out / "profiler.elf")], check=True)
    print(out / "profiler.elf")


if __name__ == "__main__":
    main()
