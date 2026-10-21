#!/usr/bin/env python3
"""Build a quest: a browser game made from a pack of content, such as AgentQL Quest.

A pack is a folder under `packs/` (design: docs/superpowers/specs/2026-10-21-agentql-quest-pack-design.md):

  - `pack.yaml`: the manifest. Its id, title, Pages folder and save key; the code panes every
    encounter shows; the reward screen's rule tags; the lexicon; and the checks (plugins) to run.
  - `content.yaml`: the realms, halls, encounters and their questions.
  - `strings.yaml`: wording a front end shows that isn't content.
  - `art/classic/*.txt`: the classic page's ASCII art (see the tool's README).

The engine knows only general things: realms, halls, trials, encounters, panes, points, routes,
scoring and saves. Anything specific to one game, such as AgentQL's captured SQL and course, is a
plugin in `checks/` that the pack names.

The build writes the game's data, `quest.json`; the schema it fits, `quest.schema.json`, generated
for this pack from `schema/core.json`; and one self-contained `index.html` (the classic text
adventure, `classic/game.html` with the data, the pack's art, its title and description, and the
fonts written in), so the page makes no outside requests and runs from GitHub Pages, any static
host, or a double-click.

    python3 tools/quest/build.py                   # write tools/quest/dist/
    python3 tools/quest/build.py --out _site/index.html   # quest.json and its schema land beside it
    python3 tools/quest/build.py --check           # validate only (tools/validate/check_agentql_quest.py)
    python3 tools/quest/build.py --pack <id>       # another pack (default: agentql)

Fails when the content, a plugin's check, the published-name denylist or the generated schema
says so. For AgentQL Quest that includes a lesson or Module the text names that the course no
longer has, a missing or rejected case, AgentQL that differs by more than layout, an `sql` line
that is no longer in the SQL exactly, an `sql_count` that no longer holds, a row cap or null guard
credited to anyone but ThoughtSpot by a who point, or a capture header that names a different Model from the one
the AgentQL queries. A recapture that changes what a lesson teaches therefore breaks the build
instead of quietly teaching something false.

Plugins
-------
A plugin is a module in `checks/` with a NAME. Everything else is optional:

  KEYS          {level: {content keys it owns}}, levels top, realm, hall, encounter, point, trial, path.
                The build rejects any content key that neither the engine nor a plugin owns.
  REFS          {"realm" | "encounter": {key: JSON Schema}}: what it records under that level's refs.
  META          a JSON Schema object for what it records under meta[NAME] (needs a meta hook).
  SOURCES       the pack.yaml sources it reads; a pack that lacks one fails before compiling.
  STRINGS       the strings.yaml keys it reads (so the build knows they are used).
  POINT_KINDS, TRIAL_KINDS   point and trial kinds it compiles; COMPILES_PATH: it compiles paths.
                A kind belongs to one owner: the engine's own (claim, choice) can't be taken.
A pane whose `from` names the plugin is filled by its encounter hook. Plugins run in the order the
pack lists them; none may depend on another's output.
  load(pack, errors) -> ctx                       read its sources once
  meta(ctx) -> dict
  realm(ctx, r, where, errors) -> refs
  encounter(ctx, e, panes, where, errors) -> refs  may fill panes {id: lines}
  check_point(ctx, p, panes, where, errors)        any point
  point(ctx, p, panes, highlights, where, errors) -> {options, correct, rule_tag}   its kinds
  trial(ctx, t, where, errors) -> trial            its kinds
  path(ctx, path, where, errors) -> path
  finish(ctx, pack, data, errors)                  whole-quest checks
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import denylist  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKS = HERE / "packs"
CHECKS = HERE / "checks"
CORE_SCHEMA = HERE / "schema" / "core.json"
TEMPLATE = HERE / "classic" / "game.html"
DEFAULT_PACK = "agentql"
SCHEMA_VERSION = 2
BESIDE = ("quest.json", "quest.schema.json")  # written next to the page, so --out may not name them
FONT_DIR = HERE / "fonts"
DEFAULT_OUT = HERE / "dist" / "index.html"
PLACEHOLDER = "__QUEST_DATA__"
FONT_PLACEHOLDER = "/*__FONT_FACES__*/"
ART_PLACEHOLDER = "__CLASSIC_ART__"
TITLE_PLACEHOLDER, DESCRIPTION_PLACEHOLDER = "__PAGE_TITLE__", "__PAGE_DESCRIPTION__"
PAGES = "https://thoughtspot.github.io/thoughtspot-agent-skills"

# (family, weight, file in fonts/) — Latin subsets from Fontsource 5.3.0, SIL OFL 1.1.
FONTS = (
    ("VT323", 400, "vt323-latin-400-normal.woff2"),
    ("IBM Plex Mono", 400, "ibm-plex-mono-latin-400-normal.woff2"),
    ("IBM Plex Mono", 600, "ibm-plex-mono-latin-600-normal.woff2"),
)

ID = re.compile(r"[a-z][a-z0-9_]*")
RESERVED_IDS = {"hall"}  # step ids are "<encounter id>:<step>" and "hall:<hall id>"
ALL = "*"
LEVELS = ("top", "realm", "hall", "encounter", "point", "trial", "path")
CORE_KEYS = {
    "top": {"realms", "encounters", "routes"},
    "realm": {"id", "name", "depth", "minutes", "covers", "sealed", "scroll", "halls", "decree", "encounters",
              "source"},  # source: a note for maintainers, not shown
    "hall": {"id", "title", "teach", "columns", "rows", "trials"},
    "encounter": {"id", "quest", "path", "points", "takeaway"},  # plus the ids of content panes
    "point": {"kind", "ask", "hint", "why", "options", "rule", "rule_tag"},  # plus pane ids (highlights)
    "trial": {"kind", "text", "why", "options", "claim", "truth"},
    "path": {"options"},
}
MANIFEST_KEYS = {"id", "title", "publish_path", "storage_key", "unlock", "checks", "sources", "panes",
                 "rule_tags", "lexicon", "explore"}
LEXICON = ("guide", "compiler", "foe", "reward", "currency")
GROUPS = ("rules", "yours", "verdict")
UNLOCKS = ("first_realm_first",)  # the only rule a front end implements today
MATCHES = ("contains", "line")


class Pack:
    """One pack folder, read and checked as far as it can be without its content compiled."""

    def __init__(self, pid: str, packs: pathlib.Path | None = None):
        self.dir = (packs or PACKS) / pid
        self.errors: list[str] = []
        self.manifest = self._yaml("pack.yaml")
        self.content_text = (self.dir / "content.yaml").read_text(encoding="utf-8")
        self.doc = yaml.safe_load(self.content_text) or {}
        self.strings_text = (self.dir / "strings.yaml").read_text(encoding="utf-8")
        self.strings = self._yaml("strings.yaml")
        m = self.manifest
        self.id, self.title = m.get("id"), m.get("title", "")
        self.publish_path, self.storage_key = m.get("publish_path", ""), m.get("storage_key", "")
        self.panes = m.get("panes") if isinstance(m.get("panes"), list) else []
        self.rule_tags = m.get("rule_tags") if isinstance(m.get("rule_tags"), dict) else {}
        shapes = {"checks": list, "sources": dict, "lexicon": dict, "explore": dict, "rule_tags": dict, "panes": list}
        for key, kind in shapes.items():
            if key in m and not isinstance(m[key], kind):
                self.errors.append(f"pack.yaml: {key} must be a {'list' if kind is list else 'mapping'}")
                m[key] = kind()  # checked as empty from here on, so the rest reports cleanly
        self._check_manifest(pid)

    def _yaml(self, name: str) -> dict:
        data = yaml.safe_load((self.dir / name).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            self.errors.append(f"{name}: must be a mapping")
            return {}
        return data

    def source(self, name: str) -> pathlib.Path:
        return ROOT / (self.manifest.get("sources") or {})[name]

    def string(self, key: str, **values: str) -> str:
        """The string, with each {name} filled once (a value is never filled again)."""
        return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), self.strings.get(key, ""))

    def _check_manifest(self, pid: str) -> None:
        m, err = self.manifest, self.errors.append
        for k in sorted(set(m) - MANIFEST_KEYS):
            err(f"pack.yaml: unknown key {k!r}")
        if self.id != pid or not ID.fullmatch(str(self.id)):
            err(f"pack.yaml: id must be the folder name ({pid!r}), lowercase letters, digits and _")
        if not self.title:
            err("pack.yaml: missing title")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(self.publish_path)):
            err("pack.yaml: publish_path must be a folder name (lowercase letters, digits and -)")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", str(self.storage_key)):
            err("pack.yaml: storage_key must be lowercase letters, digits, - and _")
        if m.get("unlock") not in UNLOCKS:
            err(f"pack.yaml: unlock must be one of {list(UNLOCKS)}")
        for name in m.get("checks") or []:
            if not ID.fullmatch(str(name)) or not (CHECKS / f"{name}.py").is_file():
                err(f"pack.yaml: no plugin checks/{name}.py")
        for name, rel in (m.get("sources") if isinstance(m.get("sources"), dict) else {}).items():
            if not isinstance(rel, str) or not (ROOT / rel).is_file():
                err(f"pack.yaml: source {name!r} is not a file in the repo: {rel!r}")
        lexicon = m.get("lexicon") or {}
        if sorted(lexicon) != sorted(LEXICON) or not all(isinstance(v, str) and v for v in lexicon.values()):
            err(f"pack.yaml: lexicon must name exactly {list(LEXICON)}")
        for tag, spec in self.rule_tags.items():
            if not ID.fullmatch(str(tag)) or not isinstance(spec, dict) or set(spec) != {"label", "group"} \
                    or not isinstance(spec.get("label"), str) or spec.get("group") not in GROUPS:
                err(f"pack.yaml: rule tag {tag!r} needs a label and a group ({'/'.join(GROUPS)})")
        if not isinstance((m.get("explore") or {}).get("realms", []), list):
            err("pack.yaml: explore.realms must be a list of realm ids")
        for k, v in (self.strings if isinstance(self.strings, dict) else {}).items():
            if not ID.fullmatch(str(k)) or not isinstance(v, str):
                err(f"strings.yaml: {k!r} must be a lowercase key with a text value")
        self._check_panes()

    def _check_panes(self) -> None:
        err, ids = self.errors.append, []
        if not self.panes:
            err("pack.yaml: needs at least one pane")
        for n, p in enumerate(self.panes, 1):
            if not isinstance(p, dict):
                err(f"pack.yaml: pane {n} must be a mapping")
                continue
            pid = p.get("id")
            if not isinstance(pid, str) or not ID.fullmatch(pid) or pid in ids:
                err(f"pack.yaml: pane {n}: id must be unique, lowercase letters, digits and _")
            ids.append(pid)
            if set(p) != {"id", "from", "match", "label", "name", "caption"}:
                err(f"pack.yaml: pane {pid}: needs exactly id, from, match, label, name, caption")
            if p.get("from") != "content" and p.get("from") not in (self.manifest.get("checks") or []):
                err(f"pack.yaml: pane {pid}: from must be content or one of the pack's checks")
            if p.get("match") not in MATCHES:
                err(f"pack.yaml: pane {pid}: match must be one of {list(MATCHES)}")
            for k in ("label", "name"):
                if not isinstance(p.get(k), str) or p.get(k) not in self.strings:
                    err(f"pack.yaml: pane {pid}: {k} {p.get(k)!r} is not in strings.yaml")
            if p.get("caption") and (not isinstance(p.get("caption"), str) or p.get("caption") not in self.strings):
                err(f"pack.yaml: pane {pid}: caption {p.get('caption')!r} is not in strings.yaml")

    @property
    def pane_ids(self) -> list[str]:
        return [p.get("id") for p in self.panes if isinstance(p, dict) and isinstance(p.get("id"), str)]

    @property
    def content_panes(self) -> list[str]:
        return [p.get("id") for p in self.panes if isinstance(p, dict) and p.get("from") == "content"]


def pack_ids(packs: pathlib.Path | None = None) -> list[str]:
    return sorted(p.parent.name for p in (packs or PACKS).glob("*/pack.yaml"))


def check_packs_unique(packs: pathlib.Path | None = None) -> list[str]:
    """Every pack is served from the same origin, and saving rewrites the whole progress object,
    so two packs sharing a storage key would erase each other's saves."""
    errors, seen, packs = [], {}, packs or PACKS
    for pid in pack_ids(packs):
        m = yaml.safe_load((packs / pid / "pack.yaml").read_text(encoding="utf-8")) or {}
        for key in ("id", "publish_path", "storage_key"):
            other = seen.setdefault((key, m.get(key)), pid)
            if other != pid:
                errors.append(f"packs {other} and {pid} share {key} {m.get(key)!r}")
    return errors


