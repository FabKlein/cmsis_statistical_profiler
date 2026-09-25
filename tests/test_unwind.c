/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        test_unwind.c
 * Description:  Bounded compact EHABI unwinder regression tests
 *
 * $Date:        24 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include "sampling_profiler_unwind.h"
#include <assert.h>
#include <string.h>

static uint32_t index_words[6], extra[10], stack[512];
static struct ProfilerSample sample;
static uint32_t regs[16];
static struct ProfilerStackBounds bounds;
static int bad_tables;

static uint32_t relative(const uint32_t *word, uintptr_t target)
{
    return (uint32_t)(target - (uintptr_t)word) & 0x7FFFFFFFU;
}
int profiler_unwind_tables(struct ProfilerUnwindTables *tables)
{
    *tables = (struct ProfilerUnwindTables){
        0x10001000U, 0x3000U, index_words, bad_tables ? 7U : sizeof(index_words), extra, sizeof(extra)};
    return 1;
}
static void reset(uint32_t recipe)
{
    memset(stack, 0, sizeof(stack));
    memset(regs, 0, sizeof(regs));
    memset(&sample, 0, sizeof(sample));
    memset(extra, 0, sizeof(extra));
    index_words[0] = relative(index_words, 0x10001000U);
    index_words[1] = recipe;
    index_words[2] = relative(index_words + 2, 0x10002000U);
    index_words[3] = 0x808400B0U; /* pop LR; finish */
    index_words[4] = relative(index_words + 4, 0x10004000U);
    index_words[5] = 1U;
    assert(profiler_unwind_init());
    assert((uintptr_t)stack <= UINT32_MAX);
    bounds = (struct ProfilerStackBounds){(uintptr_t)stack, sizeof(stack)};
    regs[13] = (uint32_t)(uintptr_t)stack;
    regs[14] = 0x10002005U;
    regs[15] = 0x10001004U;
}
static void expect(uint32_t depth, uint32_t status)
{
    profiler_unwind_capture(&sample, regs, &bounds);
    assert(sample.unwind == (depth | (status << 8)));
    for (uint32_t i = depth; i < PROFILER_UNWIND_MAX_DEPTH; ++i)
        assert(sample.callers[i] == 0U);
}
int main(void)
{
    reset(0x808400B0U);
    stack[0] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    assert(sample.callers[0] == 0x10002005U);

    reset(0x808400B0U);
    for (unsigned i = 0; i < PROFILER_UNWIND_MAX_DEPTH; ++i)
        stack[i] = 0x10001005U; /* Recursion with increasing SP is legitimate. */
    expect(PROFILER_UNWIND_MAX_DEPTH, PROFILER_UNWIND_DEPTH_LIMIT);

    reset(1U);
    expect(0, PROFILER_UNWIND_NO_TABLE);
    reset(0x80B4B0B0U); /* PAC opcode unsupported; never guess. */
    expect(0, PROFILER_UNWIND_UNSUPPORTED);
    reset(0x80B0B0B0U);
    regs[14] = regs[15] | 1U;
    expect(0, PROFILER_UNWIND_NO_PROGRESS);
    reset(0x808400B0U);
    stack[0] = 0x10001004U; /* No Thumb bit. */
    expect(0, PROFILER_UNWIND_INVALID_PC);
    reset(0x808400B0U);
    stack[0] = 0xFFFFFFFDU; /* Do not cross exception boundaries. */
    expect(0, PROFILER_UNWIND_INVALID_PC);
    reset(0x808400B0U);
    bounds.bytes = 0;
    expect(0, PROFILER_UNWIND_BOUNDS);
    reset(0x808400B0U);
    regs[13] += 1;
    expect(0, PROFILER_UNWIND_BOUNDS);
    reset(0x808400B0U);
    regs[13] += sizeof(stack);
    expect(0, PROFILER_UNWIND_BOUNDS);
    reset(0x80408400U); /* SP subtraction crosses allocation base. */
    expect(0, PROFILER_UNWIND_BOUNDS);
    reset(0x80978400U); /* SP = r7 then pop LR. */
    regs[7] = (uint32_t)(uintptr_t)(stack + 2);
    stack[2] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x80978400U);
    regs[7] = 0x20U; /* Must not dereference an arbitrary frame pointer. */
    expect(0, PROFILER_UNWIND_BOUNDS);
    reset(0x808800B0U); /* pop PC */
    stack[0] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x808600B0U); /* pop SP, LR: restored SP overrides post-pop address. */
    stack[0] = (uint32_t)(uintptr_t)(stack + 4);
    stack[1] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x80B8A8B0U); /* Skip FSTMFDX d8 (12 bytes), pop r4,LR. */
    stack[4] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x80D0A8B0U); /* VPUSH d8 skips only 8 bytes. */
    stack[3] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x80B101B0U); /* pop r0; leaf returns via live LR. */
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0x80B180B0U);
    expect(0, PROFILER_UNWIND_UNSUPPORTED);
    reset(0x808000B0U); /* Refuse to unwind. */
    expect(0, PROFILER_UNWIND_UNSUPPORTED);

    reset(0U);
    index_words[1] = relative(index_words + 1, (uintptr_t)extra);
    extra[0] = 0x8101B200U; /* PR1, 1 extra word; SP += 0x204. */
    extra[1] = 0x8400B0B0U;
    stack[129] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0U);
    index_words[1] = relative(index_words + 1, (uintptr_t)extra);
    extra[0] = 0x8201C900U; /* PR2, VPUSH d0, then pop LR. */
    extra[1] = 0x8400B0B0U;
    stack[2] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0U);
    index_words[1] = relative(index_words + 1, (uintptr_t)extra);
    extra[0] = 0x808400B0U; /* PR0 in extab. */
    stack[0] = 0x10002005U;
    expect(1, PROFILER_UNWIND_COMPLETE);
    reset(0U);
    index_words[1] = relative(index_words + 1, 0x20U);
    expect(0, PROFILER_UNWIND_UNSUPPORTED);
    reset(0U);
    index_words[1] = relative(index_words + 1, (uintptr_t)extra);
    extra[0] = 0x81FF0000U; /* Excessive recipe length. */
    expect(0, PROFILER_UNWIND_UNSUPPORTED);
    reset(0x808400B0U);
    stack[0] = 0x10002005U;
    index_words[3] = 1U;
    expect(1, PROFILER_UNWIND_NO_TABLE); /* Keep a valid partial chain. */
    reset(0x808400B0U);
    regs[15] = 0x90000000U;
    expect(0, PROFILER_UNWIND_INVALID_PC);
    bad_tables = 1;
    assert(!profiler_unwind_init());
    bad_tables = 0;
    reset(0x808400B0U);
    index_words[2] = index_words[0] - 8U; /* Duplicate function address. */
    assert(!profiler_unwind_init());
    return 0;
}
