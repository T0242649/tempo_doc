#!/usr/bin/env python3
"""Convert a vector PDF drawing into an SVG with merged straight strokes."""

from __future__ import annotations

import argparse
import collections
import importlib
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]
MAX_SVG_BYTES = 2_000_000


def multiply_matrices(a: Matrix, b: Matrix) -> Matrix:
    """Compose two PDF matrices using the PDF row-vector convention."""
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def format_number(value: float) -> str:
    """Format a number to one decimal place without trailing zeros or -0."""
    result = ("%.1f" % value).rstrip("0").rstrip(".")
    return "0" if result in ("-0", "") else result


def edge_key(a: Point, b: Point) -> tuple[Point, Point]:
    return (a, b) if a < b else (b, a)


def chain_segments(edges: set[tuple[Point, Point]]) -> list[list[Point]]:
    """Walk the segment graph and return polylines using every edge once."""
    adjacency: dict[Point, list[Point]] = collections.defaultdict(list)
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)

    used: set[tuple[Point, Point]] = set()
    paths: list[list[Point]] = []
    starts = sorted(adjacency, key=lambda point: (len(adjacency[point]) % 2 == 0, point))

    for start in starts:
        while any(edge_key(start, neighbor) not in used for neighbor in adjacency[start]):
            path = [start]
            current = start
            while True:
                options = [
                    neighbor
                    for neighbor in adjacency[current]
                    if edge_key(current, neighbor) not in used
                ]
                if not options:
                    break
                if len(path) > 1:
                    dx = current[0] - path[-2][0]
                    dy = current[1] - path[-2][1]
                    options.sort(
                        key=lambda point: -(
                            (point[0] - current[0]) * dx
                            + (point[1] - current[1]) * dy
                        )
                        / (
                            math.hypot(dx, dy)
                            * math.hypot(point[0] - current[0], point[1] - current[1])
                            + 1e-9
                        )
                    )
                next_point = options[0]
                used.add(edge_key(current, next_point))
                path.append(next_point)
                current = next_point
            paths.append(path)
    return paths


def remove_collinear_points(points: list[Point]) -> list[Point]:
    """Remove intermediate points lying on a straight line in the same direction."""
    if len(points) < 3:
        return points

    result = [points[0]]
    for index in range(1, len(points) - 1):
        a, b, c = result[-1], points[index], points[index + 1]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if abs(cross) >= 0.05 or dot <= 0:
            result.append(b)
    result.append(points[-1])
    return result


def make_path_data(points: list[Point]) -> str:
    """Build SVG path data using one absolute move and relative line commands."""
    first_x, first_y = points[0]
    data = f"M{format_number(first_x)} {format_number(first_y)}"
    previous_x, previous_y = first_x, first_y
    for x, y in points[1:]:
        data += f"l{format_number(x - previous_x)} {format_number(y - previous_y)}"
        previous_x, previous_y = x, y
    return data


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a vector PDF into a smaller SVG by merging straight strokes."
    )
    parser.add_argument("pdf", type=Path, help="input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output SVG file (default: <PDF name>_merged.svg)",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.96,
        help=(
            "remove simple stroked paths with total length <= this value in PDF points "
            "(default: 0.96; 0 keeps short paths)"
        ),
    )
    parser.add_argument("-p", "--page", type=int, default=1, help="page number (default: 1)")
    return parser


def load_pikepdf():
    try:
        return importlib.import_module("pikepdf")
    except ModuleNotFoundError as exc:
        if exc.name != "pikepdf":
            raise RuntimeError(f"Cannot load pikepdf: {exc}") from exc

    print("Installing missing dependency pikepdf using pip...", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pikepdf>=9.0"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Could not install pikepdf. Check the pip output and your network or permissions."
        ) from exc

    importlib.invalidate_caches()
    try:
        return importlib.import_module("pikepdf")
    except ImportError as exc:
        raise RuntimeError(f"Could not load pikepdf after installation: {exc}") from exc


def find_pdftocairo() -> str:
    renderer = shutil.which("pdftocairo")
    if renderer:
        return renderer

    if sys.platform == "win32":
        script_dir = Path(__file__).resolve().parent
        patterns = (
            "Release-*/poppler-*/Library/bin/pdftocairo.exe",
            "Release-*/Library/bin/pdftocairo.exe",
            "poppler-*/Library/bin/pdftocairo.exe",
            "poppler/Library/bin/pdftocairo.exe",
        )
        matches = sorted({
            path.resolve()
            for pattern in patterns
            for path in script_dir.glob(pattern)
            if path.is_file()
        })
        if len(matches) == 1:
            return str(matches[0])
        if len(matches) > 1:
            raise RuntimeError(
                "Multiple Poppler installations found next to the script. "
                "Keep one there or add the desired Poppler bin directory to PATH."
            )

    raise RuntimeError(
        "`pdftocairo` was not found. On Windows, extract Poppler next to the "
        "script or add its Library/bin directory to PATH (see README.md)."
    )


