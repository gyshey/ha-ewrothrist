"""Regenerates the brand assets in Rothrist's colours (red/white/green).

Deliberately NOT the municipal coat of arms: no shield, no stars, no
ploughshare - only the colour family. Swiss coats of arms are reserved for
the public body they belong to (WSchG art. 8), and this is an unofficial
integration.

Run with Pillow installed:  python3 brand_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "custom_components/ewrothrist/brand"
SS = 4

RED_TOP = (222, 8, 8)
RED_BOTTOM = (176, 4, 4)
GREEN = (0, 153, 68)
WHITE = (255, 255, 255, 240)
WHITE_DIM = (255, 255, 255, 140)


def icon(size: int) -> Image.Image:
    s = size * SS

    # Draw everything on a full opaque square; round the corners only at the
    # end, so no later paste can punch holes in the background.
    img = Image.new("RGBA", (s, s), RED_TOP + (255,))
    gd = ImageDraw.Draw(img)
    for y in range(s):
        t = y / max(s - 1, 1)
        gd.line(
            [(0, y), (s, y)],
            fill=tuple(
                round(RED_TOP[i] + (RED_BOTTOM[i] - RED_TOP[i]) * t)
                for i in range(3)
            ) + (255,),
        )

    d = ImageDraw.Draw(img)

    # green ground strip (nods to the Dreiberg colour, but a plain band)
    d.rectangle((0, int(s * 0.855), s, s), fill=GREEN + (255,))
    heights = [0.30, 0.42, 0.36, 0.55, 0.74, 0.62, 0.85, 0.58, 0.44, 0.33]
    margin = s * 0.13
    usable = s - 2 * margin
    slot = usable / len(heights)
    bar_w = slot * 0.56
    base = s * 0.855
    for i, h in enumerate(heights):
        x0 = margin + i * slot + (slot - bar_w) / 2
        top = base - (base - s * 0.20) * h
        d.rounded_rectangle(
            (x0, top, x0 + bar_w, base),
            radius=bar_w * 0.32,
            fill=WHITE if i % 2 == 0 else WHITE_DIM,
        )

    cx, cy = s * 0.5, s * 0.5
    u = s * 0.30
    bolt = [
        (cx + 0.16 * u, cy - 1.15 * u),
        (cx - 0.72 * u, cy + 0.16 * u),
        (cx - 0.10 * u, cy + 0.16 * u),
        (cx - 0.28 * u, cy + 1.18 * u),
        (cx + 0.74 * u, cy - 0.22 * u),
        (cx + 0.10 * u, cy - 0.22 * u),
    ]
    d.polygon(bolt, fill=(255, 255, 255, 255), outline=(140, 0, 0, 255),
              width=int(s * 0.016))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255
    )
    img.putalpha(mask)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512),
                       ("logo.png", 256), ("logo@2x.png", 512)):
        icon(size).save(OUT / name, optimize=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
