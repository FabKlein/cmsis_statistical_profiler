import html
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
import visualize_profiler_report as visualizer


class SymbolLabelTests(unittest.TestCase):
    def test_limit_identity_and_overloads(self):
        self.assertEqual(visualizer.compact_symbol("arm_nn_kernel"), "arm_nn_kernel")
        self.assertEqual(visualizer.compact_symbol("x" * 120), "x" * 120)
        name = "namespace::kernel<" + "LongType, " * 40 + ">(int) const"
        for limit in (40, 100, 120):
            label = visualizer.compact_symbol(name, limit)
            self.assertEqual(len(label), limit)
            self.assertTrue(label.startswith("namespace"))
            self.assertIn("const", label)
            if limit >= 100:
                self.assertIn(">(int) const", label)
            self.assertEqual(label, visualizer.compact_symbol(name, limit))
        other = name.replace("LongType, ", "OtherType, ", 1)
        self.assertNotEqual(visualizer.compact_symbol(name), visualizer.compact_symbol(other))
        with self.assertRaises(ValueError):
            visualizer.compact_symbol(name, 39)

    def test_hover_escapes_and_wraps(self):
        name = '<script title="bad">' + "X" * 300 + "</script>"
        hover = visualizer.symbol_hover(name)
        self.assertNotIn("<script", hover)
        self.assertIn("&lt;script", hover)
        self.assertTrue(all(len(html.unescape(line)) <= 110 for line in hover.split("<br>")))

    def test_perfetto_preserves_full_name(self):
        name = "kernel<" + "Type" * 60 + ">(float)"
        samples = [{"function": name, "time_us": 1, "pc": "0x1000", "lr": "0x2000"}]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "trace.json"
            visualizer.write_perfetto(destination, {}, samples, [], [], 100)
            events = json.loads(destination.read_text())["traceEvents"]
        sample = next(event for event in events if event.get("cat") == "pc.sample")
        self.assertEqual(len(sample["name"]), 100)
        self.assertEqual(sample["args"]["function"], name)
        self.assertEqual(samples[0]["function"], name)

    @unittest.skipUnless(importlib.util.find_spec("plotly"), "Plotly not installed")
    def test_html_keeps_full_hover_and_distinct_categories(self):
        import plotly.graph_objects as graph

        names = ['kernel<"' + "Type" * 60 + '">(int)',
                 'kernel<"' + "Type" * 60 + '">(float)']
        samples = [{"function": name, "time_us": index + 1, "sample": index,
                    "pc": "0x1000", "lr": "0x2000"} for index, name in enumerate(names)]
        figures = []

        def capture(figure, **kwargs):
            figures.append(figure.to_plotly_json())
            return "<div>plot</div>"

        with tempfile.TemporaryDirectory() as directory, patch.object(graph.Figure, "to_html", capture):
            destination = Path(directory) / "report.html"
            visualizer.write_html(destination, {"header": {}}, samples, [], [], 100)
            document = destination.read_text()
        for name in names:
            self.assertIn(f'title="{html.escape(name, quote=True)}"', document)
            self.assertIn(f"<code>{html.escape(name)}</code>", document)
        bars, timeline = figures
        self.assertEqual(len(set(bars["data"][0]["y"])), 2)
        for label in bars["layout"]["yaxis"]["ticktext"]:
            self.assertLessEqual(len(html.unescape(label)), 100)
        for trace in timeline["data"]:
            self.assertLessEqual(len(html.unescape(trace["name"])), 100)
            self.assertIn(trace["customdata"][0][3], [visualizer.symbol_hover(name) for name in names])


if __name__ == "__main__":
    unittest.main()
