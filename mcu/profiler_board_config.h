/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        profiler_board_config.h
 * Description:  Shared device and readable stack memory configuration
 *
 * $Date:        22 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 *
 * -------------------------------------------------------------------- */

/**
 * @file profiler_board_config.h
 * @brief Shared device and readable stack memory configuration.
 *
 * @par PROFILER_DEVICE_HEADER
 * Required quoted CMSIS device header selected by the board layer or application.
 *
 * @par PROFILER_STACK_REGIONS
 * Readable stack RAM whitelist as {{base, bytes}, ...}; excludes BASE/BYTES overrides.
 *
 * @par PROFILER_STACK_BASE
 * Application override for 1 CPU-readable stack RAM region; requires STACK_BYTES.
 *
 * @par PROFILER_STACK_BYTES
 * Size of the application stack RAM region; requires STACK_BASE.
 *
 * @par PROFILER_DEFAULT_STACK_BASE
 * SDK-derived board stack RAM base, used if no application bounds are supplied.
 *
 * @par PROFILER_DEFAULT_STACK_BYTES
 * SDK-derived board stack RAM size; paired with DEFAULT_STACK_BASE.
 *
 * @par PROFILER_DEFAULT_DTCM_BASE
 * Explicit opt-in CPU-visible DTCM base; size is detected from MEMSYSCTL at init.
 *
 * @par PROFILER_STACK_SIZE_FROM_DTCM
 * Internal flag selecting runtime DTCM size detection; not a generic RAM size probe.
 */

#ifndef PROFILER_BOARD_CONFIG_H
#define PROFILER_BOARD_CONFIG_H

/* Shared contract for every board. PROFILER_USER_CONFIG is included first.
 * Board layers select the device header and SDK-derived RAM defaults.
 * Application stack bounds override those defaults. */
#ifndef PROFILER_DEVICE_HEADER
    #error "Select a board layer or define PROFILER_DEVICE_HEADER to your CMSIS device header"
#endif

/* Use BASE/BYTES for 1 region, or the full {{base, bytes}, ...} initializer
 * for several. SDK constants expand after the backend includes the device.
 * Only whitelist initialized, CPU-readable memory containing MSP/PSP stacks. */
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
#elif defined(PROFILER_DEFAULT_STACK_BASE) || defined(PROFILER_DEFAULT_STACK_BYTES)
    #if !defined(PROFILER_DEFAULT_STACK_BASE) || !defined(PROFILER_DEFAULT_STACK_BYTES)
        #error "Supply both board-default stack bounds; use PROFILER_DEFAULT_DTCM_BASE for DTCM detection"
    #endif
    #define PROFILER_STACK_REGIONS                                                                                     \
        {                                                                                                              \
            {                                                                                                          \
                PROFILER_DEFAULT_STACK_BASE, PROFILER_DEFAULT_STACK_BYTES                                              \
            }                                                                                                          \
        }
#elif defined(PROFILER_DEFAULT_DTCM_BASE)
    /* No SDK size constant: snapshot enabled DTCM size from CMSIS at init.
     * This base must describe CPU-visible DTCM, never another RAM. */
    #define PROFILER_STACK_SIZE_FROM_DTCM 1
    #define PROFILER_STACK_REGIONS                                                                                     \
        {                                                                                                              \
            {                                                                                                          \
                PROFILER_DEFAULT_DTCM_BASE, 0U                                                                         \
            }                                                                                                          \
        }
#else
    #error "Supply stack bounds or select a board layer with RAM defaults"
#endif
#endif
