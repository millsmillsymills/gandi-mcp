"""Generate the 8-bit logo and favicon from the source Gandi icon.

Source: https://uxwing.com/gandi-icon/ (free for commercial use, no attribution required).
Run from repo root:
    python3 docs/assets/_make_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "_gandi-source.png"
LOGO_OUT = HERE / "logo.png"
LOGO_LARGE_OUT = HERE / "logo@2x.png"
FAVICON_OUT = HERE / "favicon.ico"
FAVICON_PNG_OUT = HERE / "favicon.png"

PIXEL_GRID = 24  # logical 8-bit canvas size — chunky pixels
LOGO_SIZE = 256
LOGO_LARGE_SIZE = 512
PALETTE_COLORS = 6  # NES-era vibe: tight palette
CONTRAST_BOOST = 1.6
FAVICON_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]


def _split_alpha(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    rgba = img.convert("RGBA")
    return rgba.convert("RGB"), rgba.split()[3]


def pixelate(src: Image.Image, grid: int, out_size: int, palette_colors: int) -> Image.Image:
    rgb, alpha = _split_alpha(src)
    rgb = ImageEnhance.Contrast(rgb).enhance(CONTRAST_BOOST)
    small_rgb = rgb.resize((grid, grid), Image.Resampling.LANCZOS)
    small_alpha = alpha.resize((grid, grid), Image.Resampling.LANCZOS)
    quantized = small_rgb.quantize(colors=palette_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quant_rgb = quantized.convert("RGB")
    binary_alpha = small_alpha.point(lambda v: 255 if v >= 110 else 0)
    pixel = Image.merge("RGBA", (*quant_rgb.split(), binary_alpha))
    return pixel.resize((out_size, out_size), Image.Resampling.NEAREST)


def main() -> None:
    src = Image.open(SOURCE)

    logo = pixelate(src, PIXEL_GRID, LOGO_SIZE, PALETTE_COLORS)
    logo.save(LOGO_OUT, optimize=True)

    logo_large = pixelate(src, PIXEL_GRID, LOGO_LARGE_SIZE, PALETTE_COLORS)
    logo_large.save(LOGO_LARGE_OUT, optimize=True)

    favicon_master = pixelate(src, 16, 64, 4)
    favicon_master.save(FAVICON_PNG_OUT, optimize=True)
    favicon_master.save(FAVICON_OUT, format="ICO", sizes=FAVICON_SIZES)

    print(f"wrote {LOGO_OUT.relative_to(HERE.parent.parent)}")
    print(f"wrote {LOGO_LARGE_OUT.relative_to(HERE.parent.parent)}")
    print(f"wrote {FAVICON_PNG_OUT.relative_to(HERE.parent.parent)}")
    print(f"wrote {FAVICON_OUT.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
