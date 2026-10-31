
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 2200, 1400
image = Image.new("RGB", (WIDTH, HEIGHT), "white")
draw = ImageDraw.Draw(image)

try:
    title_font = ImageFont.load_default(size=56)
    body_font = ImageFont.load_default(size=40)
except TypeError:
    title_font = ImageFont.load_default()
    body_font = title_font

lines = [
    ("ACME SUPPLIES LTD", title_font),
    ("INVOICE", title_font),
    ("Invoice Number: INV-OCR-777", body_font),
    ("Invoice Date: 2026-10-12", body_font),
    ("Supplier Name: Acme Supplies Ltd", body_font),
    ("Customer Name: Example Customer Ltd", body_font),
    ("Currency: BDT", body_font),
    ("Subtotal: 2000.00", body_font),
    ("Tax: 300.00", body_font),
    ("Total: 2300.00", body_font),
    (
        "Line Item: A4 Paper | Quantity: 20 | Unit Price: 100.00 | Amount: 2000.00",
        body_font,
    ),
]

y = 100

for text, font in lines:
    draw.text((100, y), text, fill="black", font=font)
    y += 100 if font is title_font else 85

output_path = Path("/app/ocr_sample_clean.png")
image.save(output_path)

print(f"Created test invoice: {output_path}")
print(f"Image dimensions: {WIDTH} x {HEIGHT}")
