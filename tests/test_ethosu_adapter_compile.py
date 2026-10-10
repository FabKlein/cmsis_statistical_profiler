# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_ethosu_adapter_compile.py
# Description:  Compile checks for Ethos-U trace driver variants
#
# $Date:        5 October 2026
# $Revision:    V.1.0.2
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Compile the optional adapter for every core-driver variant."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "ethosu"
STUBS = {
    "sampling_profiler_config.h": """
#define PROFILER_ETHOSU_TRACE 1
#define PROFILER_ETHOSU_TRACE_BUFFER_BYTES 512U
#ifndef PROFILER_ETHOSU_PMU_COUNT
#define PROFILER_ETHOSU_PMU_COUNT 4
#endif
#define PROFILER_ETHOSU_PMU_EVENT0 ETHOSU_PMU_NPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT1 ETHOSU_PMU_MAC_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT2 ETHOSU_PMU_MAC_DPU_ACTIVE
#define PROFILER_ETHOSU_PMU_EVENT3 ETHOSU_PMU_CYCLE
""",
    "sampling_profiler_format.h": """
#include <stdint.h>
struct FakeCoreCapture { struct { uint32_t sample_hz, timestamp_hz; } header; };
extern struct FakeCoreCapture statistical_samples;
""",
    "sampling_profiler_port.h": """
#include <stdint.h>
uint32_t profiler_port_timestamp(void);
uint32_t profiler_port_ticks(void);
void profiler_port_barrier(void);
void profiler_port_flush(const void *, uint32_t);
""",
    "ethosu_driver.h": """
#include <stdint.h>
struct ethosu_driver {
    struct { const void *custom_data_ptr; int custom_data_size; } job;
};
int ethosu_request_power(struct ethosu_driver *);
void ethosu_release_power(struct ethosu_driver *);
""",
    "pmu_ethosu.h": """
#include <stdint.h>
struct ethosu_driver;
enum ethosu_pmu_event_type {
    ETHOSU_PMU_CYCLE, ETHOSU_PMU_NPU_ACTIVE,
    ETHOSU_PMU_MAC_ACTIVE, ETHOSU_PMU_MAC_DPU_ACTIVE
};
void ETHOSU_PMU_Enable(struct ethosu_driver *);
void ETHOSU_PMU_Disable(struct ethosu_driver *);
void ETHOSU_PMU_Set_EVTYPER(struct ethosu_driver *, uint32_t, enum ethosu_pmu_event_type);
void ETHOSU_PMU_Set_EVCNTR(struct ethosu_driver *, uint32_t, uint32_t);
void ETHOSU_PMU_CNTR_Enable(struct ethosu_driver *, uint32_t);
void ETHOSU_PMU_CNTR_Disable(struct ethosu_driver *, uint32_t);
uint32_t ETHOSU_PMU_CNTR_Status(struct ethosu_driver *);
uint32_t ETHOSU_PMU_Get_EVCNTR(struct ethosu_driver *, uint32_t);
uint32_t ETHOSU_PMU_Get_QREAD(struct ethosu_driver *);
uint32_t ETHOSU_PMU_Get_STATUS(struct ethosu_driver *);
""",
}


class EthosuAdapterCompileTest(unittest.TestCase):
    def test_stream_discovery_runtime_and_host_decode(self):
        from test_ethosu_trace import MODULE

        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in STUBS.items():
                (root / name).write_text(source)
            for count, wrapper in ((0, 0), (0, 1), (4, 0), (4, 1)):
                with self.subTest(count=count, wrapper=wrapper):
                    executable, capture = root / "streams", root / "trace.bin"
                    subprocess.run(
                        [
                            compiler,
                            "-std=c11",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-DETHOSU55",
                            f"-DPROFILER_ETHOSU_PMU_COUNT={count}",
                            "-DPROFILER_ETHOSU_MAX_STREAMS=2",
                            f"-DPROFILER_ETHOSU_DRIVER_CALLBACK={wrapper}",
                            "-I",
                            directory,
                            "-I",
                            str(ADAPTER),
                            str(ADAPTER / "ethosu_trace.c"),
                            str(Path(__file__).with_name("test_ethosu_streams.c")),
                            "-o",
                            str(executable),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run([str(executable), str(capture)], check=True)
                    summary, records = MODULE.decode(capture.read_bytes())
                    self.assertEqual(summary["stream_count"], 2)
                    self.assertEqual(summary["unknown_stream_samples"], 4)
                    self.assertEqual(summary["unregistered_streams"], 3)
                    self.assertEqual(summary["pmu_count"], count)
                    self.assertEqual(summary["full"], 1)
                    self.assertEqual(
                        [
                            (r["stream_id"], r["samples"])
                            for r in MODULE.qread_histogram(records)
                        ],
                        [(1, 2), (2, 1)],
                    )

    def test_all_driver_variants(self):
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory() as directory:
            for name, source in STUBS.items():
                (Path(directory) / name).write_text(source)
            for variant in ("ETHOSU55", "ETHOSU65", "ETHOSU85"):
                for count in range(5):
                    with self.subTest(variant=variant, count=count):
                        subprocess.run(
                            [
                                compiler,
                                "-std=c11",
                                "-Wall",
                                "-Wextra",
                                "-Werror",
                                "-fsyntax-only",
                                f"-D{variant}",
                                f"-DPROFILER_ETHOSU_PMU_COUNT={count}",
                                "-I",
                                directory,
                                str(ADAPTER / "ethosu_trace.c"),
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                        )


if __name__ == "__main__":
    unittest.main()
