"""Map checks for packs with an explorable front end (design §4.2): a pack's Tiled maps must bind
to its content, and every object on them must be reachable.

A pack with realms in `explore.realms` has `maps/overworld.tmj` and one `maps/<realm id>.tmj` per
such realm, saved by Tiled 1.10 or later as JSON with tilesets embedded. On a map:

  - a tile layer named `walls` is the only collision: any non-empty tile blocks;
  - every object has a `type`, and string properties only:
        spawn                      where the player appears (one per map)
        portal   to=<realm id>     overworld only: enters a realm
        exit                       realm maps only: back to the overworld
        merchant|guide|compiler|foe|reward   encounter=<encounter id>
        throne   hall=<hall id>
        gate     requires=<step id>,<step id>,...   blocks its tiles until those steps are DONE
  - a step id is "<encounter id>:<merchant|guide|compiler|foe|reward>" or "hall:<hall id>".

Only what Phaser 4 and the explore page read the same way: an orthogonal, finite map; layers at
the top level (no groups) with no offsets: tile layers `floor` and `walls`, the map's size, and one
object layer `objects`; one embedded tileset named `tiles`; unrotated rectangle objects (not tile
objects, which Tiled and Phaser anchor differently), each exactly one tile on the grid (the explore
page gives each a 16px body at its centre); tiles of 16px; a wall all round the edge (the page
doesn't stop the player at the map's edge).

An object sits on the tile containing its centre.
Everything but the spawn and gates is solid; reaching an object means standing on a walkable tile
next to it (up, down, left or right). The game plays a realm's steps in one order (realm_steps,
which tests pin to Quest.machine's expected()), so the check walks that order: before each step,
a flood-fill from the spawn with only the gates whose required steps are all done open must reach
that step's object. The exit must be reachable from the start, so a player can always leave.
"""
from __future__ import annotations

import json
import math
import pathlib

ROLES = ("merchant", "guide", "compiler", "foe", "reward")
PROPS = {"spawn": set(), "exit": set(), "portal": {"to"}, "throne": {"hall"}, "gate": {"requires"},
         **{role: {"encounter"} for role in ROLES}}
REALM_TYPES = set(PROPS) - {"portal"}
OVERWORLD_TYPES = {"spawn", "portal", "gate"}
OVERWORLD = "overworld"
IMAGES = (".png",)
GID = 0x1FFFFFFF   # a tile number without Tiled's flip and rotation flags
TILE = 16          # the explore page's tiles and its player's body are sized for 16px
MAX_TILES = 200 * 200


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def realm_steps(realm: dict) -> list[str]:
    """Every step a realm's map must hold, in the order the game plays them."""
    steps = [f"hall:{h['id']}" for h in realm["halls"]]
    for e in realm["encounters"]:
        steps += [f"{e['id']}:{role}" for role in ROLES]
    return steps


