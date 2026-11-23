# PDF Plan to SVG Simplifier

`simplify_pdf_plan_to_svg.py` converts vector PDF drawings into SVG. It merges repeated and collinear straight segments to reduce SVG size, then uses `pdftocairo` to keep text and other elements that are not simplified.

## Requirements

- Python 3.10 or later
- Poppler, which provides the `pdftocairo` command
- The Python dependencies listed in `requirements.txt` (`pikepdf`)

### Installation

Windows (PowerShell):

1. Install Python 3.10 or later and Poppler for Windows.
2. Add Poppler's `bin` directory to `PATH`, open a new PowerShell window, and verify that `pdftocairo -v` works.
3. In the project directory, create a virtual environment and install the Python dependency:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux (Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install poppler-utils
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

macOS (with Homebrew):

```bash
brew install poppler
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Usage

On Windows, run from the project directory:

```powershell
.\.venv\Scripts\python.exe simplify_pdf_plan_to_svg.py plan.pdf
```

On Linux or macOS, with the virtual environment activated:

```bash
python3 simplify_pdf_plan_to_svg.py plan.pdf
```

By default, the script reads the first page and creates `plan_merged.svg` beside the PDF. To choose the output path, page, or short-stroke threshold on Windows:

```powershell
.\.venv\Scripts\python.exe simplify_pdf_plan_to_svg.py plan.pdf -o result.svg -p 2 -t 0.5
```

On Linux or macOS:

```bash
python3 simplify_pdf_plan_to_svg.py plan.pdf -o result.svg -p 2 -t 0.5
```

Options:

- `-o, --output`: path for the output SVG.
- `-p, --page`: PDF page number, starting at `1`.
- `-t, --threshold`: maximum length in PDF points for removing isolated short strokes. The default is `0.96`; `0` only removes duplicate or zero-length segments.
- `-h, --help`: show command-line help.

## What it simplifies and known limitations

- It extracts and merges only simple paths made of `moveto`/`lineto` operators and painted with the PDF `S` operator.
- Extracted paths are rendered in black; this stage does not preserve their original colors or dashed-line styles, and does not simplify curves or filled paths.
- Clipping paths are not applied to extracted segments. Some graphics-state operators (`gs`) are not preserved in the intermediate PDF.
- Rotated pages may have the wrong orientation.
- The input PDF is not modified, and the output cannot overwrite the source PDF.

The script reports input, page, dependency, and conversion errors in the terminal. It also warns when the selected page is rotated.
