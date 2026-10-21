"""Plugin: AgentQL Quest's game rules.

- `who` points: "who put this line here?", answered model / thoughtspot (both the Forge option)
  or agentql (the scroll). The third option, the Wizard (the AI), is never right: the AI never
  writes the SQL that runs.
- `route` trials: send a petition to one of the engines (Keyword Search, AgentQL, Code Complete).
- The path choice: the foe is the AgentQL path, so AgentQL is always the answer; every other
  engine explains why it doesn't fit, or is blocked in that realm (choosing it costs nothing).
- The first realm, where every player starts, teaches in halls.
- Crediting: null guards and the row cap are ThoughtSpot's (cluster settings), never the Model's.
  A `who` point whose highlighted SQL lines all lie wholly within a `LIMIT <n>` line or a full
  null guard (`CASE WHEN <aggregate> IS NOT NULL THEN <aggregate> ELSE 0 END`) must answer
  thoughtspot.

See build.py's "Plugins" section for the hooks.
"""
from __future__ import annotations

import re

NAME = "agentql_rules"
SQL_PANE = "sql"
WHO_ANSWERS = {"model": "forge", "thoughtspot": "forge", "agentql": "agentql"}
WHO_ORDER = ("forge", "agentql", "ai")
KEYS = {"top": {"who_options", "engines"}, "point": {"answer"}, "trial": {"petition", "answer"},
        "path": {"answer", "blocked", "why"}}
POINT_KINDS = {"who"}
TRIAL_KINDS = {"route"}
COMPILES_PATH = True

_LIMIT = re.compile(r"\s*LIMIT\s+\d+\s*", re.I)
_GUARD = re.compile(r"CASE\s+WHEN\s+((?:sum|count|avg|min|max)\s*\((?:[^()]|\([^()]*\))*\))\s+IS\s+NOT\s+NULL"
                    r"\s+THEN\s+\1\s+ELSE\s+0\s+END", re.I)


class Rules:
    def __init__(self, pack):
        self.who = pack.doc.get("who_options") or {}
        self.engines = pack.doc.get("engines") or {}
        self.send_to = pack.strings.get("send_to", "")


def load(pack, errors: list[str]) -> Rules:
    rules = Rules(pack)
    missing = [k for k in WHO_ORDER if not rules.who.get(k)]
    if missing:
        errors.append(f"who_options: missing {missing}")
    if len(rules.engines) < 2:
        errors.append("engines: need at least two engines for petitions")
    if "{engine}" not in rules.send_to:
        errors.append("strings.yaml: send_to must name {engine}")
    return rules


def _send_to(rules: Rules) -> list[str]:
    return [rules.send_to.replace("{engine}", name) for name in rules.engines.values()]


def path(rules: Rules, p: dict, where: str, errors: list[str]) -> dict:
    """Every other engine either explains why it doesn't fit (`why`) or is closed in this realm
    (`blocked`), which costs nothing: the player simply chooses again."""
    order = list(rules.engines)
    answer, blocked, why = p.get("answer"), p.get("blocked") or {}, p.get("why") or {}
    if answer != "agentql":
        errors.append(f"{where}: the foe is the AgentQL path, so path.answer must be 'agentql', got {answer!r}")
    if answer in blocked:
        errors.append(f"{where}: the right path can't be blocked")
    outcomes = []
    for k in order:
        text = blocked.get(k) if k in blocked else why.get(k)
        if not text:
            errors.append(f"{where}: path needs a why (or blocked) text for {k}")
        outcomes.append({"kind": "blocked" if k in blocked else "win" if k == answer else "loss", "why": text or ""})
    for k in list(blocked) + list(why):
        if k not in rules.engines:
            errors.append(f"{where}: unknown engine {k!r} in path")
    return {"options": _send_to(rules), "outcomes": outcomes,
            "correct": order.index(answer) if answer in order else 0}


def trial(rules: Rules, t: dict, where: str, errors: list[str]) -> dict:
    """A petition, answered by the engine it should go to; compiled to a general choice."""
    order = list(rules.engines)
    if t.get("answer") not in rules.engines:
        errors.append(f"{where}: answer must be one of {order}, got {t.get('answer')!r}")
    if not t.get("petition") or not t.get("why"):
        errors.append(f"{where}: a route needs petition and why")
    return {"kind": "choice", "text": t.get("petition", ""), "why": t.get("why", ""),
            "options": _send_to(rules), "correct": order.index(t["answer"]) if t.get("answer") in rules.engines else 0}


def _credit_lines(sql: list[str]) -> set[int]:
    """Lines that lie wholly within a LIMIT <n> line or a full null guard."""
    inside = {i for i, line in enumerate(sql) if _LIMIT.fullmatch(line)}
    text, starts, at = "\n".join(sql), [], 0
    for line in sql:
        starts.append(at)
        at += len(line) + 1
    for m in _GUARD.finditer(text):
        for i, line in enumerate(sql):
            if not line.strip():
                continue
            begin = starts[i] + len(line) - len(line.lstrip())
            end = starts[i] + len(line.rstrip())
            if m.start() <= begin and end <= m.end():
                inside.add(i)
    return inside


def point(rules: Rules, p: dict, panes: dict[str, list[str]], highlights: dict, where: str,
          errors: list[str]) -> dict:
    """A `who` point: the three who-options, the answer's option, and its rule tag."""
    if not p.get("sql"):
        errors.append(f"{where}: a who point must highlight the SQL it asks about")
    if not p.get("rule"):
        errors.append(f"{where}: a who point needs a rule (the hoard lists it)")
    if "rule_tag" in p:  # otherwise a null guard answered thoughtspot could still be tagged MODEL
        errors.append(f"{where}: a who point takes its rule tag from its answer; drop rule_tag")
    answer = p.get("answer")
    target = WHO_ANSWERS.get(answer)
    if target is None:
        errors.append(f"{where}: answer must be one of {sorted(WHO_ANSWERS)}, got {answer!r}")
        target = "forge"
    lit = highlights.get(SQL_PANE)
    if isinstance(lit, list) and lit and set(lit) <= _credit_lines(panes.get(SQL_PANE) or []) and answer != "thoughtspot":
        errors.append(f"{where}: it asks about a row cap or a null guard, which ThoughtSpot adds "
                      f"(a cluster setting, not the Model), so the answer must be thoughtspot, not {answer!r}")
    return {"options": [rules.who.get(k, "") for k in WHO_ORDER], "correct": WHO_ORDER.index(target),
            "rule_tag": answer or ""}


def finish(rules: Rules, pack, data: dict, errors: list[str]) -> None:
    realms = data.get("realms") or []
    if realms and not realms[0]["halls"]:
        errors.append("realms: the first realm is where every player starts; it must teach in halls")
    # The classic page introduces every non-claim trial as a petition about engines.
    for r in pack.doc.get("realms") or []:
        for h in r.get("halls") or []:
            for t in h.get("trials") or []:
                if t.get("kind") not in ("claim", "route"):
                    errors.append(f"realm {r.get('id')} hall {h.get('id')}: AgentQL Quest's halls ask claims and "
                                  f"routes only, got {t.get('kind')!r}")
