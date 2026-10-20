"""Render Meridian's calculator icon (icon.png + multi-size icon.ico) with Pillow."""
import pathlib

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).parent
S = 1024  # draw large, downsample for crisp edges

GOLD = (201, 168, 92)
GOLD_DARK = (138, 110, 52)
EBONY = (18, 17, 20)
KEY = (52, 49, 56)
IVORY = (250, 246, 234)
SCREEN = (8, 8, 10)


def render():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Lacquered tile with a double gold rule (same frame as Nocturne)
    d.rounded_rectangle((24, 24, S - 24, S - 24), radius=200, fill=EBONY)
    d.rounded_rectangle((60, 60, S - 60, S - 60), radius=168, outline=GOLD, width=18)
    d.rounded_rectangle((92, 92, S - 92, S - 92), radius=140, outline=GOLD_DARK, width=5)

    # Display with a stacked fraction
    d.rounded_rectangle((200, 180, S - 200, 440), radius=36, fill=SCREEN, outline=GOLD_DARK, width=6)
    cx = S - 330
    d.rectangle((cx - 70, 304, cx + 70, 318), fill=IVORY)
    d.rounded_rectangle((cx - 26, 206, cx + 26, 286), radius=8, outline=IVORY, width=14)
    d.rounded_rectangle((cx - 26, 336, cx + 26, 416), radius=8, outline=IVORY, width=14)

    # 3 x 2 keys, the last one gold like the = key
    kw, kh, gap = 176, 130, 36
    x0, y0 = (S - 3 * kw - 2 * gap) / 2, 500
    for row in range(2):
        for col in range(3):
            x, y = x0 + col * (kw + gap), y0 + row * (kh + gap)
            fill = GOLD if (row, col) == (1, 2) else KEY
            d.rounded_rectangle((x, y, x + kw, y + kh), radius=26, fill=fill)
    return img


def main():
    img = render()
    img.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
