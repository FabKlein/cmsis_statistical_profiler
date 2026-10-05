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
    "sampling_profiler.h": """
#include <stdint.h>
extern struct { struct { uint32_t sample_hz, timestamp_hz; } header; } statistical_samples;
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
    struct { const void *custom_data_ptr; uint32_t custom_data_size; } job;
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
