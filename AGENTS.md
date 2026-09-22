# Agent guide

Start with [README.md](README.md). Use [configuration](docs/CONFIGURATION.md),
[adapter template](adapters/template/README.md) and the
[Corstone FVP example](examples/corstone300/README.md) for integration.

- Use numerals for quantities in prose and documentation: 1, 2, 3, etc.
- Keep 3 layers: capture/storage, Cortex-M backend, board timer adapter.
  Vendor dependencies belong in adapters, not the capture core.
- Use 1 dedicated timer. Preserve HAL/RTOS interrupt ownership. The application
  supplies clocks, startup, linker placement and readable stack bounds; TCM is optional.
- For AMP, keep buffers/state physically separate per image and reserve distinct
  timer channels. Serialize shared peripheral clock setup; decode with each core's ELF.
- Run lifecycle calls serially in privileged thread mode on 1 core. Always stop
  before dumping the whole buffer with [dump_samples.gdb](tools/dump_samples.gdb);
  decode with the exact unstripped executable.
- Keep ISR code bounded and integer-only: no allocation, blocking, logging, FP or
  vector instructions. Preserve the original exception frame.
- Maintain 1 [format](FORMAT.md): 6 base words plus `pmu_count` words, 24–40
  bytes for 0–4 events. Change firmware, decoder and tests together; no legacy compatibility branches.
  PMU deltas are not per-function counts.
- Preserve SPDX/project headers and Doxygen contracts. Use `.clang-format` for C/H;
  preserve protected device include order.
- For behavior changes, run `python3 -B -m unittest discover -s tests -v`.
  For backend/adapter changes, also use the relevant [compile/FVP checks](tests/VALIDATION.md).
  State hardware validation limits accurately.
