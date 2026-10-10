# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        create_profiler_report.py
# Description:  Package decoded captures and local visualizations
#
# $Date:        2 October 2026
# $Revision:    V.1.0.1
#
# Target :  Arm(R) M-Profile Architecture
#
# ----------------------------------------------------------------------

"""Decode and package a local report with exact inputs, provenance and optional visualizations."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def sha256(path):
    """Identify archived bytes; this does not verify which firmware made a capture."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", type=Path, required=True)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="New or empty report directory")
    p.add_argument("--board", required=True, help="Actual board or simulator used for capture")
    p.add_argument("--application", required=True, help="Application name")
    p.add_argument("--platform", type=Path, help="Verified platform.json to copy into the report")
    p.add_argument("--stack-root")
    p.add_argument("--html", action="store_true", help="Also render the Plotly dashboard")
    p.add_argument("--flamegraph", type=Path, help="Local flamegraph.pl; requires Perl")
    p.add_argument(
        "--compiler-id", default="unknown", help="Application compiler identity, supplied by caller"
    )
    p.add_argument(
        "--producer-revision",
        default="unknown",
        help="Firmware profiler revision, supplied by caller",
    )
    p.add_argument(
        "--capture-command", default="unknown", help="Capture/export command, supplied by caller"
    )
    p.add_argument("--cxxfilt")
    p.add_argument("--no-demangle", action="store_true")
    args = p.parse_args()
    try:
        if args.output.exists() and any(args.output.iterdir()):
            raise ValueError(
                "Use a new or empty output directory to avoid mixing captures or stale exports"
            )
        args.output.mkdir(parents=True, exist_ok=True)
        inputs = args.output / "inputs"
        inputs.mkdir()
        # Snapshot first: every downstream tool and hash sees these exact bytes.
        shutil.copyfile(args.samples, inputs / "samples.bin")
        shutil.copyfile(args.elf, inputs / "firmware.elf")
        if args.platform:
            shutil.copyfile(args.platform, args.output / "platform.json")
        commands = []

        def run(command, **kwargs):
            """Record exact arguments and invoke tools without shell interpretation."""
            commands.append([str(x) for x in command])
            subprocess.run(commands[-1], check=True, **kwargs)

        decode = [
            sys.executable,
            HERE / "analyze_profiler_buffer.py",
            "--samples",
            inputs / "samples.bin",
            "--elf",
            inputs / "firmware.elf",
            "--output",
            args.output,
        ]
        for key in ("stack_root", "cxxfilt"):
            if getattr(args, key):
                decode += ["--" + key.replace("_", "-"), getattr(args, key)]
        if args.no_demangle:
            decode += ["--no-demangle"]
        run(decode)
        summary = json.loads((args.output / "summary.json").read_text())
        problems = []
        visualize = [sys.executable, HERE / "visualize_profiler_report.py", "--report", args.output]
        if args.html:
            visualize += ["--html"]
        # Keep successfully decoded data if an optional renderer fails. Record
        # the problem in the package and return failure after writing its index.
        try:
            run(visualize)
        except subprocess.CalledProcessError:
            problems.append(
                "Visualization failed; inspect capture timing and optional Plotly dependency. Decoded data retained."
            )
        graph = summary.get("flamegraph")
        if args.flamegraph:
            if not graph or not graph["included_samples"]:
                problems.append("Flamegraph omitted: no included backtraces.")
            else:
                svg = args.output / "flamegraph.svg"
                try:
                    with svg.open("w") as stream:
                        run(
                            [
                                "perl",
                                args.flamegraph.resolve(),
                                "--countname",
                                "samples",
                                "--subtitle",
                                graph["subtitle"],
                                args.output / "stacks.folded",
                            ],
                            stdout=stream,
                        )
                except (OSError, subprocess.CalledProcessError):
                    svg.unlink(missing_ok=True)
                    problems.append(
                        "Flamegraph renderer failed; folded stacks and warning subtitle retained."
                    )
        try:
            revision = subprocess.check_output(
                ["git", "-C", str(HERE), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            dirty = bool(
                subprocess.check_output(
                    ["git", "-C", str(HERE), "status", "--porcelain"], text=True
                )
            )
        except (OSError, subprocess.CalledProcessError):
            revision, dirty = "unknown", None
        try:
            plotly_version = metadata.version("plotly")
        except metadata.PackageNotFoundError:
            plotly_version = None
        # Separate measured artifact hashes from caller-supplied build labels.
        # Together they make a report reproducible, not authenticated to a device.
        manifest = dict(
            board=args.board,
            application=args.application,
            plotly=plotly_version,
            python=platform.python_version(),
            host_revision=revision,
            host_dirty=dirty,
            producer_revision=args.producer_revision,
            compiler_id=args.compiler_id,
            capture_command=args.capture_command,
            commands=commands,
            configuration=summary["header"],
            validation_passed=summary["header"]["validation_passed"],
            timing_valid=summary["timing_valid"],
            problems=problems,
            hashes={
                "samples.bin": sha256(inputs / "samples.bin"),
                "firmware.elf": sha256(inputs / "firmware.elf"),
            },
            host_tools={f.name: sha256(f) for f in HERE.glob("*.py")},
            provenance_note="Compiler, producer revision and capture command are caller supplied, not embedded firmware identity.",
        )
        if args.flamegraph and args.flamegraph.is_file():
            manifest["flamegraph_sha256"] = sha256(args.flamegraph)
        if args.platform:
            manifest["hashes"]["platform.json"] = sha256(args.output / "platform.json")
        index_command = [
            str(value)
            for value in (
                sys.executable,
                HERE / "generate_report_index.py",
                "--run-dir",
                args.output,
                "--board",
                args.board,
                "--application",
                args.application,
            )
        ]
        commands.append(index_command)
        header = summary["header"]
        note = graph["subtitle"] if graph else "PC/PMU sampling; no backtraces."
        report = [
            f"# {args.application} · profiling report",
            "",
            f"Board / target: {args.board}",
            "",
            f"Sampling rate: {header['sample_hz']} Hz; samples: {header['count']}.",
            f"Capture complete={header['complete']}, active={header['active']}, "
            f"full={header['full']}, validation_passed={header['validation_passed']}.",
            f"Timing valid: {summary['timing_valid']}; rejected frames: {header['rejected']}; "
            f"unresolved PCs: {summary['unknown_samples']}.",
            "",
            summary["notes"],
            "",
            note,
            "",
            "Stack inclusion and reaching a selected root do not prove stack accuracy.",
            "",
            "Exact inputs: [capture](inputs/samples.bin), [ELF](inputs/firmware.elf).",
            "[Decoded metadata](summary.json) and [provenance](manifest.json) retain "
            "configuration, hashes, tool versions and caller-supplied build labels.",
            "",
        ]
        if problems:
            report += ["## Incomplete optional outputs", "", *problems, ""]
        (args.output / "REPORT.md").write_text("\n".join(report))
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # All optional artifacts and their diagnostics are ready before indexing.
        subprocess.run(index_command, check=True)
        if problems:
            p.exit(1, "\n".join(problems) + "\n")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        p.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
