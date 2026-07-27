"""Qlik app extraction — offline (.qvf) and engine-artifacts (dir) parsers.

Ported from the vendored q2t extract package (qvf_sqlite.py, qvf_offline.py,
engine_artifacts.py, __init__.py). Reads a source (a .qvf file or an artifacts
directory) and returns a normalized :class:`~ts_cli.qlik.ir.QlikApp` IR. The
only I/O here is *reading the source* — every downstream builder is pure and
never touches Qlik again (see ir.py).

A .qvf has no public spec. Two offline paths, tried in order:
  1. ``_extract_sqlite`` — a .qvf is sometimes a SQLite 3 db with a renamed
     extension holding the layout/script JSON. Clean, reliable when present.
  2. ``_extract_bytescan`` — best-effort printable-string scavenge. Records in
     ``app.notes`` everything it could not interpret so nothing is silently
     lost, and degrades gracefully (warnings, never a crash) on an opaque file.

``build_inventory`` turns a QlikApp into the flat JSON the ``ts qlik parse``
command emits.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
from typing import Any, Iterator, Optional

from .ir import (
    Chart, Column, Connection, MasterMeasure, QlikApp, Sheet, Table,
)
from .layout import _parse_layout

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def parse_app(source: str, *, mode: str = "offline") -> QlikApp:
    """Parse a Qlik app from ``source`` into the IR.

    mode="offline"          -> ``source`` is a .qvf file (SQLite path first,
                               then byte-scan fallback).
    mode="engine-artifacts" -> ``source`` is a directory of JSON artifacts from
                               the headless-engine extractor.
    """
    if mode == "engine-artifacts":
        from .engine import extract_engine_artifacts
        return extract_engine_artifacts(source)
    if mode != "offline":
        raise ValueError(f"unknown mode: {mode!r} (expected 'offline' or 'engine-artifacts')")
    app = _extract_sqlite(source)
    if app is not None:
        return app
    return _extract_bytescan(source)


def build_inventory(app: QlikApp) -> dict[str, Any]:
    """Flatten a QlikApp into the structured inventory JSON ``parse`` emits."""
    columns = _inventory_columns(app)
    charts = _inventory_charts(app)
    counts = {
        "connections": len(app.connections),
        "tables": len(app.tables),
        "columns": len(columns),
        "measures": len(app.measures),
        "dimensions": len(app.dimensions),
        "variables": len(app.variables),
        "sheets": len(app.sheets),
        "charts": len(charts),
    }
    return {
        "app_name": app.app_name,
        "extraction_mode": app.extraction_mode,
        "connections": [{"name": c.name, "qlik_type": c.qlik_type} for c in app.connections],
        "tables": _inventory_tables(app),
        "columns": columns,
        "measures": [{"id": m.id, "label": m.label, "expression": m.expression,
                      "number_format": m.number_format} for m in app.measures],
        "dimensions": [{"id": d.id, "label": d.label, "fields": d.fields,
                        "expression": d.expression} for d in app.dimensions],
        "variables": [{"name": v.name, "definition": v.definition} for v in app.variables],
        "sheets": [{"id": s.id, "title": s.title,
                    "charts": [c.id for c in s.charts]} for s in app.sheets],
        "charts": charts,
        "counts": counts,
        "warnings": _inventory_warnings(app),
    }


def _inventory_columns(app: QlikApp) -> list[dict]:
    return [
        {"table": t.name, "name": c.name, "data_type": c.data_type}
        for t in app.tables for c in t.columns
    ]


def _inventory_charts(app: QlikApp) -> list[dict]:
    return [
        {"sheet": s.title or s.id, "id": c.id, "title": c.title,
         "viz_type": c.viz_type, "dimensions": c.dimensions, "measures": c.measures}
        for s in app.sheets for c in s.charts
    ]


def _inventory_tables(app: QlikApp) -> list[dict]:
    return [{"name": t.name, "db_name": t.db_name, "schema_name": t.schema_name,
             "source_connection": t.source_connection,
             "columns": [c.name for c in t.columns]} for t in app.tables]


def _inventory_warnings(app: QlikApp) -> list[dict]:
    return [
        {"severity": n.severity, "area": n.area, "message": n.message}
        for n in app.notes if n.severity in ("warning", "manual")
    ]


# ---------------------------------------------------------------------------
# SQLite-backed .qvf
# ---------------------------------------------------------------------------

_SQLITE_MAGIC = b"SQLite format 3\x00"

_LAYOUT_QUERIES = [
    "SELECT value FROM Layout WHERE key='AppProperties'",
    "SELECT value FROM Layout LIMIT 1",
    "SELECT value FROM AppEntry WHERE key='Layout'",
    "SELECT data FROM Layout LIMIT 1",
]
_SCRIPT_QUERIES = [
    "SELECT value FROM Script LIMIT 1",
    "SELECT script FROM Script LIMIT 1",
    "SELECT value FROM Layout WHERE key='Script'",
]


def _looks_like_sqlite(qvf_path: str) -> bool:
    try:
        with open(qvf_path, "rb") as fh:
            return fh.read(16) == _SQLITE_MAGIC
    except OSError:
        return False


def _extract_sqlite(qvf_path: str) -> Optional[QlikApp]:
    """Return a populated QlikApp, or None if this isn't a usable SQLite .qvf."""
    if not _looks_like_sqlite(qvf_path):
        return None

    app = QlikApp(app_name=_stem(qvf_path), source_file=qvf_path, extraction_mode="sqlite")
    try:
        conn = sqlite3.connect(qvf_path)
    except sqlite3.Error as e:
        app.note("warning", "general", f"File has SQLite header but failed to open: {e}")
        return None
    try:
        tables = _list_tables(conn)
        app.note("info", "general", f"SQLite tables present: {', '.join(tables) or '(none)'}")

        layout = _first_json(conn, _LAYOUT_QUERIES)
        if layout is None:
            app.note("manual", "general",
                     "SQLite .qvf opened but no recognizable Layout JSON found; "
                     "falling back to offline byte-scan.")
            return None

        script = _first_text(conn, _SCRIPT_QUERIES)
        if script:
            app.load_script = script
            _parse_connections_from_script(script, app)
            _parse_tables_from_script(script, app)

        _parse_layout(layout, app)
        return app
    finally:
        conn.close()


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []


