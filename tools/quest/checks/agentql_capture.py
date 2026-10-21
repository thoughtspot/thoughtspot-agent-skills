"""Plugin: pin AgentQL Quest to the captured lesson SQL (references/lesson-sql.md).

The capture is the only source of SQL; the game never carries a hand-written copy. For each
encounter's `case` this fills the `sql` pane with the warehouse SQL ThoughtSpot generated, checks
the `scroll` pane (the AgentQL, laid out for reading) against the captured AgentQL, and checks the
facts a point states about the whole statement. A recapture that changes what a lesson teaches
therefore fails the build instead of quietly teaching something false.

See build.py's "Plugins" section for the hooks.
"""
from __future__ import annotations

import re

NAME = "agentql_capture"
SOURCES = {"lesson_sql"}
AGENTQL_PANE, SQL_PANE = "scroll", "sql"
KEYS = {"encounter": {"case"}, "point": {"sql_count", "sql_last_line", "sql_before", "rejected_case"}}
REFS = {"encounter": {"case": {"description": "The lesson-sql.md case id.", "type": "string"}}}
META = {
    "description": "The capture the SQL comes from.",
    "type": "object", "additionalProperties": False, "required": ["model", "captured"],
    "properties": {
        "model": {"description": "The ThoughtSpot Model the lesson SQL was captured on.", "type": "string"},
        "captured": {"description": "The date the lesson SQL was captured (YYYY-MM-DD).", "type": "string"},
    },
}

_STRING = re.compile(r"""('(?:[^']|'')*'|"(?:[^"]|"")*")""")    # string literals and quoted names


def parse_lesson_sql(text: str) -> tuple[str | None, dict[str, dict]]:
    """Read the capture date and, per case id, its AgentQL and generated SQL (None if rejected).

    The layout is fixed by tools/agentql-retest/build_lesson_sql.py: a `## <case id>` heading,
    an AgentQL ```sql block, then a second ```sql block only when the status was SUCCESS.
    """
    m = re.search(r"captured live on .*? on\s+(\d{4}-\d{2}-\d{2})", text, re.S)
    date = m.group(1) if m else None
    cases: dict[str, dict] = {}
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        cid = block.split("\n", 1)[0].strip()
        blocks = re.findall(r"```sql\n(.*?)\n```", block, re.S)
        ok = "`status: SUCCESS`" in block and len(blocks) > 1
        cases[cid] = {"agentql": blocks[0] if blocks else "", "sql": blocks[1] if ok else None}
    return date, cases


def parse_capture_model(text: str) -> str | None:
    """The Model the capture was taken on, from the header's "captured live on the sample Model **`…`**"."""
    m = re.search(r"captured\s+live\s+on\s+the\s+sample\s+Model\s+\*\*`([^`]+)`\*\*", text)
    return m.group(1).strip() if m else None


def norm(sql: str) -> str:
    """Normalise layout only: line breaks and indentation may differ, nothing else.

    Outside string literals, runs of whitespace collapse to one space, and whitespace is
    dropped just inside brackets and before commas — the places a reader adds line breaks.
    `(Sample) Retail` and `(Sample)Retail`, or `a, b` and `a,b`, stay different. String
    literals and double-quoted names are kept byte for byte.
    """
    parts = _STRING.split(sql)
    for i in range(0, len(parts), 2):
        s = re.sub(r"\s+", " ", parts[i])  # not " ".join(split()): that trims the edges next to a literal
        s = re.sub(r"\(\s+", "(", s)
        s = re.sub(r"\s+([),])", r"\1", s)
        parts[i] = s
    return "".join(parts).strip()


class Capture:
    def __init__(self, date: str | None, cases: dict[str, dict], model: str | None):
        self.date, self.cases, self.model = date, cases, (model or "").strip()


def load(pack, errors: list[str]) -> Capture:
    text = pack.source("lesson_sql").read_text(encoding="utf-8")
    return Capture(*parse_lesson_sql(text), parse_capture_model(text))


def meta(cap: Capture) -> dict:
    return {"model": cap.model, "captured": cap.date or ""}


def finish(cap: Capture, pack, data: dict, errors: list[str]) -> None:
    if not cap.model:
        errors.append("lesson-sql.md: no Model named in its header")
    if not cap.date:
        errors.append("lesson-sql.md: no capture date found in its header")


def encounter(cap: Capture, e: dict, panes: dict[str, list[str]], where: str, errors: list[str]) -> dict:
    cid = e.get("case")
    found = cap.cases.get(cid)
    if found is None:
        errors.append(f"{where}: case {cid!r} is not in lesson-sql.md")
        return {"case": cid or ""}
    if found["sql"] is None:
        errors.append(f"{where}: case {cid}: captured status was not SUCCESS, so there is no SQL to fight")
        return {"case": cid}
    if norm("\n".join(panes.get(AGENTQL_PANE) or [])) != norm(found["agentql"]):
        errors.append(f"{where}: the {AGENTQL_PANE} pane differs from the captured AgentQL for {cid} (only layout may differ)")
    panes[SQL_PANE] = found["sql"].splitlines()
    # The dragon's caption names the header's Model: it must be the one this AgentQL queries.
    if cap.model and not re.search(rf'\bFROM\s+"{re.escape(cap.model)}"', found["agentql"], re.I):
        errors.append(f"{where}: the capture header names Model {cap.model!r}, "
                      f"but this AgentQL does not query FROM \"{cap.model}\"")
    return {"case": cid}


def check_point(cap: Capture, p: dict, panes: dict[str, list[str]], where: str, errors: list[str]) -> None:
    """Facts about the whole statement that a single highlighted line can't pin down, e.g. the
    fact table appears once (pruning held) or only one join is outer."""
    sql = panes.get(SQL_PANE) or []
    whole = "\n".join(sql)
    for needle, want in (p.get("sql_count") or {}).items():
        got = whole.count(needle)
        if got != want:
            errors.append(f"{where}: expected {needle!r} {want} time(s) in the SQL, found {got}")
    stripped = [line.strip() for line in sql if line.strip()]
    last = p.get("sql_last_line")
    if last and (not stripped or stripped[-1] != last.strip()):
        errors.append(f"{where}: expected the statement to end with {last!r}, it ends with {stripped[-1] if stripped else None!r}")
    for before, after in p.get("sql_before") or []:
        ia = next((i for i, line in enumerate(stripped) if line == before.strip()), None)
        ib = next((i for i, line in enumerate(stripped) if line == after.strip()), None)
        if ia is None or ib is None or ia >= ib:
            errors.append(f"{where}: expected {before!r} before {after!r} in the SQL")
    # "Could the AI write X?" — only true while the capture still shows X being rejected.
    rejected = p.get("rejected_case")
    if rejected:
        found = cap.cases.get(rejected)
        if found is None:
            errors.append(f"{where}: rejected_case {rejected!r} is not in lesson-sql.md")
        elif found["sql"] is not None:
            errors.append(f"{where}: rejected_case {rejected!r} now compiles (SUCCESS), so the answer is wrong")
