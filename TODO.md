# TODO

- [ ] Review the per-record `profiler_port_barrier()` in `profiler_record()`: it adds
  overhead to every sample. Measure the cost and verify memory-ordering requirements
  for the single-core ISR writer and post-stop readers before changing it.

- [ ] Circular buffering with defined overwrite and export ordering.
- [ ] Repeated capture/export/resume: capture until full, stop and finalize,
  export through the debugger, then resume capture.

- [ ] Broaden backtrace validation on hardware, RTOS context switches and optimized
  libraries; measure worst-case ISR time. Compact EHABI and folded-stack export
  are implemented; additional unwind encodings and task IDs remain future work.

- [ ] Capture the unwind termination address; current records retain status and
  recovered prefix only. Root reached and complete unwind remain distinct.
- [ ] Embed an immutable build ID in loadable read-only firmware data, copy it
  into capture metadata and compare it with the supplied ELF during decoding.
  Generate it per build and retain it through linking; bump the capture format.
  Keep the full ELF SHA-256 separately for artifact integrity, avoiding a
  self-referential hash of the ELF containing its own ID.
- [ ] Resolve selective AC6 retention through input ELF/archive EXIDX associations;
  the current helper infers names from the first-pass map and uses object wildcards.
- [ ] Reproduce reported macOS test failures with logs/toolchain details; native
  firmware tests currently require Linux ELF and low 32-bit addresses.
