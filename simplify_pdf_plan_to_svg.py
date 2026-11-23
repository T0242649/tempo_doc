#!/usr/bin/env python3
"""Convert a vector PDF drawing into an SVG with merged straight strokes."""

from __future__ import annotations

import argparse
import collections
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]


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
            "remove isolated strokes with total length <= this value in PDF points "
            "(default: 0.96; 0 only removes duplicates)"
        ),
    )
    parser.add_argument("-p", "--page", type=int, default=1, help="page number (default: 1)")
    return parser


def convert_pdf(
    source: Path,
    output: Path,
    threshold: float,
    page_number: int,
) -> tuple[int, int, int]:
    try:
        import pikepdf
    except ImportError as exc:
        raise RuntimeError(
            "Missing Python dependency: install it with `python3 -m pip install -r requirements.txt`."
        ) from exc

    renderer = shutil.which("pdftocairo")
    if renderer is None:
        raise RuntimeError(
            "`pdftocairo` was not found. Install Poppler (see README.md)."
        )
    if not source.is_file():
        raise RuntimeError(f"Input PDF does not exist or is not a file: {source}")
    if source.resolve() == output.resolve():
        raise RuntimeError("The output path must not overwrite the input PDF.")
    if not output.parent.is_dir():
        raise RuntimeError(f"Output directory does not exist: {output.parent}")

    segments: dict[float, set[tuple[Point, Point]]] = collections.defaultdict(set)
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
        height = abs(box[3] - box[1])
        if int(page.obj.get("/Rotate", 0)) % 360:
            print("Warning: rotated pages may be oriented incorrectly.", file=sys.stderr)

        instructions = pikepdf.parse_content_stream(page)
        ctm: Matrix = (1, 0, 0, 1, 0, 0)
        graphics_stack: list[tuple[Matrix, float]] = []
        line_width = 1.0
        pending = []
        remaining = []

        def to_page(x: float, y: float) -> Point:
            return (
                round(ctm[0] * x + ctm[2] * y + ctm[4] - x0, 1),
                round(height - (ctm[1] * x + ctm[3] * y + ctm[5] - y0), 1),
            )

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
                if length <= threshold:
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
                graphics_stack.append((ctm, line_width))
            elif name == "Q":
                if not graphics_stack:
                    raise RuntimeError("Invalid PDF content stream: unmatched `Q` operator.")
                ctm, line_width = graphics_stack.pop()
            elif name == "cm":
                ctm = multiply_matrices(tuple(float(value) for value in operands), ctm)
            elif name == "w":
                line_width = float(operands[0])

            # Keep graphics-state operators other than `gs`, matching the original
            # conversion behavior for PDFs that use large Darken blend groups.
            if name != "gs":
                remaining.append((operands, operator))
        flush_pending()

        merged_group = [
            '<g fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round">'
        ]
        polyline_count = 0
        for width, edges in sorted(segments.items()):
            paths = [
                remove_collinear_points(path) for path in chain_segments(edges)
            ]
            polyline_count += len(paths)
            data = "".join(make_path_data(path) for path in paths)
            merged_group.append(f'<path stroke-width="{width}" d="{data}"/>')
        merged_group.append("</g>")

        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(remaining))
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
    output.write_text(svg, encoding="utf-8")
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
