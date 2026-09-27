/*
 * SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/* ----------------------------------------------------------------------
 * Project:      CMSIS Statistical Profiler
 * Title:        call_tree_clone.c
 * Description:  Independent named copy of the second worker workload
 *
 * $Date:        27 September 2026
 * $Revision:    V.1.0.0
 *
 * Target :  Arm(R) M-Profile Architecture
 * -------------------------------------------------------------------- */

#define functionA functionA1
#define functionB functionB1
#define functionC functionC1
#define functionD functionD1
#define functionE functionE1
#define functionF functionF1
#define run_once run_once1
#define validate validate1
#include "../corstone300/call_tree.c"
