# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        build.py
# Description:  Build the Corstone-300 capture example with CMSIS and BSP packs
#
# $Date:        25 September 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Build the secure bare-metal example with AC6, Arm GNU GCC or ATfE Clang and installed CMSIS/BSP packs."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmsis", type=Path, required=True, help="ARM.CMSIS pack root")
    parser.add_argument("--bsp", type=Path, required=True, help="ARM.V2M_MPS3_SSE_300_BSP pack root")
    parser.add_argument("--cc", default="arm-none-eabi-gcc")
    parser.add_argument("--output", type=Path, default=Path("build/corstone300"))
    parser.add_argument("--semihosting", action="store_true", help="FVP: export samples.bin and exit after capture")
    parser.add_argument("--reference-timestamp", action="store_true", help="Use the TIMER0 reference counter instead of DWT (recommended for FVP)")
    parser.add_argument("--float-workload", action="store_true", help="Exercise FP extended exception frames")
    parser.add_argument("--call-tree", action="store_true", help="Run the non-inlined A-F NOP workload; enables backtraces")
    parser.add_argument("--stack-unwind", action="store_true", help="Collect up to 16 EHABI callers; enables precise bounds")
    parser.add_argument("--precise-stack-bounds", action="store_true", help="Validate frames against exact MSP/PSP allocations")
    pmu = parser.add_mutually_exclusive_group()
    pmu.add_argument("--pmu", dest="pmu_count", action="store_const", const=2, default=0, help="Record 2 PMU events")
    pmu.add_argument("--pmu-count", type=int, choices=range(5), default=0, help="Number of PMU events (0–4)")
    parser.add_argument("--psp", action="store_true", help="Run capture on the process stack")
    parser.add_argument("--sample-hz", type=int, default=1000, help="Requested sampling interrupt rate in Hz")
    parser.add_argument("--captures", type=int, default=1, help="Repeat capture to exercise timer restart")
    parser.add_argument("--timer-clock-hz", type=int, required=True, help="Actual TIMER0 reference clock, Hz")
    parser.add_argument("--buffer-bytes", type=int, default=65536, help="Capture allocation budget, including header")
    parser.add_argument("--split-code", action="store_true", help="Place functionF in separate code SRAM; requires --call-tree")
    args = parser.parse_args()
    if args.split_code and not args.call_tree:
        parser.error("--split-code requires --call-tree")
    args.stack_unwind = args.stack_unwind or args.call_tree
    if args.call_tree and args.float_workload:
        parser.error("--call-tree and --float-workload select different workloads")
    if not 1 <= args.captures <= 100 or not 0 < args.timer_clock_hz <= 0xFFFFFFFF or not 0 < args.sample_hz <= 0xFFFFFFFF or not (200 + 4 * args.pmu_count + 4 * args.stack_unwind) <= args.buffer_bytes <= 0x7FFFFFFF:
        parser.error("sample-hz must be a positive uint32; buffer-bytes must fit the 176-byte header plus 1 configured record, up to 2147483647")
    ac6 = "armclang" in Path(args.cc).name
    clang = "clang" in Path(args.cc).name
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    flags = ["-mcpu=cortex-m55", "-mthumb", "-mcmse", "-mfloat-abi=hard", "-O2", "-g", "-std=c11",
             "-Wall", "-Wextra", "-Werror", "-ffunction-sections", "-fdata-sections",
             '-DPROFILER_USER_CONFIG="profiler_config.h"',
             "-DPROFILER_SAMPLE_DURATION_MS=250U", f"-DPROFILER_SAMPLE_HZ={args.sample_hz}U",
             f"-DPROFILER_SAMPLE_BUFFER_BYTES={args.buffer_bytes}U",
             f"-DPROFILER_TIMER_CLOCK_HZ={args.timer_clock_hz}U",
             f"-DPROFILER_EXAMPLE_CAPTURES={args.captures}U"]
    if ac6:
        flags += ["--target=arm-arm-none-eabi", "-D__MICROLIB"]
    elif clang:
        flags += ["--target=arm-none-eabi"]
    isr_flags = ["-fno-vectorize", "-fno-slp-vectorize"] if clang else ["-fno-tree-vectorize"]
    if args.semihosting:
        flags.append("-DPROFILER_FVP_SEMIHOSTING=1")
    if args.reference_timestamp:
        flags.append("-DPROFILER_TIMESTAMP_CUSTOM=1")
    if args.float_workload:
        flags.append("-DPROFILER_EXAMPLE_FLOAT=1")
    if args.precise_stack_bounds or args.stack_unwind:
        flags.append("-DPROFILER_PRECISE_STACK_BOUNDS=1")
    if args.stack_unwind:
        flags.append("-DPROFILER_STACK_UNWIND=1")
    flags.append(f"-DPROFILER_PMU_COUNT={args.pmu_count}")
    if args.call_tree:
        flags.append("-DPROFILER_EXAMPLE_CALL_TREE=1")
    if args.split_code:
        flags.append("-DPROFILER_EXAMPLE_SPLIT_CODE=1")
    if args.psp:
        flags.append("-DPROFILER_EXAMPLE_PSP=1")
    for directory in [root / "mcu", root / "adapters/corstone300", root / "examples", root / "examples/corstone300",
                      args.cmsis / "CMSIS/Core/Include", args.bsp / "Device/Include"]:
        flags += ["-I", str(directory.resolve())]
    sources = [root / name for name in ["mcu/sampling_profiler.c", "mcu/sampling_profiler_cortex_m.c", "mcu/sampling_profiler_pmu.c", "mcu/sampling_profiler_unwind.c",
               "adapters/corstone300/profiler_timer0.c",
               "examples/profile_workload.c", "examples/corstone300/main.c", "examples/corstone300/startup.c"]]
    sources.append(args.bsp.resolve() / "Device/Source/system_SSE300MPS3.c")
    reference_source = root / "examples/corstone300/reference_timestamp.c"
    if args.reference_timestamp:
        sources.append(reference_source)
    if args.stack_unwind:
        sources.append(root / "examples/corstone300/unwind_tables.c")
    if args.call_tree:
        sources.append(root / "examples/corstone300/call_tree.c")
    objects = []
    for source in sources:
        obj = output / (source.stem + ".o")
        source_flags = isr_flags if source.parent in (root / "mcu", root / "adapters/corstone300") or source == reference_source else []
        # Generate metadata for the workload and other application/BSP functions.
        if args.stack_unwind and source.parent not in (root / "mcu", root / "adapters/corstone300"):
            source_flags = source_flags + ["-funwind-tables"]
        if args.call_tree and source.name in ("call_tree.c", "main.c", "profile_workload.c"):
            source_flags += ["-fno-inline", "-fno-optimize-sibling-calls"]
        subprocess.run([args.cc] + flags + source_flags + ["-c", str(source), "-o", str(obj)], check=True)
        objects.append(str(obj))
    elf = output / "profiler.elf"
    if ac6:
        compiler = Path(shutil.which(args.cc) or args.cc).resolve()
        unwind_link = ["--keep=*(.ARM.exidx*)", "--no_compressexidx"] if args.stack_unwind else []
        subprocess.run([str(compiler.with_name("armlink")), "--cpu=Cortex-M55", "--library_type=microlib",
                        "--entry=Reset_Handler", "--scatter=" + str(root / "examples/corstone300" / ("linker_split.sct" if args.split_code else "linker.sct")),
                        "--map", "--list=" + str(output / "profiler.map"), "--output=" + str(elf)] + unwind_link + objects,
                       check=True)
    else:
        subprocess.run([args.cc] + flags + ["-nostartfiles", "-T", str(root / "examples/corstone300" / ("linker_split.ld" if args.split_code else "linker.ld")),
                       "-Wl,--gc-sections", "-Wl,-Map=" + str(output / "profiler.map")] + objects +
                       (["-Wl,--no-merge-exidx-entries"] if args.stack_unwind else []) +
                       ([] if clang else ["--specs=nosys.specs"]) + ["-o", str(elf)], check=True)
    print(elf)


if __name__ == "__main__":
    main()
