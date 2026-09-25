/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_unwind.h
 * Description:  Bounded EHABI stack tracing interface
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/** @file sampling_profiler_unwind.h
 * @brief Optional compact EHABI stack tracing, independent of the board and RTOS.
 */
#ifndef PROFILER_UNWIND_H
#define PROFILER_UNWIND_H
#include "sampling_profiler_cortex_m.h"

/** @brief 1 executable allocation; gaps between allocations are never executable. */
struct ProfilerCodeRegion
{
    uintptr_t base; /**< Execution address, not the load-image address. */
    size_t bytes;   /**< Nonzero size, excluding the end. */
};
/** @brief Bound the region search cost in the sampling ISR. */
#define PROFILER_MAX_CODE_REGIONS 8U

/** @brief Application-owned, immutable, CPU-readable code and unwind table ranges. */
struct ProfilerUnwindTables
{
    const struct ProfilerCodeRegion *code; /**< Immutable regions sorted by address, without overlap. */
    size_t code_count;                     /**< 1..PROFILER_MAX_CODE_REGIONS; independent of table placement. */
    const uint32_t *exidx;                 /**< Sorted .ARM.exidx table, 2 words per entry. */
    size_t exidx_bytes;                    /**< Table size; includes any linker-generated end sentinel. */
    const uint32_t *extab;                 /**< Optional .ARM.extab range, NULL if empty. */
    size_t extab_bytes;                    /**< Readable size of .ARM.extab. */
};
#ifdef __cplusplus
extern "C" {
#endif
/** @brief Supply linker-derived ranges at initialization, returning 1 on success.
 * @warning Application must ensure these ranges are readable and remain immutable.
 * No board addresses or toolchain-specific linker symbols belong in the unwinder.
 */
int profiler_unwind_tables(struct ProfilerUnwindTables *tables);
/** @brief Validate and cache table ranges; called before sampling starts. */
int profiler_unwind_init(void);
/** @brief Append at most PROFILER_UNWIND_MAX_DEPTH callers, preserving the valid prefix on failure.
 * @param sample Validated PC sample; backtrace fields are overwritten.
 * @param regs Interrupted r0-r15 virtual registers, updated during unwinding.
 * @param bounds Precise task/MSP allocation intersected with the RAM whitelist.
 * @note Integer-only, no allocation; at most 32 opcode bytes per frame.
 */
void profiler_unwind_capture(struct ProfilerSample *sample,
                             uint32_t regs[16],
                             const struct ProfilerStackBounds *bounds);
#ifdef __cplusplus
}
#endif
#endif
