"""One-off icon generator for the todo app.

Draws a rounded square in the app's accent color (#4f46e5) with a simple
white checkmark centered in it, then exports it at the sizes needed for
favicon.ico, the web manifest, and the iOS home-screen icon.

Requires Pillow (dev-only, not a runtime dependency -- not added to
requirements.txt). Run once:

    python scripts/generate_icons.py

Safe to delete after running; the generated PNG/ICO files under web/ are
what actually get committed and served.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (88, 86, 214, 255)  # #5856d6 - new purple from redesign
WHITE = (255, 255, 255, 255)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ICONS = WEB / "icons"
ICONS.mkdir(parents=True, exist_ok=True)

# Render everything at a large size and downscale for crisp edges.
SIZE = 1024
CORNER_RADIUS = round(SIZE * 0.22)


def draw_base(size: int, radius: int, bg=ACCENT, transparent_bg=True) -> Image.Image:
    """Rounded square with a checkmark, at `size`x`size`."""
    mode = "RGBA"
    img = Image.new(mode, (size, size), (0, 0, 0, 0) if transparent_bg else bg)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=radius,
        fill=bg,
    )

    # Checkmark as a thick stroked polyline, drawn as a filled polygon so
    # corners stay crisp at small sizes.
    stroke = max(2, round(size * 0.09))
    p1 = (size * 0.26, size * 0.53)
    p2 = (size * 0.43, size * 0.70)
    p3 = (size * 0.76, size * 0.32)

    draw.line([p1, p2, p3], fill=WHITE, width=stroke, joint="curve")

    # Round the line caps by drawing circles at each vertex.
    r = stroke / 2
    for x, y in (p1, p2, p3):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)

    return img


def save_png(img: Image.Image, size: int, path: Path) -> None:
    img.resize((size, size), Image.LANCZOS).save(path, format="PNG")


def main() -> None:
    # Transparent-background master, used for favicon + manifest icons.
    master = draw_base(SIZE, CORNER_RADIUS, transparent_bg=True)

    save_png(master, 192, ICONS / "icon-192.png")
    save_png(master, 512, ICONS / "icon-512.png")

    # Favicon: multi-resolution ICO built from the same master.
    master.resize((256, 256), Image.LANCZOS).save(
        WEB / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32)],
    )

    # Apple touch icon: iOS ignores transparency and rounds corners itself,
    # so use a flat (non-rounded, opaque) square background instead.
    apple_master = draw_base(SIZE, radius=0, transparent_bg=False)
    save_png(apple_master, 180, ICONS / "apple-touch-icon.png")

    print("Wrote:")
    for p in [
        WEB / "favicon.ico",
        ICONS / "icon-192.png",
        ICONS / "icon-512.png",
        ICONS / "apple-touch-icon.png",
    ]:
        print(" -", p)


if __name__ == "__main__":
    main()
