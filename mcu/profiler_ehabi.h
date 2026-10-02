/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_ehabi.h
 * Description:  Private EHABI table layout and compact opcode definitions
 *
 * $Date:        2 October 2026
 * $Revision:    V.1.0.4
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file profiler_ehabi.h
 * @brief Private definitions for the supported subset of the Arm Exception Handling ABI (EHABI).
 * @details Internal to the profiler; not an application API or a complete EHABI runtime header.
 * These are ABI encodings, not configurable profiler settings.
 *
 * Table layouts, PREL31 references and compact personalities:
 * https://github.com/ARM-software/abi-aa/blob/main/ehabi32/ehabi32.rst
 *
 * Compact instruction encodings (section 10.3):
 * https://github.com/ARM-software/abi-aa/blob/main/ehabi32/ehabi32.rst#103-frame-unwinding-instructions
 */
#ifndef PROFILER_EHABI_H
#define PROFILER_EHABI_H

/* Core register indices in the unwinder's virtual r0-r15 array. */
#define EHABI_SP_IDX 13U
#define EHABI_LR_IDX 14U
#define EHABI_PC_IDX 15U

/* EXIDX entries contain 2 words: a code-range start and a recipe descriptor.
 * EXTAB holds recipes too large to fit inline. Both tables are word-aligned. */
#define EHABI_WORD_BYTES  4U /* sizeof(uint32_t): EHABI words are 32 bits. */
#define EXIDX_ENTRY_WORDS 2U
#define EXIDX_ENTRY_BYTES (EXIDX_ENTRY_WORDS * EHABI_WORD_BYTES)

/* Thumb code addresses are halfword-aligned, without the function-pointer tag. */
#define THUMB_CODE_ALIGNMENT 2U

/* PREL31: signed 31-bit offset relative to the address of the encoded word.
 * Bit 31 is excluded from the offset; bit 30 supplies its sign. */
#define EHABI_PREL31_OFFSET_MASK  0x7FFFFFFFU
#define EHABI_PREL31_SIGN_BIT     0x40000000U
#define EHABI_PREL31_RESERVED_BIT 0x80000000U

/* The second EXIDX word is CANTUNWIND, an inline compact recipe, or PREL31 to EXTAB. */
#define EHABI_EXIDX_CANTUNWIND 1U
#define EHABI_COMPACT_BIT      0x80000000U

/* First compact recipe word, shown by bit position (not memory byte order):
 *
 *                  31        24 23        16 15         8 7          0
 * Personality 0:  |    0x80    |  opcode 1  |  opcode 2  |  opcode 3  |
 * Personality 1/2:| 0x81/0x82  | extra words|  opcode 1  |  opcode 2  |
 *
 * The extra-word count excludes this header word. Each following word holds
 * 4 more opcode bytes, decoded most-significant byte first.
 * Only personality 0 may be stored inline in EXIDX; all 3 may appear in EXTAB.
 */
#define EHABI_COMPACT_TAG_SHIFT          24U
#define EHABI_COMPACT_EXTRA_WORDS_SHIFT  16U
#define EHABI_COMPACT_EXTRA_WORDS_MASK   0xFFU
#define EHABI_COMPACT_SHORT_OPCODE_BYTES 3U
#define EHABI_COMPACT_LONG_OPCODE_BYTES  2U

/* High-byte tags combine the compact-format flag and the personality index. */
#define EHABI_COMPACT_PERSONALITY_0 0x80U
#define EHABI_COMPACT_PERSONALITY_1 0x81U
#define EHABI_COMPACT_PERSONALITY_2 0x82U

/* Ordered opcode families; low bits carry operands, not separate opcodes. */
#define EHABI_OP_ADJUST_SP_LAST     0x7FU /* 0x00-0x7F: increase/decrease virtual SP. */
#define EHABI_OP_POP_MASK_LAST      0x8FU /* 0x80-0x8F: restore r4-r15 using a second-byte mask. */
#define EHABI_OP_SET_SP_LAST        0x9FU /* 0x90-0x9F: recover SP from a core register. */
#define EHABI_OP_POP_RANGE_LAST     0xAFU /* 0xA0-0xAF: restore r4 upwards, optionally LR. */
#define EHABI_OP_FINISH             0xB0U
#define EHABI_OP_POP_LOW_REGS       0xB1U /* Second byte selects r0-r3. */
#define EHABI_OP_LARGE_SP_INCREMENT 0xB2U /* Followed by an unsigned base-128 operand. */

/* Floating-point saves: the profiler skips their stack footprint, never loads FP registers.
 * Legacy FSTMFDX forms include an extra 4-byte format word. */
#define EHABI_OP_POP_VFP_FSTMFDX       0xB3U
#define EHABI_OP_POP_VFP_D16           0xC8U /* Register range starts at D16 + operand start. */
#define EHABI_OP_POP_VFP_D0            0xC9U /* Register range starts at D0 + operand start. */
#define EHABI_OP_VFP_RANGE_MASK        0xF8U
#define EHABI_OP_POP_VFP_RANGE_FSTMFDX 0xB8U /* 0xB8-0xBF: D8 upwards. */
#define EHABI_OP_POP_VFP_RANGE         0xD0U /* 0xD0-0xD7: D8 upwards, no format word. */

#endif /* PROFILER_EHABI_H */
