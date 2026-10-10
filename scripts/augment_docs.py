# Owner: Laptop B
"""INX – Script: produce hard augmented variants of clean synthetic documents.

Generates deterministic, seeded hard variants into fixtures/synthetic_docs/hard/:
- tilt 2-6 deg
- perspective warp (phone angle)
- shadow gradient
- grain
- JPEG quality 35 compression
- downscale to about 900 px
- a decorative-font certificate
- a scanned look (slight yellowing)
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DEFAULT_HARD_DIR = _REPO_ROOT / "fixtures" / "synthetic_docs" / "hard"


def _get_font(size: int = 18) -> ImageFont.ImageFont:
    font_file = _REPO_ROOT / "DejaVuSans.ttf"
    if font_file.exists():
        try:
            return ImageFont.truetype(str(font_file), size)
        except OSError:
            pass
    for name in ["DejaVuSans.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_clean_synthetic_page(
    title: str = "OFFICIAL RECORD",
    lines: list[tuple[str, str]] | None = None,
    size: tuple[int, int] = (1400, 1000),
) -> Image.Image:
    """Generate a clean base synthetic document page in memory."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    f_title = _get_font(28)
    f_body = _get_font(20)

    draw.text((80, 80), title, fill=(20, 20, 20), font=f_title)
    draw.line([(80, 130), (size[0] - 80, 130)], fill=(80, 80, 80), width=2)

    lines = lines or [
        ("Applicant Name", "Vikramaditya Rao"),
        ("Identification Number", "236123456783"),
        ("Date of Issue", "2023-04-15"),
        ("Course / Position", "Senior Technical Specialist"),
        ("Issuing Authority", "Central Verification Bureau"),
    ]

    y = 170
    for label, val in lines:
        draw.text((100, y), f"{label}:", fill=(40, 40, 40), font=f_body)
        draw.text((450, y), str(val), fill=(10, 10, 10), font=f_body)
        y += 50

    return img


def apply_tilt(img: Image.Image, angle: float = 3.5) -> Image.Image:
    """Tilt / rotate document by 2-6 degrees."""
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")


def apply_perspective_warp(img: Image.Image, seed: int = 42) -> Image.Image:
    """Simulate a smartphone camera angled perspective warp."""
    arr = np.array(img)
    h, w = arr.shape[:2]
    rng = np.random.RandomState(seed)

    # Shift corners slightly to simulate perspective
    dx1, dy1 = rng.uniform(20, 50), rng.uniform(10, 40)
    dx2, dy2 = rng.uniform(30, 60), rng.uniform(20, 50)

    pts1 = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
    pts2 = np.float32([
        [dx1, dy1],
        [w - dx2, 0],
        [0, h - dy1],
        [w - dx1, h - dy2],
    ])

    matrix = cv2.getPerspectiveTransform(pts1, pts2)
    warped = cv2.warpPerspective(
        arr, matrix, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)
    )
    return Image.fromarray(warped)


def apply_shadow_gradient(img: Image.Image, seed: int = 42) -> Image.Image:
    """Apply non-uniform shadow gradient across the document page."""
    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape[:2]

    # Create linear shadow gradient from top-left (darker) to bottom-right (lighter)
    y_grad = np.linspace(0.65, 1.0, h)[:, None]
    x_grad = np.linspace(0.70, 1.0, w)[None, :]
    grad = (y_grad * x_grad)[:, :, None]

    shadowed = np.clip(arr * grad, 0, 255).astype(np.uint8)
    return Image.fromarray(shadowed)


def apply_grain(img: Image.Image, intensity: float = 14.0, seed: int = 42) -> Image.Image:
    """Add deterministic camera sensor grain / noise."""
    arr = np.array(img, dtype=np.float32)
    rng = np.random.RandomState(seed)
    noise = rng.normal(0, intensity, arr.shape)
    grainy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(grainy)


