/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        call_tree.c
 * Description:  Non-inlined A-F call tree for backtrace validation
 *
 * $Date:        25 September 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

#include <stdint.h>

/* Exactly 100 instructions, kept inline inside each named function. */
#define NOPS_100() __asm volatile(".rept 100\n nop\n .endr\n" ::: "memory")
static volatile uint32_t leaf_calls;

#if PROFILER_EXAMPLE_SPLIT_CODE
    #define LEAF_PLACEMENT __attribute__((section(".sram_text")))
#else
    #define LEAF_PLACEMENT
#endif

/** Leaf: 100 NOPs and evidence that every call executed. */
LEAF_PLACEMENT __attribute__((noinline)) void functionF(void)
{
    NOPS_100();
    ++leaf_calls;
}

/** Call functionF 32 times, with 100 NOPs after each call. */
__attribute__((noinline)) void functionE(void)
{
    for (uint32_t i = 0; i < 32U; ++i)
    {
        functionF();
        NOPS_100();
    }
}

/** Call functionE 16 times, with 100 NOPs after each call. */
__attribute__((noinline)) void functionD(void)
{
    for (uint32_t i = 0; i < 16U; ++i)
    {
        functionE();
        NOPS_100();
    }
}

/** Call functionD 8 times, with 100 NOPs after each call. */
__attribute__((noinline)) void functionC(void)
{
    for (uint32_t i = 0; i < 8U; ++i)
    {
        functionD();
        NOPS_100();
    }
}

/** Call functionC 4 times, with 100 NOPs after each call. */
__attribute__((noinline)) void functionB(void)
{
    for (uint32_t i = 0; i < 4U; ++i)
    {
        functionC();
        NOPS_100();
    }
}

/** Call functionB 2 times, with 100 NOPs after each call. */
__attribute__((noinline)) void functionA(void)
{
    for (uint32_t i = 0; i < 2U; ++i)
    {
        functionB();
        NOPS_100();
    }
}

/** The capture harness repeats functionA followed by 100 NOPs. */
__attribute__((noinline)) int run_once(void)
{
    leaf_calls = 0;
    functionA();
    NOPS_100();
    return 1;
}

/** 2 * 4 * 8 * 16 * 32 leaf calls per workload iteration. */
int validate(void) { return leaf_calls == 32768U; }