def prepare_svg(svg: str) -> bytes:
    """Make the SVG responsive and encode it as UTF-8."""
    root = re.search(r"<svg\b[^>]*>", svg)
    if root is None:
        raise RuntimeError("`pdftocairo` produced an SVG without an <svg> root.")
    tag = root.group()
    if not re.search(r"\bviewBox\s*=", tag):
        raise RuntimeError("`pdftocairo` produced an SVG without a viewBox.")
    for attribute in ("width", "height"):
        tag, count = re.subn(
            rf'\s{attribute}\s*=\s*(["\']).*?\1',
            f' {attribute}="100%"',
            tag,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"`pdftocairo` produced an SVG without {attribute}.")
    if re.search(r"\spreserveAspectRatio\s*=", tag):
        tag = re.sub(
            r'\spreserveAspectRatio\s*=\s*(["\']).*?\1',
            ' preserveAspectRatio="xMidYMid meet"',
            tag,
            count=1,
        )
    else:
        tag = tag[:-1] + ' preserveAspectRatio="xMidYMid meet">'
    return (svg[:root.start()] + tag + svg[root.end():]).encode("utf-8")


def convert_pdf(
    source: Path,
    output: Path,
    threshold: float,
    page_number: int,
) -> tuple[int, int, int]:
    if not source.is_file():
        raise RuntimeError(f"Input PDF does not exist or is not a file: {source}")
    if source.resolve() == output.resolve():
        raise RuntimeError("The output path must not overwrite the input PDF.")
    if not output.parent.is_dir():
        raise RuntimeError(f"Output directory does not exist: {output.parent}")

    pikepdf = load_pikepdf()
    renderer = find_pdftocairo()

    segments: dict[float, set[tuple[Point, Point]]] = collections.defaultdict(set)
    dots: dict[float, set[Point]] = collections.defaultdict(set)
    short_count = path_count = 0

    try:
        pdf_context = pikepdf.open(source)
    except pikepdf.PdfError as exc:
        raise RuntimeError(f"Could not open PDF '{source}': {exc}") from exc

    with pdf_context as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise RuntimeError(
                f"Page {page_number} is out of range; the PDF has {len(pdf.pages)} page(s)."
            )
        page = pdf.pages[page_number - 1]
        box = [float(value) for value in page.cropbox]
        x0, y0 = min(box[0], box[2]), min(box[1], box[3])
        page_width, page_height = abs(box[2] - box[0]), abs(box[3] - box[1])
        rotation = int(page.obj.get("/Rotate", 0)) % 360
        if rotation not in (0, 90, 180, 270):
            raise RuntimeError(f"Unsupported PDF page rotation: {rotation} degrees.")

        instructions = pikepdf.parse_content_stream(page)
        ctm: Matrix = (1, 0, 0, 1, 0, 0)
        point_caches: dict[Matrix, dict[Point, Point]] = {}
        graphics_stack: list[tuple[Matrix, float, int]] = []
        line_width = 1.0
        line_cap = 0
        pending = []
        remaining = []

        def to_page(x: float, y: float) -> Point:
            cache = point_caches.get(ctm)
            if cache is None:
                cache = point_caches[ctm] = {}
            source_point = (x, y)
            cached = cache.get(source_point)
            if cached is not None:
                return cached

            px = ctm[0] * x + ctm[2] * y + ctm[4] - x0
            py = ctm[1] * x + ctm[3] * y + ctm[5] - y0
            if rotation == 90:
                px, py = py, px
            elif rotation == 180:
                px, py = page_width - px, py
            elif rotation == 270:
                px, py = page_height - py, page_width - px
            else:
                py = page_height - py
            result = round(px, 1), round(py, 1)
            cache[source_point] = result
            return result

        def flush_pending() -> None:
            remaining.extend(pending)
            pending.clear()

        for operands, operator in instructions:
            name = str(operator)
            if name in ("m", "l"):
                pending.append((operands, operator))
                continue

            if (
                name == "S"
                and pending
                and str(pending[0][1]) == "m"
                and all(str(item[1]) == "l" for item in pending[1:])
            ):
                path_count += 1
                points = [
                    to_page(float(item[0][0]), float(item[0][1]))
                    for item in pending
                ]
                pending.clear()
                length = sum(
                    math.dist(points[index], points[index + 1])
                    for index in range(len(points) - 1)
                )
                if length == 0:
                    if threshold == 0 and line_cap == 1 and len(points) > 1:
                        scale = math.sqrt(abs(ctm[0] * ctm[3] - ctm[1] * ctm[2]))
                        width = round(max(line_width * scale, 0.1), 2)
                        dots[width].add(points[0])
                    else:
                        short_count += 1
                    continue
                if threshold > 0 and length <= threshold:
                    short_count += 1
                    continue
                scale = math.sqrt(abs(ctm[0] * ctm[3] - ctm[1] * ctm[2]))
                width = round(max(line_width * scale, 0.1), 2)
                for a, b in zip(points, points[1:]):
                    if a != b:
                        segments[width].add(edge_key(a, b))
                continue

            flush_pending()
            if name == "q":
                graphics_stack.append((ctm, line_width, line_cap))
            elif name == "Q":
                if not graphics_stack:
                    raise RuntimeError("Invalid PDF content stream: unmatched `Q` operator.")
                ctm, line_width, line_cap = graphics_stack.pop()
            elif name == "cm":
                ctm = multiply_matrices(tuple(float(value) for value in operands), ctm)
            elif name == "w":
                line_width = float(operands[0])
            elif name == "J":
                line_cap = int(operands[0])

            # Keep graphics-state operators other than `gs`, matching the original
            # conversion behavior for PDFs that use large Darken blend groups.
            if name != "gs":
                remaining.append((operands, operator))
        flush_pending()
        del instructions

        merged_group = [
            '<g fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round">'
        ]
        polyline_count = 0
        for width in sorted(segments.keys() | dots.keys()):
            edges = segments[width]
            paths = [
                remove_collinear_points(path) for path in chain_segments(edges)
            ]
            polyline_count += len(paths)
            data = "".join(make_path_data(path) for path in paths)
            data += "".join(
                f"M{format_number(x)} {format_number(y)}l0 0"
                for x, y in sorted(dots[width])
            )
            merged_group.append(f'<path stroke-width="{width}" d="{data}"/>')
        merged_group.append("</g>")

        remaining_content = pikepdf.unparse_content_stream(remaining)
        del remaining
        page.Contents = pdf.make_stream(remaining_content)
        if "/ExtGState" in page.Resources:
            del page.Resources["/ExtGState"]

        with tempfile.TemporaryDirectory(prefix="pdf-svg-") as temp_dir:
            temp_path = Path(temp_dir)
            rest_pdf = temp_path / "rest.pdf"
            rest_svg = temp_path / "rest.svg"
            pdf.save(rest_pdf)
            subprocess.run(
                [
                    renderer, "-svg", "-f", str(page_number), "-l", str(page_number),
                    str(rest_pdf), str(rest_svg),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            svg = rest_svg.read_text(encoding="utf-8")

    def round_path_numbers(match: re.Match[str]) -> str:
        def round_number(number_match: re.Match[str]) -> str:
            return format_number(float(number_match.group()))

        return re.sub(r"-?\d+\.\d+", round_number, match.group())

    svg = re.sub(r' d="[^"]*"', round_path_numbers, svg)
    closing_tag = re.search(r"</svg\s*>", svg, flags=re.IGNORECASE)
    if closing_tag is None:
        raise RuntimeError("`pdftocairo` produced an SVG without a closing </svg> tag.")
    svg = (
        svg[: closing_tag.start()]
        + "\n".join(merged_group)
        + "\n"
        + svg[closing_tag.start() :]
    )
    data = prepare_svg(svg)
    output.write_bytes(data)
    if len(data) > MAX_SVG_BYTES:
        print(
            f"Warning: SVG is {len(data):,} bytes, exceeding 2,000,000 bytes (2 MB).",
            file=sys.stderr,
        )
    return path_count, short_count, polyline_count


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.threshold) or args.threshold < 0:
        parser.error("--threshold must be a finite number greater than or equal to 0.")
    if args.page < 1:
        parser.error("--page must be a positive integer.")

    output = args.output or args.pdf.with_name(f"{args.pdf.stem}_merged.svg")
    try:
        path_count, short_count, polyline_count = convert_pdf(
            args.pdf, output, args.threshold, args.page
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        parser.error(f"PDF renderer failed: {detail}")
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))

    print(
        f"Strokes: {path_count} | removed as too short: {short_count} "
        f"| polylines after merging: {polyline_count}"
    )
    print(f"Output: {output} ({output.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
