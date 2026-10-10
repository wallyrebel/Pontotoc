"""Render original typography and geometric lock art; no source art or logos."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    font_dir = Path("/System/Library/Fonts/Supplemental")
    regular = str(font_dir / "Arial.ttf")
    bold = str(font_dir / "Arial Bold.ttf")
    image = Image.new("RGB", (1600, 900), "#102c37")
    d = ImageDraw.Draw(image)
    teal = "#78d7c4"
    ivory = "#f5f3e9"
    d.rectangle((85, 82, 91, 135), fill=teal)
    d.text((114, 85), "PONTOTOC NEWS", font=ImageFont.truetype(bold, 36), fill=ivory)
    d.text((85, 226), "PROTECT YOUR", font=ImageFont.truetype(bold, 84), fill=ivory)
    d.text((85, 326), "ONLINE ACCOUNTS", font=ImageFont.truetype(bold, 84), fill=ivory)
    d.rectangle((85, 467, 170, 473), fill=teal)
    d.text((85, 516), "PEPA shares October", font=ImageFont.truetype(regular, 40), fill=ivory)
    d.text((85, 571), "cybersecurity reminder", font=ImageFont.truetype(regular, 40), fill=ivory)
    d.line((85, 766, 1515, 766), fill="#43616a", width=2)
    d.text((85, 806), "OCTOBER 10, 2026", font=ImageFont.truetype(bold, 27), fill=teal)
    d.text((1142, 806), "ACCOUNT SECURITY", font=ImageFont.truetype(regular, 25), fill=ivory)
    # A geometric lock inside a circle, drawn from primitive shapes.
    d.ellipse((1110, 217, 1510, 617), outline="#43616a", width=3)
    d.arc((1212, 280, 1408, 498), 180, 360, fill=teal, width=24)
    d.line((1212, 389, 1212, 425), fill=teal, width=24)
    d.line((1408, 389, 1408, 425), fill=teal, width=24)
    d.rounded_rectangle((1173, 401, 1447, 565), radius=24, fill=teal)
    d.ellipse((1290, 449, 1330, 489), fill="#102c37")
    d.rectangle((1300, 478, 1320, 522), fill="#102c37")
    target = ROOT / "reviewed/assets/pepa-account-security-2026-10-10.png"
    image.save(target, optimize=True)
    print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()
