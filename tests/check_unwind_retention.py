# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        check_unwind_retention.py
# Description:  Compare GNU ld and LLD EHABI retention using Corstone example objects
#
# $Date:        27 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Link-only check: use freshly built Corstone --call-tree --split-code objects.

Select the same GCC or ATfE compiler as the example build. No FVP run is required.
Output includes each ELF, map, log, compiler identity and results.json.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from analyze_profiler_buffer import elf_functions
from check_profiler_elf import check

PROBE = '''__attribute__((noinline)) int retention_live(int x) { return x+7; }
__attribute__((noinline)) int retention_dead_inline(int x) { return x*3; }
__attribute__((noinline)) int retention_live_extab(int x) {
    volatile int array[129]; array[0]=x;
    __asm volatile("" : : "r"(array) : "r4", "r5", "r6", "r8", "r10", "r11", "d8", "d10");
    return array[0]+1;
}
__attribute__((noinline)) int retention_dead_extab(int x) {
    volatile int array[129]; array[0]=x;
    __asm volatile("" : : "r"(array) : "r4", "r5", "r6", "r8", "r10", "r11", "d8", "d10");
    return array[0]+3;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', required=True, help='GCC or ATfE Clang matching the supplied objects')
    parser.add_argument('--ar', default='arm-none-eabi-ar')
    parser.add_argument('--readelf', default='arm-none-eabi-readelf')
    parser.add_argument('--objects', type=Path, required=True, help='Fresh --call-tree --split-code example build directory')
    parser.add_argument('--output', type=Path, required=True, help='New or empty results directory')
    args = parser.parse_args()
    try:
        if 'armclang' in Path(args.cc).name:
            raise ValueError('This test targets GNU ld/LLD, not armlink')
        clang = 'clang' in Path(args.cc).name
        objects = sorted(args.objects.resolve().glob('*.o'))
        if not objects:
            raise ValueError('No example objects found; build the split-code example first')
        out = args.output.resolve()
        if out.exists() and any(out.iterdir()):
            raise ValueError('Use a new or empty output directory')
        out.mkdir(parents=True, exist_ok=True)
        flags = ['-mcpu=cortex-m55', '-mthumb', '-mcmse', '-mfloat-abi=hard', '-O2', '-g',
                 '-funwind-tables', '-ffunction-sections', '-fdata-sections']
        if clang:
            flags += ['--target=arm-none-eabi']
        for kind, prefix in [('direct', 'retention_'), ('member', 'archive_'), ('unselected', 'unselected_')]:
            source = out / (kind + '.c')
            source.write_text(PROBE.replace('retention_', prefix))
            subprocess.run([args.cc] + flags + ['-c', str(source), '-o', str(source.with_suffix('.o'))], check=True)
        subprocess.run([args.ar, 'rcs', str(out / 'libprobe.a'), str(out / 'member.o'), str(out / 'unselected.o')], check=True)
        # Verify that the complex probes really exercise out-of-line recipes.
        for kind in ('direct', 'member'):
            unwind = subprocess.check_output([args.readelf, '-u', str(out / (kind + '.o'))], text=True)
            (out / (kind + '-unwind.txt')).write_text(unwind)
            if unwind.count('Compact model index: 1') < 2:
                raise ValueError('Compiler did not generate the expected live/dead EXTAB recipes; inspect probe disassembly')
        objects += [out / 'direct.o', out / 'libprobe.a']
        live = [prefix + suffix for prefix in ('retention_', 'archive_') for suffix in ('live', 'live_extab')]
        dead = [prefix + suffix for prefix in ('retention_', 'archive_') for suffix in ('dead_inline', 'dead_extab')]
        version = subprocess.check_output([args.cc, '--version'], text=True).splitlines()[0]
        results = []
        for mode in ('none', 'exidx', 'extab', 'both'):
            script = (ROOT / 'examples/corstone300/linker_split.ld').read_text()
            # Start from ordinary selectors, independent of the example's retention policy.
            for section in ('exidx', 'extab'):
                selector = f'*(.ARM.{section}*)'
                script = script.replace(f'KEEP({selector})', selector)
                if mode in (section, 'both'):
                    script = script.replace(selector, f'KEEP({selector})')
            linker = out / (mode + '.ld')
            linker.write_text(script)
            elf = out / (mode + '.elf')
            command = [args.cc] + flags + ['-nostartfiles', '-T', str(linker), '-Wl,--gc-sections',
                       '-Wl,--no-merge-exidx-entries', '-Wl,-Map=' + str(out / (mode + '.map'))]
            command += ['-Wl,-u,' + name for name in live]
            command += list(map(str, objects)) + ([] if clang else ['--specs=nosys.specs']) + ['-o', str(elf)]
            result = subprocess.run(command, text=True, capture_output=True)
            (out / (mode + '.log')).write_text(result.stdout + result.stderr)
            result.check_returncode()
            data = elf.read_bytes()
            symbols = {name for _, _, name in elf_functions(data)}
            coverage = check(data, ['functionE', 'functionF'] + live, require_unwind=True)
            (out / (mode + '-preflight.json')).write_text(json.dumps(coverage, indent=2) + '\n')
            if not coverage['ok']:
                raise ValueError(f'{mode}: required live unwind recipes failed preflight: {coverage["errors"]}')
            kept = [name for name in dead if name in symbols]
            if mode == 'none' and kept:
                raise ValueError('Ordinary EHABI selectors retained unused probe functions')
            if any(name.startswith('unselected_') for name in symbols):
                raise ValueError(f'{mode}: extracted an unreferenced archive member')
            results.append(dict(mode=mode, retained_dead_functions=kept, live_recipes_valid=True, command=command))
            print(f'{mode}: {len(kept)}/4 unused functions retained; live inline/EXTAB recipes valid')
        report = dict(compiler=version, results=results,
                      limits='Link/preflight check for these objects and flags; no hardware/FVP or LTO validation.')
        (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print('PASS:', out / 'results.json')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'FAIL: {error}\n')


if __name__ == '__main__':
    main()
