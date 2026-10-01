/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_stack_regions.h
 * Description:  Readable stack memory region selection and validation
 *
 * $Date:        1 October 2026
 * $Revision:    V.1.0.1
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file profiler_stack_regions.h
 * @brief Select and validate CPU-readable RAM regions that may contain stacks.
 *
 * @par PROFILER_STACK_REGIONS
 * Readable stack RAM whitelist as {{base, bytes}, ...}; excludes BASE/BYTES overrides.
 *
 * @par PROFILER_STACK_BASE
 * Application-supplied base for 1 CPU-readable stack RAM region; requires STACK_BYTES.
 *
 * @par PROFILER_STACK_BYTES
 * Application-supplied size of the stack RAM region; requires STACK_BASE.
 */

#ifndef PROFILER_STACK_REGIONS_H
#define PROFILER_STACK_REGIONS_H

/* The application supplies BASE/BYTES for 1 region, or the full
 * {{base, bytes}, ...} initializer for several. SDK constants expand after
 * the backend includes the CMSIS device header. Only whitelist initialized,
 * CPU-readable memory containing MSP/PSP stacks. */
#if defined(PROFILER_STACK_REGIONS)
    #if defined(PROFILER_STACK_BASE) || defined(PROFILER_STACK_BYTES)
        #error "Use either PROFILER_STACK_REGIONS or PROFILER_STACK_BASE/BYTES, not both"
    #endif
#elif defined(PROFILER_STACK_BASE) || defined(PROFILER_STACK_BYTES)
    #if !defined(PROFILER_STACK_BASE) || !defined(PROFILER_STACK_BYTES)
        #error "Supply both PROFILER_STACK_BASE and PROFILER_STACK_BYTES"
    #endif
    #define PROFILER_STACK_REGIONS                                                                                     \
        {                                                                                                              \
            {                                                                                                          \
                PROFILER_STACK_BASE, PROFILER_STACK_BYTES                                                              \
            }                                                                                                          \
        }
#else
    #error "Application must supply PROFILER_STACK_REGIONS or PROFILER_STACK_BASE/BYTES"
#endif
#endif
