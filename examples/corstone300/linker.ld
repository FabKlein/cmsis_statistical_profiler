/* SPDX-License-Identifier: Apache-2.0
 * Secure SSE-300 MPS3 example: 512 KiB ITCM and 512 KiB DTCM. */
ENTRY(Reset_Handler)
MEMORY
{
    ITCM (rx)  : ORIGIN = 0x10000000, LENGTH = 512K
    DTCM (rwx) : ORIGIN = 0x30000000, LENGTH = 512K
}
__StackTop = ORIGIN(DTCM) + LENGTH(DTCM);
__StackLimit = __StackTop - 16K;
SECTIONS
{
    .vectors : { KEEP(*(.vectors)) } > ITCM
    .text : { *(.text*) *(.rodata*) } > ITCM
    .ARM.extab : { *(.ARM.extab*) } > ITCM
    .ARM.exidx : { *(.ARM.exidx*) } > ITCM
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
    ASSERT(__bss_end__ <= __StackLimit, "Data overlaps the reserved stack")
}
