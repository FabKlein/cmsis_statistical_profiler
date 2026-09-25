# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        check_layer_scope.py
# Description:  Check generated CMSIS compiler flags stay within profiler groups
#
# $Date:        22 September 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Generate CMSIS builds and verify vectorization flags are restricted to profiler sources.

Requires csolution, PyYAML and installed ARM.CMSIS 6.3.0 / SSE-300 BSP 1.5.0 packs.
No compilation or board SDKs beyond that BSP are required.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLAGS = {"AC6": {"-fno-vectorize", "-fno-slp-vectorize"}, "GCC": {"-fno-tree-vectorize"}}
ALL_FLAGS = set().union(*FLAGS.values())
TIMERS = ["adapters/stm32n6/stm32n6_tim2.clayer.yml",
          "adapters/corstone300/corstone300_timer0.clayer.yml",
          "adapters/alif_e8/alif_e8_utimer.clayer.yml",
          "adapters/template/template_timer.clayer.yml",
          "integrations/systick/systick.clayer.yml"]


def check_build(build, compiler):
    data = yaml.safe_load(build.read_text())["build"]
    seen = []

    def walk(node, inherited):
        flags = inherited + node.get("misc", {}).get("C", [])
        for source in node.get("files", []):
            if source.get("category") != "sourceC":
                continue
            effective = flags + source.get("misc", {}).get("C", [])
            actual = ALL_FLAGS.intersection(effective)
            name = Path(source["file"]).name
            expected = set() if name == "application.c" else FLAGS[compiler]
            if actual != expected:
                raise RuntimeError(f"{compiler} {name}: expected {sorted(expected)}, got {sorted(actual)}")
            if "-DAPPLICATION_BUILD_SENTINEL=1" not in effective:
                raise RuntimeError(f"{name}: application build settings were lost")
            seen.append(name)
        for group in node.get("groups", []):
            walk(group, flags)

    walk(data, [])
    if len(seen) != 6 or "application.c" not in seen:
        raise RuntimeError(f"Expected application, 4 common sources and 1 timer; got {seen}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csolution", default="csolution")
    parser.add_argument("--compiler", choices=FLAGS, nargs="+", default=["AC6"])
    args = parser.parse_args()
    for compiler in args.compiler:
        for timer in TIMERS:
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                solution = {"solution": {"compiler": compiler,
                    "packs": [{"pack": "ARM::CMSIS@6.3.0"}, {"pack": "ARM::V2M_MPS3_SSE_300_BSP@1.5.0"}],
                    "target-types": [{"type": "M55", "device": "ARM::SSE-300-MPS3",
                                      "processor": {"trustzone": "secure"}}],
                    "projects": [{"project": "app.cproject.yml"}]}}
                project = {"project": {
                    "misc": [{"for-compiler": compiler, "C": ["-DAPPLICATION_BUILD_SENTINEL=1"]}],
                    "layers": [{"layer": os.path.relpath(ROOT / name, tmp)} for name in
                               ("cmsis_statistical_profiler.clayer.yml", timer)],
                    "groups": [{"group": "Application", "files": [{"file": "application.c"}]}]}}
                (tmp / "scope.csolution.yml").write_text(yaml.safe_dump(solution, sort_keys=False))
                (tmp / "app.cproject.yml").write_text(yaml.safe_dump(project, sort_keys=False))
                (tmp / "application.c").write_text("void application(void) {}\n")
                result = subprocess.run([args.csolution, "convert", str(tmp / "scope.csolution.yml")],
                                        capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                builds = list(tmp.rglob("*.cbuild.yml"))
                if len(builds) != 1:
                    raise RuntimeError(f"Expected one generated build; got {builds}")
                check_build(builds[0], compiler)
                print(f"PASS: {compiler} {timer}: application untouched, all profiler sources protected")


if __name__ == "__main__":
    main()
