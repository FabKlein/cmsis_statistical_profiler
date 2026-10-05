# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        export_ethosu_trace_buffer.gdb
# Description:  Export a finalized Ethos-U trace buffer through GDB
#
# $Date:        5 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

define export_ethosu_trace_buffer
  if $argc != 1
    echo Usage: export_ethosu_trace_buffer output.bin\n
  else
    if ethosu_trace_samples.header.complete != 1 || ethosu_trace_samples.header.active != 0
      echo Ethos-U trace is not complete. Stop before export.\n
    else
      print ethosu_trace_samples.header
      dump binary memory $arg0 &ethosu_trace_samples (&ethosu_trace_samples+1)
    end
  end
end

document export_ethosu_trace_buffer
Export the finalized separate Ethos-U EUTR buffer to a binary file on the host.
Usage: export_ethosu_trace_buffer output.bin
The target must be halted after trace_ethosu_stop has returned.
Export the whole allocation for length and record-count validation.
end
