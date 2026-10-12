# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Compile supported variants and run ownership probes with the real pinned SDK."""

import argparse
from pathlib import Path
import subprocess
import tempfile

from test_ethosu_adapter_compile import STUBS

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", required=True, type=Path, help="core-driver 1.26.2 ethos_u_core_driver directory")
    parser.add_argument("--cc", default="cc", help="Native C compiler")
    args = parser.parse_args()
    driver = args.driver.resolve()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for name in ("sampling_profiler_config.h", "sampling_profiler_port.h"):
            source = STUBS[name]
            if name == "sampling_profiler_config.h":
                source = source.replace("#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE",
                                        "#ifndef PROFILER_ETHOSU_PMU_EVENT0\n#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE\n#endif")
            (root / name).write_text(source)
        for variant in ("ETHOSU55", "ETHOSU65", "ETHOSU85"):
            flags = [args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D" + variant, "-DETHOSU_ARCH=u" + variant[6:],
                     "-I" + folder, "-I" + str(driver / "include"), "-I" + str(driver / "src"),
                     "-I" + str(ROOT / "adapters/ethosu"), "-DETHOSU_LOG_ENABLE=0"]
            for count in (0, 1, 4):
                subprocess.run([*flags, f"-DPROFILER_ETHOSU_PMU_COUNT={count}", "-c",
                                str(ROOT / "adapters/ethosu/ethosu_trace.c"), "-o", str(root / "adapter.o")], check=True)
            for event in ("-1", "ETHOSU_PMU_SENTINEL", "0x7fffffff"):
                result = subprocess.run([*flags, "-DPROFILER_ETHOSU_PMU_COUNT=1", f"-DPROFILER_ETHOSU_PMU_EVENT0={event}",
                                         "-c", str(ROOT / "adapters/ethosu/ethosu_trace.c"), "-o", str(root / "invalid.o")],
                                        capture_output=True, text=True)
                if result.returncode == 0 or "Invalid Ethos-U PMU event" not in result.stderr:
                    raise RuntimeError(f"{variant}: invalid event was not rejected: {event}\n{result.stderr}")
            subprocess.run([*flags, "-DPROFILER_ETHOSU_PMU_COUNT=1", "-c",
                            str(ROOT / "adapters/ethosu/ethosu_trace.c"), "-o", str(root / "adapter.o")], check=True)
            # The SDK's disabled log statements still type-check LP64 %llu
            # arguments. Suppress that SDK-only warning, keeping adapter Werror.
            subprocess.run([*flags, "-Wno-format", "-c", str(driver / "src/ethosu_pmu.c"),
                            "-o", str(root / "driver.o")], check=True)
            binary = root / "probe"
            subprocess.run([*flags, "-DPROFILER_ETHOSU_PMU_COUNT=1", str(ROOT / "tests/test_ethosu_real_pmu.c"),
                            str(root / "adapter.o"), str(root / "driver.o"), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            print(f"{variant}: real SDK compile, invalid-event and ownership probes passed")


if __name__ == "__main__":
    main()
