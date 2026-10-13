# TODO

- [ ] Circular buffering with defined overwrite and export ordering.
- [ ] Automate the existing manual [capture/export/resume workflow](docs/REPEATED_CAPTURES.md).

- [ ] Broaden backtrace validation on hardware, RTOS context switches and optimized
  libraries; measure worst-case ISR time. Extend unwind encodings and task identification.

- [ ] Capture the unwind termination address; current records retain status and
  recovered prefix only. Root reached and complete unwind remain distinct.
- [ ] Resolve selective AC6 retention through input ELF/archive EXIDX associations;
  the current helper infers names from the first-pass map and uses object wildcards.
- [ ] Reproduce reported macOS test failures with logs/toolchain details; native
  firmware tests currently require Linux ELF and low 32-bit addresses.
