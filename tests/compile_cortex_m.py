# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        compile_cortex_m.py
# Description:  Compile Cortex-M architecture, security and timestamp variants
#
# $Date:        2 October 2026
# $Revision:    V.1.0.3
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Compile Cortex-M variants and optionally report compiler stack frames."""

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORES = [
    ("m0", "cm0"),
    ("m0plus", "cm0plus"),
    ("m1", "cm1"),
    ("m3", "cm3"),
    ("m4", "cm4"),
    ("m7", "cm7"),
    ("m23", "cm23"),
    ("m33", "cm33"),
    ("m35p", "cm35p"),
    ("m52", "cm52"),
    ("m55", "cm55"),
    ("m85", "cm85"),
]


def stack_frames(path):
    """Read GCC/Clang .su entries; bytes are local frames, not call-chain totals."""
    frames = []
    for line in path.read_text().splitlines():
        location, size, kind = line.split("\t")
        frames.append(
            {"function": location.rsplit(":", 1)[-1], "bytes": int(size), "kind": kind}
        )
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cmsis",
        type=Path,
        required=True,
        help="CMSIS pack root (6.3 or later for M52)",
    )
    parser.add_argument("--cc", default="arm-none-eabi-gcc")
    parser.add_argument(
        "--cpu",
        choices=[cpu for cpu, _ in CORES],
        nargs="+",
        help="Subset of the architecture matrix (default: all)",
    )
    parser.add_argument("--optimization", choices=["O2", "Os"], default="O2")
    parser.add_argument(
        "--pmu-count", type=int, choices=range(5), nargs="+", default=[4]
    )
    parser.add_argument(
        "--unwind-depth",
        type=int,
        nargs="+",
        default=[16],
        help="Caller limits 1..255 to compile; 0 disables backtraces",
    )
    parser.add_argument(
        "--stack-usage",
        type=Path,
        help="New directory for frames.csv and provenance.json",
    )
    args = parser.parse_args()
    if any(not 0 <= depth <= 255 for depth in args.unwind_depth):
        parser.error("--unwind-depth must be 0..255")
    if args.stack_usage and args.stack_usage.exists():
        parser.error("--stack-usage must name a new output directory")
    clang = "clang" in Path(args.cc).name
    armclang = "armclang" in Path(args.cc).name
    cores = [(cpu, header) for cpu, header in CORES if not args.cpu or cpu in args.cpu]
    frames, configurations, device_headers = [], [], {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "irq.c").write_text(
            '#include "profiler_backend.h"\nPROFILER_DEFINE_IRQ_HANDLER(Test_Handler)\n'
        )
        for cpu, header in cores:
            (tmp / "device.h").write_text(
                "#include <stdint.h>\n"
                "typedef enum { NonMaskableInt_IRQn=-14, HardFault_IRQn=-13, "
                "MemoryManagement_IRQn=-12, BusFault_IRQn=-11, UsageFault_IRQn=-10, "
                "SecureFault_IRQn=-9, SVCall_IRQn=-5, DebugMonitor_IRQn=-4, PendSV_IRQn=-2, "
                "SysTick_IRQn=-1, Test_IRQn=0 } IRQn_Type;\n"
                "#define __NVIC_PRIO_BITS 2U\n#define __FPU_PRESENT 0U\n"
                "#define __DSP_PRESENT 1U\n#define __MPU_PRESENT 0U\n#define __VTOR_PRESENT 1U\n"
                f"#define __PMU_PRESENT {int(cpu in ('m52', 'm55', 'm85'))}U\n#define __PMU_NUM_EVENTCNT 8U\n"
                "#define __Vendor_SysTickConfig 0U\n"
                f'#include "core_{header}.h"\nextern uint32_t SystemCoreClock;\n'
            )
            device_headers[cpu] = (tmp / "device.h").read_text()
            v8 = cpu in ("m23", "m33", "m35p", "m52", "m55", "m85")
            for secure in [False, True] if v8 else [False]:
                for custom in [1] if cpu in ("m0", "m0plus", "m1", "m23") else [0, 1]:
                    # GCC 13 lacks the M52 name, but supports its architecture.
                    target = (
                        ["-march=armv8.1-m.main"]
                        if cpu == "m52" and not clang
                        else ["-mcpu=cortex-" + cpu]
                    )
                    flags = target + [
                        "-mthumb",
                        "-mfloat-abi=soft",
                        "-" + args.optimization,
                        "-std=c11",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-Imcu",
                        "-I" + str(tmp),
                        "-I" + str(args.cmsis / "CMSIS/Core/Include"),
                        '-DPROFILER_DEVICE_HEADER="device.h"',
                        "-DPROFILER_STACK_BASE=0x20000000U",
                        "-DPROFILER_STACK_BYTES=4096U",
                        f"-DPROFILER_TIMESTAMP_CUSTOM={custom}",
                        "-DPROFILER_PRECISE_STACK_BOUNDS=1",
                    ]
                    flags += (
                        [
                            "--target="
                            + ("arm-arm-none-eabi" if armclang else "arm-none-eabi"),
                            "-fno-vectorize",
                            "-fno-slp-vectorize",
                        ]
                        if clang
                        else ["-fno-tree-vectorize"]
                    )
                    if secure:
                        flags += ["-mcmse"]
                    if args.stack_usage:
                        flags += [
                            "-fstack-usage",
                            "-ffunction-sections",
                            "-fdata-sections",
                        ]
                    for pmu, depth in itertools.product(
                        args.pmu_count, args.unwind_depth
                    ):
                        feature_flags = [
                            f"-DPROFILER_PMU_COUNT={pmu}",
                            f"-DPROFILER_STACK_UNWIND={int(depth != 0)}",
                        ]
                        if depth:
                            feature_flags += [f"-DPROFILER_UNWIND_MAX_DEPTH={depth}"]
                        variant = dict(
                            cpu=cpu,
                            secure=int(secure),
                            timestamp_custom=custom,
                            pmu_count=pmu,
                            unwind_depth=depth,
                        )
                        configurations.append(
                            dict(variant, flags=flags + feature_flags)
                        )
                        for source in [
                            "mcu/sampling_profiler.c",
                            "mcu/profiler_backend.c",
                            "mcu/sampling_profiler_pmu.c",
                            "mcu/sampling_profiler_unwind.c",
                            str(tmp / "irq.c"),
                        ]:
                            usage = tmp / "test.su"
                            usage.unlink(missing_ok=True)
                            subprocess.run(
                                [args.cc]
                                + flags
                                + feature_flags
                                + ["-c", source, "-o", str(tmp / "test.o")],
                                cwd=ROOT,
                                check=True,
                            )
                            if args.stack_usage:
                                # Disabled PMU/unwind sources can be empty translation units.
                                if not usage.exists() and not (
                                    (
                                        source.endswith("sampling_profiler_unwind.c")
                                        and not depth
                                    )
                                    or (
                                        source.endswith("sampling_profiler_pmu.c")
                                        and not pmu
                                    )
                                ):
                                    raise RuntimeError(
                                        "Compiler did not emit stack usage for "
                                        + source
                                    )
                                if usage.exists():
                                    for frame in stack_frames(usage):
                                        frames.append(
                                            dict(
                                                variant,
                                                source=Path(source).name,
                                                **frame,
                                            )
                                        )
            print(
                cpu
                + ": IRQ entry, core, timestamp modes and applicable security states passed"
            )
    if args.stack_usage:
        args.stack_usage.mkdir(parents=True)
        with (args.stack_usage / "frames.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "cpu",
                    "secure",
                    "timestamp_custom",
                    "pmu_count",
                    "unwind_depth",
                    "source",
                    "function",
                    "bytes",
                    "kind",
                ],
            )
            writer.writeheader()
            writer.writerows(frames)
        sources = list((ROOT / "mcu").glob("*.[ch]")) + [Path(__file__).resolve()]
        metadata = {
            "scope": "Per-function compiler frames; not a complete IRQ stack bound or ISR timing measurement.",
            "compiler": subprocess.check_output([args.cc, "--version"], text=True),
            "cmsis_root": str(args.cmsis.resolve()),
            "cmsis_core_sha256": {
                header: hashlib.sha256(
                    (
                        args.cmsis / "CMSIS/Core/Include" / ("core_" + header + ".h")
                    ).read_bytes()
                ).hexdigest()
                for _, header in cores
            },
            "source_sha256": {
                str(path.relative_to(ROOT)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(sources)
            },
            "device_headers": device_headers,
            "irq_wrapper_bytes": {"without_backtraces": 0, "with_backtraces": 40},
            "isr_cycles": None,
            "configurations": configurations,
        }
        (args.stack_usage / "provenance.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
        print(
            "Compiler stack frames (hardware/assembly/callees excluded):",
            args.stack_usage,
        )


if __name__ == "__main__":
    main()