def _first_json(conn: sqlite3.Connection, queries: list[str]) -> Optional[dict]:
    for q in queries:
        try:
            row = conn.execute(q).fetchone()
        except sqlite3.Error:
            continue
        if row and row[0] is not None:
            obj = _decode_blob(row[0])
            if isinstance(obj, dict):
                return obj
    return None


def _first_text(conn: sqlite3.Connection, queries: list[str]) -> Optional[str]:
    for q in queries:
        try:
            row = conn.execute(q).fetchone()
        except sqlite3.Error:
            continue
        if row and row[0] is not None:
            val = row[0]
            if isinstance(val, bytes):
                if val[:2] == b"\x1f\x8b":
                    val = gzip.decompress(val)
                val = val.decode("utf-8", "ignore")
            return val
    return None


def _decode_blob(data: Any) -> Any:
    if isinstance(data, bytes):
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        data = data.decode("utf-8", "ignore")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return data


# ---------------------------------------------------------------------------
# Byte-scan (best-effort offline)
# ---------------------------------------------------------------------------

_MIN_STR = 4
_PRINTABLE = re.compile(rb"[\x09\x0a\x0d\x20-\x7e]{%d,}" % _MIN_STR)
_SCRIPT_MARKERS = ("LOAD ", "SQL SELECT", "SET ", "LET ", "lib://", "CONNECT")


