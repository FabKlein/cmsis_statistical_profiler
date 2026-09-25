/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        sampling_profiler_unwind.c
 * Description:  Bounded compact EHABI stack tracing
 *
 * $Date:        24 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/** @file sampling_profiler_unwind.c
 * @brief Best-effort EHABI compact personalities 0/1/2; never execute personality routines.
 * @details Tables describe call sites, not every instruction. Bounds checks cannot
 * identify all plausible but incorrect traces sampled inside prologues/epilogues.
 * Encoding reference: https://github.com/ARM-software/abi-aa/blob/main/ehabi32/ehabi32.rst
 *
 * @code
 * Init: validate/cache linker code + EHABI table ranges
 *                         |
 * Sample: interrupted registers + precise stack bounds
 *                         |
 *                         v
 *              Virtual PC/SP/LR + registers <----------------+
 *                         |                                  |
 *              Find PC range in .ARM.exidx                   |
 *                         |                                  |
 *              Decode inline / .ARM.extab recipe             |
 *                         |                                  |
 *              Apply recipe to virtual registers             |
 *              (bounded stack reads; no live-state writes)   |
 *                         |                                  |
 *              Check caller address and stack progress       |
 *                         |                                  |
 *              Append caller; continue within depth limit ---+
 *
 * Stop: end / unsupported / invalid / depth limit
 *       -> keep recovered caller prefix + depth/status
 * @endcode
 */
#include "sampling_profiler_unwind.h"

#if PROFILER_STACK_UNWIND
/* Immutable linker ranges, validated before sampling starts. Their readability
 * is an application contract; address-range checks cannot detect MPU faults. */
static struct ProfilerUnwindTables tables;
static int ready;

/** @brief Check a bounded address span without overflowing arithmetic. */
static int contains(uintptr_t base, size_t bytes, uintptr_t address, size_t size)
{
    return bytes && bytes - 1U <= UINTPTR_MAX - base && size <= bytes && address >= base &&
        address - base <= bytes - size;
}

/** @brief Resolve a PREL31 (31-bit signed place-relative offset).
 * @details target = address of this word + sign_extend(word[30:0]).
 * Bit 30 is the sign bit; bit 31 is excluded. EHABI uses this for code/table references.
 */
static uintptr_t prel31(const uint32_t *word)
{
    /* PREL31 is relative to this word's address, not the section or image base. */
    uint32_t offset = *word & 0x7FFFFFFFU;
    if (offset & 0x40000000U)
        offset |= 0x80000000U;
    return (uintptr_t)word + (intptr_t)(int32_t)offset;
}

int profiler_unwind_init(void)
{
    ready = 0;
    tables = (struct ProfilerUnwindTables){0};
    if (!profiler_unwind_tables(&tables) || !tables.code_bytes || tables.code_bytes > UINTPTR_MAX - tables.code_base ||
        !tables.exidx || ((uintptr_t)tables.exidx & 3U) || !tables.exidx_bytes || (tables.exidx_bytes & 7U) ||
        !contains((uintptr_t)tables.exidx, tables.exidx_bytes, (uintptr_t)tables.exidx, tables.exidx_bytes) ||
        (tables.extab_bytes &&
         (!tables.extab || ((uintptr_t)tables.extab & 3U) || (tables.extab_bytes & 3U) ||
          !contains((uintptr_t)tables.extab, tables.extab_bytes, (uintptr_t)tables.extab, tables.extab_bytes))))
        return 0;
    /* Sorted starts permit binary search in the ISR. A terminal entry may point
     * just beyond executable code; it marks a boundary, not a callable address. */
    uintptr_t previous = 0;
    for (size_t i = 0; i < tables.exidx_bytes / 8U; ++i)
    {
        uintptr_t address = prel31(tables.exidx + 2U * i);
        if ((tables.exidx[2U * i] & 0x80000000U) || (address & 1U) || address < tables.code_base ||
            address - tables.code_base > tables.code_bytes || (i && address <= previous))
            return 0;
        previous = address;
    }
    ready = 1;
    return 1;
}

/** @brief Read a compact recipe into a bounded byte array, MSB first.
 * @details Index entries cover address ranges; the linker may merge equal recipes.
 * @code
 * .ARM.exidx entry (2 words)
 * +----------------------+--------------------------------+
 * | PREL31: range start  | 1: cannot unwind               |
 * |                      | or inline compact recipe       |
 * |                      | or PREL31 -> .ARM.extab recipe  |
 * +----------------------+--------------------------------+
 * @endcode
 */
