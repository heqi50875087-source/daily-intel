#!/usr/bin/env python3
"""生成 PWA 图标:暖纸底 + 宋体「情」+ 朱砂点。输出到 docs/icons/。"""
import pathlib
from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
PAPER = (250, 247, 240, 255)
INK = (33, 28, 21, 255)
ACCENT = (192, 69, 47, 255)
FONTS = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STSong.ttf",
    "/System/Library/Fonts/Supplemental/STSong.ttf",
    "/System/Library/Fonts/PingFang.ttc",
]

def load_font(sz):
    for p in FONTS:
        try:
            f = ImageFont.truetype(p, sz)
            return f, p
        except Exception:
            continue
    return ImageFont.load_default(), "default"

def centered(d, size, ch, fs, weight):
    f, used = load_font(fs)
    bb = d.textbbox((0, 0), ch, font=f, stroke_width=weight)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((size - w) / 2 - bb[0], (size - h) / 2 - bb[1]), ch, font=f,
           fill=INK, stroke_width=weight, stroke_fill=INK)
    return used

def make(size, maskable=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, size, size], fill=PAPER)          # 满幅,留系统裁切
        used = centered(d, size, "情", int(size * 0.46), max(1, size // 200))
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=PAPER)
        s, m = int(size * 0.072), int(size * 0.17)
        d.rounded_rectangle([m, m, m + s, m + s], radius=int(s * 0.2), fill=ACCENT)
        used = centered(d, size, "情", int(size * 0.6), max(1, size // 160))
    return img, used

used = None
for name, size, mask in [("icon-512.png", 512, False), ("icon-192.png", 192, False),
                         ("icon-180.png", 180, False), ("icon-maskable-512.png", 512, True)]:
    img, used = make(size, mask)
    img.save(OUT / name)
    print("wrote", name)
print("font:", used)
