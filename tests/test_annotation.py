# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0

# ----------------------------------------------------------------------
# Project:      CMSIS Statistical Profiler
# Title:        test_annotation.py
# Description:  Instruction-group annotation regression tests
#
# $Date:        5 October 2026
# $Revision:    V.1.0.3
#
# Target :  Arm(R) M-Profile Architecture
# ----------------------------------------------------------------------

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_integration_tools import elf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import annotate_profiler_report as annotate


GNU = """
00001000 <leaf>:
    1000:\tldr.w\tr0, [r1]
    1004:\tadds\tr0, #1
    1006:\tbne.n\t1000 <leaf>
    1008:\tbx\tlr
    100a:\t.short\t0x1234
"""
LLVM = """
00001000 <leaf>:
    1000:      \tldr.w\tr0, [r1]
    1004:      \tadds\tr0, #1
    1006:      \tbne.n\t0x1000 <leaf>
    1008:      \tbx\tlr
    100a:      \t<unknown>
"""


class AnnotationTests(unittest.TestCase):
    def fixture(self, root):
        binary = root / "firmware.elf"
        data = elf()
        binary.write_bytes(data)
        (root / "summary.json").write_text(
            json.dumps(
                {"elf_sha256": hashlib.sha256(data).hexdigest(), "header": {"count": 4}}
            )
        )
        (root / "samples.csv").write_text(
            "sample,pc\n0,0x1000\n1,0x1004\n2,0x1004\n3,0x2000\n"
        )
        (root / "functions.csv").write_text(
            "address,function\n0x1000,leaf()\n0x2000,parent\n"
        )
        return binary

    def test_mixed_width_groups_and_unmatched_hits(self):
        for text in (GNU, LLVM):
            instructions = annotate.parse_disassembly(text, 0x1000, 16)
            self.assertEqual(
                [pc for pc, _ in instructions], [0x1000, 0x1004, 0x1006, 0x1008]
            )
            # 0x1002 lies inside the 32-bit LDR; it must not be rounded down.
            result = annotate.render_function(
                "leaf",
                0x1000,
                instructions,
                Counter({0x1000: 2, 0x1004: 1, 0x1008: 1, 0x1002: 1}),
                10,
                3,
            )
            self.assertIn("5 samples, 50.00% of capture", result)
            self.assertIn("3 hits | 60.00% of function | 3 instructions", result)
            self.assertIn("1 hits | 20.00% of function | 1 instructions", result)
            self.assertIn("1 hits do not match", result)
            single = annotate.render_function(
                "leaf", 0x1000, instructions, Counter(), 0, 1, show_zero_hit_groups=True
            )
            self.assertEqual(single.count("| 1 instructions"), 4)

    def test_zero_hit_groups_hidden_without_moving_boundaries(self):
        instructions = [(0x1000 + 2 * i, "nop") for i in range(10)]
        hits = Counter({0x1004: 3, 0x1010: 1})
        text = annotate.render_function("leaf", 0x1000, instructions, hits, 4, 2)
        self.assertNotIn("------- 0 hits", text)
        self.assertIn("3 hits | 75.00%", text)
        self.assertIn("00001004    nop\n00001006    nop", text)
        self.assertIn("... 3 zero-hit group(s) omitted ...", text)
        self.assertNotIn("00001008", text)
        full = annotate.render_function("leaf", 0x1000, instructions, hits, 4, 2, True)
        self.assertEqual(full.count("------- 0 hits"), 3)
        self.assertNotIn("omitted", full)
        empty = annotate.render_function("leaf", 0x1000, instructions, Counter(), 0, 2)
        self.assertIn("... 5 zero-hit group(s) omitted ...", empty)

    def test_groups_sorted_by_sample_share_with_address_tiebreak(self):
        instructions = [(0x1000 + 2 * i, "nop") for i in range(8)]
        hits = Counter({0x1000: 1, 0x1004: 3, 0x1008: 3, 0x100c: 2})
        text = annotate.render_function("leaf", 0x1000, instructions, hits, 9, 2)
        self.assertLess(text.index("00001004"), text.index("00001008"))
        self.assertLess(text.index("00001008"), text.index("0000100c"))
        self.assertLess(text.index("0000100c    nop"), text.index("00001000    nop"))
        self.assertEqual(text.count("3 hits | 33.33%"), 2)

    def test_objdump_discovery_and_explicit_failure(self):
        with patch.object(
            annotate.shutil,
            "which",
            side_effect=lambda name: (
                "/tools/llvm-objdump" if name == "llvm-objdump" else None
            ),
        ):
            self.assertEqual(annotate.find_objdump(), "/tools/llvm-objdump")
            with self.assertRaisesRegex(ValueError, "--objdump"):
                annotate.find_objdump("/missing/explicit-tool")
        with patch.object(annotate.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "objdump not found"):
                annotate.find_objdump()

    def test_report_identity_count_and_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            functions, names, hits, total, unknown = annotate.read_report(root, binary)
            self.assertEqual((total, unknown), (4, 0))
            self.assertEqual(names[0x1000], "leaf()")
            index = next(i for i, row in enumerate(functions) if row[0] == 0x1000)
            self.assertEqual(sum(hits[index].values()), 3)
            with (root / "samples.csv").open("a") as stream:
                stream.write("4,0x1000\n")
            with self.assertRaisesRegex(ValueError, "count differs"):
                annotate.read_report(root, binary)
            binary.write_bytes(b"wrong ELF")
            with self.assertRaisesRegex(ValueError, "ELF hash differs"):
                annotate.read_report(root, binary)

    def test_cli_selection_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            tool = root / "fake objdump"
            tool.write_text(f"#!{sys.executable}\nprint({GNU!r})\n")
            tool.chmod(0o755)
            command = [
                sys.executable,
                str(ROOT / "host/annotate_profiler_report.py"),
                "--report",
                str(root),
                "--elf",
                str(binary),
                "--objdump",
                str(tool),
                "--view",
                "groups",
            ]
            summary = subprocess.run(
                command[:-2] + ["--top", "1"], capture_output=True, text=True
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn("HOTSPOTS (self PC samples)", summary.stdout)
            self.assertIn("F1", summary.stdout)
            self.assertNotIn("------- 3 hits", summary.stdout)
            for selection in (
                ["--top", "1"],
                ["--function", "leaf()"],
                ["--function", "0x1000"],
            ):
                result = subprocess.run(
                    command + selection + ["--group-instructions", "3"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("leaf() @ 0x00001000: 3 samples, 75.00%", result.stdout)
                self.assertIn("3 hits | 100.00%", result.stdout)
                self.assertNotIn("parent @", result.stdout)
            for args in (
                ["--group-instructions", "0"],
                ["--hotspot-limit", "0"],
                ["--top", "-1"],
                ["--function", "absent"],
            ):
                self.assertNotEqual(
                    subprocess.run(command + args, capture_output=True).returncode, 0
                )
            tool.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(2)\n")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("objdump failed", result.stderr)

    def test_batched_source_locations_and_missing_debug(self):
        instructions = [(0x1000, "nop"), (0x1002, "nop"), (0x1004, "bx lr")]
        for output in (
            "file.c:12 (discriminator 2)\nfile.c:13\n??:0\n",
            "file.c:12:4\nfile.c:13\n??:0\n",
        ):
            with patch.object(
                annotate.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout=output, stderr=""
                ),
            ) as run:
                locations = annotate.source_locations(
                    "addr2line", Path("firmware.elf"), instructions
                )
                self.assertEqual(
                    locations, {0x1000: ("file.c", 12), 0x1002: ("file.c", 13)}
                )
                run.assert_called_once()
                self.assertEqual(
                    run.call_args.kwargs["input"], "0x1000\n0x1002\n0x1004\n"
                )
        with patch.object(
            annotate.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout="??:0\n", stderr=""),
        ):
            with self.assertRaisesRegex(ValueError, "1 location per instruction"):
                annotate.source_locations(
                    "addr2line", Path("firmware.elf"), instructions
                )

    def test_source_snippets_dedup_remap_and_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "kernel.c").write_text("void kernel(void) {\n    work();\n}\n")
            group = [(0x1000, "nop"), (0x1002, "nop")]
            locations = {pc: ("/old/source/kernel.c", 2) for pc, _ in group}
            maps = [("/old/source", directory)]
            cache = {}
            lines = annotate.source_snippet(group, locations, cache, maps)
            self.assertEqual(lines, ["; /old/source/kernel.c:2: work();"])
            # The same source file is reused across groups without rereading it.
            (root / "kernel.c").unlink()
            self.assertEqual(
                annotate.source_snippet(group, locations, cache, maps), lines
            )
            self.assertIn(
                "source file unavailable",
                annotate.source_snippet(group, locations, {}, maps)[0],
            )
            self.assertIn(
                "no line information", annotate.source_snippet(group, {}, {}, ())[0]
            )
            (root / "kernel.c").write_text("short file\n")
            self.assertIn(
                "check source version",
                annotate.source_snippet(group, locations, {}, maps)[0],
            )

    def test_source_cli_and_tool_selection(self):
        with patch.object(
            annotate.shutil,
            "which",
            side_effect=lambda name: (
                "/tools/llvm-addr2line" if name == "llvm-addr2line" else None
            ),
        ):
            self.assertEqual(annotate.find_addr2line(), "/tools/llvm-addr2line")
            with self.assertRaisesRegex(ValueError, "--addr2line"):
                annotate.find_addr2line("missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            dump = root / "objdump"
            dump.write_text(f"#!{sys.executable}\nprint({GNU!r})\n")
            dump.chmod(0o755)
            resolver = root / "addr2line"
            resolver.write_text(
                f"#!{sys.executable}\nimport sys\nfor line in sys.stdin: print('/old/kernel.c:1')\n"
            )
            resolver.chmod(0o755)
            (root / "kernel.c").write_text("work();\n")
            command = [
                sys.executable,
                str(ROOT / "host/annotate_profiler_report.py"),
                "--report",
                str(root),
                "--elf",
                str(binary),
                "--objdump",
                str(dump),
                "--view",
                "groups",
                "--top",
                "1",
                "--source",
                "--addr2line",
                str(resolver),
                "--source-map",
                f"/old={root}",
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("; /old/kernel.c:1: work();"), 1)
            self.assertIn("3 hits | 100.00%", result.stdout)

    def test_disassembly_rejects_empty_and_overlapping_ranges(self):
        for text in ("no disassembly", "1000: nop\n1000: bx lr"):
            with self.assertRaises(ValueError):
                annotate.parse_disassembly(text, 0x1000, 16)

    def test_disassembly_forwards_target_architecture(self):
        with patch.object(
            annotate.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=GNU, stderr=""),
        ) as run:
            instructions = annotate.disassemble(
                "objdump", Path("firmware.elf"), 0x1000, 16, ("-m", "armv8.1-m.main")
            )
            self.assertEqual(len(instructions), 4)
            self.assertEqual(run.call_args.args[0][1:3], ["-m", "armv8.1-m.main"])

    def test_hotspot_view_ranks_functions_source_lines_and_pcs(self):
        annotated = [
            (
                "leaf",
                0x1000,
                [(0x1000, "nop"), (0x1002, "add r0, #1")],
                Counter({0x1000: 2, 0x1002: 1}),
                {0x1000: ("/src/kernel.c", 7), 0x1002: ("/src/kernel.c", 8)},
            ),
            (
                "parent",
                0x2000,
                [(0x2000, "bx lr")],
                Counter({0x2000: 4}),
                {0x2000: ("/src/kernel.c", 7)},
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "kernel.c").write_text("\n" * 6 + "work();\nreturn;\n")
            text = annotate.render_hotspots(
                annotated, 10, 2, {}, (("/src", directory),)
            )
        self.assertIn("7 of 10 samples (70.00% of capture)", text)
        self.assertLess(text.index("kernel.c:7: work();"), text.index("kernel.c:8: return;"))
        self.assertIn("60.00%        6  kernel.c:7", text)
        self.assertLess(text.index("0x00002000"), text.index("0x00001000  nop"))
        self.assertIn("40.00%        4  F2", text)
