from pathlib import Path
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import pikepdf

import simplify_pdf_plan_to_svg


SCRIPT = Path(__file__).resolve().parents[1] / "simplify_pdf_plan_to_svg.py"


class OutputTests(unittest.TestCase):
    def test_responsive_dimensions(self):
        template = '<svg width="100pt" height="200pt" viewBox="0 0 100 200">{}</svg>'
        result = simplify_pdf_plan_to_svg.prepare_svg(template.format(""))
        root = ET.fromstring(result)
        self.assertEqual(root.attrib["width"], "100%")
        self.assertEqual(root.attrib["height"], "100%")
        self.assertEqual(root.attrib["viewBox"], "0 0 100 200")
        self.assertEqual(root.attrib["preserveAspectRatio"], "xMidYMid meet")

class DependencyTests(unittest.TestCase):
    def test_installs_pikepdf_if_missing(self):
        missing = ModuleNotFoundError("No module named 'pikepdf'", name="pikepdf")
        with mock.patch.object(
            simplify_pdf_plan_to_svg.importlib, "import_module", side_effect=[missing, pikepdf]
        ), mock.patch.object(simplify_pdf_plan_to_svg.subprocess, "run") as run:
            self.assertIs(simplify_pdf_plan_to_svg.load_pikepdf(), pikepdf)
            run.assert_called_once_with(
                [sys.executable, "-m", "pip", "install", "pikepdf>=9.0"], check=True
            )

    def test_failed_installation_is_reported(self):
        missing = ModuleNotFoundError("No module named 'pikepdf'", name="pikepdf")
        with mock.patch.object(
            simplify_pdf_plan_to_svg.importlib, "import_module", side_effect=missing
        ), mock.patch.object(
            simplify_pdf_plan_to_svg.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "pip"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not install pikepdf"):
                simplify_pdf_plan_to_svg.load_pikepdf()


@unittest.skipUnless(shutil.which("pdftocairo"), "pdftocairo is required")
class ConversionTests(unittest.TestCase):
    def test_rotated_pages_and_short_strokes(self):
        cases = {
            0: ("M10 180l30 0", "M11 179l0.2 0"),
            90: ("M20 10l0 30", "M21 11l0 0.2"),
            180: ("M60 20l30 0", "M88.8 21l0.2 0"),
            270: ("M180 60l0 30", "M179 88.8l0 0.2"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for rotation, expected_paths in cases.items():
                with self.subTest(rotation=rotation):
                    source = Path(directory) / f"drawing-{rotation}.pdf"
                    pdf = pikepdf.Pdf.new()
                    page = pdf.add_blank_page(page_size=(100, 200))
                    page.obj["/Rotate"] = rotation
                    page.Contents = pdf.make_stream(
                        b"10 20 m 40 20 l S 11 21 m 11.2 21 l S"
                    )
                    pdf.save(source)
                    subprocess.run(
                        [sys.executable, str(SCRIPT), str(source)],
                        capture_output=True, text=True, check=True,
                    )
                    svg = source.with_name(f"drawing-{rotation}_merged.svg").read_text(
                        encoding="utf-8"
                    )
                    root = ET.fromstring(svg)
                    expected_viewbox = (
                        "0 0 200 100" if rotation in (90, 270) else "0 0 100 200"
                    )
                    self.assertEqual(root.attrib["viewBox"], expected_viewbox)
                    self.assertEqual(root.attrib["width"], "100%")
                    self.assertEqual(root.attrib["height"], "100%")
                    for expected in expected_paths:
                        self.assertIn(expected, svg)

    def test_warning_only_when_output_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "drawing.pdf"
            output = source.with_name("drawing_merged.svg")
            pdf = pikepdf.Pdf.new()
            pdf.add_blank_page(page_size=(100, 100))
            pdf.save(source)
            for limit, warning_expected in ((1, True), (2_000_000, False)):
                stderr = io.StringIO()
                with mock.patch.object(simplify_pdf_plan_to_svg, "MAX_SVG_BYTES", limit):
                    with contextlib.redirect_stderr(stderr):
                        simplify_pdf_plan_to_svg.convert_pdf(source, output, 0, 1)
                self.assertEqual("Warning:" in stderr.getvalue(), warning_expected)
                self.assertEqual(ET.parse(output).getroot().tag, "{http://www.w3.org/2000/svg}svg")
            actual_size = output.stat().st_size
            for limit, warning_expected in ((actual_size, False), (actual_size - 1, True)):
                stderr = io.StringIO()
                with mock.patch.object(simplify_pdf_plan_to_svg, "MAX_SVG_BYTES", limit):
                    with contextlib.redirect_stderr(stderr):
                        simplify_pdf_plan_to_svg.convert_pdf(source, output, 0, 1)
                self.assertEqual("Warning:" in stderr.getvalue(), warning_expected)

    def test_threshold_removes_short_paths_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "drawing.pdf"
            pdf = pikepdf.Pdf.new()
            page = pdf.add_blank_page(page_size=(100, 100))
            page.Contents = pdf.make_stream(b"10 10 m 10.2 10 l S")
            pdf.save(source)
            subprocess.run(
                [sys.executable, str(SCRIPT), str(source), "-t", "0.5"],
                capture_output=True, text=True, check=True,
            )
            svg = source.with_name("drawing_merged.svg").read_text(encoding="utf-8")
            self.assertNotIn("M10 90l0.2 0", svg)

    def test_round_cap_dots_are_preserved_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "drawing.pdf"
            pdf = pikepdf.Pdf.new()
            page = pdf.add_blank_page(page_size=(100, 100))
            page.Contents = pdf.make_stream(
                b"1 J 10 10 m 10 10 l S 0 J 20 20 m 20 20 l S"
            )
            pdf.save(source)
            subprocess.run(
                [sys.executable, str(SCRIPT), str(source)],
                capture_output=True, text=True, check=True,
            )
            svg = source.with_name("drawing_merged.svg").read_text(encoding="utf-8")
            self.assertIn("M10 90l0 0", svg)
            self.assertNotIn("M20 80l0 0", svg)

    def test_selected_page_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="pdf svg test ") as directory:
            source = Path(directory) / "drawing (1).pdf"
            pdf = pikepdf.Pdf.new()
            first = pdf.add_blank_page(page_size=(100, 100))
            first.Contents = pdf.make_stream(b"1 0 0 rg 10 10 20 20 re f")
            second = pdf.add_blank_page(page_size=(100, 100))
            second.Contents = pdf.make_stream(
                b"0 0 1 rg 30 30 20 20 re f 10 10 m 50 10 l 90 10 l S"
            )
            pdf.save(source)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), "--page", "2"],
                capture_output=True,
                text=True,
                check=True,
            )
            output = source.with_name("drawing (1)_merged.svg")
            svg = output.read_text(encoding="utf-8")
            ET.fromstring(svg)
            self.assertIn("M10 90l80 0", svg)
            self.assertIn('fill="rgb(0%, 0%, 100%)"', svg)
            self.assertNotIn('fill="rgb(100%, 0%, 0%)"', svg)
            self.assertIn("polylines after merging: 1", result.stdout)

    def test_invalid_page_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "drawing.pdf"
            pdf = pikepdf.Pdf.new()
            pdf.add_blank_page(page_size=(100, 100))
            pdf.save(source)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), "--page", "2"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("out of range", result.stderr)
            self.assertFalse(source.with_name("drawing_merged.svg").exists())


if __name__ == "__main__":
    unittest.main()
