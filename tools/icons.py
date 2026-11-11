"""Draw the app icons in web/icons/: a glowing LED strip on the app's background.

    python3 tools/icons.py    # needs Pillow (pip install pillow); not needed on the Pi

The strip stays inside the middle 60% so Android can crop the icon to any
shape (a "maskable" icon) and iPhones can round its corners.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"
BACKGROUND = (11, 13, 18)  # the app's background, #0b0d12
STRIP = (30, 34, 44)
LEDS = [(255, 40, 40), (255, 140, 0), (255, 220, 0), (40, 230, 70), (0, 200, 255), (60, 90, 255), (200, 60, 255)]
SIZES = {"icon-512.png": 512, "icon-192.png": 192, "apple-touch-icon.png": 180}


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGB", (size, size), BACKGROUND)
    s = size / 1024
    cx = size / 2
    top, bottom = 230 * s, 794 * s  # inside the middle 60%
    width = 120 * s
    step = (bottom - top) / len(LEDS)
    centers = [bottom - step * (k + 0.5) for k in range(len(LEDS))]  # red at the bottom
    radius = 34 * s

    glow = Image.new("RGB", (size, size), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    for y, color in zip(centers, LEDS):
        g.ellipse((cx - radius * 2.2, y - radius * 2.2, cx + radius * 2.2, y + radius * 2.2), fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(40 * s))
    img = Image.blend(img, glow, 0.55)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((cx - width / 2, top - 20 * s, cx + width / 2, bottom + 20 * s), radius=width / 2, fill=STRIP)
    for y, color in zip(centers, LEDS):
        d.ellipse((cx - radius, y - radius, cx + radius, y + radius), fill=color)
        hi = radius * 0.4  # a bright center, like a lit LED
        d.ellipse((cx - hi, y - hi, cx + hi, y + hi), fill=tuple(min(255, c + 120) for c in color))
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw()
    for name, size in SIZES.items():
        big.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
