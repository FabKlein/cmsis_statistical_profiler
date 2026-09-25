# TODO

- [ ] Circular buffering with defined overwrite and export ordering.
- [ ] Repeated capture/export/resume: capture until full, stop and finalize,
  export through the debugger, then resume capture.

- [ ] Broaden backtrace validation on hardware, RTOS context switches and optimized
  libraries; measure worst-case ISR time. Compact EHABI and folded-stack export
  are implemented; additional unwind encodings and task IDs remain future work.

- [ ] Capture the unwind termination address; current records retain status and
  recovered prefix only. Root reached and complete unwind remain distinct.
- [ ] Reproduce reported macOS test failures with logs/toolchain details; native
  firmware tests currently require Linux ELF and low 32-bit addresses.
