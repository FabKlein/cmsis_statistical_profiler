# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        compile_cortex_m.py
# Description:  Compile Cortex-M architecture, security and timestamp variants
#
# $Date:        22 September 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Compile core, IRQ entry and timestamp modes against each CMSIS Cortex-M header."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cmsis', type=Path, required=True, help='CMSIS pack root (6.3 or later for M52)')
    parser.add_argument('--cc', default='arm-none-eabi-gcc')
    args = parser.parse_args()
    clang = 'clang' in Path(args.cc).name
    cores = [('m0', 'cm0'), ('m0plus', 'cm0plus'), ('m1', 'cm1'), ('m3', 'cm3'),
             ('m4', 'cm4'), ('m7', 'cm7'), ('m23', 'cm23'), ('m33', 'cm33'),
             ('m35p', 'cm35p'), ('m52', 'cm52'), ('m55', 'cm55'), ('m85', 'cm85')]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'irq.c').write_text('#include "sampling_profiler_cortex_m.h"\n'
                                   'PROFILER_DEFINE_IRQ_HANDLER(Test_Handler)\n')
        for cpu, header in cores:
            (tmp / 'device.h').write_text('#include <stdint.h>\n'
                'typedef enum { NonMaskableInt_IRQn=-14, HardFault_IRQn=-13, '
                'MemoryManagement_IRQn=-12, BusFault_IRQn=-11, UsageFault_IRQn=-10, '
                'SecureFault_IRQn=-9, SVCall_IRQn=-5, DebugMonitor_IRQn=-4, PendSV_IRQn=-2, '
                'SysTick_IRQn=-1, Test_IRQn=0 } IRQn_Type;\n'
                '#define __NVIC_PRIO_BITS 2U\n#define __FPU_PRESENT 0U\n'
                '#define __DSP_PRESENT 1U\n#define __MPU_PRESENT 0U\n#define __VTOR_PRESENT 1U\n'
                f'#define __PMU_PRESENT {int(cpu in ("m52", "m55", "m85"))}U\n#define __PMU_NUM_EVENTCNT 8U\n'
                '#define __Vendor_SysTickConfig 0U\n'
                f'#include "core_{header}.h"\nextern uint32_t SystemCoreClock;\n')
            v8 = cpu in ('m23', 'm33', 'm35p', 'm52', 'm55', 'm85')
            for secure in ([False, True] if v8 else [False]):
                for custom in ([1] if cpu in ('m0', 'm0plus', 'm1', 'm23') else [0, 1]):
                    # GCC 13 lacks the M52 name, but supports its architecture.
                    target = ['-march=armv8.1-m.main'] if cpu == 'm52' and not clang else ['-mcpu=cortex-' + cpu]
                    flags = target + ['-mthumb', '-mfloat-abi=soft', '-O2', '-std=c11',
                        '-Wall', '-Wextra', '-Werror', '-Imcu', '-I' + str(tmp),
                        '-I' + str(args.cmsis / 'CMSIS/Core/Include'),
                        '-DPROFILER_DEVICE_HEADER="device.h"', '-DPROFILER_STACK_BASE=0x20000000U',
                        '-DPROFILER_STACK_BYTES=4096U', '-DPROFILER_PMU_COUNT=4', f'-DPROFILER_TIMESTAMP_CUSTOM={custom}',
                        '-DPROFILER_PRECISE_STACK_BOUNDS=1', '-DPROFILER_STACK_UNWIND=1']
                    flags += ['--target=arm-none-eabi', '-fno-vectorize', '-fno-slp-vectorize'] if clang else ['-fno-tree-vectorize']
                    if secure:
                        flags += ['-mcmse']
                    for source in ['mcu/sampling_profiler.c', 'mcu/sampling_profiler_cortex_m.c', 'mcu/sampling_profiler_pmu.c', 'mcu/sampling_profiler_unwind.c', str(tmp / 'irq.c')]:
                        subprocess.run([args.cc] + flags + ['-c', source, '-o', str(tmp / 'test.o')], cwd=ROOT, check=True)
            print(cpu + ': IRQ entry, core, timestamp modes and applicable security states passed')


if __name__ == '__main__':
    main()
