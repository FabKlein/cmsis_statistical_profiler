/* SPDX-License-Identifier: Apache-2.0
 * Secure SSE-300 MPS3 example: 512 KiB ITCM and 512 KiB DTCM. */
/* Memory layout (addresses increase downward; section sizes depend on the build).
 *
 *         ITCM: 512 KiB                       DTCM: 512 KiB
 * 0x10000000 +---------------------+  0x30000000 +---------------------+
 *            | Interrupt vectors   |             | .data               |
 *            +---------------------+             | Initialized globals |
 *            | .text               |             +---------------------+
 *            | Application and     |             | .bss                |
 *            | profiler code       |             | - Capture buffer    |
 *            +---------------------+             | - Thread PSP stacks |
 *            | .rodata: constants  |             | - Other globals     |
 *            +---------------------+             +---------------------+
 *            | .ARM.extab          |             | Free space          |
 *            | Unwind recipes      |             |                     |
 *            +---------------------+  0x3007C000 +---------------------+
 *            | .ARM.exidx          |             | MSP stack: 16 KiB   |
 *            | Code-to-recipe index|             |          ^          |
 *            +---------------------+             | Grows toward lower  |
 *            | Initial .data image |             | addresses           |
 *            | Copied into DTCM    |             |                     |
 *            +---------------------+             |                     |
 *            | Free space          |             | Initial SP          |
 * 0x10080000 +---------------------+  0x30080000 +---------------------+
 *
 * Region end addresses are exclusive. PSP stacks are separate .bss arrays.
 * See profiler.map for exact section boundaries.
 */
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
    /* Bound executable code separately from constants for caller validation. */
    .text : { __profiler_code_start = .; *(.text*) __profiler_code_end = .; *(.rodata*) } > ITCM
    /* Follow live code with --gc-sections; blanket EXIDX KEEP can retain dead code in GNU ld. */
    .ARM.extab : { __profiler_extab_start = .; *(.ARM.extab*) __profiler_extab_end = .; } > ITCM
    .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > ITCM
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