def load_plugins(names: list[str]) -> list:
    plugins = []
    for name in names:
        path = CHECKS / f"{name}.py"
        if not ID.fullmatch(str(name)) or not path.is_file():
            continue  # reported by the manifest check
        spec = importlib.util.spec_from_file_location(f"quest_check_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "NAME", None) != name:
            raise ValueError(f"checks/{name}.py must set NAME = {name!r}")
        strings = getattr(mod, "STRINGS", set())
        if not isinstance(strings, (set, frozenset, list, tuple)) or not all(isinstance(k, str) for k in strings):
            raise ValueError(f"checks/{name}.py: STRINGS must be a set of strings.yaml keys")
        if getattr(mod, "META", None) and not hasattr(mod, "meta"):
            raise ValueError(f"checks/{name}.py declares META but has no meta hook")
        plugins.append(mod)
    return plugins


def _unknown(item: dict, allowed: set[str], where: str, errors: list[str]) -> None:
    for k in sorted(set(item) - allowed, key=str):
        errors.append(f"{where}: unknown key {k!r} (no check owns it)")


def _id(value, where: str, seen: set, errors: list[str]) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value) or value in RESERVED_IDS:
        errors.append(f"{where}: id {value!r} must be lowercase letters, digits and _ (and not 'hall')")
        return str(value)
    if value in seen:
        errors.append(f"{where}: duplicate id {value!r}")
    seen.add(value)
    return value