def _props(obj: dict, where: str, errors: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    props = obj.get("properties") or []
    if not isinstance(props, list):
        errors.append(f"{where}: properties must be a list")
        return out
    for p in props:
        if (not isinstance(p, dict) or not isinstance(p.get("name"), str) or p.get("type", "string") != "string"
                or not isinstance(p.get("value"), str)):
            errors.append(f"{where}: property {p.get('name') if isinstance(p, dict) else p!r} must be a string")
            continue
        if p["name"] in out:   # the checks and the page must read the same one
            errors.append(f"{where}: property {p['name']!r} is given twice")
        out[p["name"]] = p["value"]
    return out


class Map:
    """One .tmj, read as far as it can be."""

    def __init__(self, path: pathlib.Path, errors: list[str]):
        self.path, self.name, self.errors = path, f"maps/{path.name}", errors
        try:
            self.doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"{self.name}: not readable Tiled JSON ({e})")
            self.doc = {}
        if not isinstance(self.doc, dict):
            errors.append(f"{self.name}: not a Tiled map (a JSON object)")
            self.doc = {}
        d = self.doc
        self.w, self.h = d.get("width", 0), d.get("height", 0)
        self.tw, self.th = d.get("tilewidth", 0), d.get("tileheight", 0)
        if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (self.w, self.h, self.tw, self.th)) and d:
            errors.append(f"{self.name}: needs whole-number width, height, tilewidth and tileheight")
            self.w = self.h = self.tw = self.th = 1
        elif d and (self.tw, self.th) != (TILE, TILE):
            errors.append(f"{self.name}: tiles must be {TILE}x{TILE} (the explore page's player is sized for them)")
        if self.w * self.h > MAX_TILES:
            errors.append(f"{self.name}: {self.w}x{self.h} is over {MAX_TILES:,} tiles")
            self.w = self.h = 1
            d = {}
        if d and d.get("orientation", "orthogonal") != "orthogonal":
            errors.append(f"{self.name}: orientation must be orthogonal (the checks and the explore page lay tiles out square)")
        if d.get("infinite"):
            errors.append(f"{self.name}: is infinite; uncheck Infinite in Tiled's map properties")
        layers = d.get("layers") if isinstance(d.get("layers"), list) else []
        for layer in layers:
            if not isinstance(layer, dict):
                errors.append(f"{self.name}: a layer is not a JSON object")
            elif layer.get("type") == "group":
                errors.append(f"{self.name}: layer {layer.get('name')!r} is a group; keep every layer at the top level")
            elif any(layer.get(k) for k in ("offsetx", "offsety", "startx", "starty")):
                errors.append(f"{self.name}: layer {layer.get('name')!r} is offset; set its offsets to 0")
            elif layer.get("type") == "tilelayer" and (layer.get("x"), layer.get("y")) != (0, 0):
                errors.append(f"{self.name}: tile layer {layer.get('name')!r} needs x 0 and y 0 (Phaser places it there)")
        layers = [l for l in layers if isinstance(l, dict)]
        walls = [l for l in layers if l.get("type") == "tilelayer" and l.get("name") == "walls"]
        if d and len(walls) != 1:
            errors.append(f"{self.name}: needs exactly one tile layer named walls (the collision)")
        tiles = [l for l in layers if l.get("type") == "tilelayer"]
        if d and sorted(str(l.get("name")) for l in tiles) != ["floor", "walls"]:
            errors.append(f"{self.name}: needs exactly the tile layers floor and walls (the explore page draws those two)")
        for l in tiles:
            if (l.get("width"), l.get("height")) != (self.w, self.h):
                errors.append(f"{self.name}: tile layer {l.get('name')!r} must be the map's size, {self.w}x{self.h}")
        groups = [l for l in layers if l.get("type") == "objectgroup"]
        if d and [l.get("name") for l in groups] != ["objects"]:
            errors.append(f"{self.name}: needs exactly one object layer, named objects (the explore page reads that one)")
        good = lambda l: (isinstance(l.get("data"), list) and len(l["data"]) == self.w * self.h
                          and all(isinstance(g, int) and not isinstance(g, bool) and g >= 0 for g in l["data"])
                          and (l.get("width"), l.get("height")) == (self.w, self.h))
        for l in tiles:
            if not good(l):
                errors.append(f"{self.name}: the {l.get('name')} layer must be {self.w}x{self.h} tile numbers (CSV, not base64)")
        data = walls[0].get("data") if walls and good(walls[0]) else None
        self.wall = {(i % self.w, i // self.w) for i, g in enumerate(data or []) if g & GID}
        self.objects = []
        for layer in layers:
            if layer.get("type") != "objectgroup":
                continue
            for o in layer.get("objects") if isinstance(layer.get("objects"), list) else []:
                if not isinstance(o, dict):
                    errors.append(f"{self.name}: an object in layer {layer.get('name')!r} is not a JSON object")
                    continue
                where = f"{self.name}: object {o.get('id')} ({o.get('type') or o.get('class') or '?'})"
                if not isinstance(o.get("type", ""), str):
                    errors.append(f"{where}: type must be text")
                    continue
                if "template" in o:
                    errors.append(f"{where}: uses a Tiled template, which Phaser doesn't resolve; detach it")
                if "class" in o and "type" not in o:
                    errors.append(f"{where}: has a class but no type (saved by Tiled 1.9); save with Tiled 1.10 or later")
                if not all(_num(o.get(k, 0)) and math.isfinite(o.get(k, 0)) for k in ("x", "y", "width", "height")):
                    errors.append(f"{where}: x, y, width and height must be numbers")
                    continue
                if (o.get("rotation") or o.get("point") or o.get("ellipse")
                        or any(k in o for k in ("polygon", "polyline", "text", "gid"))):
                    errors.append(f"{where}: must be an unrotated rectangle (insert tile objects as rectangles)")
                    continue
                if (o.get("width"), o.get("height")) != (self.tw, self.th) or o.get("x", 0) % self.tw or o.get("y", 0) % self.th:
                    errors.append(f"{where}: must be exactly one tile on the grid ({self.tw}x{self.th} at a multiple of "
                                  f"{self.tw}; snap to grid in Tiled); the explore page gives it a body that size at its centre")
                    continue
                self.objects.append({"type": o.get("type"), "props": _props(o, where, errors), "where": where,
                                     "tile": self._tile(o), "rect": self._rect(o)})
        pack_dir = path.parent.parent.resolve()
        sets = d.get("tilesets") if isinstance(d.get("tilesets"), list) else []
        if d and [t.get("name") if isinstance(t, dict) else None for t in sets] != ["tiles"]:
            errors.append(f"{self.name}: needs exactly one tileset, named tiles (the explore page draws with that one)")
        for ts in sets:
            if not isinstance(ts, dict):
                errors.append(f"{self.name}: a tileset is not a JSON object")
            elif "source" in ts:
                errors.append(f"{self.name}: tileset {ts.get('source')!r} is external; embed it (Phaser reads embedded tilesets only)")
            else:
                image = ts.get("image")
                try:
                    target = (path.parent / image).resolve() if isinstance(image, str) and image else None
                except (OSError, ValueError):
                    target = None
                if (target is None or not target.is_relative_to(pack_dir) or target.suffix.lower() not in IMAGES
                        or not target.is_file()):
                    errors.append(f"{self.name}: tileset {ts.get('name')!r} image {image!r} is not in the pack "
                                  f"(a {'/'.join(IMAGES)} file under the pack's folder)")

    def _box(self, o: dict) -> tuple[float, float, float, float]:
        x, y, w, h = (float(o.get(k, 0) or 0) for k in ("x", "y", "width", "height"))
        return x, y, max(w, 0.0), max(h, 0.0)

    def _tile(self, o: dict) -> tuple[int, int]:
        x, y, w, h = self._box(o)
        return int((x + w / 2) // self.tw), int((y + h / 2) // self.th)

    def _rect(self, o: dict) -> set[tuple[int, int]]:
        x, y, w, h = self._box(o)
        x0, y0 = int(x // self.tw), int(y // self.th)
        x1, y1 = int(max(x, x + w - 1e-9) // self.tw), int(max(y, y + h - 1e-9) // self.th)
        return {(i, j) for i in range(x0, x1 + 1) for j in range(y0, y1 + 1)}

    def of(self, kind: str) -> list[dict]:
        return [o for o in self.objects if o["type"] == kind]

    def inside(self, t: tuple[int, int]) -> bool:
        return 0 <= t[0] < self.w and 0 <= t[1] < self.h


def step_of(o: dict) -> str | None:
    if o["type"] in ROLES:
        return f"{o['props'].get('encounter')}:{o['type']}"
    if o["type"] == "throne":
        return f"hall:{o['props'].get('hall')}"
    return None


def requires(gate: dict) -> list[str]:
    return [s.strip() for s in gate["props"].get("requires", "").split(",") if s.strip()]


def _near(t: tuple[int, int]) -> list[tuple[int, int]]:
    return [(t[0] + 1, t[1]), (t[0] - 1, t[1]), (t[0], t[1] + 1), (t[0], t[1] - 1)]


def reachability(m: Map, steps: list[str] | None = None) -> list[str]:
    """The walk of §4.2. `steps` is the realm's step order (None on the overworld, which has none).
    Returns an error for the first step that can't be reached when the game waits on it, and for
    any other object that can't be reached."""
    spawns = m.of("spawn")
    if len(spawns) != 1:
        return []   # reported by the shape checks
    gates = [(g, requires(g)) for g in m.of("gate")]
    solid = {o["tile"] for o in m.objects if o["type"] not in ("spawn", "gate")}
    start = spawns[0]["tile"]
    if not m.inside(start) or start in m.wall or start in solid:
        return [f"{spawns[0]['where']}: the spawn is outside the map, in a wall, or on a solid object"]
    for g, _ in gates:
        if start in g["rect"]:
            return [f"{g['where']}: covers the spawn"]

    def walk(done: set[str]) -> set[tuple[int, int]]:
        blocked = m.wall | solid | {t for g, needs in gates if not set(needs) <= done for t in g["rect"]}
        seen, todo = {start}, [start]
        while todo:
            for n in _near(todo.pop()):
                if m.inside(n) and n not in seen and n not in blocked:
                    seen.add(n)
                    todo.append(n)
        return seen

    reach = lambda o, seen: any(n in seen for n in _near(o["tile"]))
    errors = []
    first = walk(set())
    for o in m.of("exit") + m.of("portal"):
        if not reach(o, first):
            errors.append(f"{o['where']}: can't be reached from the spawn")
    by_step = {step_of(o): o for o in m.objects if step_of(o)}
    done: set[str] = set()
    for s in steps or []:
        if s not in by_step:
            continue    # reported by the binding checks
        if not reach(by_step[s], walk(done)):
            shut = [g["where"] for g, needs in gates if not set(needs) <= done]
            errors.append(f"{by_step[s]['where']}: can't be reached when the game waits on {s}"
                          + (f" (still shut: {'; '.join(shut)})" if shut else ""))
            break       # every later step waits on this one
        done.add(s)
    return errors


def _shape(m: Map, allowed: set[str], errors: list[str]) -> None:
    for o in m.objects:
        if o["type"] not in allowed:
            errors.append(f"{o['where']}: type must be one of {sorted(allowed)}")
            continue
        missing, extra = PROPS[o["type"]] - set(o["props"]), set(o["props"]) - PROPS[o["type"]]
        if missing or extra:
            errors.append(f"{o['where']}: needs exactly the properties {sorted(PROPS[o['type']]) or 'none'}")
        if o["type"] == "gate":
            if not all(m.inside(t) for t in o["rect"]):
                errors.append(f"{o['where']}: is not wholly on the map")
            elif len(o["rect"]) != 1:
                errors.append(f"{o['where']}: must fill exactly one tile (the explore page blocks one; use a gate per tile)")
            if not requires(o):
                errors.append(f"{o['where']}: requires names no step, so it never blocks anything")
        elif not m.inside(o["tile"]):
            errors.append(f"{o['where']}: is outside the map")
        elif len(o["rect"]) != 1:
            errors.append(f"{o['where']}: must fill exactly one tile (it is solid on one tile only)")
    if len(m.of("spawn")) != 1:
        errors.append(f"{m.name}: needs exactly one spawn")
    edge = {(x, y) for x in range(m.w) for y in (0, m.h - 1)} | {(x, y) for y in range(m.h) for x in (0, m.w - 1)}
    shut = m.wall | {o["tile"] for o in m.objects if o["type"] not in ("spawn", "gate")}   # walls, or someone solid
    if m.doc and not edge <= shut:
        x, y = min(edge - shut, key=lambda t: (t[1], t[0]))
        errors.append(f"{m.name}: the map's edge must all be wall or someone solid (the explore page doesn't stop the player there); "
                      f"({x}, {y}) isn't")


def check_realm_map(m: Map, realm: dict) -> list[str]:
    errors = m.errors
    # The walk follows realm_steps, which is the machine's order only for a realm of halls or of one encounter.
    if realm["halls"] and realm["encounters"] or len(realm["encounters"]) > 1:
        return errors + [f"{m.name}: realm {realm['id']} has halls and an encounter, or two encounters; a map plays one or the other"]
    _shape(m, REALM_TYPES, errors)
    if len(m.of("exit")) != 1:
        errors.append(f"{m.name}: needs exactly one exit")
    steps = realm_steps(realm)
    placed = [step_of(o) for o in m.objects if step_of(o)]
    for o in m.objects:
        s = step_of(o)
        if s and s not in steps:
            errors.append(f"{o['where']}: {s} is not a step of realm {realm['id']}")
    for s in steps:
        if placed.count(s) != 1:
            errors.append(f"{m.name}: step {s} needs exactly one object, has {placed.count(s)}")
    for g in m.of("gate"):
        for need in requires(g):
            if need not in steps:
                errors.append(f"{g['where']}: requires {need}, which is not a step of realm {realm['id']}")
    return errors + reachability(m, steps)


def check_overworld(m: Map, realms: list[dict]) -> list[str]:
    errors = m.errors
    _shape(m, OVERWORLD_TYPES, errors)
    ids = [r["id"] for r in realms]
    to = [o["props"].get("to") for o in m.of("portal")]
    for o in m.of("portal"):
        if o["props"].get("to") not in ids:
            errors.append(f"{o['where']}: to={o['props'].get('to')!r} is not a realm")
    for rid in ids:
        if to.count(rid) != 1:
            errors.append(f"{m.name}: realm {rid} needs exactly one portal, has {to.count(rid)}")
    for g in m.of("gate"):
        errors.append(f"{g['where']}: the overworld has no steps to open a gate")
    return errors + reachability(m)


def check_maps(pack_dir: pathlib.Path, data: dict) -> list[str]:
    """Every map a pack's explore front end needs, and nothing else under maps/."""
    explore = (data.get("pack") or {}).get("explore_realms") or []
    folder = pack_dir / "maps"
    files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    present = {p.stem: p for p in files if p.suffix == ".tmj"}
    if not explore:
        return [f"maps/{p.name}: no realm is explorable (explore.realms), so no map is used"
                for p in files if p.suffix.lower() not in IMAGES]
    errors = []
    realms = {r["id"]: r for r in data.get("realms") or []}
    images = set()
    for m in present.values():
        for ts in _tilesets(m):
            try:
                images.add((m.parent / ts["image"]).resolve())
            except (KeyError, TypeError, OSError, ValueError):
                pass    # reported by the map's own checks
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        if p.is_dir():
            errors.append(f"maps/{p.name}/: maps/ holds no folders")
    for p in files:
        if p.suffix != ".tmj" and p.resolve() not in images:
            errors.append(f"maps/{p.name}: not used (maps/ holds {OVERWORLD}.tmj, a .tmj per realm in explore.realms, "
                          f"and their tileset images)")
    for name in sorted(set(present) - set(explore) - {OVERWORLD}):
        errors.append(f"maps/{name}.tmj: not used (maps are {OVERWORLD} and the realms in explore.realms)")
    if OVERWORLD in realms:
        errors.append(f"realm id {OVERWORLD!r} is reserved for the overworld map; rename the realm")
    for rid in explore:
        if (realms.get(rid) or {}).get("sealed"):
            errors.append(f"explore.realms: realm {rid} is sealed, so its map can never be played")
    if OVERWORLD not in present:
        errors.append(f"maps/{OVERWORLD}.tmj: missing (every explorable pack needs an overworld)")
    else:
        errors += check_overworld(Map(present[OVERWORLD], []), list(realms.values()))
    for rid in explore:
        if rid not in present:
            errors.append(f"maps/{rid}.tmj: missing (realm {rid} is in explore.realms)")
        elif rid in realms:
            errors += check_realm_map(Map(present[rid], []), realms[rid])
    return errors


def _tilesets(path: pathlib.Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sets = doc.get("tilesets") if isinstance(doc, dict) else None
    return [t for t in sets if isinstance(t, dict)] if isinstance(sets, list) else []
