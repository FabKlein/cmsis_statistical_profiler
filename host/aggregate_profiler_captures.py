"""Aggregate finalized Cortex-M and Ethos-U profiler reports across captures.

The debugger pauses between captures are not represented as sample time. Stream
IDs are capture-local, so their descriptor tables must match before QREAD
histograms can be added together.
"""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path, columns, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def capture_sort_key(path):
    match = re.search(r"(\d+)$", path.name)
    return (
        path.name[: match.start()] if match else path.name,
        int(match.group(1)) if match else -1,
    )


def select_captures(args, parser):
    if args.input_dir:
        if args.captures:
            parser.error("use either --input-dir or explicit capture directories")
        if not args.input_dir.is_dir():
            parser.error(f"input directory does not exist: {args.input_dir}")
        captures = sorted(
            (p for p in args.input_dir.glob(args.pattern) if p.is_dir()), key=capture_sort_key
        )
        output = args.output_dir or args.input_dir
    else:
        if not args.captures:
            parser.error("provide --input-dir or one or more capture directories")
        if not args.output_dir:
            parser.error("--output-dir is required with explicit capture directories")
        captures = args.captures
        output = args.output_dir
    if not captures:
        parser.error("no capture directories found")
    for directory in captures:
        if not directory.is_dir():
            parser.error(f"capture directory does not exist: {directory}")
    return captures, output