def _highlight(matches: list[str], lines: list[str], mode: str, where: str, errors: list[str]) -> list[int] | str:
    """`contains`: substring match. `line`: each match must equal a whole line (indentation
    ignored), so a recapture that edits that line — LIMIT 100000 → 1000000, JOIN → LEFT OUTER
    JOIN — fails."""
    if ALL in matches:
        return "all"
    hits: set[int] = set()
    for m in matches:
        if mode == "line":
            found = [i for i, line in enumerate(lines) if line.strip() == m.strip()]
            if not found:
                errors.append(f"{where}: no line is exactly {m!r}")
        else:
            found = [i for i, line in enumerate(lines) if m in line]
            if not found:
                errors.append(f"{where}: match {m!r} hits no line")
        hits.update(found)
    return sorted(hits)


class Compiler:
    """Turns a pack's content, with its plugins, into the game's data."""

    def __init__(self, pack: Pack, plugins: list, contexts: dict | None = None):
        self.pack, self.plugins = pack, plugins
        self.errors: list[str] = list(pack.errors)
        given = contexts or {}  # tests hand in a plugin's sources already loaded, e.g. an edited capture
        self.ctx = {pl.NAME: given[pl.NAME] if pl.NAME in given else (pl.load(pack, self.errors) if hasattr(pl, "load") else None)
                    for pl in plugins}
        self.owned = {lvl: set().union(*(getattr(pl, "KEYS", {}).get(lvl, set()) for pl in plugins)) for lvl in LEVELS}
        self.point_kinds = self._kinds("POINT_KINDS", {"choice"})
        self.trial_kinds = self._kinds("TRIAL_KINDS", {"claim", "choice"})
        self.path_plugin = next((pl for pl in plugins if getattr(pl, "COMPILES_PATH", False)), None)
        self.meta = {pl.NAME: pl.meta(self.ctx[pl.NAME]) for pl in plugins if getattr(pl, "META", None)}

    def _kinds(self, attr: str, core: set[str]) -> dict:
        owners: dict = {}
        for pl in self.plugins:
            for kind in getattr(pl, attr, ()):
                if kind in core or kind in owners:
                    self.errors.append(f"checks/{pl.NAME}.py: {attr} {kind!r} already belongs to "
                                       f"{'the engine' if kind in core else owners[kind].NAME}")
                else:
                    owners[kind] = pl
        return owners

    def _hooks(self, name: str):
        return [(pl, self.ctx[pl.NAME]) for pl in self.plugins if hasattr(pl, name)]

    def _refs(self, level: str, item: dict, where: str) -> dict:
        refs = {}
        for pl, ctx in self._hooks(level):
            refs.update(getattr(pl, level)(ctx, item, where, self.errors) if level == "realm"
                        else getattr(pl, level)(ctx, item, self._panes, where, self.errors))
        return refs

    def trial(self, t: dict, where: str) -> dict:
        kind = t.get("kind")
        allowed = CORE_KEYS["trial"] | self.owned["trial"]
        _unknown(t, allowed, where, self.errors)
        if kind in self.trial_kinds:
            pl = self.trial_kinds[kind]
            return pl.trial(self.ctx[pl.NAME], t, where, self.errors)
        if kind == "claim":
            if not t.get("claim") or not t.get("why") or not isinstance(t.get("truth"), bool):
                self.errors.append(f"{where}: a claim needs claim, why and a true/false truth")
            for key in ("claim_true", "claim_false"):
                if not self.pack.strings.get(key):
                    self.errors.append(f"{where}: a claim's buttons come from strings.yaml, which has no {key}")
            return {"kind": "claim", "text": t.get("claim", ""), "why": t.get("why", ""),
                    "options": [self.pack.string("claim_true"), self.pack.string("claim_false")],
                    "correct": 0 if t.get("truth") is True else 1}
        if kind == "choice":
            opts = t.get("options") or []
            for i, o in enumerate(o for o in opts if isinstance(o, dict)):
                _unknown(o, {"text", "correct"}, f"{where} option {i + 1}", self.errors)
            correct = [i for i, o in enumerate(opts) if isinstance(o, dict) and o.get("correct")]
            if len(opts) < 2 or len(correct) != 1 or not t.get("text") or not t.get("why"):
                self.errors.append(f"{where}: a choice needs text, why, 2+ options and exactly one correct")
            return {"kind": "choice", "text": t.get("text", ""), "why": t.get("why", ""),
                    "options": [o.get("text", "") for o in opts if isinstance(o, dict)], "correct": correct[0] if correct else 0}
        kinds = sorted({"claim", "choice"} | set(self.trial_kinds))
        self.errors.append(f"{where}: kind must be one of {kinds}, got {kind!r}")
        return {"kind": "choice", "text": "", "why": "", "options": [], "correct": 0}

    def halls(self, r: dict, rid: str, hall_ids: set) -> list[dict]:
        """A realm of halls teaches one idea per hall, with just the slice of the comparison table it
        needs, then tests it straight away. The full table (`scroll`) is the recap at the end."""
        errors = self.errors
        scroll = r.get("scroll") or {}
        columns = scroll.get("columns") or []
        rows = {row.get("label"): row.get("cells") or [] for row in scroll.get("rows") or []}
        for label, cells in rows.items():
            if len(cells) != len(columns):
                errors.append(f"realm {rid}: scroll row {label!r} has {len(cells)} cells for {len(columns)} "
                              f"columns (an unquoted comma in YAML splits a cell)")
        halls, taught = [], set()
        for n, h in enumerate(r.get("halls") or [], 1):
            where = f"realm {rid} hall {n}"
            _unknown(h, CORE_KEYS["hall"] | self.owned["hall"], where, errors)
            hid = _id(h.get("id"), where, hall_ids, errors)
            cols = h.get("columns") or []
            bad_cols = [c for c in cols if c not in columns]
            bad_rows = [x for x in h.get("rows") or [] if x not in rows]
            if bad_cols or bad_rows:
                errors.append(f"{where}: unknown scroll columns {bad_cols} or rows {bad_rows}")
            if not h.get("title") or not h.get("teach"):
                errors.append(f"{where}: needs a title and something to teach")
            trials = [self.trial(t, f"{where} trial {i}") for i, t in enumerate(h.get("trials") or [], 1)]
            if not trials:
                errors.append(f"{where}: needs at least one question")
            idx = [columns.index(c) for c in cols if c in columns]
            table = [{"label": x, "cells": [rows[x][i] for i in idx if i < len(rows[x])]} for x in h.get("rows") or [] if x in rows]
            taught.update(x for x in h.get("rows") or [])
            halls.append({"id": hid, "title": h.get("title", ""), "teach": h.get("teach") or [], "columns": cols,
                          "rows": table, "trials": trials})
        for label in rows:
            if halls and label not in taught:
                errors.append(f"realm {rid}: scroll row {label!r} is in the recap but no hall teaches it")
        return halls

    def path(self, p: dict, where: str) -> dict:
        if self.path_plugin:
            _unknown(p, self.owned["path"], where, self.errors)
            return self.path_plugin.path(self.ctx[self.path_plugin.NAME], p, where, self.errors)
        _unknown(p, CORE_KEYS["path"], where, self.errors)
        opts = [o for o in p.get("options") or [] if isinstance(o, dict)]
        for i, o in enumerate(opts, 1):
            _unknown(o, {"text", "outcome", "why"}, f"{where} option {i}", self.errors)
        wins = [i for i, o in enumerate(opts) if o.get("outcome") == "win"]
        if len(opts) < 2 or len(wins) != 1 or any(o.get("outcome") not in ("win", "loss", "blocked") or not o.get("why")
                                                   for o in opts):
            self.errors.append(f"{where}: a path needs 2+ options, each with an outcome (win/loss/blocked) and why, "
                               f"and exactly one win")
        return {"options": [o.get("text", "") for o in opts],
                "outcomes": [{"kind": o.get("outcome", "loss"), "why": o.get("why", "")} for o in opts],
                "correct": wins[0] if wins else 0}

    def point(self, p: dict, where: str) -> dict:
        errors, pack = self.errors, self.pack
        _unknown(p, CORE_KEYS["point"] | set(pack.pane_ids) | self.owned["point"], where, errors)
        highlights = {}
        for spec in pack.panes:
            matches = p.get(spec["id"]) or []
            if not isinstance(matches, list) or not all(isinstance(m, str) for m in matches):
                errors.append(f"{where}: {spec['id']} must be a list of text matches")
                matches = []
            highlights[spec["id"]] = _highlight(matches, self._panes.get(spec["id"]) or [], spec["match"],
                                                f"{where} {spec['id']}", errors)
        out = {"ask": p.get("ask", ""), "hint": p.get("hint", ""), "why": p.get("why", ""), "highlights": highlights}
        for field in ("ask", "hint", "why"):
            if not out[field]:
                errors.append(f"{where}: missing {field}")
        for pl, ctx in self._hooks("check_point"):
            pl.check_point(ctx, p, self._panes, where, errors)
        kind = p.get("kind")
        default_tag = ""
        if kind in self.point_kinds:
            pl = self.point_kinds[kind]
            got = pl.point(self.ctx[pl.NAME], p, self._panes, highlights, where, errors)
            options, correct, default_tag = got["options"], got["correct"], got.get("rule_tag", "")
        elif kind == "choice":
            opts = p.get("options") or []
            for i, o in enumerate(o for o in opts if isinstance(o, dict)):
                _unknown(o, {"text", "correct"}, f"{where} option {i + 1}", errors)
            right = [i for i, o in enumerate(opts) if isinstance(o, dict) and o.get("correct")]
            if len(opts) < 2 or len(right) != 1:
                errors.append(f"{where}: a choice needs 2+ options and exactly one correct")
            options, correct = [o.get("text", "") for o in opts if isinstance(o, dict)], right[0] if right else 0
        else:
            errors.append(f"{where}: kind must be one of {sorted({'choice'} | set(self.point_kinds))}, got {kind!r}")
            options, correct = [], 0
        tag = p.get("rule_tag") or default_tag
        if p.get("rule") and tag not in pack.rule_tags:
            errors.append(f"{where}: rule_tag must be one of {list(pack.rule_tags)}, got {tag!r}")
        out.update(options=options, correct=correct, rule=p.get("rule", ""),
                   ruleTag=tag if p.get("rule") and tag in pack.rule_tags else "")
        return out

    def encounter(self, e: dict, where: str) -> dict:
        errors, pack = self.errors, self.pack
        _unknown(e, CORE_KEYS["encounter"] | set(pack.content_panes) | self.owned["encounter"], where, errors)
        self._panes = {pid: str(e.get(pid) or "").rstrip("\n").splitlines() for pid in pack.content_panes}
        for pid in pack.content_panes:
            if not self._panes[pid]:
                errors.append(f"{where}: missing the {pid} pane")
        refs = self._refs("encounter", e, where)
        panes = []
        for spec in pack.panes:
            lines = self._panes.get(spec["id"])
            if lines is None:
                errors.append(f"{where}: {spec['from']} did not fill the {spec['id']} pane")
                lines = []
            panes.append({"id": spec["id"], "label": pack.string(spec["label"]), "name": pack.string(spec["name"]),
                          "lines": lines, "caption": self.caption(spec, refs, where)})
        points = [self.point(p, f"{where} point {i}") for i, p in enumerate(e.get("points") or [], 1)]
        if not points:
            errors.append(f"{where}: no points")
        for field in ("quest", "path", "takeaway"):
            if not e.get(field):
                errors.append(f"{where}: missing {field}")
        return {"id": e.get("id", ""), "quest": e.get("quest", ""), "path": self.path(e.get("path") or {}, f"{where} path"),
                "panes": panes, "points": points, "takeaway": e.get("takeaway", ""), "refs": refs}

    def caption(self, spec: dict, refs: dict, where: str) -> str:
        if not spec.get("caption"):
            return ""
        values = {k: str(v) for m in self.meta.values() for k, v in m.items()} | {k: str(v) for k, v in refs.items()}
        text = self.pack.strings.get(spec["caption"], "")
        for name in re.findall(r"\{(\w+)\}", text):
            if name not in values:
                self.errors.append(f"{where}: caption {spec['caption']} names {{{name}}}, which nothing provides")
        return self.pack.string(spec["caption"], **values)

    def compile(self) -> dict:
        errors, pack, doc = self.errors, self.pack, self.pack.doc
        _unknown(doc, CORE_KEYS["top"] | self.owned["top"], "content.yaml", errors)
        encounter_ids, hall_ids, realm_ids = set(), set(), set()
        by_id: dict[str, dict] = {}
        for n, e in enumerate(doc.get("encounters") or [], 1):
            eid = _id(e.get("id"), f"encounter {n}", encounter_ids, errors)
            by_id[eid] = self.encounter(e, f"encounter {eid}")

        realms, used = [], set()
        for n, r in enumerate(doc.get("realms") or [], 1):
            rid = _id(r.get("id"), f"realm {n}", realm_ids, errors)
            where = f"realm {rid}"
            _unknown(r, CORE_KEYS["realm"] | self.owned["realm"], where, errors)
            for field in ("name", "covers", "depth", "minutes"):
                if not r.get(field):
                    errors.append(f"{where}: missing {field}")
            if not isinstance(r.get("minutes"), int) or isinstance(r.get("minutes"), bool):
                errors.append(f"{where}: minutes must be a whole number")  # never 4.0: strict decoders reject a float
            halls = self.halls(r, rid, hall_ids)
            trials = [t for h in halls for t in h["trials"]]
            enc_ids = list(r.get("encounters") or [])
            for eid in enc_ids:
                if eid not in by_id:
                    errors.append(f"{where}: encounter {eid!r} is not defined under encounters")
                elif eid in used:
                    errors.append(f"{where}: encounter {eid!r} is already in another realm")
                used.add(eid)
            sealed = bool(r.get("sealed"))
            if sealed and (trials or enc_ids):
                errors.append(f"{where}: a sealed realm has no trials or encounters")
            if not sealed and not (trials or enc_ids):
                errors.append(f"{where}: an open realm needs trials or encounters (or sealed: true)")
            if halls and not r.get("decree"):
                errors.append(f"{where}: a realm of halls needs a decree")
            realms.append({
                "id": rid, "name": r.get("name", ""), "depth": r.get("depth", ""),
                "minutes": r.get("minutes", 0), "covers": r.get("covers", ""), "sealed": sealed,
                "scroll": r.get("scroll"), "halls": halls, "decree": r.get("decree") or [],
                "encounters": [by_id[eid] for eid in enc_ids if eid in by_id], "refs": self._refs("realm", r, where),
            })
        if not realms:
            errors.append("realms: none defined")
        elif pack.manifest.get("unlock") == "first_realm_first" and realms[0]["sealed"]:
            errors.append("realms: the first realm is where every player starts, and every other realm waits "
                          "for it (unlock: first_realm_first); it can't be sealed")
        for eid in by_id:
            if eid not in used:
                errors.append(f"encounter {eid}: defined under encounters but in no realm")
        explore = (pack.manifest.get("explore") or {}).get("realms", [])
        for rid in explore if isinstance(explore, list) else []:
            if rid not in realm_ids:
                errors.append(f"pack.yaml: explore realm {rid!r} is not a realm")

        routes = []
        for rt in doc.get("routes") or []:
            bad = [x for x in rt.get("path") or [] if x not in realm_ids]
            if bad or not rt.get("who") or not rt.get("path"):
                errors.append(f"route {rt.get('who')!r}: needs who and a path of realm ids (unknown: {bad})")
            routes.append({"who": rt.get("who", ""), "path": rt.get("path") or []})

        data = {"schema_version": SCHEMA_VERSION, "pack": self.pack_data(), "meta": self.meta,
                "realms": realms, "routes": routes}
        for pl, ctx in self._hooks("finish"):
            pl.finish(ctx, pack, data, errors)
        return data

    def pack_data(self) -> dict:
        m = self.pack.manifest
        return {"id": self.pack.id, "title": self.pack.title, "storage_key": self.pack.storage_key,
                "unlock": m.get("unlock"), "explore_realms": list((m.get("explore") or {}).get("realms") or []),
                "lexicon": dict(m.get("lexicon") or {}), "rule_tags": self.pack.rule_tags, "strings": self.pack.strings}


