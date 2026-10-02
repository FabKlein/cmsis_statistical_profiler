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
 * $Date:        2 October 2026
 * $Revision:    V.1.0.7
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
    #include "profiler_ehabi.h"

/* Immutable linker ranges, validated before sampling starts. Their readability
 * is an application contract; address-range checks cannot detect MPU faults. */
static struct ProfilerUnwindTables tables;

/* Set only after all table/range checks pass; a failed reinit disables unwinding. */
static int ready;

/** @brief Check a bounded address span without overflowing arithmetic. */
static int contains(uintptr_t base, size_t bytes, uintptr_t address, size_t size)
{
    /* Prove the allocation itself does not wrap around the address space. */
    if (!bytes || bytes - 1U > UINTPTR_MAX - base)
        return 0;

    /* Check subtraction operands before computing the requested span's offset. */
    if (size > bytes || address < base)
        return 0;

    return address - base <= bytes - size;
}

/** @brief Validate a nonempty word-aligned table containing whole entries. */
static int valid_table_span(const uint32_t *table, size_t bytes, size_t entry_bytes)
{
    uintptr_t address = (uintptr_t)table;

    if (!table || address % EHABI_WORD_BYTES)
        return 0;

    if (bytes % entry_bytes)
        return 0;

    return contains(address, bytes, address, bytes);
}

/** @brief Resolve a PREL31 (31-bit signed place-relative offset).
 * @details target = address of this word + sign_extend(word[30:0]).
 * Bit 30 is the sign bit; bit 31 is excluded. EHABI uses this for code/table references.
 */
static uintptr_t prel31(const uint32_t *word)
{
    /* PREL31 is relative to this word's address, not the section or image base. */
    uint32_t offset = *word & EHABI_PREL31_OFFSET_MASK;

    if (offset & EHABI_PREL31_SIGN_BIT)
        offset |= EHABI_PREL31_RESERVED_BIT;

    return (uintptr_t)word + (intptr_t)(int32_t)offset;
}

/** @brief Return a 1-based executable-region index, or 0 for an address in no region. */
static size_t code_region(uintptr_t address, size_t bytes)
{
    for (size_t i = 0; i < tables.code_count; ++i)
        if (contains(tables.code[i].base, tables.code[i].bytes, address, bytes))
            return i + 1U;

    return 0;
}

/**
 * @brief Check application-supplied memory ranges before allowing ISR unwinding.
 * @details The application hook supplies linker addresses, not copies of tables.
 * Their storage must remain readable and unchanged throughout capture.
 *
 * Validation order:
 *     hook -> table alignment/sizes -> code allocations -> sorted index -> ready
 *
 * This checks table structure and lookup boundaries, not every unwind recipe.
 * Recipe decoding and stack-read checks happen on demand for each sampled frame.
 */