def aggregate(captures, output):
    capture_rows = []
    cpu_rows = []
    npu_rows = []
    functions = Counter()
    qreads = Counter()
    stream_identity = None
    elf_sha256 = None
    sample_hz = None
    pmu_counts = None
    buffer_layout = None
    components = None

    for index, directory in enumerate(captures):
        cpu_path = directory / "cortex_m_report/summary.json"
        npu_path = directory / "ethosu_report/summary.json"
        present = (cpu_path.is_file(), npu_path.is_file())
        if not any(present):
            raise ValueError(f"{directory}: no decoded Cortex-M or Ethos-U report")
        if components is None:
            components = present
        elif present != components:
            raise ValueError(f"{directory}: processor reports differ between captures")
        cpu = json.loads(cpu_path.read_text()) if present[0] else None
        npu = json.loads(npu_path.read_text()) if present[1] else None
        ch = cpu["header"] if cpu else None
        streams = read_csv(directory / "ethosu_report/streams.csv") if npu else []
        identity = tuple(
            (row["stream_id"], row["command_address"], row["stream_bytes"]) for row in streams
        )
        rate = ch["sample_hz"] if ch else npu["sample_hz"]
        pmu = (
            (ch["pmu"]["count"], tuple(ch["pmu"].get("events", [])), ch["pmu"].get("status"))
            if ch
            else None,
            (
                npu["pmu_count"],
                tuple(npu[f"pmu_event{i}"] for i in range(npu["pmu_count"])),
                npu.get("pmu_status"),
            )
            if npu
            else None,
        )
        layout = (
            (
                ch["buffer_bytes"],
                ch["record_base_bytes"],
                ch.get("features"),
                ch.get("unwind_max_depth"),
            )
            if ch
            else None,
            (npu["buffer_bytes"], npu["record_bytes"], npu["format"]) if npu else None,
        )
        if stream_identity is None:
            stream_identity = identity
            elf_sha256 = cpu["elf_sha256"] if cpu else None
            sample_hz = rate
            pmu_counts = pmu
            buffer_layout = layout
        if identity != stream_identity:
            raise ValueError(
                f"{directory}: stream IDs/descriptors differ; cannot merge QREAD offsets"
            )
        if cpu and cpu["elf_sha256"] != elf_sha256:
            raise ValueError(f"{directory}: CPU reports use different firmware ELFs")
        if rate != sample_hz or (npu and npu["sample_hz"] != rate):
            raise ValueError(f"{directory}: sample rate differs between captures or processors")
        if pmu != pmu_counts:
            raise ValueError(f"{directory}: PMU configuration differs between captures")
        if layout != buffer_layout:
            raise ValueError(f"{directory}: buffer sizes or record formats differ between captures")
        if (ch and (ch["complete"] != 1 or ch["active"])) or (
            npu and (npu["complete"] != 1 or npu["active"])
        ):
            raise ValueError(f"{directory}: capture was not finalized")
        if npu and npu["total_samples"] != npu["running_samples"] + npu["idle_samples"]:
            raise ValueError(f"{directory}: Ethos-U tick totals disagree")

        row = {"capture": index, "capture_dir": directory.name}
        if cpu:
            row.update(
                {
                    "cpu_samples": ch["count"],
                    "cpu_unknown_pc": cpu["unknown_samples"],
                    "cpu_rejected": ch["rejected"],
                    "cpu_full": ch["full"],
                    "cpu_timing_valid": cpu["timing_valid"],
                    "cpu_validation_passed": ch["validation_passed"],
                    "frame_counter_at_stop": ch["iterations"],
                }
            )
        if npu:
            row.update(
                {
                    "ethosu_ticks": npu["total_samples"],
                    "ethosu_records": npu["count"],
                    "ethosu_running_ticks": npu["running_samples"],
                    "ethosu_idle_ticks": npu["idle_samples"],
                    "ethosu_records_saved": npu["total_samples"] - npu["count"],
                    "ethosu_full": npu["full"],
                    "ethosu_validation_passed": npu["validation_passed"],
                    "ethosu_invalid_qread": npu["invalid_qread"],
                    "ethosu_unknown_stream_samples": npu["unknown_stream_samples"],
                    "ethosu_unregistered_streams": npu["unregistered_streams"],
                    "ethosu_submissions": npu["streams_seen"],
                }
            )
        capture_rows.append(row)
        if cpu:
            for sample in read_csv(directory / "cortex_m_report/samples.csv"):
                cpu_rows.append({"capture": index, **sample})
            for function in read_csv(directory / "cortex_m_report/functions.csv"):
                functions[(function["address"], function["function"])] += int(function["hits"])
        if npu:
            for sample in read_csv(directory / "ethosu_report/samples.csv"):
                npu_rows.append({"capture": index, **sample})
            for sample in read_csv(directory / "ethosu_report/qread_histogram.csv"):
                qreads[(sample["stream_id"], int(sample["qread_bytes"]))] += int(sample["samples"])

    totals = {
        "captures": len(captures),
        "sample_hz": sample_hz,
        "all_validation_passed": all(
            (not components[0] or row["cpu_validation_passed"])
            and (not components[1] or row["ethosu_validation_passed"])
            for row in capture_rows
        ),
    }
    if components[0]:
        totals.update(
            {
                "cpu_pmu_count": pmu_counts[0][0],
                "cpu_samples": sum(row["cpu_samples"] for row in capture_rows),
                "cpu_unknown_pc": sum(row["cpu_unknown_pc"] for row in capture_rows),
                "cpu_rejected": sum(row["cpu_rejected"] for row in capture_rows),
                "all_cpu_timing_valid": all(row["cpu_timing_valid"] for row in capture_rows),
                "elf_sha256": elf_sha256,
            }
        )
        if len(cpu_rows) != totals["cpu_samples"]:
            raise ValueError("Cortex-M sample rows do not match the header counts")
    if components[1]:
        totals.update(
            {
                "ethosu_pmu_count": pmu_counts[1][0],
                "ethosu_ticks": sum(row["ethosu_ticks"] for row in capture_rows),
                "ethosu_records": sum(row["ethosu_records"] for row in capture_rows),
                "ethosu_running_ticks": sum(row["ethosu_running_ticks"] for row in capture_rows),
                "ethosu_idle_ticks": sum(row["ethosu_idle_ticks"] for row in capture_rows),
                "ethosu_records_saved": sum(row["ethosu_records_saved"] for row in capture_rows),
                "ethosu_invalid_qread": sum(row["ethosu_invalid_qread"] for row in capture_rows),
                "ethosu_unknown_stream_samples": sum(
                    row["ethosu_unknown_stream_samples"] for row in capture_rows
                ),
                "ethosu_unregistered_streams": sum(
                    row["ethosu_unregistered_streams"] for row in capture_rows
                ),
                "ethosu_submissions": sum(row["ethosu_submissions"] for row in capture_rows),
                "stream_identity": [
                    {"stream_id": sid, "command_address": address, "stream_bytes": int(size)}
                    for sid, address, size in stream_identity
                ],
            }
        )
        if len(npu_rows) != totals["ethosu_records"]:
            raise ValueError("Ethos-U record rows do not match the header counts")
        if sum(int(row["sample_count"]) for row in npu_rows) != totals["ethosu_ticks"]:
            raise ValueError("Ethos-U compressed record weights do not match represented ticks")
        if sum(qreads.values()) != sum(
            json.loads((directory / "ethosu_report/summary.json").read_text())["qread_samples"]
            for directory in captures
        ):
            raise ValueError("QREAD histogram totals do not match decoded QREAD samples")
        totals["ethosu_running_percent"] = (
            round(100 * totals["ethosu_running_ticks"] / totals["ethosu_ticks"], 2)
            if totals["ethosu_ticks"]
            else 0.0
        )

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "captures.csv", list(capture_rows[0]), capture_rows)
    if components[0]:
        write_csv(
            output / "cortex_m_samples.csv",
            list(cpu_rows[0]) if cpu_rows else ["capture"],
            cpu_rows,
        )
        write_csv(
            output / "cortex_m_functions.csv",
            ["address", "function", "hits", "percent_of_cpu_samples"],
            (
                {
                    "address": address,
                    "function": function,
                    "hits": hits,
                    "percent_of_cpu_samples": round(100 * hits / totals["cpu_samples"], 2)
                    if totals["cpu_samples"]
                    else 0.0,
                }
                for (address, function), hits in sorted(
                    functions.items(), key=lambda item: (-item[1], item[0])
                )
            ),
        )
    if components[1]:
        write_csv(
            output / "ethosu_samples.csv", list(npu_rows[0]) if npu_rows else ["capture"], npu_rows
        )
        write_csv(
            output / "ethosu_qread_histogram.csv",
            ["stream_id", "qread_bytes", "qread_hex", "samples", "percent_of_running_samples"],
            (
                {
                    "stream_id": sid,
                    "qread_bytes": offset,
                    "qread_hex": f"0x{offset:06X}",
                    "samples": hits,
                    "percent_of_running_samples": round(
                        100 * hits / totals["ethosu_running_ticks"], 2
                    )
                    if totals["ethosu_running_ticks"]
                    else 0.0,
                }
                for (sid, offset), hits in sorted(
                    qreads.items(), key=lambda item: (-item[1], item[0])
                )
            ),
        )
    (output / "summary.json").write_text(json.dumps(totals, indent=2) + "\n")
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "captures", nargs="*", type=Path, help="capture directories in aggregation order"
    )
    parser.add_argument(
        "--input-dir", type=Path, help="discover capture directories below this directory"
    )
    parser.add_argument(
        "--pattern",
        default="capture_*",
        help="directory glob with --input-dir (default: capture_*)",
    )
    parser.add_argument("--output-dir", type=Path, help="output directory (default: --input-dir)")
    args = parser.parse_args(argv)
    captures, output = select_captures(args, parser)
    try:
        totals = aggregate(captures, output)
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"aggregation failed: {error}\n")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
