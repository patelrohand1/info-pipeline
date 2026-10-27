"""Draws the app icon (1024px PNG). Called by build_app.sh."""
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# macOS icon grid: ~824px rounded square centered, soft shadow underneath.
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((100, 118, 924, 942), 185, fill=(0, 0, 0, 120))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))

bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    gd.line([(0, y), (S, y)], fill=(int(28 - 12 * t), int(34 - 14 * t), int(52 - 22 * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((100, 100, 924, 924), 185, fill=255)
bg.paste(grad, (0, 0), mask)
img.alpha_composite(bg)

d = ImageDraw.Draw(img)
# Three stacked cards (the digest), front one highlighted: triage down to what matters.
cards = [((262, 300, 762, 420), (52, 60, 82)), ((232, 400, 792, 540), (70, 82, 115)), ((202, 520, 822, 720), (91, 123, 245))]
for box, color in cards:
    d.rounded_rectangle(box, 38, fill=color + (255,))
# Lines on the front card + a score dot.
d.rounded_rectangle((262, 580, 600, 606), 13, fill=(235, 240, 255, 255))
d.rounded_rectangle((262, 636, 520, 658), 11, fill=(200, 212, 255, 230))
d.ellipse((682, 585, 762, 665), fill=(110, 231, 160, 255))

img.save(sys.argv[1] if len(sys.argv) > 1 else "AppIcon.png")
