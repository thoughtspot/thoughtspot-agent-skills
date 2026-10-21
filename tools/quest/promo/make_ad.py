#!/usr/bin/env python3
"""AgentQL Quest advert: amber-CRT cutscenes that tell the game's own story.

The Wizard (the AI) writes the scroll (AgentQL); the dwarves of the Forge (ThoughtSpot) compile
it; a dragon made of SQL rises from the fire; the player names who wrote each line and wins gold.
Drawn at 320x200 in the game's own amber palette, scaled 3x with hard pixels and CRT scanlines.
All art and the 5x7 font are original.

    python3 tools/quest/promo/make_ad.py <out_dir>                 # GIF + poster
    python3 tools/quest/promo/make_ad.py <out_dir> --video-frames  # also 1920x1200 frames
    swift tools/quest/promo/encode_mp4.swift <out_dir>/video-frames/manifest.txt <out.mp4> 30
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

W, H, SCALE = 320, 200, 3
# The game's palette (game.html :root), plus two darker browns for depth.
C = {"K": (0, 0, 0), "G": (21, 14, 6), "D": (42, 26, 8), "R": (74, 50, 16), "M": (168, 114, 42),
     "A": (255, 180, 58), "H": (255, 230, 176), "E": (255, 106, 69)}
SCAN = 150                                   # scanline rows are this /255 as bright

FONT = {
 "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
 "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
 "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
 "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
 "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
 "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
 "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
 "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
 "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
 "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
 "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
 "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
 "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
 "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
 "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
 "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
 "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
 "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
 ".": "00000 00000 00000 00000 00000 01100 01100", "!": "00100 00100 00100 00100 00100 00000 00100",
 "?": "01110 10001 00001 00010 00100 00000 00100", "+": "00000 00100 00100 11111 00100 00100 00000",
 "-": "00000 00000 00000 11111 00000 00000 00000", ":": "00000 01100 01100 00000 01100 01100 00000",
 ",": "00000 00000 00000 00000 01100 00100 01000", "'": "01100 00100 01000 00000 00000 00000 00000",
 "(": "00010 00100 01000 01000 01000 00100 00010", ")": "01000 00100 00010 00010 00010 00100 01000",
 "=": "00000 00000 11111 00000 11111 00000 00000", "[": "01110 01000 01000 01000 01000 01000 01110",
 "]": "01110 00010 00010 00010 00010 00010 01110", "*": "00000 10101 01110 11111 01110 10101 00000",
 ">": "01000 00100 00010 00001 00010 00100 01000", " ": "00000 00000 00000 00000 00000 00000 00000",
}


# ---- drawing primitives --------------------------------------------------------------------

def blank(c="G"):
    return Image.new("RGB", (W, H), C[c])


def put(img, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        img.putpixel((int(x), int(y)), C[c])


def text(img, s, x, y, c, scale=1):
    d = img.load()
    for n, ch in enumerate(s):
        for j, row in enumerate(FONT.get(ch, FONT["?"]).split()):
            for i, b in enumerate(row):
                if b == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            X, Y = x + (n * 6 + i) * scale + dx, y + j * scale + dy
                            if 0 <= X < W and 0 <= Y < H:
                                d[X, Y] = C[c]


def tw(s, scale=1):
    return len(s) * 6 * scale - scale


def ctext(img, s, y, c, scale=1, shadow="R", x=None):
    x = (W - tw(s, scale)) // 2 if x is None else x
    if shadow:
        text(img, s, x + max(1, scale // 2), y + max(1, scale // 2), shadow, scale)
    text(img, s, x, y, c, scale)


def caption(img, big, small=None):
    """A cutscene title card along the top: two lines of gold, one of explanation."""
    dr = ImageDraw.Draw(img)
    bottom = 46 if small else 38
    dr.rectangle([0, 0, W, bottom], fill=C["K"])
    dr.line([(0, bottom), (W, bottom)], fill=C["M"])
    y = 5
    for line in big:
        ctext(img, line, y, "A", 2)
        y += 15
    if small:
        ctext(img, small, 36, "M", 1, shadow=None)


def wall(img):
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W, H], fill=C["G"])
    for row in range(0, H, 10):
        off = 0 if (row // 10) % 2 == 0 else 12
        for x in range(-off, W, 24):
            dr.rectangle([x + 1, row + 1, x + 22, row + 8], fill=C["D"])


def glow(img, cx, cy, r, colours=("R", "D")):
    """A dithered halo: light falls on the stones around a flame."""
    for y in range(int(cy - r), int(cy + r)):
        for x in range(int(cx - r), int(cx + r)):
            if not (0 <= x < W and 0 <= y < H):
                continue
            d = math.hypot(x - cx, y - cy) / r
            if d < 1 and img.getpixel((x, y)) in (C["G"], C["D"]):
                if d < 0.55 and (x + y) % 2 == 0:
                    put(img, x, y, colours[0])
                elif (x + y) % 4 == 0:
                    put(img, x, y, colours[0] if d < 0.8 else colours[1])


def flame(img, x, base, h, rng, w=5):
    dr = ImageDraw.Draw(img)
    h = h + rng.randint(-2, 2)
    dr.polygon([(x - w, base), (x + rng.randint(-1, 1), base - h - 3), (x + w, base)], fill=C["E"])
    dr.polygon([(x - w + 2, base), (x, base - h), (x + w - 2, base)], fill=C["A"])
    dr.polygon([(x - 1, base), (x, base - h // 2), (x + 1, base)], fill=C["H"])


def torch(img, x, y, rng):
    glow(img, x, y - 6, 26)
    dr = ImageDraw.Draw(img)
    dr.polygon([(x - 4, y), (x + 4, y), (x + 2, y + 10), (x - 2, y + 10)], fill=C["M"])
    dr.rectangle([x - 1, y + 10, x + 1, y + 24], fill=C["R"])
    flame(img, x, y, 13, rng, 5)


def fire(img, x0, x1, base, height, rng, intensity=1.0):
    dr = ImageDraw.Draw(img)
    for col, hm, wm in (("E", 1.0, 1.0), ("A", 0.72, 0.8), ("H", 0.4, 0.55)):
        x = x0
        while x < x1:
            w = int((5 + rng.randint(0, 6)) * wm) + 3
            h = int(height * hm * (0.5 + rng.random() * 0.5) * intensity)
            cx = min(x1, x + w // 2)
            dr.polygon([(x, base), (cx + rng.randint(-2, 2), base - h), (min(x1, x + w), base)], fill=C[col])
            x += max(3, w - 3)


def coin(img, x, y):
    dr = ImageDraw.Draw(img)
    dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=C["A"], outline=C["M"])
    put(img, x - 1, y - 2, "H"); put(img, x - 2, y - 1, "H")


# ---- the cast --------------------------------------------------------------------------------

def wizard(img, x, y, f):
    """The Wizard (the AI): robe, starry hat, white beard, glowing staff. y = feet."""
    dr = ImageDraw.Draw(img)
    orb = "H" if f % 6 < 3 else "A"
    glow(img, x - 18, y - 66, 16, ("R", "D"))
    dr.line([(x - 18, y), (x - 18, y - 62)], fill=C["M"], width=2)
    dr.ellipse([x - 22, y - 70, x - 14, y - 62], fill=C[orb])
    dr.polygon([(x - 15, y), (x + 15, y), (x + 9, y - 36), (x - 9, y - 36)], fill=C["R"])
    dr.line([(x - 15, y - 1), (x + 15, y - 1)], fill=C["A"], width=2)
    for sx, sy in ((x - 6, y - 24), (x + 5, y - 14), (x - 2, y - 8)):
        put(img, sx, sy, "A")
    dr.ellipse([x - 6, y - 48, x + 6, y - 36], fill=C["H"])
    dr.polygon([(x - 6, y - 41), (x + 6, y - 41), (x + 3, y - 22), (x, y - 18), (x - 3, y - 22)], fill=C["H"])
    put(img, x - 2, y - 43, "K"); put(img, x + 2, y - 43, "K")
    dr.polygon([(x - 15, y - 46), (x + 15, y - 46), (x + 4, y - 74), (x + 13, y - 80), (x - 1, y - 76)], fill=C["M"])
    dr.line([(x - 15, y - 46), (x + 15, y - 46)], fill=C["A"], width=2)
    put(img, x + 1, y - 58, "H"); put(img, x - 4, y - 52, "A")
    qx, qy = x + 22 + (f % 4), y - 30 + (f % 2)                      # writing arm and quill
    dr.line([(x + 8, y - 32), (qx, qy)], fill=C["R"], width=3)
    dr.line([(qx, qy), (qx + 6, qy - 10)], fill=C["H"], width=1)


def dwarf(img, x, y, arm=None, face=1):
    """A dwarf of the Forge: horned helm, braided beard, apron. y = feet. face=1 looks right."""
    dr = ImageDraw.Draw(img)
    dr.rectangle([x - 9, y - 4, x - 2, y], fill=C["R"]); dr.rectangle([x + 2, y - 4, x + 9, y], fill=C["R"])
    dr.rectangle([x - 10, y - 18, x + 10, y - 4], fill=C["M"])
    dr.rectangle([x - 6, y - 16, x + 6, y - 4], fill=C["D"])                 # leather apron
    dr.line([(x - 10, y - 10), (x + 10, y - 10)], fill=C["R"])
    dr.ellipse([x - 7, y - 30, x + 7, y - 17], fill=C["H"])
    dr.polygon([(x - 8, y - 23), (x + 8, y - 23), (x + 4, y - 9), (x, y - 6), (x - 4, y - 9)], fill=C["A"])
    dr.line([(x, y - 21), (x, y - 8)], fill=C["M"])                            # beard braid
    dr.pieslice([x - 8, y - 35, x + 8, y - 21], 180, 360, fill=C["M"])
    dr.line([(x - 9, y - 28), (x + 9, y - 28)], fill=C["A"], width=2)
    dr.line([(x - 8, y - 29), (x - 12, y - 36)], fill=C["H"], width=2)
    dr.line([(x + 8, y - 29), (x + 12, y - 36)], fill=C["H"], width=2)
    put(img, x + 3 * face, y - 25, "K")
    if arm is not None:                                                          # hammer arm
        sx, sy = x + 8 * face, y - 15
        ex, ey = sx + 9 * math.cos(arm), sy + 9 * math.sin(arm)
        dr.line([(sx, sy), (ex, ey)], fill=C["M"], width=3)
        hx, hy = ex + 9 * math.cos(arm), ey + 9 * math.sin(arm)
        dr.line([(ex, ey), (hx, hy)], fill=C["R"], width=2)
        dr.rectangle([hx - 4, hy - 3, hx + 4, hy + 3], fill=C["H"], outline=C["M"])


def anvil(img, x, y):
    dr = ImageDraw.Draw(img)
    dr.polygon([(x - 24, y), (x + 18, y), (x + 28, y + 3), (x + 18, y + 7), (x + 8, y + 7), (x + 6, y + 15),
                (x + 15, y + 21), (x - 15, y + 21), (x - 6, y + 15), (x - 8, y + 7), (x - 18, y + 7)], fill=C["R"])
    dr.line([(x - 24, y), (x + 18, y)], fill=C["A"])


def furnace(img, cx, base, rng, intensity=1.0):
    dr = ImageDraw.Draw(img)
    glow(img, cx, base - 30, 70 * min(1.3, intensity), ("R", "D"))
    dr.rectangle([cx - 52, base - 86, cx + 52, base], fill=C["D"])
    for yy in range(base - 86, base, 8):
        dr.line([(cx - 52, yy), (cx + 52, yy)], fill=C["R"])
        for xx in range(cx - 52 + (8 if (yy // 8) % 2 else 0), cx + 52, 16):
            dr.line([(xx, yy), (xx, yy + 8)], fill=C["R"])
    dr.rectangle([cx - 14, base - 110, cx + 14, base - 86], fill=C["D"])        # chimney
    dr.rectangle([cx - 36, base - 40, cx + 36, base], fill=C["K"])
    dr.pieslice([cx - 36, base - 66, cx + 36, base - 14], 180, 360, fill=C["K"])
    fire(img, cx - 33, cx + 33, base, 58, rng, intensity)
    dr.line([(cx - 52, base), (cx + 52, base)], fill=C["M"])


# The dragon: built from parts so it reads as a dragon. Its body is made of SQL; the wing is a
# dark membrane with gold ribs. Head at the left, facing the player. Box about 172 x 106.
DRAGON_BODY = [
    [(0, 40), (10, 30), (28, 26), (40, 30), (46, 36), (40, 42), (26, 44), (14, 48), (4, 50), (12, 43)],  # head
    [(36, 29), (52, 31), (74, 48), (68, 66), (50, 52), (38, 42)],                                    # neck
    [(60, 50), (90, 43), (122, 47), (142, 60), (138, 78), (110, 86), (80, 84), (62, 74)],              # body
    [(136, 60), (156, 68), (172, 86), (166, 90), (150, 80), (132, 77)],                                # tail
    [(78, 80), (88, 80), (86, 98), (94, 104), (76, 104)],                                              # front leg
    [(116, 82), (127, 82), (129, 98), (137, 104), (120, 104)],                                         # back leg
]
DRAGON_WING = [(84, 49), (96, 4), (108, 22), (121, 0), (131, 24), (148, 14), (141, 42), (120, 48)]
DRAGON_RIBS = [((90, 47), (96, 4)), ((104, 47), (121, 0)), ((118, 47), (148, 14))]
DRAGON_HORNS = [((33, 27), (44, 12)), ((39, 29), (54, 17))]
DRAGON_SPIKES = [[(150, 74), (156, 64), (160, 76)], [(160, 80), (168, 72), (168, 84)],
                 [(96, 44), (102, 36), (108, 44)], [(112, 46), (118, 38), (124, 48)]]
SQL_WORDS = "JOIN ON KEY SUM CASE WHEN NULL LIMIT 100000 WHERE LOWER GROUP BY FROM MODEL "
_SQL_LAYER = []


def sql_layer():
    if not _SQL_LAYER:
        layer = blank("K")
        for row in range(0, H, 8):
            s = (SQL_WORDS * 8)[(row * 3) % 40:]
            text(layer, s[:60], -((row * 7) % 30), row, "A" if (row // 8) % 2 else "M")
        _SQL_LAYER.append(layer)
    return _SQL_LAYER[0]


def dragon(img, x, y, scale=1.0, flash=False, scale_box=None):
    t = lambda pts: [(x + px_ * scale, y + py * scale) for px_, py in pts]
    dr = ImageDraw.Draw(img)
    wing = t(DRAGON_WING)                                             # the wing sits behind the body
    dr.polygon(wing, fill=C["H"] if flash else C["D"])
    for a_, b_ in DRAGON_RIBS:
        dr.line(t([a_, b_]), fill=C["A"], width=max(1, int(scale)))
    dr.line(wing + [wing[0]], fill=C["H"])
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for part in DRAGON_BODY:
        md.polygon(t(part), fill=255)
    img.paste(blank("H") if flash else sql_layer(), (0, 0), mask)
    for part in DRAGON_BODY:                                          # outline each part
        pts = t(part)
        dr.line(pts + [pts[0]], fill=C["H"])
    for sp in DRAGON_SPIKES:
        dr.polygon(t(sp), fill=C["A"])
    for a_, b_ in DRAGON_HORNS:
        dr.line(t([a_, b_]), fill=C["H"], width=max(1, int(scale * 2)))
    ex, ey = x + 30 * scale, y + 33 * scale                           # a burning eye
    dr.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=C["E"])
    for k in range(4):                                                # fangs
        fx = x + (8 + k * 5) * scale
        dr.polygon([(fx, y + 44 * scale), (fx + 2, y + 44 * scale), (fx + 1, y + 48 * scale)], fill=C["H"])
    if scale_box:                                                     # one scale, singled out
        bx, by, word, state = scale_box
        if state != "gone":
            dr.rectangle([bx - 2, by - 2, bx + tw(word) + 2, by + 8], fill=C["H"] if state == "lit" else C["K"],
                         outline=C["A"])
            text(img, word, bx, by, "K" if state == "lit" else "A")


# ---- the storyboard ---------------------------------------------------------------------------

def frames():
    rng = random.Random(11)
    out = []

    # 1. The title, by torchlight.
    for f in range(20):
        img = blank(); wall(img)
        torch(img, 34, 70, rng); torch(img, W - 34, 70, rng)
        y = min(40, -40 + f * 8)
        ctext(img, "AGENTQL", y, "A", 5, shadow="R")
        ctext(img, "QUEST", y + 42, "H", 5, shadow="R")
        if f > 10:
            ctext(img, "A FANTASY QUEST IN DETERMINISTIC SQL", 136, "M", 1, shadow="K")
        out.append((img, 100))

    # 2. The Wizard writes the scroll.
    lines = ["SELECT SUM(SALES)", "FROM MODEL", "WHERE REGION = 'WEST'"]
    total = sum(len(s) for s in lines)
    for f in range(34):
        img = blank(); wall(img)
        torch(img, 300, 96, rng)
        dr = ImageDraw.Draw(img)
        dr.rectangle([120, 150, 300, 156], fill=C["R"]); dr.line([(120, 150), (300, 150)], fill=C["M"])
        dr.rectangle([130, 156, 136, 196], fill=C["D"]); dr.rectangle([284, 156, 290, 196], fill=C["D"])
        flame(img, 280, 134, 7, rng, 3); dr.rectangle([277, 134, 283, 150], fill=C["H"])   # candle
        width = min(132, 20 + f * 8)                                     # the scroll unrolls
        dr.rectangle([132, 108, 132 + width, 148], fill=C["H"])
        for ex in (128, 132 + width):
            dr.rectangle([ex, 104, ex + 5, 152], fill=C["M"], outline=C["R"])
        shown = max(0, int(total * (f - 6) / 20))
        yy = 114
        for s in lines:
            n = max(0, min(len(s), shown)); shown -= len(s)
            text(img, s[:n][: (width - 8) // 6], 138, yy, "R")
            yy += 11
        wizard(img, 92, 196, f)
        caption(img, ["THE WIZARD", "WRITES THE SCROLL"], "THE WIZARD IS THE AI. THE SCROLL IS ITS AGENTQL.")
        out.append((img, 100))

    # 3. The dwarves of the Forge compile it.
    hits = list(range(6, 36, 6))
    for f in range(36):
        img = blank(); wall(img)
        furnace(img, 236, 186, rng, 1.0)
        dr = ImageDraw.Draw(img)
        dr.rectangle([0, 186, W, H], fill=C["D"]); dr.line([(0, 186), (W, 186)], fill=C["R"])
        anvil(img, 96, 162)
        up = f in hits or (f - 1) in hits
        dwarf(img, 66, 186, arm=-0.2 if f in hits else (-2.2 if up else -1.4), face=1)
        for h_ in hits:                                                  # sparks from each strike
            age = f - h_
            if 0 <= age < 6:
                srng = random.Random(h_)
                for _ in range(10):
                    vx, vy = srng.uniform(-3, 3), srng.uniform(-5, -1)
                    put(img, 96 + vx * age, 160 + vy * age + 0.5 * age * age, "H" if age < 3 else "A")
        sx = min(196, 150 + f * 2)                                       # the scroll goes into the fire
        dwarf(img, 150 if f < 23 else 150 + (f - 23), 186, face=1)
        if sx < 196:
            dr.rectangle([sx, 150, sx + 18, 158], fill=C["H"], outline=C["M"])
        caption(img, ["THE DWARVES", "OF THE FORGE"], "THE FORGE IS THOUGHTSPOT. IT COMPILES THE SCROLL.")
        out.append((img, 100))

    # 4. A dragon made of SQL rises from the fire.
    for f in range(30):
        img = blank(); wall(img)
        furnace(img, 236, 186, rng, 1.0 + min(0.5, f * 0.04))
        ImageDraw.Draw(img).rectangle([0, 186, W, H], fill=C["D"])
        s = min(1.0, 0.3 + f * 0.045)
        dragon(img, 236 - 86 * s - 50 * min(1, f / 16), 176 - 106 * s - min(22, f * 2), s)
        caption(img, ["A DRAGON OF SQL", "RISES FROM THE FIRE"], "EVERY LINE OF THE SQL IS A SCALE.")
        out.append((img, 100))

    # 5. Who wrote each line? The player answers, a scale shatters, gold rises.
    opts = ["[1] THE FORGE: THOUGHTSPOT ADDED IT", "[2] YOUR SCROLL: IT'S IN THE AGENTQL",
            "[3] THE WIZARD: THE AI MADE IT UP"]
    for f in range(44):
        img = blank(); wall(img)
        dr = ImageDraw.Draw(img); dr.rectangle([0, 186, W, H], fill=C["D"])
        state = "lit" if f < 18 else ("gone" if f >= 22 else ("lit" if f % 2 else "dark"))
        dragon(img, 136, 48, 0.95, flash=(18 <= f < 22 and f % 2 == 0), scale_box=(226, 102, "JOIN", state))
        dr.rectangle([8, 132, 312, 194], fill=C["K"], outline=C["M"])
        text(img, "WHO PUT THIS JOIN HERE?", 16, 138, "H")
        for i, o in enumerate(opts):
            y = 152 + i * 13
            chosen = i == 0 and f >= 14
            if chosen:
                dr.rectangle([12, y - 2, 308, y + 8], fill=C["A"])
            text(img, o[: max(0, (f - 2) * 6 - i * 10)], 16, y, "K" if chosen else "A")
        if f >= 22:                                                       # the scale shatters
            age = f - 22
            srng = random.Random(5)
            for _ in range(26):
                vx, vy = srng.uniform(-4, 4), srng.uniform(-6, 0)
                put(img, 238 + vx * age, 106 + vy * age + 0.6 * age * age, "H" if srng.random() < 0.5 else "A")
            rise = min(age * 3, 24)                                       # clear of the dragon
            ctext(img, "*CLANG*", 52, "H", 2, shadow="R", x=24)
            ctext(img, "+10 GOLD", 104 - rise, "A", 2, shadow="R", x=28)
            for k in range(4):
                coin(img, 30 + k * 22, 126 - rise // 2 - (k % 2) * 5)
        caption(img, ["WHO WROTE", "EACH LINE?"])
        out.append((img, 100))

    # 6. The end card.
    for f in range(30):
        img = blank(); wall(img)
        torch(img, 34, 80, rng); torch(img, W - 34, 80, rng)
        ctext(img, "AGENTQL", 14, "A", 4, shadow="R")
        ctext(img, "QUEST", 48, "H", 4, shadow="R")
        ctext(img, "5 REALMS. ABOUT 15 MINUTES.", 92, "H", 1, shadow="K")
        ctext(img, "SEE HOW THOUGHTSPOT TURNS AGENTQL", 106, "A", 1, shadow="K")
        ctext(img, "INTO GOVERNED, REPEATABLE SQL.", 116, "A", 1, shadow="K")
        ctext(img, "FREE IN YOUR BROWSER. NO LOGIN.", 132, "M", 1, shadow="K")
        if f % 6 < 4:
            ctext(img, "PRESS START", 150, "H", 2, shadow="R")
        ctext(img, "LINK IN THE POST", 182, "M", 1, shadow="K")
        out.append((img, 100 if f < 29 else 2000))
    return out


def poster():
    rng = random.Random(3)
    img = blank(); wall(img)
    furnace(img, 236, 186, rng, 1.3)
    ImageDraw.Draw(img).rectangle([0, 186, W, H], fill=C["D"])
    dragon(img, 146, 66, 1.0)
    anvil(img, 70, 162)
    dwarf(img, 40, 186, arm=-2.0)
    ctext(img, "AGENTQL", 8, "A", 4, shadow="R", x=12)
    ctext(img, "QUEST", 40, "H", 4, shadow="R", x=12)
    text(img, "WHO WROTE EACH LINE", 14, 76, "H")
    text(img, "OF THE SQL?", 14, 86, "H")
    text(img, "5 REALMS. ABOUT 15 MINUTES.", 14, 104, "M")
    text(img, "FREE IN YOUR BROWSER.", 14, 114, "M")
    return img


# ---- output -----------------------------------------------------------------------------------

_SCANLINES = []


def crt(img):
    """Scale up with hard pixels, then darken every third row: the game's CRT scanlines."""
    big = img.resize((W * SCALE, H * SCALE), Image.NEAREST)
    if not _SCANLINES:
        lines = Image.new("RGB", big.size, (255, 255, 255))
        dr = ImageDraw.Draw(lines)
        for y in range(SCALE - 1, big.size[1], SCALE):
            dr.line([(0, y), (big.size[0], y)], fill=(SCAN, SCAN, SCAN))
        _SCANLINES.append(lines)
    return ImageChops.multiply(big, _SCANLINES[0])


