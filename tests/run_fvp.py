# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        run_fvp.py
# Description:  Build, run and validate the AC6 Corstone-300 PMU regression
#
# $Date:        22 September 2026
# $Revision:    V.1.0.0
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Build with AC6, run Corstone-300 FVP, decode and check the capture."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from check_fvp import check_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmsis", type=Path, required=True)
    parser.add_argument("--bsp", type=Path, required=True)
    parser.add_argument("--cc", default="armclang", help="AC6 armclang executable")
    parser.add_argument("--fvp", default="FVP_Corstone_SSE-300")
    parser.add_argument("--output", type=Path, default=ROOT / "build/fvp")
    parser.add_argument("--timeout", type=int, default=120, help="Wall-clock limit for each command, seconds")
    args = parser.parse_args()
    if "armclang" not in Path(args.cc).name or args.timeout <= 0:
        parser.error("use AC6 armclang and a positive timeout")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report"
    report.mkdir(exist_ok=True)
    # An early FVP exit must not pass using a previous run's capture or reports.
    for path in [output / "samples.bin", output / "result.json"] + [report / name for name in
                 ("summary.json", "functions.csv", "samples.csv", "events.csv")]:
        path.unlink(missing_ok=True)

    def run(command, log, cwd=ROOT):
        print("Running:", " ".join(map(str, command)), flush=True)
        with (output / log).open("w") as stream:
            subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=args.timeout, check=True)

    failures = []
    try:
        run([sys.executable, ROOT / "examples/corstone300/build.py", "--cc", args.cc,
             "--cmsis", args.cmsis.resolve(), "--bsp", args.bsp.resolve(), "--output", output,
             "--semihosting", "--sample-hz", "333", "--timer-clock-hz", "100000000",
             "--buffer-bytes", "65536", "--captures", "2", "--psp", "--float-workload",
             "--precise-stack-bounds", "--pmu", "--reference-timestamp"], "build.log")
        command = [args.fvp, "-a", "profiler.elf", "--simlimit", "3"]
        parameters = ["core_clk.mul=32000000", "mps3_board.sse300.refcounter.base_frequency=100000000",
                      "cpu0.semihosting-enable=1", "mps3_board.visualisation.disable-visualisation=1"]
        parameters += [f"mps3_board.telnetterminal{port}.start_telnet=0" for port in (0, 1, 2, 5)]
        for parameter in parameters:
            command += ["-C", parameter]
        run(command, "fvp.log", output)
        run([sys.executable, ROOT / "host/analyze_profiler_buffer.py", "--samples", output / "samples.bin",
             "--elf", output / "profiler.elf", "--output", report], "decode.log")
        reference = json.loads((ROOT / "tests/fvp_reference.json").read_text())
        failures = check_report(report, reference)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failures = [str(error)]
    result = {"status": "fail" if failures else "pass", "failures": failures}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        print("Logs:", output)
        return 1
    print((output / "decode.log").read_text(), end="")
    print("PASS: AC6/FVP capture matches tests/fvp_reference.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