int profiler_unwind_init(void)
{
    /* Invalidate the previous configuration first, including on reinitialization. */
    ready = 0;
    tables = (struct ProfilerUnwindTables){0};

    /* The index is required. The extension table is optional: compact recipes
     * can fit entirely inside an index entry. */
    if (!profiler_unwind_tables(&tables) || !tables.exidx || !tables.exidx_bytes)
        return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MISSING_TABLES, 0, 0);

    /* A bounded code-region list is required before checking index addresses. */
    if (!tables.code || !tables.code_count || tables.code_count > PROFILER_MAX_CODE_REGIONS)
        return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, 0, 0);

    /* EXIDX must contain whole 2-word entries. Validate before dereferencing it;
     * address arithmetic alone cannot establish MPU access permissions. */
    if (!valid_table_span(tables.exidx, tables.exidx_bytes, EXIDX_ENTRY_BYTES))
        return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, 0, 0);

    /* An absent EXTAB is valid when all recipes fit in EXIDX. If present, it
     * must contain whole words; individual recipe lengths are checked later. */
    if (tables.extab_bytes && !valid_table_span(tables.extab, tables.extab_bytes, EHABI_WORD_BYTES))
        return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, 0, 0);

    /* Executable allocations must be ordered and non-overlapping. Keeping each
     * allocation separate prevents a recipe from covering an unmapped code gap. */
    for (size_t i = 0; i < tables.code_count; ++i)
    {
        const struct ProfilerCodeRegion *r = &tables.code[i];

        if (!r->bytes || r->base % THUMB_CODE_ALIGNMENT)
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_INVALID_CONFIG, (uint32_t)i, 0);

        /* The exclusive end must be representable before checking overlap. */
        if (r->bytes > UINTPTR_MAX - r->base)
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_INVALID_CONFIG, (uint32_t)i, 0);

        if (i && r->base < tables.code[i - 1U].base + tables.code[i - 1U].bytes)
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_INVALID_CONFIG, (uint32_t)i, 0);
    }

    /* Sorted starts permit binary search in the ISR. A terminal entry may point
     * just beyond executable code; it marks a boundary, not a callable address. */
    uintptr_t previous = 0;

    for (size_t i = 0; i < tables.exidx_bytes / EXIDX_ENTRY_BYTES; ++i)
    {
        uintptr_t address = prel31(tables.exidx + EXIDX_ENTRY_WORDS * i);

        /* Index starts are even instruction addresses encoded as PREL31; bit 31
         * must be clear. A zero-sized lookup permits an allocation-end sentinel. */
        if (tables.exidx[EXIDX_ENTRY_WORDS * i] & EHABI_PREL31_RESERVED_BIT)
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, (uint32_t)i, 0);

        if (address % THUMB_CODE_ALIGNMENT || !code_region(address, 0))
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, (uint32_t)i, 0);

        if (i && address <= previous)
            return profiler_init_fail(PROFILER_INIT_UNWIND, PROFILER_INIT_MALFORMED_TABLES, (uint32_t)i, 0);

        previous = address;
    }

    /* Publish readiness only after the full index has passed validation. */
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
    size_t lo = 0, hi = tables.exidx_bytes / EXIDX_ENTRY_BYTES;

    /* Find the last range start at or before PC, rather than an exact symbol match. */
    while (lo < hi)
    {
        size_t mid = lo + (hi - lo) / 2U;

        if (prel31(tables.exidx + EXIDX_ENTRY_WORDS * mid) <= pc)
            lo = mid + 1U;
        else
            hi = mid;
    }

    if (!lo)
        return PROFILER_UNWIND_NO_TABLE;

    /* A recipe from another allocation must not bleed across a code gap,
     * even when the linker omitted an explicit CANTUNWIND boundary. */
    const uint32_t *index_entry = tables.exidx + EXIDX_ENTRY_WORDS * (lo - 1U);
    uintptr_t range_start = prel31(index_entry);

    if (code_region(range_start, 2U) != code_region(pc, 2U))
        return PROFILER_UNWIND_NO_TABLE;

    /* The second index word selects no recipe, an inline recipe, or EXTAB. */
    const uint32_t *entry = index_entry + 1U;
    uint32_t word = *entry;

    if (word == EHABI_EXIDX_CANTUNWIND)
        return PROFILER_UNWIND_NO_TABLE;

    /* Compact 0 packs 3 opcode bytes after its tag. Compact 1/2 reserve
     * another byte for extension length. Generic personality code is never run. */
    uint32_t words = 1U, first_bytes = EHABI_COMPACT_SHORT_OPCODE_BYTES;

    if (!(word & EHABI_COMPACT_BIT))
    {
        entry = (const uint32_t *)prel31(entry);
        if (((uintptr_t)entry % EHABI_WORD_BYTES) ||
            !contains((uintptr_t)tables.extab, tables.extab_bytes, (uintptr_t)entry, EHABI_WORD_BYTES))
            return PROFILER_UNWIND_UNSUPPORTED;

        /* Bits 31:24 identify the compact personality; see the header diagram
         * in profiler_ehabi.h before interpreting the remaining bytes. */
        word = *entry;
        uint32_t tag = word >> EHABI_COMPACT_TAG_SHIFT;

        if (tag == EHABI_COMPACT_PERSONALITY_1 || tag == EHABI_COMPACT_PERSONALITY_2)
        {
            /* Bits 23:16 count additional words, leaving only the low 2 bytes
             * of this header word for opcodes. Include the header in total size. */
            uint32_t extra_words = (word >> EHABI_COMPACT_EXTRA_WORDS_SHIFT) & EHABI_COMPACT_EXTRA_WORDS_MASK;

            words += extra_words;
            first_bytes = EHABI_COMPACT_LONG_OPCODE_BYTES;
        }
        else if (tag != EHABI_COMPACT_PERSONALITY_0)
            return PROFILER_UNWIND_UNSUPPORTED;

        /* Limit ISR decoding work and prove every extension word is in bounds. */
        if (words > 8U ||
            !contains((uintptr_t)tables.extab, tables.extab_bytes, (uintptr_t)entry, words * EHABI_WORD_BYTES))
            return PROFILER_UNWIND_UNSUPPORTED;
    }
    else if ((word >> EHABI_COMPACT_TAG_SHIFT) != EHABI_COMPACT_PERSONALITY_0)
        return PROFILER_UNWIND_UNSUPPORTED;

    /* Opcode order is MSB first within each word, even on little-endian targets. */
    *length = 0;

    for (uint32_t i = 0; i < words; ++i)
    {
        word = entry[i];
        for (uint32_t n = i ? EHABI_WORD_BYTES : first_bytes; n; --n)
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
    uint32_t cursor = regs[EHABI_SP_IDX];

    for (uint32_t reg = 0; reg < 16U; ++reg)
    {
        if (!(mask & (1U << reg)))
            continue;

        if (!valid_sp(cursor, bounds))
            return 0;

        /* A legal SP may point at the stack end, where no saved word is readable. */
        if (!contains(bounds->base, bounds->bytes, cursor, EHABI_WORD_BYTES))
            return 0;

        if (cursor > UINT32_MAX - EHABI_WORD_BYTES)
            return 0;

        regs[reg] = *(const uint32_t *)(uintptr_t)cursor;
        cursor += 4U;
    }

    /* Prefer an explicitly restored SP; otherwise advance beyond the save area. */
    if (!(mask & (1U << EHABI_SP_IDX)))
        regs[EHABI_SP_IDX] = cursor;

    return valid_sp(regs[EHABI_SP_IDX], bounds);
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

        /* Each opcode modifies virtual SP or selects registers to restore.
         * Reserved/unsupported encodings stop this trace; never guess a layout. */
        if (op <= EHABI_OP_ADJUST_SP_LAST)
        {
            uint32_t amount = ((op & 0x3FU) << 2) + 4U;

            if (op & 0x40U)
            {
                if (regs[EHABI_SP_IDX] < amount)
                    return PROFILER_UNWIND_BOUNDS;

                regs[EHABI_SP_IDX] -= amount;
            }
            else
                add = amount;
        }
        /* A 2-byte register mask describes a saved subset of r4-r15. */
        else if (op <= EHABI_OP_POP_MASK_LAST)
        {
            if (++i >= length)
                return PROFILER_UNWIND_UNSUPPORTED;

            mask = (((op & 15U) << 8) | bytes[i]) << 4;
            if (!mask)
                return PROFILER_UNWIND_UNSUPPORTED;
        }
        /* Frame-pointer-style recipes recover SP from another core register. */
        else if (op <= EHABI_OP_SET_SP_LAST)
        {
            uint32_t reg = op & 15U;

            if (reg == EHABI_SP_IDX || reg == EHABI_PC_IDX)
                return PROFILER_UNWIND_UNSUPPORTED;

            regs[EHABI_SP_IDX] = regs[reg];
        }
        /* A compact contiguous save of r4 upwards, optionally including LR. */
        else if (op <= EHABI_OP_POP_RANGE_LAST)
        {
            mask = ((1U << ((op & 7U) + 1U)) - 1U) << 4;
            if (op & 8U)
                mask |= 1U << EHABI_LR_IDX;
        }
        else if (op == EHABI_OP_FINISH)
            break;
        /* Some recipes also restore low registers r0-r3. */
        else if (op == EHABI_OP_POP_LOW_REGS)
        {
            if (++i >= length)
                return PROFILER_UNWIND_UNSUPPORTED;

            if (!bytes[i] || (bytes[i] & 0xF0U))
                return PROFILER_UNWIND_UNSUPPORTED;

            mask = bytes[i];
        }
        /* Variable-length stack adjustments need a separate bound against
         * unterminated ULEB128 (unsigned base-128) values and overflowing arithmetic. */
        else if (op == EHABI_OP_LARGE_SP_INCREMENT)
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
        else if (op == EHABI_OP_POP_VFP_FSTMFDX || op == EHABI_OP_POP_VFP_D16 || op == EHABI_OP_POP_VFP_D0)
        {
            if (++i >= length)
                return PROFILER_UNWIND_UNSUPPORTED;

            uint32_t first_register = bytes[i] >> 4;
            uint32_t extra_registers = bytes[i] & 15U;

            if (first_register + extra_registers > 15U)
                return PROFILER_UNWIND_UNSUPPORTED;

            add = 8U * (extra_registers + 1U) + (op == EHABI_OP_POP_VFP_FSTMFDX ? 4U : 0U);
        }
        else if ((op & EHABI_OP_VFP_RANGE_MASK) == EHABI_OP_POP_VFP_RANGE_FSTMFDX ||
                 (op & EHABI_OP_VFP_RANGE_MASK) == EHABI_OP_POP_VFP_RANGE)
            add = 8U * ((op & 7U) + 1U) + ((op & EHABI_OP_VFP_RANGE_MASK) == EHABI_OP_POP_VFP_RANGE_FSTMFDX ? 4U : 0U);
        else
            return PROFILER_UNWIND_UNSUPPORTED;

        /* Apply the deferred adjustment, then validate SP before any pop reads. */
        if (add > UINT32_MAX - regs[EHABI_SP_IDX])
            return PROFILER_UNWIND_BOUNDS;

        regs[EHABI_SP_IDX] += add;
        if (!valid_sp(regs[EHABI_SP_IDX], bounds))
            return PROFILER_UNWIND_BOUNDS;

        if (mask && !pop(regs, mask, bounds))
            return PROFILER_UNWIND_BOUNDS;

        if (mask & (1U << EHABI_PC_IDX))
            pc_restored = 1;
    }

    /* EHABI finish uses LR unless a recipe explicitly restored PC. */
    if (!pc_restored)
        regs[EHABI_PC_IDX] = regs[EHABI_LR_IDX];

    return PROFILER_UNWIND_COMPLETE;
}

