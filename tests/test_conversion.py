from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import pikepdf


SCRIPT = Path(__file__).resolve().parents[1] / "simplify_pdf_plan_to_svg.py"


@unittest.skipUnless(shutil.which("pdftocairo"), "pdftocairo is required")
class ConversionTests(unittest.TestCase):
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
