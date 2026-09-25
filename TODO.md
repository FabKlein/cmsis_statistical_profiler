# TODO

- [ ] Circular buffering with defined overwrite and export ordering.
- [ ] Repeated capture/export/resume: capture until full, stop and finalize,
  export through the debugger, then resume capture.

- [ ] Broaden backtrace validation on hardware, RTOS context switches and optimized
  libraries; measure worst-case ISR time. Compact EHABI and folded-stack export
  are implemented; additional unwind encodings and task IDs remain future work.