void profiler_unwind_capture(struct ProfilerSample *sample, uint32_t regs[16], const struct ProfilerStackBounds *bounds)
{
    uint32_t depth = 0, status = PROFILER_UNWIND_DEPTH_LIMIT;
    int valid_start = ready && bounds->bytes && bounds->bytes <= UINTPTR_MAX - bounds->base;

    /* Only recovered callers are initialized; storage reads the reported depth. */
    if (!valid_start || !valid_sp(regs[EHABI_SP_IDX], bounds))
        status = PROFILER_UNWIND_BOUNDS;
    else
        for (; depth < PROFILER_UNWIND_MAX_DEPTH; ++depth)
        {
            uint32_t old_sp = regs[EHABI_SP_IDX], old_pc = regs[EHABI_PC_IDX] & ~1U;
            uint32_t lookup = old_pc;

            /* The initial PC is an interrupted instruction. Later PCs are return
             * addresses: -2 places lookup inside the call, not the next function. */
            if (depth && lookup >= 2U)
                lookup -= 2U;
            if (!code_region(lookup, 2U))
            {
                status = PROFILER_UNWIND_INVALID_PC;
                break;
            }

            /* Interpret 1 frame; failures retain only already committed callers. */
            status = step(regs, bounds, lookup);
            if (status)
                break;

            /* Leaf frames may leave SP unchanged; recursion may repeat PC.
             * Neither alone proves a loop. Downward movement is not a caller. */
            if (regs[EHABI_SP_IDX] < old_sp)
            {
                status = PROFILER_UNWIND_NO_PROGRESS;
                break;
            }

            if (!regs[EHABI_PC_IDX])
                break; /* Explicit zero return address terminates the chain. */

            /* Recovered return addresses must carry the Thumb bit. */
            uint32_t pc = regs[EHABI_PC_IDX] & ~1U;

            if (!(regs[EHABI_PC_IDX] & 1U) || pc < 2U)
            {
                status = PROFILER_UNWIND_INVALID_PC;
                break;
            }

            /* Subtract only after the lower-bound check; lookup must stay in code. */
            if (!code_region(pc - 2U, 2U))
            {
                status = PROFILER_UNWIND_INVALID_PC;
                break;
            }

            if (regs[EHABI_SP_IDX] == old_sp && pc == old_pc)
            {
                status = PROFILER_UNWIND_NO_PROGRESS;
                break;
            }

            /* Commit only a checked frame; a later failure preserves this prefix.
             * Executable addresses still cannot prove an interrupted prologue valid. */
            sample->callers[depth] = regs[EHABI_PC_IDX];
        }

    /* The low byte counts initialized caller slots; the next byte explains
     * termination. A partial chain is useful even when the next frame fails. */
    if (depth == PROFILER_UNWIND_MAX_DEPTH)
        status = PROFILER_UNWIND_DEPTH_LIMIT;

    sample->unwind = depth | (status << 8);
}
#endif
