"""Abrek Download simgelerini üretir (PIL)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

SIZE = 1024
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)

# Yuvarlatılmış köşeli arka plan.
radius = int(SIZE * 0.23)
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=radius, fill=255)

# Mavi -> mor degrade.
start = (66, 133, 255)
end = (139, 92, 246)
gradient = Image.new("RGB", (SIZE, SIZE))
gdraw = ImageDraw.Draw(gradient)
for y in range(SIZE):
    t = y / (SIZE - 1)
    color = tuple(int(start[i] * (1 - t) + end[i] * t) for i in range(3))
    gdraw.line([(0, y), (SIZE, y)], fill=color)
image = Image.composite(gradient.convert("RGBA"), image, mask)
draw = ImageDraw.Draw(image)

# Hafif iç parlaklık.
overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
odraw = ImageDraw.Draw(overlay)
odraw.ellipse((int(-SIZE * 0.35), int(-SIZE * 0.75), int(SIZE * 0.85), int(SIZE * 0.45)), fill=(255, 255, 255, 26))
image = Image.alpha_composite(image, Image.composite(overlay, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), mask))
draw = ImageDraw.Draw(image)

# Beyaz oynat üçgeni.
cx, cy = SIZE * 0.52, SIZE * 0.5
w, h = SIZE * 0.30, SIZE * 0.36
points = [
    (cx - w * 0.42, cy - h * 0.5),
    (cx - w * 0.42, cy + h * 0.5),
    (cx + w * 0.62, cy),
]
draw.polygon(points, fill=(255, 255, 255, 245))

# Alt tarafta küçük indirme oku.
arrow_color = (255, 255, 255, 230)
ax = SIZE * 0.5
ay = SIZE * 0.76
draw.rounded_rectangle((ax - SIZE * 0.018, ay - SIZE * 0.075, ax + SIZE * 0.018, ay + SIZE * 0.035), radius=SIZE * 0.018, fill=arrow_color)
draw.polygon(
    [
        (ax - SIZE * 0.075, ay + SIZE * 0.005),
        (ax + SIZE * 0.075, ay + SIZE * 0.005),
        (ax, ay + SIZE * 0.085),
    ],
    fill=arrow_color,
)
draw.rounded_rectangle(
    (ax - SIZE * 0.095, ay + SIZE * 0.105, ax + SIZE * 0.095, ay + SIZE * 0.135),
    radius=SIZE * 0.015,
    fill=arrow_color,
)

# Kenar çizgisi.
edge = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
ImageDraw.Draw(edge).rounded_rectangle(
    (2, 2, SIZE - 3, SIZE - 3), radius=radius, outline=(255, 255, 255, 42), width=4
)
image = Image.alpha_composite(image, edge)

image.save(ASSETS / "icon.png")
for size in (512, 256, 128, 64, 48, 32, 16):
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    resized.save(ASSETS / f"icon-{size}.png")

for folder in ("chrome", "firefox"):
    target = ROOT / "extension" / folder
    target.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        image.resize((size, size), Image.Resampling.LANCZOS).save(target / f"icon{size}.png")

print("Simgeler üretildi:", ASSETS)
