# PDF Plan to SVG Simplifier

`simplify_pdf_plan_to_svg.py` converts vector PDF drawings into lightweight SVG. It merges repeated and nearly collinear straight segments and removes short stroked paths to reduce SVG size, then uses `pdftocairo` for the remaining elements.

## Requirements

- Python 3.10 or later
- Poppler, which provides the `pdftocairo` command
- `pip` and network access to install `pikepdf` automatically if it is missing

## Windows: setup and run

1. Install Python 3.10 or later with the Python launcher (`py`).
2. Extract Poppler for Windows next to `simplify_pdf_plan_to_svg.py`. The extracted folder must contain `pdftocairo.exe` under `Release-*/poppler-*/Library/bin` or `Release-*/Library/bin`.
3. Open PowerShell in the folder containing the script and run:

```powershell
py -3 .\simplify_pdf_plan_to_svg.py "Plan IHM_L15S T2_Gare_09BVC_S01-S1A (1)-Objet.pdf"
```

Replace the example PDF name with your own. Keep the quotes around paths containing spaces or parentheses. By default, the SVG is saved beside the PDF as `<PDF name>_merged.svg`.

No separate virtual environment or `pip` command is required: the script installs `pikepdf` in the active Python environment if missing. This requires `pip`, package-index access, and permission to install packages. Poppler is not installed automatically. If Poppler is on `PATH`, that installation is used first; if multiple extracted copies are found next to the script, keep only one or use `PATH` to choose.

## Linux and macOS: installation

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

## Additional usage

On Linux or macOS, with the virtual environment activated:

```bash
python3 simplify_pdf_plan_to_svg.py plan.pdf
```

By default, the script reads the first page. To choose the output path, page, or short-stroke threshold on Windows:

```powershell
py -3 .\simplify_pdf_plan_to_svg.py plan.pdf -o result.svg -p 2 -t 0.5
```

On Linux or macOS:

```bash
python3 simplify_pdf_plan_to_svg.py plan.pdf -o result.svg -p 2 -t 0.5
```

Options:

- `-o, --output`: path for the output SVG.
- `-p, --page`: PDF page number, starting at `1`.
- `-t, --threshold`: remove simple stroked paths whose total length is at or below this value in PDF points, even if they connect to other paths. The default is `0.96`; use `0` to keep short paths and round-cap dots.
- `-h, --help`: show command-line help.

The SVG uses the PDF page's orientation and aspect ratio and scales to the available browser viewport or container. For an embedded SVG, the page must give its container a defined size; it cannot detect the physical screen size.

For example, to fit the image within the browser window:

```html
<img src="plan_merged.svg" alt="Plan" style="width: 100vw; height: 100vh; object-fit: contain">
```

The default simplification targets smaller output but does not guarantee a size below 2 MB. The script writes the SVG even if it exceeds **2,000,000 bytes** (2 MB), and displays a warning with the actual size. Raising `-t` can remove more detail and may reduce the size further.

## What it simplifies and known limitations

- It extracts and merges only simple paths made of `moveto`/`lineto` operators and painted with the PDF `S` operator.
- Coordinates are rounded to 0.1 PDF point and nearly collinear points may be removed; small details can be lost.
- Extracted paths are rendered in black; this stage does not preserve their original colors or dashed-line styles, and does not simplify curves or filled paths.
- Clipping paths are not applied to extracted segments. Some graphics-state operators (`gs`) are not preserved in the intermediate PDF.
- Straight strokes on pages rotated by 90, 180, or 270 degrees are mapped to the rotated output.
- The input PDF is not modified, and the output cannot overwrite the source PDF.

The script reports input, page, dependency, and conversion errors in the terminal.
