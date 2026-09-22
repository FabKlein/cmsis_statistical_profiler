# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        compile_adapters.py
# Description:  Compile board adapters against real SDK headers
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Compile adapters against real SDK headers; does not download SDKs or run hardware."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="arm-none-eabi-gcc", help="Arm GNU GCC or AC6 armclang")
    parser.add_argument("--nm", default="arm-none-eabi-nm", help="ELF symbol inspection tool")
    parser.add_argument("--cmsis", type=Path, required=True, help="ARM.CMSIS pack root")
    parser.add_argument("--corstone-bsp", type=Path, help="ARM.V2M_MPS3_SSE_300_BSP pack root")
    parser.add_argument("--stm32-cmsis", type=Path, help="ST cmsis-device-n6 repository root")
    parser.add_argument("--stm32-hal", type=Path, help="ST stm32n6xx-hal-driver repository root")
    parser.add_argument("--alif-dfp", type=Path, help="Alif Ensemble 2.x DFP root (E8 AE822FA0E5597)")
    parser.add_argument("--pmu", action="store_true", help="Compile optional PMU snapshots")
    parser.add_argument("--sample-hz", type=int, nargs="+", default=[1000], help="Requested rates to compile")
    args = parser.parse_args()
    if any(not 0 < rate <= 0xFFFFFFFF for rate in args.sample_hz):
        parser.error("sample-hz values must be positive uint32 integers")
    if bool(args.stm32_cmsis) != bool(args.stm32_hal):
        parser.error("Supply both STM32 SDK paths")
    if not any([args.corstone_bsp, args.stm32_cmsis, args.alif_dfp]):
        parser.error("Supply at least one board SDK")
    armclang = "armclang" in Path(args.cc).name
    flags = ["-mcpu=cortex-m55", "-mthumb", "-mcmse", "-mfloat-abi=hard", "-O2", "-std=c11",
             "-Wall", "-Wextra", "-Werror", "-Imcu", "-Iexamples",
             "-DPROFILER_TIMER_CLOCK_HZ=100000000U",
             "-I" + str(args.cmsis.resolve() / "CMSIS/Core/Include")]
    flags += [f"-DPROFILER_PMU_ENABLE={int(args.pmu)}"]
    flags += (["--target=arm-arm-none-eabi", "-fno-vectorize", "-fno-slp-vectorize"] if armclang
              else ["-fno-tree-vectorize"])
    boards = []
    if args.corstone_bsp:
        boards.append(("corstone300", "corstone300", ["-I" + str(args.corstone_bsp.resolve() / "Device/Include")]))
    if args.stm32_cmsis:
        boards.append(("stm32n6", "stm32n6", ["-DSTM32N657xx",
                       "-I" + str(args.stm32_cmsis.resolve() / "Include"),
                       "-I" + str(args.stm32_hal.resolve() / "Inc")]))
    if args.alif_dfp:
        root = args.alif_dfp.resolve()
        for core, channel in [("hp", None), ("he", None), ("hp", 11), ("he", 2)]:
            boards.append(("alif_e8_" + core + (f"_ch{channel}" if channel is not None else ""), "alif_e8",
                           ([f"-DPROFILER_ALIF_UTIMER_CHANNEL={channel}"] if channel is not None else []) +
                           ["-DRTSS_" + core.upper(),
                           "-I" + str(root / "Device/core/common/include"),
                           "-I" + str(root / "Device/soc/AE822FA0E5597/include"),
                           "-I" + str(root / ("Device/soc/AE822FA0E5597/include/rtss_" + core))]))
    with tempfile.TemporaryDirectory() as tmp:
        # Minimal application HAL configuration; adapter includes RCC headers explicitly.
        (Path(tmp) / "stm32n6xx_hal_conf.h").write_text(
            '#include "stm32n6xx_hal_def.h"\n#define USE_RTOS 0U\n'
            '#define TICK_INT_PRIORITY 15U\n#define assert_param(x) ((void)0U)\n')
        for name, board, includes in boards:
            header = {"corstone300": "SSE300MPS3.h", "stm32n6": "stm32n6xx.h",
                      "alif_e8": "profiler_alif_device.h"}[board]
            base = {"corstone300": "DTCM0_BASE_S", "stm32n6": "DTCM_BASE_S",
                    "alif_e8": "DTCM_BASE"}[board]
            base_setting = "PROFILER_DEFAULT_DTCM_BASE" if board == "stm32n6" else "PROFILER_DEFAULT_STACK_BASE"
            config = [f'-DPROFILER_DEVICE_HEADER="{header}"', f"-D{base_setting}={base}"]
            if board == "corstone300":
                config += ["-DPROFILER_DEFAULT_STACK_BYTES=(DTCM_BLK_SIZE*DTCM_BLK_NUM)"]
            elif board == "alif_e8":
                config += ["-DPROFILER_DEFAULT_STACK_BYTES=DTCM_SIZE"]
            board_flags = flags + config + ["-I" + tmp, "-Iadapters/" + board] + includes
            for rate in args.sample_hz:
                for enabled in [0, 1]:
                    objects = {}
                    for source in ["mcu/sampling_profiler.c", "mcu/sampling_profiler_cortex_m.c", "mcu/sampling_profiler_pmu.c",
                                   "integrations/systick/profiler_systick.c",
                                   "adapters/" + board + "/profiler_" +
                                   {"corstone300": "timer0", "stm32n6": "tim2", "alif_e8": "utimer"}[board] + ".c",
                                   "examples/profile_workload.c"]:
                        obj = Path(tmp) / (Path(source).stem + ".o")
                        subprocess.run([args.cc] + board_flags + [f"-DPROFILER_SAMPLING_ENABLED={enabled}",
                                       f"-DPROFILER_SAMPLE_HZ={rate}U", "-c", source,
                                       "-o", str(obj)], cwd=ROOT, check=True)
                        objects[Path(source).stem] = obj
                    timer = {"corstone300": "timer0", "stm32n6": "tim2", "alif_e8": "utimer"}[board]
                    vector = {"corstone300": "TFM_TIMER0_IRQ_Handler", "stm32n6": "TIM2_IRQHandler",
                              "alif_e8": ("UTIMER_IRQ95Handler" if name.endswith("_ch11") else
                                          "UTIMER_IRQ23Handler" if name.endswith("_ch2") else
                                          "UTIMER_IRQ15Handler" if name == "alif_e8_he" else "UTIMER_IRQ7Handler")}[board]
                    dedicated = [obj for stem, obj in objects.items() if stem != "profiler_systick"]
                    symbols = subprocess.check_output([args.nm] + list(map(str, dedicated)), text=True)
                    if "SysTick_Handler" in symbols or "HAL_IncTick" in symbols or "HAL_GetTick" in symbols:
                        raise RuntimeError("Dedicated timer build must not own SysTick or HAL tick")
                    defined = subprocess.check_output([args.nm, "--defined-only",
                                                       str(objects["profiler_" + timer])], text=True)
                    if " T " + vector not in defined:
                        raise RuntimeError("Missing strong timer vector: " + vector)
                    # A relocatable link catches duplicate strong symbols without
                    # supplying a board startup or linking vendor clock code.
                    if not armclang:
                        subprocess.run([args.cc, "-nostdlib", "-r"] + list(map(str, dedicated)) +
                                       ["-o", str(Path(tmp) / "combined.o")], check=True)
                print(name + f": {rate} Hz enabled and disabled builds passed")


if __name__ == "__main__":
    main()
