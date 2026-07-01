from __future__ import annotations

import re

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "performance"
_SQL_PASSTHROUGH = re.compile(r"sql_(int|string|bool)_aggregate_op", re.IGNORECASE)
_ID_PATTERN = re.compile(r"(_id|_guid|_uuid|transaction_id|row_id|surrogate_key)$", re.IGNORECASE)
_FUNC_IN_EXPR = re.compile(r"\b(UPPER|LOWER|TRIM|CAST|CONCAT|CONTAINS|IF)\s*\(", re.IGNORECASE)
_IF_PATTERN = re.compile(r"\bif\s*\(", re.IGNORECASE)
_BRACKET_REF = re.compile(r"\[([^\]]+)\]")


def _bfs_depth(graph, start):
    visited = set()
    queue = [(start, 0)]
    max_d = 0
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        max_d = max(max_d, d)
        for nb in graph.get(node, []):
            queue.append((nb, d + 1))
    return max_d


def check_p1(ctx: AuditContext) -> list:
    findings = []
    for entry in ctx.metadata:
        header = entry.get("metadata_header") or entry
        if header.get("type") == "SQL_VIEW":
            findings.append(Finding(
                check_id="P1", angle=_ANGLE, severity="MEDIUM",
                object_type="table", object_name=header.get("name", ""),
                object_guid=header.get("id", ""),
                detail="SQL_VIEW data source blocks filter pushdown",
            ))
    return findings


def check_p2(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        cols = m.get("columns") or []
        agg_formula_ids = {c.get("formula_id") for c in cols
                          if (c.get("properties") or {}).get("aggregation")}
        scalar = [f for f in formulas if f.get("id") not in agg_formula_ids]
        count = len(scalar)
        if count > 10:
            severity = "HIGH"
        elif count > 5:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P2", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{count} scalar formulas (run at query time in TS engine)",
            metric=count, threshold={"green": 5, "yellow": 10},
        ))
    return findings


def check_p3(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        filters = m.get("filters") or []
        if not filters:
            continue
        non_prog = [f for f in filters if not (f.get("apply_on_tables") or [])]
        if non_prog:
            findings.append(Finding(
                check_id="P3", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(non_prog)}/{len(filters)} filters lack apply_on_tables (run on every query)",
                metric=len(non_prog),
            ))
    return findings


def check_p4(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        props = m.get("properties") or {}
        if len(mt) > 5 and not props.get("join_progressive", False):
            findings.append(Finding(
                check_id="P4", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"join_progressive: false on {len(mt)}-table model — every query joins ALL tables",
                metric=len(mt),
            ))
    return findings


def check_p5(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        constraints = m.get("constraints") or []
        has_date_constraint = any(
            "date_range_condition" in str(c) for c in constraints
        )
        if has_date_constraint:
            continue
        fact_tables = set()
        for mt in (m.get("model_tables") or []):
            tname = mt.get("name", "")
            table_cols = [c for c in cols
                          if (c.get("column_id") or "").split("::")[0] == tname]
            measures = sum(1 for c in table_cols
                           if (c.get("properties") or {}).get("column_type") == "MEASURE")
            if measures > 3:
                fact_tables.add(tname)
        if fact_tables:
            findings.append(Finding(
                check_id="P5", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"No date constraints on model with fact tables: {', '.join(sorted(fact_tables)[:3])}",
                metric=len(fact_tables),
            ))
    return findings


def check_p6(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
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
                        check_id="P6", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=ctx.guid_for(model),
                        detail=f"VARCHAR join key(s) — 2-5x slower than integer: {', '.join(varchar_keys)}",
                        metric=len(varchar_keys),
                    ))
    return findings


def check_p7(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        graph = {}
        for t in mt:
            tn = t.get("name", "")
            for j in (t.get("joins") or []):
                graph.setdefault(tn, []).append(j.get("with", ""))
        if not graph:
            continue
        max_depth = 0
        for start in graph:
            visited = set()
            stack = [(start, 0)]
            while stack:
                node, depth = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                max_depth = max(max_depth, depth)
                for nb in graph.get(node, []):
                    stack.append((nb, depth + 1))
        if max_depth > 5:
            severity = "HIGH"
        elif max_depth > 3:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P7", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"Join depth {max_depth} (>5 HIGH, >3 MEDIUM) — complex query plans",
            metric=max_depth, threshold={"green": 3, "yellow": 5},
        ))
    return findings


def check_p8(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if len(cols) > 75:
            findings.append(Finding(
                check_id="P8", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(cols)} columns — wider GROUP BY, more complex query plans",
                metric=len(cols), threshold={"max": 75},
            ))
    return findings


