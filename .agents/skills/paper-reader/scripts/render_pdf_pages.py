#!/usr/bin/env python3

import argparse
import json
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render selected PDF pages to PNG screenshots."
    )
    parser.add_argument("pdf", help="Path to the input PDF")
    parser.add_argument(
        "--pages",
        default="1",
        help="Comma-separated page list, for example 1,2,5-7",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="Render resolution for Poppler-based renderers",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=2000,
        help="Thumbnail size for qlmanage fallback on macOS",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to .paper-reader/renders/<pdf-stem>",
    )
    parser.add_argument(
        "--prefix",
        help="Filename prefix. Defaults to the PDF stem",
    )
    parser.add_argument(
        "--crop",
        help=(
            "Optional crop box as left,top,right,bottom. "
            "Use fractions (0-1), percentages (10%%,15%%,90%%,60%%), or pixels."
        ),
    )
    parser.add_argument(
        "--crop-suffix",
        default="crop",
        help="Suffix added to cropped output filenames",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty JSON",
    )
    return parser.parse_args()


def parse_page_spec(spec):
    pages = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, end_text = chunk.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start < 1 or end < start:
                raise ValueError(f"Invalid page range: {chunk}")
            for page in range(start, end + 1):
                pages.add(page)
        else:
            page = int(chunk)
            if page < 1:
                raise ValueError(f"Invalid page number: {chunk}")
            pages.add(page)
    if not pages:
        raise ValueError("No pages requested")
    return sorted(pages)


def choose_renderer():
    for name in ("pdftocairo", "pdftoppm"):
        path = shutil.which(name)
        if path:
            return name, path
    if platform.system() == "Darwin":
        qlmanage = shutil.which("qlmanage")
        if qlmanage:
            return "qlmanage", qlmanage
    return None, None


def parse_crop_spec(spec):
    values = []
    for chunk in spec.split(","):
        token = chunk.strip()
        if not token:
            continue
        if token.endswith("%"):
            values.append(("percent", float(token[:-1]) / 100.0))
        else:
            value = float(token)
            if 0.0 <= value <= 1.0:
                values.append(("fraction", value))
            else:
                values.append(("pixel", value))
    if len(values) != 4:
        raise ValueError("Crop spec must contain exactly four values: left,top,right,bottom")
    return values


def read_png_size(path):
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Unsupported image format for cropping: {path}")
    return struct.unpack(">II", header[16:24])


def resolve_crop_value(value, unit, axis_length):
    if unit in ("fraction", "percent"):
        return int(round(value * axis_length))
    return int(round(value))


def resolve_crop_box(crop_spec, image_width, image_height):
    left = resolve_crop_value(crop_spec[0][1], crop_spec[0][0], image_width)
    top = resolve_crop_value(crop_spec[1][1], crop_spec[1][0], image_height)
    right = resolve_crop_value(crop_spec[2][1], crop_spec[2][0], image_width)
    bottom = resolve_crop_value(crop_spec[3][1], crop_spec[3][0], image_height)

    if left < 0 or top < 0 or right > image_width or bottom > image_height:
        raise ValueError(
            f"Crop box {left},{top},{right},{bottom} exceeds image bounds {image_width}x{image_height}"
        )
    if left >= right or top >= bottom:
        raise ValueError(
            f"Invalid crop box {left},{top},{right},{bottom}: expected left < right and top < bottom"
        )
    return left, top, right, bottom


def choose_cropper():
    if platform.system() == "Darwin":
        sips = shutil.which("sips")
        if sips:
            return "sips", sips
    return None, None


def crop_image(cropper, input_file, output_file, crop_box):
    left, top, right, bottom = crop_box
    crop_width = right - left
    crop_height = bottom - top
    if cropper != "sips":
        raise FileNotFoundError("No supported image cropper found")
    command = [
        "sips",
        "-c",
        str(crop_height),
        str(crop_width),
        "--cropOffset",
        str(top),
        str(left),
        str(input_file),
        "--out",
        str(output_file),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_file


def render_with_poppler(renderer, pdf_path, page, output_file, dpi):
    base = output_file.with_suffix("")
    command = [
        renderer,
        "-png",
        "-singlefile",
        "-f",
        str(page),
        "-l",
        str(page),
    ]
    if renderer == "pdftocairo":
        command.extend(["-r", str(dpi), str(pdf_path), str(base)])
    else:
        command.extend(["-r", str(dpi), str(pdf_path), str(base)])
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_file


def render_with_qlmanage(pdf_path, output_dir, prefix, size):
    command = [
        "qlmanage",
        "-t",
        "-s",
        str(size),
        "-o",
        str(output_dir),
        str(pdf_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    generated = output_dir / f"{pdf_path.name}.png"
    target = output_dir / f"{prefix}-page-0001.png"
    if not generated.exists():
        raise FileNotFoundError(f"qlmanage did not produce {generated}")
    generated.replace(target)
    return target


def main():
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    try:
        pages = parse_page_spec(args.pages)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    crop_spec = None
    if args.crop:
        try:
            crop_spec = parse_crop_spec(args.crop)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (Path.cwd() / ".paper-reader" / "renders" / pdf_path.stem).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or pdf_path.stem

    renderer, _ = choose_renderer()
    if not renderer:
        print(
            "No PDF renderer found. Install Poppler (`pdftocairo` or `pdftoppm`) or use macOS Quick Look.",
            file=sys.stderr,
        )
        return 1

    created = []
    cropped = []
    try:
        if renderer == "qlmanage":
            if pages != [1]:
                print(
                    "qlmanage fallback can only render the first page. Install Poppler for arbitrary pages.",
                    file=sys.stderr,
                )
                return 1
            created.append(
                str(render_with_qlmanage(pdf_path, output_dir, prefix, args.size))
            )
        else:
            for page in pages:
                output_file = output_dir / f"{prefix}-page-{page:04d}.png"
                render_with_poppler(renderer, pdf_path, page, output_file, args.dpi)
                created.append(str(output_file))

        if crop_spec:
            cropper, _ = choose_cropper()
            if not cropper:
                print(
                    "No supported image cropper found. On macOS, `sips` is required for cropped figure output.",
                    file=sys.stderr,
                )
                return 1
            for file_path in created:
                input_file = Path(file_path)
                image_width, image_height = read_png_size(input_file)
                crop_box = resolve_crop_box(crop_spec, image_width, image_height)
                output_file = input_file.with_name(
                    f"{input_file.stem}-{args.crop_suffix}{input_file.suffix}"
                )
                crop_image(cropper, input_file, output_file, crop_box)
                cropped.append(str(output_file))
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        print(stderr or f"{renderer} failed", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = {
        "renderer": renderer,
        "pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "pages": pages,
        "rendered_files": created,
        "files": cropped or created,
    }
    if crop_spec:
        payload["crop"] = args.crop
    if args.compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