def compile_pack(pack: Pack, contexts: dict | None = None) -> tuple[dict, list[str]]:
    """Compile a pack with the plugins it names. Returns (data, errors). `contexts` replaces a
    plugin's loaded sources by name (tests use it to compile against an edited capture)."""
    plugins = load_plugins(pack.manifest.get("checks") or [])
    sources = pack.manifest.get("sources") if isinstance(pack.manifest.get("sources"), dict) else {}
    missing = [f"pack.yaml: checks/{pl.NAME}.py reads the source {s!r}, which sources doesn't name"
               for pl in plugins for s in sorted(getattr(pl, "SOURCES", ())) if s not in sources]
    owned = set().union(*(set().union(*getattr(pl, "KEYS", {}).values()) for pl in plugins)) if plugins else set()
    clash = [f"pack.yaml: pane id {pid!r} is also a content key; rename the pane" for pid in pack.pane_ids
             if pid in CORE_KEYS["encounter"] | CORE_KEYS["point"] | owned]
    if missing or clash or pack.errors:
        return {}, pack.errors + missing + clash  # nothing else can be read reliably
    compiler = Compiler(pack, plugins, contexts)
    data = compiler.compile()
    return data, compiler.errors


def pack_schema(pack: Pack, plugins: list | None = None) -> dict:
    """This pack's schema: schema/core.json with the pack's parts filled in and closed (every field
    listed and required), so it passes lint_schema and a real 2020-12 validator."""
    core = json.loads(CORE_SCHEMA.read_text(encoding="utf-8"), parse_constant=_not_json)
    plugins = load_plugins(pack.manifest.get("checks") or []) if plugins is None else plugins
    schema = {"$schema": core["$schema"], "$id": f"{PAGES}/{pack.publish_path}/quest.schema.json",
              "title": f"{pack.title} data",
              "description": f"The data of {pack.title} (quest.json, version {SCHEMA_VERSION}), compiled by "
                             f"tools/quest/build.py from the {pack.id} pack. Generated from tools/quest/schema/core.json "
                             f"with this pack's strings, rule tags, panes and plugins filled in. Every field is "
                             f"required and nothing else is allowed, so a front end can rely on the shape."}
    schema.update({k: v for k, v in core.items() if k not in schema})
    defs = schema["$defs"]

    def close(node: dict, props: dict) -> None:
        node["properties"], node["required"] = props, list(props)

    close(defs["pack"]["properties"]["strings"], {k: {"type": "string"} for k in pack.strings})
    close(defs["pack"]["properties"]["rule_tags"], {k: {"$ref": "#/$defs/rule_tag"} for k in pack.rule_tags})
    close(schema["properties"]["meta"], {pl.NAME: pl.META for pl in plugins if getattr(pl, "META", None)})
    for level in ("realm", "encounter"):
        refs = {}
        for pl in plugins:
            refs.update(getattr(pl, "REFS", {}).get(level, {}))
        close(defs[level]["properties"]["refs"], refs)
    close(defs["point"]["properties"]["highlights"], {pid: {"$ref": "#/$defs/highlight"} for pid in pack.pane_ids})
    defs["point"]["properties"]["ruleTag"]["enum"] = ["", *pack.rule_tags]
    defs["pane"]["properties"]["id"] = {"enum": pack.pane_ids}
    return schema