def check_p9(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            props = c.get("properties") or {}
            ctype = props.get("column_type", "")
            idx = props.get("index_type", "")
            name = c.get("name", "")
            if ctype == "ATTRIBUTE" and idx and _ID_PATTERN.search(name):
                findings.append(Finding(
                    check_id="P9", angle=_ANGLE, severity="MEDIUM",
                    object_type="column", object_name=name,
                    object_guid=ctx.guid_for(model),
                    detail=f"High-cardinality ID column '{name}' indexed as ATTRIBUTE",
                ))
    return findings


def check_p11(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        props = m.get("properties") or {}
        spotter = (props.get("spotter_config") or {}).get("is_spotter_enabled", False)
        if not spotter:
            continue
        indexed = sum(1 for c in (m.get("columns") or [])
                      if (c.get("properties") or {}).get("index_type"))
        if indexed > 30:
            findings.append(Finding(
                check_id="P11", angle=_ANGLE, severity="INFO",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{indexed} indexed columns on Spotter-enabled model",
                metric=indexed, threshold={"info": 30},
            ))
    return findings


def check_p13(ctx: AuditContext) -> list:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        rules = rls.get("rules") or []
        count = len(rules)
        if count > 6:
            severity = "HIGH"
        elif count > 3:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P13", angle=_ANGLE, severity=severity,
            object_type="table", object_name=t.get("name", ""),
            object_guid=table.get("guid", ""),
            detail=f"{count} RLS rules — cost compounds linearly per query",
            metric=count, threshold={"medium": 3, "high": 6},
        ))
    return findings


def check_p14(ctx: AuditContext) -> list:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            if _FUNC_IN_EXPR.search(expr):
                findings.append(Finding(
                    check_id="P14", angle=_ANGLE, severity="MEDIUM",
                    object_type="table", object_name=t.get("name", ""),
                    object_guid=table.get("guid", ""),
                    detail=f"RLS expression uses functions — prevents index/partition pruning: {expr[:80]}",
                ))
    return findings


def check_p15(ctx: AuditContext) -> list:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        cols = t.get("columns") or []
        col_props = {}
        for c in cols:
            cn = c.get("name", "")
            dt = (c.get("db_column_properties") or {}).get("data_type", "")
            vc = (c.get("properties") or {}).get("value_casing", "")
            col_props[cn] = (dt, vc)
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            refs = _BRACKET_REF.findall(expr)
            for ref in refs:
                col_name = ref.split("::")[-1] if "::" in ref else ref
                dt, vc = col_props.get(col_name, ("", ""))
                if dt.upper() in ("VARCHAR", "CHAR", "STRING", "TEXT") and not vc:
                    findings.append(Finding(
                        check_id="P15", angle=_ANGLE, severity="MEDIUM",
                        object_type="column", object_name=col_name,
                        object_guid=table.get("guid", ""),
                        detail=f"VARCHAR RLS column '{col_name}' without value_casing",
                    ))
    return findings


def check_p16(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for f in (m.get("formulas") or []):
            expr = f.get("expr", "")
            depth = len(_IF_PATTERN.findall(expr))
            if depth > 5:
                severity = "LOW"
            elif depth > 3:
                severity = "INFO"
            else:
                continue
            findings.append(Finding(
                check_id="P16", angle=_ANGLE, severity=severity,
                object_type="formula", object_name=f.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"Formula has {depth} nested if() levels",
                metric=depth, threshold={"info": 3, "low": 5},
            ))
    return findings


def check_p17(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        formula_names = {f.get("name", "") for f in formulas}
        graph = {}
        for f in formulas:
            fname = f.get("name", "")
            expr = f.get("expr", "")
            refs = _BRACKET_REF.findall(expr)
            cross_refs = [r for r in refs if r in formula_names and r != fname]
            if cross_refs:
                graph[fname] = cross_refs
        for start in graph:
            depth = _bfs_depth(graph, start)
            if depth > 3:
                severity = "LOW"
            elif depth > 2:
                severity = "INFO"
            else:
                continue
            findings.append(Finding(
                check_id="P17", angle=_ANGLE, severity=severity,
                object_type="formula", object_name=start,
                object_guid=ctx.guid_for(model),
                detail=f"Formula reference chain depth {depth}",
                metric=depth, threshold={"info": 2, "low": 3},
            ))
    return findings


def check_p18(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            agg = (c.get("properties") or {}).get("aggregation", "")
            if agg == "COUNT_DISTINCT":
                findings.append(Finding(
                    check_id="P18", angle=_ANGLE, severity="INFO",
                    object_type="column", object_name=c.get("name", ""),
                    object_guid=ctx.guid_for(model),
                    detail=f"COUNT_DISTINCT aggregation on '{c.get('name', '')}'",
                ))
    return findings


ALL_CHECKS = [
    check_p1, check_p2, check_p3, check_p4, check_p5, check_p6,
    check_p7, check_p8, check_p9, check_p11, check_p13, check_p14,
    check_p15, check_p16, check_p17, check_p18,
]