def apply_jpeg_compression(img: Image.Image, quality: int = 35) -> Image.Image:
    """Apply lossy JPEG compression artifacts."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf)


def apply_downscale(img: Image.Image, target_width: int = 900) -> Image.Image:
    """Downscale document width to ~900 px maintaining aspect ratio."""
    w, h = img.size
    ratio = target_width / float(w)
    target_height = int(h * ratio)
    return img.resize((target_width, target_height), Image.Resampling.LANCZOS)


def apply_scanned_look(img: Image.Image) -> Image.Image:
    """Apply slight paper yellowing and scanner tint."""
    arr = np.array(img, dtype=np.float32)
    # Slight boost to Red and Green, slight decrease to Blue -> warm yellow tint
    arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.02, 0, 255)  # R
    arr[:, :, 1] = np.clip(arr[:, :, 1] * 0.99, 0, 255)  # G
    arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.90, 0, 255)  # B
    return Image.fromarray(arr.astype(np.uint8))


def generate_decorative_certificate(out_path: Path) -> Path:
    """Create a decorative-font certificate PDF."""
    from reportlab.lib.utils import TimeStamp

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c._doc._timeStamp = TimeStamp(1700000000)
    c._doc.ID = lambda: b"/ID [<00112233445566778899aabbccddeeff> <00112233445566778899aabbccddeeff>]"
    width, height = letter

    # Decorative border
    c.setStrokeColor(colors.HexColor("#4A3728"))
    c.setLineWidth(3)
    c.rect(36, 36, width - 72, height - 72)
    c.setLineWidth(1)
    c.rect(42, 42, width - 84, height - 84)

    # Decorative header
    c.setFont("Times-BoldItalic", 28)
    c.setFillColor(colors.HexColor("#2C221E"))
    c.drawCentredString(width / 2, height - 120, "Certificate of Completion")

    c.setFont("Times-Italic", 14)
    c.drawCentredString(width / 2, height - 160, "This is formally presented to")

    c.setFont("Times-Bold", 22)
    c.drawCentredString(width / 2, height - 200, "Vikramaditya Rao")

    c.setFont("Times-Roman", 12)
    c.drawCentredString(
        width / 2,
        height - 240,
        "for demonstrating exemplary technical proficiency in Enterprise Architecture",
    )

    c.setFont("Times-Bold", 11)
    c.drawString(80, 160, "Roll / Reg Number: 20210089")
    c.drawString(80, 140, "National ID: 236123456783")
    c.drawString(width - 240, 160, "Issue Date: 2023-05-18")
    c.drawString(width - 240, 140, "Grade: Distinction")

    c.save()
    return out_path


def generate_all_hard_variants(out_dir: Path = _DEFAULT_HARD_DIR) -> list[Path]:
    """Generate and save all hard variants deterministically."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base_img = make_clean_synthetic_page()

    created: list[Path] = []

    # 1. Tilted & downscaled (3.5 deg tilt, 900px)
    p1 = out_dir / "hard_tilted_resume.jpg"
    img1 = apply_tilt(base_img, angle=3.8)
    img1 = apply_downscale(img1, target_width=900)
    img1.save(p1, quality=90)
    created.append(p1)

    # 2. Perspective warp (phone angle) + JPEG quality 35
    p2 = out_dir / "hard_perspective_id.jpg"
    img2 = apply_perspective_warp(base_img, seed=101)
    img2 = apply_jpeg_compression(img2, quality=35)
    img2.save(p2)
    created.append(p2)

    # 3. Shadow gradient
    p3 = out_dir / "hard_shadow_marksheet.jpg"
    img3 = apply_shadow_gradient(base_img, seed=202)
    img3.save(p3, quality=90)
    created.append(p3)

    # 4. Grainy / noisy document
    p4 = out_dir / "hard_grainy_id.jpg"
    img4 = apply_grain(base_img, intensity=16.0, seed=303)
    img4.save(p4, quality=90)
    created.append(p4)

    # 5. Scanned look with yellowing tint
    p5 = out_dir / "hard_scanned_yellow_resume.jpg"
    img5 = apply_scanned_look(base_img)
    img5 = apply_downscale(img5, target_width=900)
    img5.save(p5, quality=85)
    created.append(p5)

    # 6. Decorative-font certificate PDF
    p6 = out_dir / "hard_decorative_certificate.pdf"
    generate_decorative_certificate(p6)
    created.append(p6)

    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hard synthetic document variants.")
    parser.add_argument("--out", type=Path, default=_DEFAULT_HARD_DIR, help="Output directory")
    args = parser.parse_args()

    print(f"Generating hard variants in {args.out}...")
    files = generate_all_hard_variants(args.out)
    print(f"Done. Generated {len(files)} hard variants.")


if __name__ == "__main__":
    main()
