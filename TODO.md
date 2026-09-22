# TODO

- [ ] Circular buffering with defined overwrite and export ordering.
- [ ] Repeated capture/export/resume: capture until full, stop and finalize,
  export through the debugger, then resume capture.

- [ ] Optional bounded stack tracing, with PC-only sampling as the default.
  Evaluate Zephyr's Arm EHABI unwinder; preserve attribution for reused code.
  Validate registers, complete frames, stack bounds and architecture/security cases.
  Keep tracing independent of board and RTOS adapters.
- [ ] Folded-stack export for FlameGraph once stack capture is available.