# The JSON Schema keywords quest.schema.json may use. Pre-commit needs no extra package for this;
# CI also validates the published pair with the real jsonschema (see the README). lint_schema
# checks the schema first, whole, and accepts only a strict form of 2020-12 that _check enforces
# exactly; the README lists what it refuses.
_SCHEMA_NOTES = {"$schema", "$id", "title", "description", "$defs"}
_SCHEMA_RULES = {"type", "enum", "required", "properties", "additionalProperties", "items",
                 "minItems", "anyOf", "$ref"}
_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_DEF_NAME = re.compile(r"[A-Za-z0-9_]+")  # nothing JSON Pointer (~ /) or a URI (%) would decode
_JSON_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool,
               "null": type(None)}


def lint_schema(node, root: dict, where: str = "#") -> list[str]:
    """Problems with the schema itself: anything check_schema could not enforce exactly."""
    def bad(msg: str) -> list[str]:
        return [f"quest.schema.json {where}: {msg}"]
    if not isinstance(node, dict):
        return bad("every schema must be an object (boolean schemas are not supported)")
    unknown = set(node) - _SCHEMA_NOTES - _SCHEMA_RULES
    if unknown:
        return bad(f"uses {sorted(unknown)}, which check_schema does not support")
    errors: list[str] = []
    for k in ("title", "description"):  # the metaschema types these too
        if k in node and not isinstance(node[k], str):
            errors += bad(f"{k} must be a string")
    if node is root and node.get("$schema", _DIALECT) != _DIALECT:
        errors += bad(f"$schema must be {_DIALECT!r}, the dialect check_schema follows")
    if node is root and "$id" in node and not (isinstance(node["$id"], str) and re.fullmatch(r"[^#]*#?", node["$id"])):
        errors += bad("$id must be a URI without a fragment")
    if node is not root and {"$id", "$schema", "$defs"} & node.keys():
        # $ref always resolves against the root's $defs, so nothing below may start a new scope.
        errors += bad("$id, $schema and $defs are supported only at the root")
    t = node.get("type")
    if "type" in node and (not isinstance(t, str) or t not in _JSON_TYPES):
        errors += bad(f"type {t!r} is not supported (one of {sorted(_JSON_TYPES)})")
    if "additionalProperties" in node and node["additionalProperties"] is not False:
        errors += bad("only additionalProperties: false is supported")
    if t == "object" or {"properties", "required", "additionalProperties"} & node.keys():
        # A front end relies on the shape: every field present, nothing unlisted. _check applies
        # required and additionalProperties only beside properties, so none may appear alone.
        if t != "object" or "properties" not in node or node.get("additionalProperties") is not False:
            errors += bad("an object needs type: object, properties and additionalProperties: false")
        if not isinstance(node.get("properties", {}), dict) or not isinstance(node.get("required", []), list) \
                or not all(isinstance(k, str) for k in node.get("required", [])):
            return errors + bad("properties must be an object and required a list of names")
        if set(node.get("required", [])) != set(node.get("properties", {})):
            errors += bad("every property must be required")
        if len(set(node.get("required", []))) != len(node.get("required", [])):
            errors += bad("required lists a name twice")
    if "enum" in node and not isinstance(node["enum"], list):
        errors += bad("enum must be a list")
    if "minItems" in node and (not isinstance(node["minItems"], int) or isinstance(node["minItems"], bool)
                               or node["minItems"] < 0):
        errors += bad("minItems must be an integer, 0 or more")
    if "$ref" in node:
        ref, seen = node["$ref"], set()
        defs = root.get("$defs") if isinstance(root.get("$defs"), dict) else {}
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in defs:
            errors += bad(f"unknown $ref {ref!r}")
        else:
            # A chain of $refs that comes back to itself never reaches a rule (and never ends).
            while isinstance(ref, str) and ref.startswith("#/$defs/") and ref[8:] in defs and ref not in seen:
                seen.add(ref)
                ref = defs[ref[8:]].get("$ref") if isinstance(defs[ref[8:]], dict) else None
            if ref in seen:
                errors += bad(f"$ref {node['$ref']!r} refers back to itself")
    for k, sub in (node.get("properties") or {}).items():
        errors += lint_schema(sub, root, f"{where}/properties/{k}")
    if "items" in node:
        errors += lint_schema(node["items"], root, f"{where}/items")
    if "anyOf" in node and not (isinstance(node["anyOf"], list) and node["anyOf"]):
        return errors + bad("anyOf must be a non-empty list")
    for i, sub in enumerate(node.get("anyOf") or []):
        errors += lint_schema(sub, root, f"{where}/anyOf/{i}")
    if node is root:
        if not isinstance(node.get("$defs", {}), dict):
            return errors + bad("$defs must be an object")
        for k, sub in (node.get("$defs") or {}).items():
            if not _DEF_NAME.fullmatch(k):
                errors += bad(f"definition name {k!r}: use letters, digits and _ only")
            errors += lint_schema(sub, root, f"#/$defs/{k}")
            if _rechecks_itself(sub, node["$defs"], (f"#/$defs/{k}",)):
                errors += bad(f"#/$defs/{k} reaches itself through $ref/anyOf without reading any deeper")
    return errors


