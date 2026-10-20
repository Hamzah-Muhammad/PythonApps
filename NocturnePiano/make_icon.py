"""Render Nocturne's piano icon (icon.png + multi-size icon.ico) with Pillow."""
import pathlib

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).parent
S = 1024  # draw large, downsample for crisp edges

GOLD = (201, 168, 92)
GOLD_DARK = (138, 110, 52)
EBONY = (18, 17, 20)
IVORY = (250, 246, 234)
IVORY_SHADE = (222, 214, 194)
FELT = (110, 22, 32)


def render():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Lacquered tile with a double gold rule
    d.rounded_rectangle((24, 24, S - 24, S - 24), radius=200, fill=EBONY)
    d.rounded_rectangle((60, 60, S - 60, S - 60), radius=168, outline=GOLD, width=18)
    d.rounded_rectangle((92, 92, S - 92, S - 92), radius=140, outline=GOLD_DARK, width=5)

    # Keybed: felt strip, then one octave of keys
    left, right, top, bottom = 170, S - 170, 300, 800
    d.rectangle((left, top - 34, right, top), fill=FELT)
    n_white = 7
    w = (right - left) / n_white
    for i in range(n_white):
        x0 = left + i * w
        d.rounded_rectangle((x0 + 5, top, x0 + w - 5, bottom), radius=22, fill=IVORY)
        d.rectangle((x0 + 5, bottom - 46, x0 + w - 5, bottom - 22), fill=IVORY_SHADE)
    black_h = (bottom - top) * 0.6
    bw = w * 0.58
    for i in (1, 2, 4, 5, 6):  # black keys sit on the boundary before white key i
        cx = left + i * w
        d.rounded_rectangle((cx - bw / 2, top, cx + bw / 2, top + black_h), radius=14, fill=EBONY)
        d.rectangle((cx - bw / 2 + 12, top + 6, cx + bw / 2 - 12, top + black_h - 40), fill=(48, 46, 52))

    # Gold base rail
    d.rounded_rectangle((left - 10, bottom + 18, right + 10, bottom + 44), radius=12, fill=GOLD)
    return img


def main():
    img = render()
    img.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
