/* SPDX-License-Identifier: Apache-2.0
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 * GCC/LLD split-code example, selected by build.py --call-tree --split-code.
 * Execution: ITCM 0x10000000 [vectors, A-E, tables] ... gap ... SRAM 0x11000000 [F].
 * Load: all initialized bytes in ITCM; startup copies .sram_text to SRAM.
 * Data/stacks: DTCM 0x30000000. Use the application's own map on other targets.
 */
ENTRY(Reset_Handler)
MEMORY
{
    ITCM (rx)  : ORIGIN = 0x10000000, LENGTH = 512K
    SRAM (rx) : ORIGIN = 0x11000000, LENGTH = 1M
    DTCM (rwx) : ORIGIN = 0x30000000, LENGTH = 512K
}
__StackTop = ORIGIN(DTCM) + LENGTH(DTCM);
__StackLimit = __StackTop - 16K;
SECTIONS
{
    .vectors : { KEEP(*(.vectors)) } > ITCM
    /* Bound executable code separately from constants for caller validation. */
    .text : { __profiler_code_start = .; *(.text*) __profiler_code_end = .; *(.rodata*) } > ITCM
    .sram_text : ALIGN(4)
    {
        __sram_text_start = .;
        *(.sram_text)
        . = ALIGN(4);
        __sram_text_end = .;
    } > SRAM AT > ITCM
    __sram_text_load = LOADADDR(.sram_text);
    /* Keep EHABI recipes/index with --gc-sections; unwind_tables.c exports these ranges. */
    .ARM.extab : { __profiler_extab_start = .; KEEP(*(.ARM.extab*)) __profiler_extab_end = .; } > ITCM
    .ARM.exidx : { __exidx_start = .; KEEP(*(.ARM.exidx*)) __exidx_end = .; } > ITCM
    .data : ALIGN(4)
    {
        __data_start__ = .;
        *(.data*)
        . = ALIGN(4);
        __data_end__ = .;
    } > DTCM AT > ITCM
    __data_load__ = LOADADDR(.data);
    .bss (NOLOAD) : ALIGN(32)
    {
        __bss_start__ = .;
        *(.bss*) *(COMMON)
        . = ALIGN(4);
        __bss_end__ = .;
    } > DTCM
    PROVIDE(end = __bss_end__); /* Optional unwind runtime may reference the libc heap base. */
    ASSERT(__bss_end__ <= __StackLimit, "Data overlaps the reserved stack")
}