static uint32_t recipe(uint32_t pc, uint8_t bytes[32], uint32_t *length)
{
    size_t lo = 0, hi = tables.exidx_bytes / 8U;
    while (lo < hi)
    {
        size_t mid = lo + (hi - lo) / 2U;
        if (prel31(tables.exidx + 2U * mid) <= pc)
            lo = mid + 1U;
        else
            hi = mid;
    }
    if (!lo)
        return PROFILER_UNWIND_NO_TABLE;
    const uint32_t *entry = tables.exidx + 2U * (lo - 1U) + 1U;
    uint32_t word = *entry;
    if (word == 1U)
        return PROFILER_UNWIND_NO_TABLE;
    /* Compact 0 packs 3 opcode bytes after its tag. Compact 1/2 reserve
     * another byte for extension length. Generic personality code is never run. */
    uint32_t words = 1U, first_bytes = 3U;
    if (!(word & 0x80000000U))
    {
        entry = (const uint32_t *)prel31(entry);
        if (((uintptr_t)entry & 3U) || !contains((uintptr_t)tables.extab, tables.extab_bytes, (uintptr_t)entry, 4U))
            return PROFILER_UNWIND_UNSUPPORTED;
        word = *entry;
        if ((word >> 24) == 0x81U || (word >> 24) == 0x82U)
        {
            words += (word >> 16) & 0xFFU;
            first_bytes = 2U;
        }
        else if ((word >> 24) != 0x80U)
            return PROFILER_UNWIND_UNSUPPORTED;
        if (words > 8U || !contains((uintptr_t)tables.extab, tables.extab_bytes, (uintptr_t)entry, words * 4U))
            return PROFILER_UNWIND_UNSUPPORTED;
    }
    else if ((word >> 24) != 0x80U)
        return PROFILER_UNWIND_UNSUPPORTED;
    /* Opcode order is MSB first within each word, even on little-endian targets. */
    *length = 0;
    for (uint32_t i = 0; i < words; ++i)
    {
        word = entry[i];
        for (uint32_t n = i ? 4U : first_bytes; n; --n)
            bytes[(*length)++] = (uint8_t)(word >> ((n - 1U) * 8U));
    }
    return PROFILER_UNWIND_COMPLETE;
}

/** @brief Check the virtual SP, allowing the allocation's exclusive end. */
static int valid_sp(uint32_t sp, const struct ProfilerStackBounds *bounds)
{
    return !(sp & 3U) && contains(bounds->base, bounds->bytes, sp, 0);
}

/** @brief Pop core registers with checked reads, including EHABI's restored-SP rule. */
static int pop(uint32_t regs[16], uint32_t mask, const struct ProfilerStackBounds *bounds)
{
    /* A saved SP can be among the popped registers. It must not redirect reads
     * of later registers: all slots belong to the original contiguous save area. */
    uint32_t cursor = regs[13];
    for (uint32_t reg = 0; reg < 16U; ++reg)
    {
        if (!(mask & (1U << reg)))
            continue;
        if (!valid_sp(cursor, bounds) || !contains(bounds->base, bounds->bytes, cursor, 4U) || cursor > UINT32_MAX - 4U)
            return 0;
        regs[reg] = *(const uint32_t *)(uintptr_t)cursor;
        cursor += 4U;
    }
    if (!(mask & (1U << 13)))
        regs[13] = cursor;
    return valid_sp(regs[13], bounds);
}

/** @brief Interpret a compact recipe; VFP saves are skipped using integer arithmetic.
 * @details regs[] is virtual state, not the live CPU or hardware exception frame.
 * The recipe reverses a function's stack effects to recover its caller:
 *
 *     callee SP -> [locals / saved registers] -> caller SP
 *     saved LR (or live LR for a leaf)        -> caller PC
 *
 * A failed step may leave partial virtual state; the caller stops immediately.
 */