def _rechecks_itself(node, defs: dict, stack: tuple) -> bool:
    """True if checking `node` leads back to a definition on `stack` while still checking the same
    value: through $ref and anyOf only (properties and items always move to a smaller value)."""
    if not isinstance(node, dict):
        return False
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/") and ref[8:] in defs:
        if ref in stack or _rechecks_itself(defs[ref[8:]], defs, stack + (ref,)):
            return True
    return any(_rechecks_itself(b, defs, stack) for b in node.get("anyOf") or [] if isinstance(node.get("anyOf"), list))


def _same(a, b) -> bool:
    """JSON equality: true and false are not 1 and 0, as they are to Python's ==."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


def _is_type(value, name: str) -> bool:
    if isinstance(value, bool):
        return name == "boolean"
    if name == "integer":  # 2020-12: 1.0 is an integer
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, _JSON_TYPES[name])


def check_schema(value, schema: dict) -> list[str]:
    """Check `value` against quest.schema.json's subset of JSON Schema 2020-12."""
    problems = lint_schema(schema, schema)
    return problems or _check(value, schema, schema, "quest")


def _check(value, schema: dict, root: dict, where: str) -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:  # 2020-12: $ref applies alongside its siblings, it doesn't replace them
        errors += _check(value, root["$defs"][schema["$ref"][8:]], root, where)
    if "anyOf" in schema:
        branches = [_check(value, s, root, where) for s in schema["anyOf"]]
        if all(branches):
            errors.append(f"{where}: matches none of its allowed shapes ({'; or '.join(b[0] for b in branches)})")
    if "type" in schema and not _is_type(value, schema["type"]):
        return errors + [f"{where}: expected {schema['type']}, got {type(value).__name__}"]
    if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        errors += [f"{where}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        errors += [f"{where}: {k!r} is not in quest.schema.json" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errors += _check(v, props[k], root, f"{where}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, v in enumerate(value):
                errors += _check(v, schema["items"], root, f"{where}[{i}]")
    return errors


def font_faces(font_dir: pathlib.Path = FONT_DIR) -> str:
    """@font-face rules with each font inlined as a data: URI, so the page loads nothing."""
    rules = []
    for family, weight, name in FONTS:
        b64 = base64.b64encode((font_dir / name).read_bytes()).decode("ascii")
        rules.append(f'@font-face {{ font-family: "{family}"; font-style: normal; font-weight: {weight}; '
                     f'font-display: swap; src: url(data:font/woff2;base64,{b64}) format("woff2"); }}')
    return "\n".join(rules)


def _script_json(value) -> str:
    """JSON for a <script type="application/json">. Escaping every <, > and & keeps any string from
    closing the element or opening a "<!--<script" state in the HTML parser."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def _html_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render(template: str, data: dict, fonts_css: str = "", art: dict | None = None) -> str:
    """The classic page: the data, the pack's art (art/classic/), its title and description and
    the fonts written into classic/game.html."""
    for mark in (PLACEHOLDER, FONT_PLACEHOLDER, ART_PLACEHOLDER, TITLE_PLACEHOLDER, DESCRIPTION_PLACEHOLDER):
        if template.count(mark) != 1:
            raise ValueError(f"game.html must contain {mark} exactly once")
    pack = data.get("pack") or {}
    values = {PLACEHOLDER: _script_json(data), ART_PLACEHOLDER: _script_json(art or {}),
              TITLE_PLACEHOLDER: _html_text(pack.get("title", "")),
              DESCRIPTION_PLACEHOLDER: _html_text((pack.get("strings") or {}).get("page_description", "")),
              FONT_PLACEHOLDER: fonts_css}
    # One pass over the template, so a placeholder's name inside the pack's own text is never filled.
    return re.sub("|".join(re.escape(m) for m in values), lambda m: values[m.group(0)], template)


# What the classic page reads from a pack: the string keys in its S("…") / H("…") calls (including
# both sides of a ternary), the art in its art("…") calls, the map, and a scene per realm.
_STRING_CALL = re.compile(r"\b[SH]\(((?:[^()]|\([^()]*\))*?)[,)]")
_ART_CALL = re.compile(r'\bart\("([a-z0-9_]+)"')


def classic_needs(template: str) -> tuple[set[str], set[str]]:
    script = template.split("<script>", 1)[-1]
    strings = {k for arg in _STRING_CALL.findall(script) for k in re.findall(r'"([a-z0-9_]+)"', arg)}
    return strings | {"page_description"}, set(_ART_CALL.findall(script)) | {"map"}  # the head's description


def engine_strings(pack: Pack, plugins: list, data: dict) -> set[str]:
    """The strings the engine and plugins read: the claim buttons (when a hall asks a claim), pane
    labels and captions, and each plugin's STRINGS."""
    claims = any(t.get("kind") == "claim" for r in data.get("realms") or [] for h in r.get("halls") or []
                 for t in h.get("trials") or [])
    keys = {"claim_true", "claim_false"} if claims else set()
    for spec in pack.panes:
        if isinstance(spec, dict):
            keys |= {spec.get(k) for k in ("label", "name", "caption") if isinstance(spec.get(k), str) and spec.get(k)}
    for pl in plugins:
        keys |= set(getattr(pl, "STRINGS", ()))
    return keys


def classic_art(pack: Pack) -> tuple[dict, list[str]]:
    """The pack's art/classic/*.txt, by file name: each file's text less its final newline."""
    folder, art, errors = pack.dir / "art" / "classic", {}, []
    for path in sorted(folder.glob("*.txt")) if folder.is_dir() else []:
        if not ID.fullmatch(path.stem):
            errors.append(f"art/classic/{path.name}: name it with lowercase letters, digits and _")
        text = path.read_text(encoding="utf-8")
        art[path.stem] = text[:-1] if text.endswith("\n") else text
    return art, errors


def check_classic(pack: Pack, data: dict, art: dict, template: str, unused: bool = True) -> list[str]:
    """Everything the classic page reads must be in the pack, and the pack's art must all be used.
    `unused`: also refuse strings nothing reads (skipped when the compile already failed, since a
    broken trial can make a used string look unused)."""
    strings, pieces = classic_needs(template)
    scenes = {f"scene_{r['id']}" for r in data.get("realms") or [] if not r["halls"]}  # a realm of halls shows its crown
    errors = [f"strings.yaml: the classic page needs {k!r}" for k in sorted(strings - set(pack.strings))]
    used = strings | engine_strings(pack, load_plugins(pack.manifest.get("checks") or []), data)
    if unused:
        errors += [f"strings.yaml: {k!r} is not used by the page, the engine or a plugin" for k in sorted(set(pack.strings) - used)]
    errors += [f"art/classic/{k}.txt: the classic page needs it" for k in sorted(pieces - set(art))]
    for r in data.get("realms") or []:  # the page plays a realm's halls, or its one encounter
        if r["halls"] and r["encounters"] or len(r["encounters"]) > 1:
            errors.append(f"realm {r['id']}: the classic page plays either halls or one encounter per realm")
    for k in sorted(set(art) - pieces - scenes):
        errors.append(f"art/classic/{k}.txt: not used (the page reads {sorted(pieces)}, and scene_<realm id> "
                      f"for each realm without halls)")
    return errors


def _not_json(name: str):
    raise ValueError(f"quest.schema.json: {name} is not JSON (JSON.parse and strict parsers reject it)")


def build(pack_id: str = DEFAULT_PACK, check: bool = False) -> tuple[str | None, dict, dict, list[str]]:
    """Validate, and unless `check`, render. Returns (html or None, data, schema, errors)."""
    pack = Pack(pack_id)
    data, errors = compile_pack(pack)
    errors += check_packs_unique()
    try:
        errors += denylist.scan(pack.dir) + denylist.scan(TEMPLATE.parent)
    except (OSError, ValueError) as e:  # fails closed: no list, or a list that isn't hashes
        errors.append(f"denylist: {e}")
    schema: dict = {}
    try:
        schema = pack_schema(pack)
    except ValueError as e:  # includes JSONDecodeError
        errors.append(str(e) if str(e).startswith("quest.schema.json") else f"schema/core.json: not valid JSON ({e})")
    else:
        if data:  # a pack that failed before compiling has no data to check
            errors += check_schema(data, schema)
    art, art_errors = classic_art(pack)
    errors += art_errors
    if data:
        errors += check_classic(pack, data, art, TEMPLATE.read_text(encoding="utf-8"), unused=not errors)
    if errors:
        return None, data, schema, errors
    fonts = font_faces()  # read even under --check, so a missing font file fails pre-commit too
    html = None if check else render(TEMPLATE.read_text(encoding="utf-8"), data, fonts, art)
    return html, data, schema, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", default=DEFAULT_PACK, help=f"the pack to build (default: {DEFAULT_PACK})")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output HTML (default: tools/quest/dist/index.html); "
                         "quest.json and quest.schema.json are written beside it")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--root", help="accepted for parity with the other validators; paths resolve from this script")
    args = ap.parse_args(argv)

    if pathlib.Path(args.out).name.casefold() in BESIDE:  # case-insensitive filesystems
        print(f"quest: --out names the page; {pathlib.Path(args.out).name} is written beside it", file=sys.stderr)
        return 2
    if args.pack not in pack_ids():
        print(f"quest: no pack {args.pack!r} (packs: {', '.join(pack_ids())})", file=sys.stderr)
        return 2
    html, data, schema, errors = build(args.pack, check=args.check)
    name = f"quest {args.pack}"
    if errors:
        print(f"{name}: the pack does not build:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    open_realms = [r for r in data["realms"] if not r["sealed"]]
    encs = [e for r in data["realms"] for e in r["encounters"]]
    summary = (f"{len(open_realms)}/{len(data['realms'])} realms open, {len(encs)} encounters, "
               f"{sum(len(e['points']) for e in encs)} points, "
               f"{sum(len(h['trials']) for r in data['realms'] for h in r['halls'])} hall questions")
    if args.check:
        print(f"{name}: OK ({summary})")
        return 0
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    out.with_name("quest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_name("quest.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{name}: wrote {out}, quest.json and quest.schema.json ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