def palette_image():
    cols = list(C.values()) + [tuple(v * SCAN // 255 for v in c) for c in C.values()]
    flat = [v for c in cols for v in c]
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return pal


def video_frames(fs, out, fps=30):
    """Every frame doubled to 1920x1200 with hard pixels, plus a manifest of how long to hold
    each one, for encode_mp4.swift (macOS AVFoundation; no ffmpeg needed)."""
    d = out / "video-frames"; d.mkdir(exist_ok=True)
    lines = []
    for n, (img, ms) in enumerate(fs):
        big = crt(img)
        big.resize((big.width * 2, big.height * 2), Image.NEAREST).save(d / f"f{n:04d}.png")
        lines.append(f"{d / f'f{n:04d}.png'}\t{max(1, round(ms / 1000 * fps))}")
    (d / "manifest.txt").write_text("\n".join(lines))
    print(f"wrote {len(fs)} video frames and {d / 'manifest.txt'}")


def main(out_dir, video=False):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pal = palette_image()
    fs = frames()
    imgs = [crt(i).quantize(palette=pal, dither=Image.Dither.NONE) for i, _ in fs]
    imgs[0].save(out / "agentql-quest.gif", save_all=True, append_images=imgs[1:],
                 duration=[d for _, d in fs], loop=0, optimize=True, disposal=1)
    crt(poster()).save(out / "agentql-quest-poster.png")
    if video:
        video_frames(fs, out)
    secs = sum(d for _, d in fs) / 1000
    print(f"{len(fs)} frames, {secs:.1f}s, {(out / 'agentql-quest.gif').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".", video="--video-frames" in sys.argv[2:])
