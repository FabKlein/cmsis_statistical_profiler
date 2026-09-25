# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        check_profiler_elf.py
# Description:  Preflight ELF metadata before capture
#
# $Date:        25 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Check ELF unwind metadata before flashing; this does not prove asynchronous unwind accuracy."""
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import struct

from analyze_profiler_buffer import checked_slice, elf_functions, executable_ranges


def prel31(word, place):
    return (place + (word & 0x7fffffff) - (0x80000000 if word & 0x40000000 else 0)) & 0xffffffff


def check(data, names=(), require_unwind=False):
    functions = elf_functions(data)
    regions = sorted(executable_ranges(data))
    offset = struct.unpack_from('<I', data, 32)[0]
    size, count, strings_index = struct.unpack_from('<HHH', data, 46)
    sections = [struct.unpack('<10I', checked_slice(data, offset + n * size, 40)) for n in range(count)]
    if strings_index >= count:
        raise ValueError('Invalid section-name table')
    strings = checked_slice(data, sections[strings_index][4], sections[strings_index][5])

    def section_name(s):
        end = strings.find(b'\0', s[0])
        return strings[s[0]:end].decode('utf-8', errors='replace') if end >= s[0] else ''

    def region(address, boundary=False):
        return next((i for i, (base, length) in enumerate(regions)
                     if base <= address < base + length or boundary and address == base + length), None)

    errors, warnings, entries = [], [], []
    indexes = [s for s in sections if s[1] == 0x70000001 and s[5]]
    extabs = [s for s in sections if 'extab' in section_name(s).lower() and s[5]]
    if len(indexes) > 1:
        errors.append('Multiple EXIDX sections: combine them into 1 sorted index for the table hook.')
    if not indexes:
        (errors if require_unwind or names else warnings).append(
            'No EXIDX: compile profiled sources/libraries with -funwind-tables and retain .ARM.exidx* at link time.')
    for s in extabs:
        if not s[2] & 2 or s[3] & 3 or s[5] & 3:
            errors.append('EXTAB must be allocated and word-aligned; correct linker placement.')
        checked_slice(data, s[4], s[5])
    for s in indexes:
        if not s[2] & 2 or s[3] & 3 or s[5] % 8:
            errors.append('EXIDX must be allocated, word-aligned and contain 8-byte entries.')
            continue
        previous = -1
        for n, (relative, recipe) in enumerate(struct.iter_unpack('<II', checked_slice(data, s[4], s[5]))):
            start = prel31(relative, s[3] + 8 * n)
            state = 'supported'
            if relative & 0x80000000 or start & 1 or start <= previous or region(start, True) is None:
                errors.append(f'EXIDX entry {n}: invalid/unsorted code start 0x{start:08x}; check code regions and index ordering.')
            previous = start
            if recipe == 1:
                state = 'cantunwind'
            elif recipe & 0x80000000:
                if recipe >> 24 != 0x80:
                    state = 'unsupported'
            else:
                target = prel31(recipe, s[3] + 8 * n + 4)
                table = next((t for t in extabs if t[3] <= target and target + 4 <= t[3] + t[5]), None)
                if table is None or target & 3:
                    errors.append(f'EXIDX entry {n}: EXTAB pointer 0x{target:08x} is outside retained recipes.')
                    state = 'invalid'
                else:
                    first = struct.unpack('<I', checked_slice(data, table[4] + target - table[3], 4))[0]
                    personality = first >> 24
                    words = 1 + ((first >> 16) & 255) if personality in (0x81, 0x82) else 1
                    if personality not in (0x80, 0x81, 0x82):
                        state = 'unsupported'
                    elif target + words * 4 > table[3] + table[5]:
                        errors.append(f'EXIDX entry {n}: truncated EXTAB recipe.')
                        state = 'invalid'
                    elif (3 if personality == 0x80 else 2 + 4 * (words - 1)) > 32:
                        state = 'unsupported'
            entries.append((start, state))
    starts = [e[0] for e in entries]
    coverage = []
    for address, length, name in functions:
        i = bisect_right(starts, address) - 1
        state = entries[i][1] if i >= 0 and region(entries[i][0]) == region(address) else 'missing'
        # A recipe ending within a function must also cover its final instruction.
        end_i = bisect_right(starts, address + length - 1) - 1
        if end_i != i:
            state = 'mixed'
        coverage.append(dict(function=name, address=f'0x{address:08x}', unwind=state))
    for name in names:
        matches = [f for f in coverage if f['function'] == name]
        if not matches:
            errors.append(f'{name}: symbol not found; use an exact ELF symbol name and an unstripped executable.')
        elif any(f['unwind'] != 'supported' for f in matches):
            errors.append(f'{name}: no usable recipe throughout the function; rebuild its source/library with -funwind-tables, annotate assembly and retain tables.')
    missing = sum(f['unwind'] != 'supported' for f in coverage)
    if missing:
        warnings.append(f'{missing} functions have missing/unsupported metadata; see function coverage. Rebuild their libraries if these callers matter.')
    symbols = set()
    for s in sections:
        if s[1] != 2:
            continue
        names_s = sections[s[6]]
        symstrings = checked_slice(data, names_s[4], names_s[5])
        for sym in struct.iter_unpack('<IIIBBH', checked_slice(data, s[4], s[5])):
            if sym[5]:
                end = symstrings.find(b'\0', sym[0])
                symbols.add(symstrings[sym[0]:end].decode('utf-8', errors='replace'))
    relevant = {name: name in symbols for name in ('statistical_samples', 'profiler_unwind_tables', 'profiler_stack_bounds')}
    if not relevant['statistical_samples']:
        warnings.append('statistical_samples is absent; verify that capture code is linked and not garbage-collected.')
    if require_unwind:
        for name in ('profiler_unwind_tables', 'profiler_stack_bounds'):
            if not relevant[name]:
                errors.append(f'{name} is absent; link the application hook and enable backtraces.')
    return dict(ok=not errors, errors=errors, warnings=warnings, code_regions=regions,
                symbols=relevant, functions=coverage,
                limitations='Checks table structure and compact personalities, not every opcode or runtime MPU/stack access. ELF sections do not verify the application hook ranges. Inclusion is not stack accuracy.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--function', action='append', default=[], help='Exact ELF symbol to require unwind coverage for; repeatable')
    p.add_argument('--require-unwind', action='store_true')
    p.add_argument('--output', type=Path, help='Optional JSON coverage report')
    args = p.parse_args()
    try:
        result = check(args.elf.read_bytes(), args.function, args.require_unwind)
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + '\n')
        for label in ('errors', 'warnings'):
            for message in result[label]:
                print(('FAIL' if label == 'errors' else 'WARN') + ': ' + message)
        print(('PASS' if result['ok'] else 'FAIL') + ': ELF structural preflight (runtime validation still required)')
        p.exit(0 if result['ok'] else 1)
    except (OSError, ValueError, struct.error) as error:
        p.exit(1, f'FAIL: {error}\n')


if __name__ == '__main__':
    main()
