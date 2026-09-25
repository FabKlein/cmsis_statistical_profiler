/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        unwind_tables.c
 * Description:  Linker unwind table ranges for the Corstone-300 example
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/** @file unwind_tables.c
 * @brief Example linker integration for the generic EHABI unwinder.
 */
#include "sampling_profiler_unwind.h"

#if defined(__ARMCC_VERSION)
extern const uint32_t code_start[] __asm("Image$$ER_ITCM$$Base");
extern const uint32_t code_end[] __asm("Image$$ER_ITCM$$Limit");
extern const uint32_t index_start[] __asm("Image$$ER_EXIDX$$Base");
extern const uint32_t index_end[] __asm("Image$$ER_EXIDX$$Limit");
extern const uint32_t table_start[] __asm("Image$$ER_EXTAB$$Base");
extern const uint32_t table_end[] __asm("Image$$ER_EXTAB$$Limit");
#else
extern const uint32_t __profiler_code_start[], __profiler_code_end[];
extern const uint32_t __exidx_start[], __exidx_end[];
extern const uint32_t __profiler_extab_start[], __profiler_extab_end[];
    #define code_start __profiler_code_start
    #define code_end __profiler_code_end
    #define index_start __exidx_start
    #define index_end __exidx_end
    #define table_start __profiler_extab_start
    #define table_end __profiler_extab_end
#endif

#if PROFILER_EXAMPLE_SPLIT_CODE
    #if defined(__ARMCC_VERSION)
extern const uint32_t sram_start[] __asm("Image$$ER_SRAM$$Base");
extern const uint32_t sram_end[] __asm("Image$$ER_SRAM$$Limit");
    #else
extern const uint32_t __sram_text_start[], __sram_text_end[];
        #define sram_start __sram_text_start
        #define sram_end __sram_text_end
    #endif
#endif

/** @brief Report read-only ranges from this example's linker layout. */
int profiler_unwind_tables(struct ProfilerUnwindTables *tables)
{
    static struct ProfilerCodeRegion code[2];
    code[0] = (struct ProfilerCodeRegion){(uintptr_t)code_start, (uintptr_t)code_end - (uintptr_t)code_start};
    tables->code = code;
    tables->code_count = 1;
#if PROFILER_EXAMPLE_SPLIT_CODE
    code[1] = (struct ProfilerCodeRegion){(uintptr_t)sram_start, (uintptr_t)sram_end - (uintptr_t)sram_start};
    tables->code_count = 2;
#endif
    tables->exidx = index_start;
    tables->exidx_bytes = (uintptr_t)index_end - (uintptr_t)index_start;
    tables->extab = table_start;
    tables->extab_bytes = (uintptr_t)table_end - (uintptr_t)table_start;
    return 1;
}