def _extract_bytescan(qvf_path: str) -> QlikApp:
    app = QlikApp(app_name=_stem(qvf_path), source_file=qvf_path, extraction_mode="offline")
    try:
        with open(qvf_path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        app.note("manual", "general",
                 f"Could not read '{qvf_path}': {e}. Re-export via the Qlik engine "
                 "(--mode engine-artifacts) or supply the IR by hand.")
        return app

    app.note("warning", "general",
             "Offline extraction is best-effort. Charts and master items are often "
             "not fully recoverable without a Qlik engine; verify against the source app.")

    strings = list(_iter_strings(data))
    script = _recover_load_script(strings)
    if script:
        app.load_script = script
        _parse_connections_from_script(script, app)
        _parse_tables_from_script(script, app)
    else:
        app.note("manual", "script",
                 "Could not locate a load script in the .qvf. Re-export via the Qlik "
                 "engine, or paste the script manually into the IR.")

    _recover_embedded_json(data, app)

    if not app.sheets:
        app.note("manual", "chart",
                 "No sheet/chart layout recovered offline. Charts must be rebuilt "
                 "manually or extracted via --mode engine-artifacts.")
    return app


def _iter_strings(data: bytes) -> Iterator[str]:
    for m in _PRINTABLE.finditer(data):
        yield m.group().decode("ascii", "ignore")
    try:
        text16 = data.decode("utf-16-le", "ignore")
        for run in re.findall(r"[\x09\x0a\x0d\x20-\x7e]{%d,}" % _MIN_STR, text16):
            yield run
    except Exception:
        pass


def _recover_load_script(strings: list[str]) -> Optional[str]:
    candidates = [s for s in strings if any(mk in s for mk in _SCRIPT_MARKERS)]
    if not candidates:
        return None
    best = max(candidates, key=len)
    return best if len(best) > 20 else None


def _recover_embedded_json(data: bytes, app: QlikApp) -> None:
    text = data.decode("utf-8", "ignore")
    found = 0
    for obj in _iter_json_objects(text):
        qtype = (obj.get("qInfo", {}) or {}).get("qType") or obj.get("qType")
        if qtype == "sheet" or obj.get("cells") is not None:
            app.sheets.append(_sheet_from_json(obj))
            found += 1
        elif qtype == "measure":
            qm = obj.get("qMeasure", {})
            app.measures.append(MasterMeasure(
                id=(obj.get("qInfo", {}) or {}).get("qId", "m"),
                label=qm.get("qLabel") or qm.get("title", ""),
                expression=qm.get("qDef", ""),
            ))
            found += 1
    if found:
        app.note("info", "general", f"Recovered {found} embedded JSON object(s) offline.")


def _iter_json_objects(text: str) -> Iterator[dict]:
    for anchor in re.finditer(r'\{[^{}]*"qInfo"', text):
        start = anchor.start()
        depth, i = 0, start
        in_str, esc = False, False
        while i < len(text) and i < start + 100_000:
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            yield json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            pass
                        break
            i += 1


def _sheet_from_json(obj: dict) -> Sheet:
    info = obj.get("qInfo", {}) or {}
    meta = obj.get("qMeta", {}) or obj.get("meta", {}) or {}
    sheet = Sheet(id=info.get("qId", "sheet"), title=meta.get("title", "Sheet"))
    for cell in obj.get("cells", []) or []:
        sheet.charts.append(Chart(
            id=cell.get("name", "obj"),
            viz_type=cell.get("type", "UNKNOWN"),
            raw=cell,
        ))
    return sheet


# ---------------------------------------------------------------------------
# Shared load-script parsers (used by both offline paths and engine-artifacts)
# ---------------------------------------------------------------------------


def _parse_connections_from_script(script: str, app: QlikApp) -> None:
    seen: set[str] = set()
    for name in re.findall(r"lib://([^/\"'\];]+)", script):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            app.connections.append(Connection(name=name, qlik_type=_guess_type(script)))
    for m in re.finditer(r"CONNECT\s+TO\s+\[?([^\];\n]+)", script, re.IGNORECASE):
        name = m.group(1).strip().strip("'\"")
        if name and name not in seen:
            seen.add(name)
            app.connections.append(Connection(name=name, qlik_type=_guess_type(script)))


def _guess_type(script: str) -> str:
    low = script.lower()
    for key in ("snowflake", "bigquery", "redshift", "postgres", "sqlserver",
                "sql server", "databricks", "oracle", "mysql", "teradata"):
        if key in low:
            return key
    return "UNKNOWN"


def _parse_tables_from_script(script: str, app: QlikApp) -> None:
    for m in re.finditer(r"(?:^|\n)\s*([A-Za-z_][\w ]*?):\s*\n?\s*(LOAD|SQL\s+SELECT)",
                         script, re.IGNORECASE):
        tname = m.group(1).strip()
        start = m.end()
        stmt = script[start:start + 2000]
        end = stmt.find(";")
        if end != -1:
            stmt = stmt[:end]
        cols = _parse_field_list(stmt)
        if cols:
            app.tables.append(Table(name=tname, columns=[Column(name=c) for c in cols]))


def _parse_field_list(stmt: str) -> list[str]:
    head = re.split(r"\bFROM\b|\bRESIDENT\b", stmt, maxsplit=1, flags=re.IGNORECASE)[0]
    fields: list[str] = []
    for part in head.split(","):
        part = part.strip()
        m = re.search(r"\bas\s+\[?([^\],]+)\]?\s*$", part, re.IGNORECASE)
        if m:
            fields.append(m.group(1).strip())
        else:
            m2 = re.match(r"^\[?([A-Za-z_][\w ]*)\]?$", part)
            if m2:
                fields.append(m2.group(1).strip())
    return [f for f in fields if f and f.upper() not in ("LOAD", "SELECT")]


# ---------------------------------------------------------------------------
# small accessors
# ---------------------------------------------------------------------------


def _stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
