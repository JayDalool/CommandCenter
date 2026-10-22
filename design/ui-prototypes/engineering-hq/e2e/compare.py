# Side-by-side sheets: reference PNG (left) vs prototype screenshot (right).
# Usage: python3 e2e/compare.py <references dir> <screenshots dir> <out dir>   (needs Pillow)
import sys, os
from PIL import Image, ImageDraw, ImageFont
refs, shots, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
pairs = [("00_USER_APPROVED_FULL_OPS_TOPOLOGY", "00_topology", "Operations Topology"), ("01_MY_OFFICE", "01_office", "My Office"),
  ("02_MESSAGES", "02_messages", "Messages"), ("13_PROJECT_LEAD_DM", "pop_dm_980x820", "Project-lead DM (popped out, 980x820)"),
  ("03_DECISIONS", "03_decisions", "Decisions"), ("04_TEAMS", "04_teams", "Teams"), ("06_ENGINEERING", "06_engineering", "Engineering"),
  ("07_REVENUE", "07_revenue_demo", "Revenue (fictional demo toggle on)"), ("07_REVENUE", "07_revenue_not_connected", "Revenue (default: not connected)")]
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") else ImageFont.load_default()
H = 900
for ref, shot, title in pairs:
    a = Image.open(f"{refs}/{ref}.png").convert("RGB"); b = Image.open(f"{shots}/{shot}.png").convert("RGB")
    a = a.resize((int(a.width * H / a.height), H)); b = b.resize((int(b.width * H / b.height), H))
    W = a.width + b.width + 30
    c = Image.new("RGB", (W, H + 60), (5, 8, 18)); d = ImageDraw.Draw(c)
    d.text((10, 16), f"REFERENCE · {ref}", fill=(255, 200, 97), font=font); d.text((a.width + 30, 16), f"PROTOTYPE · {title}", fill=(120, 230, 170), font=font)
    c.paste(a, (0, 60)); c.paste(b, (a.width + 30, 60))
    c.save(f"{out}/compare_{shot}.png", optimize=True)
print("ok")
