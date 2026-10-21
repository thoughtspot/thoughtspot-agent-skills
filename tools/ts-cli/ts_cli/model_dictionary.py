"""A Model's data dictionary: one row per column, behind `ts model dictionary`.

Rows are built from a Model TML plus the Table TMLs it sits on. The Model gives each
column's name, role, aggregation, description, synonyms, AI context and indexing; the
Table gives what the Model does not carry — the warehouse column name and its data
type. The type has to come from the Table: a Model column has no data type, and
reading one off the Model yields "" for every column (the same trap `AuditContext.
column_types` documents for audit 14.1).

Where each field lives was counted, not assumed, across 599 exported Models on the
SE demo cluster (2026-10-21): `description` at the column root; `synonyms` and
`ai_context` under `properties:`. Each is still read from the other place as a
fallback, so hand-written TML works too.

Pure functions; the CSV and XLSX writers take an output path, and openpyxl is
imported lazily — it is the optional `[xlsx]` extra, not a base dependency.
"""
from __future__ import annotations

import csv
import io
import re

FIELDS = [
    "Model", "Column", "Column type", "Aggregation", "Data type", "Source table",
    "Source column", "Formula", "Description", "Synonyms", "AI context",
    "Indexed", "Hidden",
]

# Excel's own limits on a worksheet title: 31 characters, none of []:*?/\
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def _prop(col: dict, key: str, root_first: bool = False):
    props = col.get("properties") if isinstance(col.get("properties"), dict) else {}
    a, b = (col.get(key), props.get(key)) if root_first else (props.get(key), col.get(key))
    return a if a not in (None, "", []) else b


def _source_columns(body: dict) -> dict:
    """{column name (lower): (source column, data_type)} for one `table:` or `sql_view:`
    body. A Table column is typed by `db_column_properties.data_type`; a SQL View column
    (`sql_view_columns[]`, sourced by `sql_output_column`) carries no data type in TML,
    so its type is left blank, not guessed."""
    cols: dict = {}
    for c in body.get("columns") or []:
        if isinstance(c, dict) and c.get("name"):
            dtype = ((c.get("db_column_properties") or {}).get("data_type")) or ""
            cols[str(c["name"]).lower()] = (c.get("db_column_name") or c["name"], dtype)
    for c in body.get("sql_view_columns") or []:
        if isinstance(c, dict) and c.get("name"):
            cols[str(c["name"]).lower()] = (c.get("sql_output_column") or c["name"], "")
    return cols


def _table_index(tables: dict) -> dict:
    """physical table name (lower) -> its `_source_columns`."""
    return {str(name).lower(): _source_columns(body or {})
            for name, body in (tables or {}).items()}


def _node_tables(model: dict) -> dict:
    """model_tables node id (alias, else id, else name; lower) -> physical table name."""
    out = {}
    for t in model.get("model_tables") or []:
        if isinstance(t, dict) and t.get("name"):
            node = t.get("alias") or t.get("id") or t["name"]
            out[str(node).lower()] = str(t["name"])
    return out


def _source(col: dict, nodes: dict, tidx: dict, formulas: dict) -> tuple:
    """(source table, source column, data type, formula) for one Model column."""
    cid = col.get("column_id") or ""
    if "::" in cid:
        node, colname = cid.split("::", 1)
        table = nodes.get(node.lower(), node)
        source_col, dtype = tidx.get(table.lower(), {}).get(colname.lower(), (colname, ""))
        return table, source_col, dtype, ""
    if col.get("formula_id"):
        return "", "", "", (formulas.get(col["formula_id"]) or {}).get("expr", "")
    return "", "", "", ""


def _row(model_name: str, col: dict, source: tuple) -> dict:
    table, source_col, dtype, formula = source
    props = col.get("properties") if isinstance(col.get("properties"), dict) else {}
    synonyms = _prop(col, "synonyms") or []
    if isinstance(synonyms, str):
        synonyms = [synonyms]
    return {
        "Model": model_name,
        "Column": col.get("name", ""),
        "Column type": props.get("column_type", ""),
        "Aggregation": props.get("aggregation", ""),
        "Data type": dtype,
        "Source table": table,
        "Source column": source_col,
        "Formula": formula,
        "Description": str(_prop(col, "description", root_first=True) or "").strip(),
        "Synonyms": "; ".join(str(s) for s in synonyms),
        "AI context": str(_prop(col, "ai_context") or "").strip(),
        "Indexed": "no" if str(props.get("index_type", "")).upper() == "DONT_INDEX" else "yes",
        "Hidden": "yes" if props.get("is_hidden") else "no",
    }


def build_rows(model_tml: dict, tables: dict = None) -> list[dict]:
    """Dictionary rows for one parsed Model TML (`{"model": {...}}`).

    `tables` maps a physical table name to its parsed `table:` (or `sql_view:`) body;
    a Model whose Tables are absent still yields every row, with the type left blank.
    """
    model = (model_tml or {}).get("model") or {}
    formulas = {f.get("id"): f for f in model.get("formulas") or [] if isinstance(f, dict)}
    nodes, tidx = _node_tables(model), _table_index(tables or {})
    return [_row(model.get("name", ""), c, _source(c, nodes, tidx, formulas))
            for c in model.get("columns") or [] if isinstance(c, dict)]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def sheet_titles(model_names: list[str]) -> list[str]:
    """One valid, unique worksheet title per Model name, in order. Excel rejects a title
    over 31 characters or containing []:*?/\\ — the source script this command replaces
    crashed on the first such Model name — and titles are unique case-insensitively."""
    used: set = set()
    out = []
    for name in model_names:
        base = _SHEET_BAD.sub("_", str(name or "Model")).strip("'") or "Model"
        title, n = base[:31], 2
        while title.lower() in used:
            suffix = f" ({n})"
            title, n = base[:31 - len(suffix)] + suffix, n + 1
        used.add(title.lower())
        out.append(title)
    return out


def write_xlsx(rows_by_model: list[tuple[str, list[dict]]], path: str) -> None:
    """One worksheet per Model: bold frozen header, wrapped long-text columns, filters."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # optional extra
        raise RuntimeError(
            "--format xlsx needs openpyxl: pip install 'thoughtspot-cli[xlsx]'"
        ) from exc
    widths = {"Column": 40, "Description": 60, "Formula": 50, "AI context": 50,
              "Synonyms": 30, "Source table": 30, "Source column": 30}
    wrap = {"Description", "Formula", "AI context", "Synonyms"}
    fields = [f for f in FIELDS if f != "Model"]
    wb = Workbook()
    wb.remove(wb.active)
    titles = sheet_titles([name for name, _ in rows_by_model])
    for title, (_, rows) in zip(titles, rows_by_model):
        ws = wb.create_sheet(title)
        ws.append(fields)
        for r in rows:
            ws.append([r.get(f, "") for f in fields])
        for i, f in enumerate(fields, 1):
            letter = get_column_letter(i)
            ws.column_dimensions[letter].width = widths.get(f, 14)
            ws.cell(row=1, column=i).font = Font(bold=True)
            if f in wrap:
                for cell in ws[letter][1:]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)
