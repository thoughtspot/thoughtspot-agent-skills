"""Rebuild tiles.png from Kenney's three CC0 packs (kenney.nl: Tiny Dungeon 1.0, Tiny Town 1.1,
Tiny Battle 1.0) plus our own row. Frames, 16px, 12 to a row:
    0-131    Tiny Dungeon       tilemap_packed.png, as it is
    132      ours               the top of a wall
    133-137  ours               the realm guards: Tiny Dungeon characters, recoloured
    144-275  Tiny Town          tilemap_packed.png frame f is 144 + f
    276-473  Tiny Battle        tilemap_packed.png (18 to a row) frame f is 276 + f
Needs Pillow; not run by the build (tiles.png is committed).
    python3 make_atlas.py <tiny-dungeon packed png> <tiny-town packed png> <tiny-battle packed png> <out png>"""
import colorsys
import sys

from PIL import Image

T = 16
GUARDS = [   # (frame, from Tiny Dungeon frame, how it is recoloured)
    (133, 87, ("tint", 0.60)),   # the Mines: a dwarf, his helmet and mail steel blue
    (134, 112, ("hue", 0.52)),   # the Lake: a fisherman, in sea green
    (135, 98, ("tint", 0.63)),   # the Isles: a sailor, in navy
    (136, 96, ("tint", 0.12)),   # the Golden Forests: an elf in golden armour
    (137, 84, ("hue", 0.56)),    # Law: a wizard, in blue
]


def frames(sheet, cols):
    return [sheet.crop(((i % cols) * T, (i // cols) * T, (i % cols) * T + T, (i // cols) * T + T))
            for i in range((sheet.width // T) * (sheet.height // T))]


def recolour(tile, how):
    kind, hue = how
    out = tile.copy()
    px = out.load()
    for y in range(T):
        for x in range(T):
            r, g, b, a = px[x, y]
            if not a:
                continue
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            skin = 0.02 <= h <= 0.11 and 0.2 <= s <= 0.65 and v > 0.6
            if v < 0.36 or skin:                      # outlines, their dark halo, and faces stay
                continue
            if kind == "tint":                          # metal and cloth, grey or not, take the realm's colour
                h, s = hue, max(s, 0.7 if hue < 0.2 else 0.5)
            elif kind == "hue" and s >= 0.25:           # cloth takes the realm's colour
                h = hue
            else:
                continue
            nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
            px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    return out


def main(dungeon, town, battle, out):
    td = frames(Image.open(dungeon).convert("RGBA"), 12)
    tt = frames(Image.open(town).convert("RGBA"), 12)
    tb = frames(Image.open(battle).convert("RGBA"), 18)
    assert len(td) == 132 and len(tt) == 132 and len(tb) == 198, (len(td), len(tt), len(tb))
    tiles = td + [Image.new("RGBA", (T, T), (0, 0, 0, 0)) for _ in range(12)] + tt + tb
    top = Image.new("RGBA", (T, T), (47, 42, 72, 255))   # 132: the top of a wall: dark stone, a lighter rim, chips
    for x in range(T):
        top.putpixel((x, 0), (64, 58, 96, 255))
    for x, y in [(3, 5), (11, 9), (6, 13), (13, 3)]:
        top.putpixel((x, y), (58, 52, 86, 255))
    tiles[132] = top
    for frame, source, how in GUARDS:
        tiles[frame] = recolour(td[source], how)
    rows = (len(tiles) + 11) // 12
    atlas = Image.new("RGBA", (12 * T, rows * T), (0, 0, 0, 0))
    for i, t in enumerate(tiles):
        atlas.alpha_composite(t, ((i % 12) * T, (i // 12) * T))
    atlas.save(out, optimize=True)
    print(out, atlas.size, len(tiles), "frames")


if __name__ == "__main__":
    main(*sys.argv[1:])
