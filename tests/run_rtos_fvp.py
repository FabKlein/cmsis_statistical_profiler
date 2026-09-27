# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        run_rtos_fvp.py
# Description:  Build, run and validate the dual-thread CMSIS-RTOS2 call tree
#
# $Date:        27 September 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Build with CMSIS-Toolbox, run RTX or FreeRTOS on FVP and validate both call trees."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def check_report(report, stack_root=None):
    summary = json.loads((report / "summary.json").read_text())
    header = summary["header"]
    with (report / "samples.csv").open() as source:
        samples = list(csv.DictReader(source))
    failures = []
    def require(ok, message):
        if not ok:
            failures.append(message)
    require(header["complete"] == 1 and header["active"] == 0 and header["validation_passed"] == 1,
            "firmware did not complete and validate both workers")
    require(header["iterations"] >= 2 and header["rejected"] == 0, "missing worker progress or rejected frames")
    require(summary["timing_valid"], "invalid timestamp timing")
    require(header["unwind_max_depth"] == 16 and header["record_base_bytes"] == 28, "incorrect backtrace layout")
    require(650 <= header["count"] <= 680 and len(samples) == header["count"], "unexpected 2-second capture size")
    groups = [{"function" + c + suffix for c in "ABCDEF"} for suffix in ("", "1")]
    for suffix, group in zip(("", "1"), groups):
        require(sum(row["function"] in group for row in samples) >= 100, "too few samples for worker" + suffix)
        expected = ["worker" + suffix, "run_once" + suffix] + ["function" + c + suffix for c in "ABCDE"]
        require(any(all(name in json.loads(row["callchain"]) for name in expected) for row in samples),
                "missing deep caller chain for worker" + suffix)
    for row in samples:
        chain = set(json.loads(row["callchain"]))
        require(not (chain & groups[0] and chain & groups[1]), "caller chain crosses thread workloads")
        require(row["function"] in groups[0] | groups[1], "sample outside the 2 workloads")
        require(int(row["exception_return"], 16) & 4, "sample did not use a thread PSP")
    lines = (report / "stacks.folded").read_text().splitlines()
    require(bool(lines), "no usable folded stacks")
    folded = []
    for line in lines:
        names, count = line.rsplit(" ", 1)
        folded.append((names.split(";"), int(count)))
    require(all(count > 0 for _, count in folded), "nonpositive folded sample count")
    if stack_root:
        require(all(chain[0] == stack_root for chain, _ in folded), "incorrect flamegraph root")
    valid_chains = 0
    for suffix in ("", "1"):
        expected = ([stack_root] if stack_root else []) + ["worker" + suffix, "run_once" + suffix]
        minimum_depth = len(expected) + 1
        expected += ["function" + c + suffix for c in "ABCDEF"]
        # Every plotted chain must be an exact prefix of this known call tree.
        # Shorter prefixes are valid PC samples in A-D, not missing callers.
        matching = [(chain, count) for chain, count in folded
                    if minimum_depth <= len(chain) <= len(expected)
                    and chain == expected[:len(chain)]]
        valid_chains += len(matching)
        require(sum(count for _, count in matching) >= 100, "too few plotted samples for worker" + suffix)
        require(any(len(chain) >= len(expected) - 1 and count > 0 for chain, count in matching),
                "missing plotted deep caller chain for worker" + suffix)
    require(valid_chains == len(folded), "invalid folded caller chain")
    require(sum(count for _, count in folded) ==
            sum(row.get("flamegraph_status", "included") == "included" for row in samples),
            "folded stacks lost samples")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", choices=("rtx", "freertos"), required=True)
    parser.add_argument("--cbuild", default="cbuild", help="CMSIS-Toolbox cbuild executable")
    parser.add_argument("--flamegraph", type=Path, help="Optional local FlameGraph flamegraph.pl")
    parser.add_argument("--fvp", default="FVP_Corstone_SSE-300")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=120, help="Wall-clock limit for each command, seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("use a positive timeout")
    freertos = args.kernel == "freertos"
    build_type = "FreeRTOS" if freertos else "RTX"
    kernel_name = "CMSIS-FreeRTOS" if freertos else "CMSIS-RTX"
    stack_root = "worker_entry" if freertos else "osThreadEntry"
    output = (args.output or ROOT / ("build/freertos-call-tree" if freertos else "build/rtos-call-tree")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report"
    report.mkdir(exist_ok=True)
    # An early FVP exit must not pass using a previous run's capture or reports.
    for path in [output / "samples.bin", output / "result.json", output / "profiler.elf", output / "preflight.json"] + [report / name for name in
                 ("summary.json", "functions.csv", "samples.csv", "events.csv", "stacks.folded", "stacks.note.txt", "flamegraph.svg")]:
        path.unlink(missing_ok=True)

    def run(command, log, cwd=ROOT):
        print("Running:", " ".join(map(str, command)), flush=True)
        with (output / log).open("w") as stream:
            subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=args.timeout, check=True)

    failures = []
    try:
        toolbox_output = output / "toolbox"
        run([args.cbuild, ROOT / "examples/corstone300_rtos2/call_tree.csolution.yml",
             "--context", f"call_tree.{build_type}+Corstone300", "--output", toolbox_output, "--update-rte"], "build.log")
        shutil.copy2(toolbox_output / "out/call_tree/Corstone300" / build_type / "profiler.elf",
                     output / "profiler.elf")
        run([sys.executable, ROOT / "host/check_profiler_elf.py", "--elf", output / "profiler.elf",
             "--require-unwind", "--function", "worker", "--function", "worker1",
             "--function", "functionF", "--function", "functionF1",
             "--output", output / "preflight.json"], "preflight.log")
        command = [args.fvp, "-a", "profiler.elf", "--simlimit", "4"]
        parameters = ["core_clk.mul=32000000", "mps3_board.sse300.refcounter.base_frequency=100000000",
                      "cpu0.semihosting-enable=1", "mps3_board.visualisation.disable-visualisation=1"]
        parameters += [f"mps3_board.telnetterminal{port}.start_telnet=0" for port in (0, 1, 2, 5)]
        for parameter in parameters:
            command += ["-C", parameter]
        run(command, "fvp.log", output)
        run([sys.executable, ROOT / "host/analyze_profiler_buffer.py", "--samples", output / "samples.bin",
             "--elf", output / "profiler.elf", "--output", report, "--stack-root", stack_root], "decode.log")
        failures = check_report(report, stack_root)
        if args.flamegraph and not failures:
            with (report / "flamegraph.svg").open("w") as svg:
                subprocess.run(["perl", str(args.flamegraph.resolve()), "--countname", "samples", "--subtitle", (report / "stacks.note.txt").read_text().strip(), "--title",
                                kernel_name + ": A-F and A1-F1 (Corstone-300)", str(report / "stacks.folded")],
                               stdout=svg, check=True, timeout=args.timeout)
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
    print(f"PASS: {kernel_name}/FVP captured both independent call trees")
    return 0


if __name__ == "__main__":
    sys.exit(main())