static uint32_t step(uint32_t regs[16], const struct ProfilerStackBounds *bounds, uint32_t pc)
{
    uint8_t bytes[32];
    uint32_t length = 0, status = recipe(pc, bytes, &length);
    if (status)
        return status;
    int pc_restored = 0;
    for (uint32_t i = 0; i < length; ++i)
    {
        uint32_t op = bytes[i], mask = 0, add = 0;
        if (op <= 0x7FU)
        {
            uint32_t amount = ((op & 0x3FU) << 2) + 4U;
            if (op & 0x40U)
            {
                if (regs[13] < amount)
                    return PROFILER_UNWIND_BOUNDS;
                regs[13] -= amount;
            }
            else
                add = amount;
        }
        else if (op <= 0x8FU)
        {
            if (++i >= length)
                return PROFILER_UNWIND_UNSUPPORTED;
            mask = (((op & 15U) << 8) | bytes[i]) << 4;
            if (!mask)
                return PROFILER_UNWIND_UNSUPPORTED;
        }
        else if (op <= 0x9FU)
        {
            uint32_t reg = op & 15U;
            if (reg == 13U || reg == 15U)
                return PROFILER_UNWIND_UNSUPPORTED;
            regs[13] = regs[reg];
        }
        else if (op <= 0xAFU)
        {
            mask = ((1U << ((op & 7U) + 1U)) - 1U) << 4;
            if (op & 8U)
                mask |= 1U << 14;
        }
        else if (op == 0xB0U)
            break;
        else if (op == 0xB1U)
        {
            if (++i >= length || !bytes[i] || (bytes[i] & 0xF0U))
                return PROFILER_UNWIND_UNSUPPORTED;
            mask = bytes[i];
        }
        /* Variable-length stack adjustments need a separate bound against
         * unterminated ULEB128 values and overflowing arithmetic. */
        else if (op == 0xB2U)
        {
            uint32_t value = 0, shift = 0;
            do
            {
                if (++i >= length || shift > 21U)
                    return PROFILER_UNWIND_UNSUPPORTED;
                value |= (bytes[i] & 0x7FU) << shift;
                shift += 7U;
            } while (bytes[i] & 0x80U);
            add = 0x204U + (value << 2);
        }
        /* Only their stack footprint matters here. Legacy FSTMFDX saves have
         * an extra 4-byte format word; no floating-point state is loaded. */
        else if (op == 0xB3U || op == 0xC8U || op == 0xC9U)
        {
            if (++i >= length || (bytes[i] >> 4) + (bytes[i] & 15U) > 15U)
                return PROFILER_UNWIND_UNSUPPORTED;
            add = 8U * ((bytes[i] & 15U) + 1U) + (op == 0xB3U ? 4U : 0U);
        }
        else if ((op & 0xF8U) == 0xB8U || (op & 0xF8U) == 0xD0U)
            add = 8U * ((op & 7U) + 1U) + ((op & 0xF8U) == 0xB8U ? 4U : 0U);
        else
            return PROFILER_UNWIND_UNSUPPORTED;
        if (add > UINT32_MAX - regs[13])
            return PROFILER_UNWIND_BOUNDS;
        regs[13] += add;
        if (!valid_sp(regs[13], bounds) || (mask && !pop(regs, mask, bounds)))
            return PROFILER_UNWIND_BOUNDS;
        if (mask & (1U << 15))
            pc_restored = 1;
    }
    /* EHABI finish uses LR unless a recipe explicitly restored PC. */
    if (!pc_restored)
        regs[15] = regs[14];
    return PROFILER_UNWIND_COMPLETE;
}

void profiler_unwind_capture(struct ProfilerSample *sample, uint32_t regs[16], const struct ProfilerStackBounds *bounds)
{
    uint32_t depth = 0, status = PROFILER_UNWIND_DEPTH_LIMIT;
    /* Volatile stores prevent replacement with an out-of-line libc clear. */
    volatile uint32_t *callers = sample->callers;
    for (uint32_t i = 0; i < PROFILER_UNWIND_MAX_DEPTH; ++i)
        callers[i] = 0;
    if (!ready || !bounds->bytes || bounds->bytes > UINTPTR_MAX - bounds->base || !valid_sp(regs[13], bounds))
        status = PROFILER_UNWIND_BOUNDS;
    else
        for (; depth < PROFILER_UNWIND_MAX_DEPTH; ++depth)
        {
            uint32_t old_sp = regs[13], old_pc = regs[15] & ~1U;
            uint32_t lookup = old_pc;
            /* The initial PC is an interrupted instruction. Later PCs are return
             * addresses: -2 places lookup inside the call, not the next function. */
            if (depth && lookup >= 2U)
                lookup -= 2U;
            if (!contains(tables.code_base, tables.code_bytes, lookup, 2U))
            {
                status = PROFILER_UNWIND_INVALID_PC;
                break;
            }
            status = step(regs, bounds, lookup);
            if (status)
                break;
            /* Leaf frames may leave SP unchanged; recursion may repeat PC.
             * Neither alone proves a loop. Downward movement is not a caller. */
            if (regs[13] < old_sp)
            {
                status = PROFILER_UNWIND_NO_PROGRESS;
                break;
            }
            if (!regs[15])
                break; /* Explicit zero return address terminates the chain. */
            uint32_t pc = regs[15] & ~1U;
            if (!(regs[15] & 1U) || pc < 2U || !contains(tables.code_base, tables.code_bytes, pc - 2U, 2U))
            {
                status = PROFILER_UNWIND_INVALID_PC;
                break;
            }
            if (regs[13] == old_sp && pc == old_pc)
            {
                status = PROFILER_UNWIND_NO_PROGRESS;
                break;
            }
            /* Commit only a checked frame; a later failure preserves this prefix.
             * Executable addresses still cannot prove an interrupted prologue valid. */
            sample->callers[depth] = regs[15];
        }
    if (depth == PROFILER_UNWIND_MAX_DEPTH)
        status = PROFILER_UNWIND_DEPTH_LIMIT;
    sample->unwind = depth | (status << 8);
}
#endif
