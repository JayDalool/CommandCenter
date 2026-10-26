# Before/after sheets: the same screenshot from two builds, side by side.
# Usage: python3 e2e/before_after.py <before dir> <after dir> <out dir>   (needs Pillow)
import sys, os
from PIL import Image, ImageDraw, ImageFont
before, after, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
font = ImageFont.truetype(F, 24) if os.path.exists(F) else ImageFont.load_default()
for name in sorted(os.listdir(before)):
    if not name.endswith(".png") or not os.path.exists(f"{after}/{name}"): continue
    a = Image.open(f"{before}/{name}").convert("RGB"); b = Image.open(f"{after}/{name}").convert("RGB")
    H = 760; a = a.resize((int(a.width * H / a.height), H)); b = b.resize((int(b.width * H / b.height), H))
    c = Image.new("RGB", (a.width + b.width + 24, H + 52), (5, 8, 18)); d = ImageDraw.Draw(c)
    d.text((10, 14), f"BEFORE · {name[:-4]}", fill=(255, 200, 97), font=font); d.text((a.width + 34, 14), "AFTER · macOS refinement", fill=(120, 230, 170), font=font)
    c.paste(a, (0, 52)); c.paste(b, (a.width + 24, 52))
    c.save(f"{out}/ba_{name[:-4]}.jpg", quality=86)
print("sheets in", out)
