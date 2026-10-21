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
        gate     requires=<step id>,<step id>,...   blocks its tiles until those steps are reachable
  - a step id is "<encounter id>:<merchant|guide|compiler|foe|reward>" or "hall:<hall id>".

An object sits on the tile containing its centre (a tile object is anchored at its bottom-left).
Everything but the spawn and gates is solid; reaching an object means standing on a walkable tile
next to it (up, down, left or right). The reachability check is a flood-fill from the spawn with
every gate closed, opening each gate once the steps it requires are reachable, until nothing
changes. Every object must end up reachable.
"""
from __future__ import annotations

import json
import pathlib

ROLES = ("merchant", "guide", "compiler", "foe", "reward")
PROPS = {"spawn": set(), "exit": set(), "portal": {"to"}, "throne": {"hall"}, "gate": {"requires"},
         **{role: {"encounter"} for role in ROLES}}
REALM_TYPES = set(PROPS) - {"portal"}
OVERWORLD_TYPES = {"spawn", "portal", "gate"}
OVERWORLD = "overworld"


def realm_steps(realm: dict) -> list[str]:
    """Every step a realm's map must hold, in the order the game plays them."""
    steps = [f"hall:{h['id']}" for h in realm["halls"]]
    for e in realm["encounters"]:
        steps += [f"{e['id']}:{role}" for role in ROLES]
    return steps


def _props(obj: dict, where: str, errors: list[str]) -> dict[str, str]:
    out = {}
    for p in obj.get("properties") or []:
        if not isinstance(p, dict) or p.get("type", "string") != "string" or not isinstance(p.get("value"), str):
            errors.append(f"{where}: property {p.get('name') if isinstance(p, dict) else p!r} must be a string")
            continue
        out[p.get("name")] = p["value"]
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
        d = self.doc
        self.w, self.h = d.get("width", 0), d.get("height", 0)
        self.tw, self.th = d.get("tilewidth", 0), d.get("tileheight", 0)
        if not all(isinstance(v, int) and v > 0 for v in (self.w, self.h, self.tw, self.th)) and d:
            errors.append(f"{self.name}: needs whole-number width, height, tilewidth and tileheight")
            self.w = self.h = self.tw = self.th = 1
        layers = d.get("layers") or []
        walls = [l for l in layers if l.get("type") == "tilelayer" and l.get("name") == "walls"]
        if d and len(walls) != 1:
            errors.append(f"{self.name}: needs exactly one tile layer named walls (the collision)")
        data = walls[0].get("data") if walls else None
        if walls and (not isinstance(data, list) or len(data) != self.w * self.h):
            errors.append(f"{self.name}: the walls layer's data must be {self.w}x{self.h} tile numbers (CSV, not base64)")
            data = None
        self.wall = {(i % self.w, i // self.w) for i, g in enumerate(data or []) if g}
        self.objects = []
        for layer in layers:
            if layer.get("type") != "objectgroup":
                continue
            for o in layer.get("objects") or []:
                where = f"{self.name}: object {o.get('id')} ({o.get('type') or o.get('class') or '?'})"
                if "template" in o:
                    errors.append(f"{where}: uses a Tiled template, which Phaser doesn't resolve; detach it")
                if "class" in o and "type" not in o:
                    errors.append(f"{where}: has a class but no type (saved by Tiled 1.9); save with Tiled 1.10 or later")
                self.objects.append({"type": o.get("type"), "props": _props(o, where, errors), "where": where,
                                     "tile": self._tile(o), "rect": self._rect(o)})
        for ts in d.get("tilesets") or []:
            if "source" in ts:
                errors.append(f"{self.name}: tileset {ts.get('source')!r} is external; embed it (Phaser reads embedded tilesets only)")
            elif not ts.get("image") or not (path.parent / ts["image"]).is_file():
                errors.append(f"{self.name}: tileset {ts.get('name')!r} image {ts.get('image')!r} is not in the pack")

    def _box(self, o: dict) -> tuple[float, float, float, float]:
        x, y, w, h = (float(o.get(k, 0) or 0) for k in ("x", "y", "width", "height"))
        if "gid" in o:  # tile objects are anchored at their bottom-left
            y -= h
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


def reachability(m: Map) -> list[str]:
    """The flood-fill of §4.2. Returns errors for every object it can't reach."""
    errors = []
    spawns = m.of("spawn")
    if len(spawns) != 1:
        return errors   # reported by the shape checks
    gates = [(o, [s.strip() for s in o["props"].get("requires", "").split(",") if s.strip()]) for o in m.of("gate")]
    solid = {o["tile"] for o in m.objects if o["type"] not in ("spawn", "gate")}
    start = spawns[0]["tile"]
    if not m.inside(start) or start in m.wall or start in solid:
        return [f"{spawns[0]['where']}: the spawn is outside the map, in a wall, or on a solid object"]
    near = lambda t: [(t[0] + 1, t[1]), (t[0] - 1, t[1]), (t[0], t[1] + 1), (t[0], t[1] - 1)]
    opened: set[int] = set()
    while True:
        blocked = m.wall | solid | {t for i, (g, _) in enumerate(gates) if i not in opened for t in g["rect"]}
        seen, todo = {start}, [start]
        while todo:
            for n in near(todo.pop()):
                if m.inside(n) and n not in seen and n not in blocked:
                    seen.add(n)
                    todo.append(n)
        reached = {step_of(o) for o in m.objects if step_of(o) and any(n in seen for n in near(o["tile"]))}
        more = {i for i, (_, needs) in enumerate(gates) if i not in opened and set(needs) <= reached}
        if not more:
            break
        opened |= more
    for o in m.objects:
        if o["type"] not in ("spawn", "gate") and not any(n in seen for n in near(o["tile"])):
            errors.append(f"{o['where']}: can't be reached from the spawn")
    for i, (g, needs) in enumerate(gates):
        if i not in opened:
            errors.append(f"{g['where']}: never opens (it needs {', '.join(needs) or 'nothing'}, which can't all be reached first)")
    return errors


def _shape(m: Map, allowed: set[str], errors: list[str]) -> None:
    for o in m.objects:
        if o["type"] not in allowed:
            errors.append(f"{o['where']}: type must be one of {sorted(allowed)}")
            continue
        missing, extra = PROPS[o["type"]] - set(o["props"]), set(o["props"]) - PROPS[o["type"]]
        if missing or extra:
            errors.append(f"{o['where']}: needs exactly the properties {sorted(PROPS[o['type']]) or 'none'}")
        if not m.inside(o["tile"]) and o["type"] != "gate":
            errors.append(f"{o['where']}: is outside the map")
    if len(m.of("spawn")) != 1:
        errors.append(f"{m.name}: needs exactly one spawn")


def check_realm_map(m: Map, realm: dict) -> list[str]:
    errors = m.errors
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
        for need in [x.strip() for x in g["props"].get("requires", "").split(",") if x.strip()]:
            if need not in steps:
                errors.append(f"{g['where']}: requires {need}, which is not a step of realm {realm['id']}")
    return errors + reachability(m)


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
    present = {p.stem: p for p in folder.glob("*.tmj")} if folder.is_dir() else {}
    if not explore:
        return [f"maps/{n}.tmj: no realm is explorable (explore.realms), so no map is used" for n in sorted(present)]
    errors = []
    realms = {r["id"]: r for r in data.get("realms") or []}
    for name in sorted(set(present) - set(explore) - {OVERWORLD}):
        errors.append(f"maps/{name}.tmj: not used (maps are {OVERWORLD} and the realms in explore.realms)")
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
