# Capture format

All fields are little-endian uint32. A 176-byte header precedes variable-length
records. Each occupies `record_base_bytes + 4 * depth` bytes (depth is 0 without
backtraces). Dump the whole
`statistical_samples` object, including unused buffer space. Use the matching firmware and decoder.

## Header

| Word | Field | Meaning |
|---|---|---|
| 0 | magic | `0x46504353`: ASCII `SCPF` in little-endian order, **Statistical Capture Profiler Format** |
| 1 | version | `2`; only the current version is supported |
| 2 | record_base_bytes | `24 + 4 * pmu_count + (unwind_max_depth ? 4 : 0)` |
| 3 | buffer_bytes | Allocated object size, rounded down to whole words |
| 4 | bytes_used | Committed record bytes, excluding the header |
| 5 | count | Committed samples; may be 0 |
| 6 | rejected | Total rejected frames |
| 7 | active | Capture gate; 0 after stop |
| 8 | timestamp_hz | Fixed timestamp-counter frequency |
| 9 | timer_period | Sampling timer input counts per interrupt |
| 10-11 | start_timestamp, start_tick | Initial counter and sampling-interrupt epochs |
| 12-13 | stop_timestamp, stop_tick | Final counter and sampling-interrupt values |
| 14 | full | Next record could not fit, or less than a record base remains; no overwrite |
| 15 | complete | Set by stop; dump after stop returns |
| 16 | iterations | Application-reported workload iterations |
| 17 | validation_passed | Nonzero if the application validated its workload |
| 18 | sample_hz | Requested sample rate |
| 19 | timer_hz | Actual sampling timer input frequency |
| 20-23 | rejected_reason | Invalid EXC_RETURN, unsupported frame, stack bounds, invalid xPSR |
| 24 | pmu_status | 0 disabled; 1 unavailable; 2 active; 3 busy; 4 unsupported; 5 denied |
| 25 | pmu_count | 1-4 when active; otherwise 0 |
| 26 | pmu_requested | Requested event count, 0-4 |
| 27-30 | pmu_events | Requested architectural event IDs; unused slots are 0 |
| 31 | pmu_counter_bits | 32 when active; otherwise 0 |
| 32-35 | pmu_start | Initial chained-counter snapshots; unused slots are 0 |
| 36-39 | pmu_stop | Final snapshots after event counters stop; unused slots are 0 |
| 40 | pmu_flags | Bits 0-3: corresponding event overflow; bit 4: incoherent read |
| 41 | unwind_max_depth | 0: backtraces absent; 1-255: EHABI caller limit (default 16) |
| 42 | header_bytes | 176 for this format |
| 43 | features | Bit 0: active PMU words; bit 1: EHABI; other bits must be 0 |

Rejection counters reset at init. Exactly 1 reason per rejected sample is counted;
their sum modulo 2^32 equals `rejected`. Gated-off/full/spurious events are excluded.

## Records

```text
timestamp, tick, pc, lr, xpsr, exception_return
[, pmu[0], ..., pmu[pmu_count - 1]]
[, unwind, callers[0], ..., callers[depth - 1]]
```

Walk exactly `count` records occupying exactly `bytes_used` bytes. Timestamp is read after timer acknowledgement;
tick counts sampling interrupts. PC/LR describe the interrupted thread, not a call stack.

PMU count is 0-4 and fixed at init; caller depth varies per record. Disabled PMU metadata is 0.
Unavailable/busy/unsupported/denied PMU preserves status, requested count and event IDs,
with 0 count, width, snapshots and flags. Those records have no PMU words.
Unused bytes after `bytes_used` are not records. Minimum allocation is
`200 + 4 * PROFILER_PMU_COUNT + 4 * PROFILER_STACK_UNWIND` bytes. A 64 KiB buffer holds 2,723 samples
without PMU, 2,042 with 2 events or 1,634 with 4 events (backtraces disabled). Event ID `0x001E`
(CHAIN) increments an odd-numbered counter when the preceding even-numbered
counter overflows. The backend pairs 2 16-bit counters per event to produce
a 32-bit count: `(high << 16) | low`. CHAIN is reserved, not user-selectable. Insufficient hardware counters produce
`unsupported` status and records without PMU words.

## Backtrace extension

Present only when `unwind_max_depth` is nonzero; follows the active PMU words. The `unwind`
word contains actual depth (0-`unwind_max_depth`) in bits 0-7 and status in bits 8-15; other bits are 0.
Exactly `depth` raw Thumb return addresses follow, immediate caller first.
There are no padding slots; the sampled PC is not duplicated. A failed append
stops recording without committing a partial record. There is no fixed sample
capacity when backtraces are enabled.

| Status | Meaning |
|---|---|
| 0 | Complete: recovered a zero return address |
| 1 | Missing table entry / CANTUNWIND |
| 2 | Unsupported or malformed recipe |
| 3 | Stack bounds/alignment failure |
| 4 | Invalid code address / exception boundary |
| 5 | No forward progress |
| 6 | Depth limit, exactly `unwind_max_depth` callers retained |

Unwind failures preserve the valid prefix. Invalid status/caller addresses
exclude only the trace. Invalid record dimensions, excessive depth or truncated
records reject the capture because record boundaries cannot be trusted. See
[unwinding](docs/UNWINDING.md) for folded-stack export and best-effort limitations.

## Decoding

- Rounded period: `floor((timer_hz + floor(sample_hz / 2)) / sample_hz)`.
  Achieved rate: `timer_hz / timer_period`.
- Timestamp wrap recovery uses `tick_delta * timer_period * timestamp_hz / timer_hz`,
  with 2 sample periods of tolerance. Every cumulative prefix and the stop epoch
  must also agree with elapsed sampling ticks; tolerance does not accumulate. Each
  period must be under 2^30 timestamp counts; tick gaps of 2^31 or more invalidate
  timing. Lost IRQs/clock changes are not repaired.
- Timing failure sets `timing_valid=false` and `timing_diagnostic` in `summary.json`.
  All derived `time_us` and `timestamp_ticks_since_start` fields become empty in CSV
  (`None` internally). Raw `timestamp`/`tick`, PC statistics and PMU results remain.
  Successful timing checks set `timing_valid=true` and a null diagnostic.
- PMU totals are stop minus start; intervals subtract the preceding sample or initial
  snapshot, modulo 2^32. Counts cover all execution from init to stop, not individual
  functions. Counter reads and PC sampling are not atomic.
- Low-half rollover is normal. Full-width overflow or incoherent reads invalidate
  derived PMU counts; raw values and PC analysis remain. Invalid values are empty
  in CSV and null in JSON. Completed captures may contain 0 samples.

Increment the format identifier whenever layout or interpretation changes incompatibly.
No compatibility decoder is required, but never reuse an identifier for a different
layout. Header length and feature flags must agree with the selected format.
