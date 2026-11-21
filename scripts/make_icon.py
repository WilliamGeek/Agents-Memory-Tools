"""生成桌面版应用的 PNG/ICO 图标（不依赖外部美术资源）。"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src-tauri" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

size = 1024
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 深色圆角底板
mask = Image.new("L", (size, size), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle((24, 24, size - 24, size - 24), radius=224, fill=255)
img.putalpha(mask)
grad = ImageDraw.Draw(img)
for y in range(26, size - 26):
    k = (y - 26) / (size - 52)
    color = (int(14 + 18 * k), int(22 + 38 * k), int(45 + 68 * k), 255)
    grad.line((26, y, size - 26, y), fill=color)
img.putalpha(mask)

# 两个叠放的对话卡片，象征跨平台会话
shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
sd = ImageDraw.Draw(shadow)
sd.rounded_rectangle((202, 236, 824, 760), radius=72, fill=(0, 0, 0, 90))
img.alpha_composite(shadow)

card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
cd = ImageDraw.Draw(card)
cd.rounded_rectangle((154, 182, 774, 704), radius=72, fill=(110, 168, 255, 255))
cd.rounded_rectangle((250, 302, 870, 824), radius=72, fill=(36, 212, 178, 255))
for x1, y1, x2, y2 in [
    (308, 410, 760, 410),
    (308, 486, 700, 486),
    (308, 562, 820, 562),
]:
    cd.rounded_rectangle((x1, y1, x2, y2), radius=(y2 - y1) // 2, fill=(255, 255, 255, 235))
img.alpha_composite(card)

font = None
for fp in [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]:
    try:
        font = ImageFont.truetype(fp, 184)
        break
    except Exception:
        continue
if font:
    fd = ImageDraw.Draw(img)
    fd.rounded_rectangle((74, 742, 438, 952), radius=52, fill=(7, 12, 26, 245))
    fd.text((116, 772), "AM", font=font, fill=(225, 240, 255, 255))

png = OUT / "icon.png"
img.save(png, "PNG")
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT / "icon.ico", format="ICO", sizes=sizes)
print(png)
print(OUT / "icon.ico")
