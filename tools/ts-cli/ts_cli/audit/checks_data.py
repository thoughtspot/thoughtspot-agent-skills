from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "data_modeling"
_SQL_PASSTHROUGH = re.compile(r"sql_(int|string|bool)_aggregate_op", re.IGNORECASE)


def _join_depth(model_tables):
    graph = {}
    for t in model_tables:
        tn = t.get("name", "")
        for j in (t.get("joins") or []):
            graph.setdefault(tn, []).append(j.get("with", ""))
    if not graph:
        return 0
    max_d = 0
    for start in graph:
        visited = set()
        stack = [(start, 0)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            max_d = max(max_d, depth)
            for nb in graph.get(node, []):
                stack.append((nb, depth + 1))
    return max_d


def _table_role(columns, table_name):
    table_cols = [c for c in columns
                  if (c.get("column_id") or "").split("::")[0] == table_name]
    if not table_cols:
        return "unknown"
    measures = sum(1 for c in table_cols
                   if (c.get("properties") or {}).get("column_type") == "MEASURE")
    return "fact" if measures > 3 else "dimension"


def check_d1(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        name = m.get("name", "")
        guid = ctx.guid_for(model)
        mt = m.get("model_tables") or []
        cols = m.get("columns") or []
        formulas = m.get("formulas") or []
        joins_count = sum(len(t.get("joins") or []) for t in mt)
        max_depth = _join_depth(mt)
        for label, val, green, yellow in [
            ("tables", len(mt), 10, 15),
            ("columns", len(cols), 50, 75),
            ("joins", joins_count, 8, 12),
            ("join depth", max_depth, 3, 5),
            ("formulas", len(formulas), 30, 50),
        ]:
            if val <= green:
                continue
            severity = "HIGH" if val > yellow else "MEDIUM"
            findings.append(Finding(
                check_id="D1", angle=_ANGLE, severity=severity,
                object_type="model", object_name=name, object_guid=guid,
                detail=f"{val} {label} (>{yellow} HIGH, >{green} MEDIUM)",
                metric=val, threshold={"green": green, "yellow": yellow},
            ))
    return findings


def check_d2(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = ctx.guid_for(model)
        col_types = {}
        for c in (m.get("columns") or []):
            cid = c.get("column_id", "")
            dt = (c.get("db_column_properties") or {}).get("data_type", "")
            col_types[cid] = dt
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                on_str = j.get("on", "")
                parts = [p.strip() for p in on_str.replace("=", ",").split(",") if p.strip()]
                varchar_keys = [p for p in parts if col_types.get(p, "").upper() in ("VARCHAR", "CHAR", "STRING", "TEXT")]
                if varchar_keys:
                    findings.append(Finding(
                        check_id="D2", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"VARCHAR join key(s): {', '.join(varchar_keys)}",
                        metric=len(varchar_keys),
                    ))
                if len(parts) > 2:
                    findings.append(Finding(
                        check_id="D2", angle=_ANGLE, severity="MEDIUM",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"Multi-column join ({len(parts)//2} keys)",
                        metric=len(parts) // 2,
                    ))
    return findings


def check_d3(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = ctx.guid_for(model)
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                jtype = (j.get("type") or "").upper()
                if jtype == "OUTER":
                    findings.append(Finding(
                        check_id="D3", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail="FULL OUTER join causes performance issues",
                    ))
                elif jtype in ("LEFT_OUTER", "RIGHT_OUTER"):
                    findings.append(Finding(
                        check_id="D3", angle=_ANGLE, severity="INFO",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"{jtype} join — may indicate data discrepancies",
                    ))
    return findings


def check_d4(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        props = m.get("properties") or {}
        if len(mt) > 5 and not props.get("join_progressive", False):
            findings.append(Finding(
                check_id="D4", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"join_progressive is false on model with {len(mt)} tables (>5)",
                metric=len(mt), threshold={"min_tables_for_flag": 5},
            ))
    return findings


def check_d5(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        if len(mt) <= 1:
            continue
        joined = set()
        for t in mt:
            for j in (t.get("joins") or []):
                joined.add(t.get("name", ""))
                joined.add(j.get("with", ""))
        for t in mt:
            tname = t.get("name", "")
            if tname not in joined:
                findings.append(Finding(
                    check_id="D5", angle=_ANGLE, severity="HIGH",
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Table '{tname}' has no joins — Cartesian product risk",
                ))
    return findings


def check_d6(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        for mt in (m.get("model_tables") or []):
            tname = mt.get("name", "")
            table_cols = [c for c in cols
                          if (c.get("column_id") or "").split("::")[0] == tname]
            if not table_cols:
                continue
            attrs = sum(1 for c in table_cols
                        if (c.get("properties") or {}).get("column_type") == "ATTRIBUTE")
            role = _table_role(cols, tname)
            if role == "fact" and len(table_cols) > 0 and (attrs / len(table_cols)) > 0.4:
                findings.append(Finding(
                    check_id="D6", angle=_ANGLE, severity="LOW",
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Fact table '{tname}' has {attrs}/{len(table_cols)} ATTRIBUTE columns (>40%)",
                    metric=round(attrs / len(table_cols) * 100, 1),
                    threshold={"max_attribute_pct": 40},
                ))
    return findings


def check_d7(ctx: AuditContext) -> list:
    findings = []
    if len(ctx.models) < 2:
        return findings
    for m1, m2 in combinations(ctx.models, 2):
        s1 = {t.get("fqn", t.get("name", "")) for t in (m1.get("model", {}).get("model_tables") or [])}
        s2 = {t.get("fqn", t.get("name", "")) for t in (m2.get("model", {}).get("model_tables") or [])}
        if not s1 or not s2:
            continue
        inter = s1 & s2
        union = s1 | s2
        if not inter:
            continue
        jaccard = len(inter) / len(union)
        n1 = m1.get("model", {}).get("name", "")
        n2 = m2.get("model", {}).get("name", "")
        if s1 == s2:
            findings.append(Finding(
                check_id="D7", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=f"{n1} / {n2}",
                object_guid=ctx.guid_for(m1),
                detail=f"Identical table sets ({len(s1)} tables) — likely duplicate models",
                metric=round(jaccard, 2),
            ))
        elif jaccard > 0.5:
            findings.append(Finding(
                check_id="D7", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=f"{n1} / {n2}",
                object_guid=ctx.guid_for(m1),
                detail=f"High overlap: {len(inter)}/{len(union)} tables shared (Jaccard {jaccard:.2f})",
                metric=round(jaccard, 2), threshold={"high_overlap": 0.5},
            ))
    return findings


def check_d8(ctx: AuditContext) -> list:
    findings = []
    table_keys = defaultdict(list)
    for entry in ctx.metadata:
        header = entry.get("metadata_header") or entry
        sub = header.get("type", "")
        if sub in ("ONE_TO_ONE_LOGICAL", "SQL_VIEW"):
            ds = header.get("dataSourceName", "")
            db = header.get("databaseStripe", "")
            schema = header.get("schemaStripe", "")
            tbl = header.get("name", "")
            key = (ds, db, schema, tbl)
            table_keys[key].append(header.get("id", ""))
    for key, guids in table_keys.items():
        if len(guids) > 1:
            findings.append(Finding(
                check_id="D8", angle=_ANGLE, severity="HIGH",
                object_type="table", object_name=f"{key[0]}.{key[1]}.{key[2]}.{key[3]}",
                object_guid=guids[0],
                detail=f"{len(guids)} ThoughtSpot objects point to the same physical table",
                metric=len(guids),
            ))
    return findings


def check_d9(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        if not formulas:
            continue
        sql_count = sum(1 for f in formulas if _SQL_PASSTHROUGH.search(f.get("expr", "")))
        ratio = sql_count / len(formulas) * 100
        if ratio > 20:
            findings.append(Finding(
                check_id="D9", angle=_ANGLE, severity="LOW",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{sql_count}/{len(formulas)} formulas use sql_*_aggregate_op ({ratio:.0f}%)",
                metric=round(ratio, 1), threshold={"max_pct": 20},
            ))
    return findings


def check_d10(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        mt = m.get("model_tables") or []
        tables_with_cols = set()
        for c in cols:
            cid = c.get("column_id", "")
            if "::" in cid:
                tables_with_cols.add(cid.split("::")[0])
        joined = set()
        for t in mt:
            for j in (t.get("joins") or []):
                joined.add(t.get("name", ""))
                joined.add(j.get("with", ""))
        for t in mt:
            tname = t.get("name", "")
            if tname not in tables_with_cols:
                role = "bridge" if tname in joined else "leaf"
                severity = "INFO" if role == "bridge" else "MEDIUM"
                findings.append(Finding(
                    check_id="D10", angle=_ANGLE, severity=severity,
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Zero-column {role} table '{tname}'",
                ))
    return findings


def check_d11(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                cardinality = (j.get("cardinality") or "").upper()
                if "ONE_TO_MANY" not in cardinality and "MANY_TO_MANY" not in cardinality:
                    continue
                tname = j.get("with", "")
                from_table = mt.get("name", "")
                from_role = _table_role(cols, from_table)
                to_role = _table_role(cols, tname)
                if from_role == "fact" and to_role == "fact":
                    findings.append(Finding(
                        check_id="D11", angle=_ANGLE, severity="MEDIUM",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=ctx.guid_for(model),
                        detail=f"Fan-out risk: fact-to-fact join '{from_table}' -> '{tname}' with {cardinality}",
                    ))
                else:
                    findings.append(Finding(
                        check_id="D11", angle=_ANGLE, severity="INFO",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=ctx.guid_for(model),
                        detail=f"ONE_TO_MANY join '{from_table}' -> '{tname}'",
                    ))
    return findings


def check_d12(ctx: AuditContext) -> list:
    findings = []
    if len(ctx.models) < 2:
        return findings
    col_types = defaultdict(dict)
    for model in ctx.models:
        m = model.get("model", {})
        mname = m.get("name", "")
        for c in (m.get("columns") or []):
            db_name = c.get("db_column_name") or c.get("name", "")
            ctype = (c.get("properties") or {}).get("column_type", "")
            if ctype:
                col_types[db_name][mname] = ctype
    for db_name, model_map in col_types.items():
        types = set(model_map.values())
        if len(types) > 1:
            models_str = ", ".join(f"{mn}={ct}" for mn, ct in model_map.items())
            findings.append(Finding(
                check_id="D12", angle=_ANGLE, severity="MEDIUM",
                object_type="column", object_name=db_name,
                object_guid="",
                detail=f"Column '{db_name}' classified differently across models: {models_str}",
            ))
    return findings


ALL_CHECKS = [
    check_d1, check_d2, check_d3, check_d4, check_d5, check_d6,
    check_d7, check_d8, check_d9, check_d10, check_d11, check_d12,
]
