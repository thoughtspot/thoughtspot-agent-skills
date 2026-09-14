"""ts columns — column-level impact analysis for ThoughtSpot."""
from __future__ import annotations

import json

import typer
import yaml

from ts_cli.client import ThoughtSpotClient

app = typer.Typer(help="Column-level analysis commands.")


def _post(client: ThoughtSpotClient, path: str, body: dict) -> "list | dict":
    resp = client.request("POST", path, json=body)
    return resp.json()


_COL_SEARCH_PAGE = 50


def _find_col_guid(client: ThoughtSpotClient, col_name: str, owner_guid: str) -> "str | None":
    """GUID of the column named `col_name` owned by `owner_guid`, or None.

    Paginates. A single 50-record page was not safe here: the search matches the
    column NAME cluster-wide and the owner filter is applied in memory, so a
    common name (`ID`, `NAME`, `CUSTOMER_ID`) can push the real match past the
    first page. This function returning None reads to `ts columns impact` as
    "no dependents", i.e. safe to delete — a silent wrong answer in the one
    command whose job is to prevent exactly that.
    """
    offset = 0
    while True:
        results = _post(client, "/api/rest/2.0/metadata/search", {
            "metadata": [{"identifier": col_name, "type": "LOGICAL_COLUMN"}],
            "include_headers": True,
            "record_size": _COL_SEARCH_PAGE,
            "record_offset": offset,
        }) or []
        match = next(
            (r for r in results
             if r.get("metadata_header", {}).get("owner") == owner_guid),
            None,
        )
        if match:
            return match["metadata_id"]
        if len(results) < _COL_SEARCH_PAGE:
            return None
        offset += _COL_SEARCH_PAGE


def _fetch_dependents(client: ThoughtSpotClient, col_guid: str) -> dict:
    resp = _post(client, "/api/rest/2.0/metadata/search", {
        "metadata": [{"identifier": col_guid, "type": "LOGICAL_COLUMN"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
        "dependent_objects_record_size": 200,
        "record_size": 1,
        "record_offset": 0,
    })
    return (resp[0].get("dependent_objects") or {}) if resp else {}


def _enrich_subtypes(
    client: ThoughtSpotClient, dep_list: list[dict]
) -> list[dict]:
    from ts_cli.column_impact import apply_subtype_labels, SUBTYPE_LABELS
    lt_guids = [d["guid"] for d in dep_list if d.get("raw_type") == "LOGICAL_TABLE" and d.get("guid")]
    if not lt_guids:
        return dep_list
    search_resp = _post(client, "/api/rest/2.0/metadata/search", {
        "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in lt_guids],
        "include_headers": True,
        "record_size": len(lt_guids),
        "record_offset": 0,
    })
    subtype_map: dict[str, str] = {}
    for r in (search_resp or []):
        h = r.get("metadata_header", {})
        subtype_map[r["metadata_id"]] = h.get("subType") or h.get("type", "")
    return apply_subtype_labels(dep_list, subtype_map)


def _print_deps(dep_list: list[dict], inaccessible: bool) -> None:
    if dep_list:
        for d in dep_list:
            typer.echo(f"  [{d['type']}] {d['name']}  ({d['guid']})", err=True)
        if inaccessible:
            typer.echo(
                "  ⚠  hasInaccessibleDependents=true — additional objects exist "
                "that you cannot see", err=True)
    else:
        typer.echo("  (none)", err=True)


@app.command("impact")
def impact_cmd(
    column: str = typer.Option(..., "--column", help="Column display name in the Model"),
    physical_col: str = typer.Option(..., "--physical-col",
                                      help="Physical DB column name (db_column_name)"),
    model_guid: str = typer.Option(..., "--model", help="Model GUID"),
    table_guid: str = typer.Option(..., "--table", help="ThoughtSpot Table GUID"),
    profile: str = typer.Option(..., "--profile", "-p", help="ThoughtSpot profile name"),
) -> None:
    """Find all ThoughtSpot objects affected by deleting a physical column (13-pass analysis).

    Runs 13 passes across the ThoughtSpot instance — model column dependents,
    formula references, broken formula dependents, table column dependents,
    column security rules, RLS rules, formula variables, AI memory/business terms,
    SQL views, custom actions, cohorts, scheduled reports, and monitor alerts —
    and prints a JSON summary to stdout.

    \\b
    Example:
      ts columns impact \\
        --column "Franchise Id" --physical-col "franchiseID" \\
        --model 252de95b-... --table 6eb11eb8-... \\
        --profile my-ts-profile
    """
    from ts_cli.column_impact import (
        build_impact_summary,
        collect_affected_lb_ans_guids,
        find_broken_formulas,
        find_broken_rls,
        parse_dependents,
    )

    client = ThoughtSpotClient(profile)

    sep = "=" * 60

    # ── PASS 1: model column direct dependents ──────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 1: Model column '{column}' direct dependents", err=True)
    typer.echo(sep, err=True)

    model_col_guid = _find_col_guid(client, column, model_guid)
    if not model_col_guid:
        typer.echo(f"  No LOGICAL_COLUMN '{column}' owned by model {model_guid} found.", err=True)
        pass1_deps, pass1_inaccessible = [], False
    else:
        typer.echo(f"  GUID: {model_col_guid}", err=True)
        raw = _fetch_dependents(client, model_col_guid)
        pass1_deps, pass1_inaccessible = parse_dependents(raw)
        pass1_deps = _enrich_subtypes(client, pass1_deps)
        _print_deps(pass1_deps, pass1_inaccessible)

    # ── PASS 2: model TML formula scan ─────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 2: Model TML formula references to '{physical_col}'", err=True)
    typer.echo(sep, err=True)

    tml_resp = _post(client, "/api/rest/2.0/metadata/tml/export", {
        "metadata": [{"identifier": model_guid}],
        "export_associated": False,
        "export_fqn": False,
    })
    edoc_raw = tml_resp[0].get("edoc", "{}") if tml_resp else "{}"
    model_doc = json.loads(edoc_raw) if isinstance(edoc_raw, str) else edoc_raw
    formulas = model_doc.get("model", {}).get("formulas", [])
    broken_formulas = find_broken_formulas(formulas, physical_col)

    if broken_formulas:
        for f in broken_formulas:
            typer.echo(f"\n  id   : {f['id']}", err=True)
            typer.echo(f"  name : {f['name']}", err=True)
            typer.echo(f"  expr : {f['expr']}", err=True)
    else:
        typer.echo("  (none)", err=True)

    # ── PASS 3: broken formula column dependents ────────────────────────
    formula_dep_results: list[tuple] = []

    if broken_formulas:
        typer.echo(f"\n{sep}", err=True)
        typer.echo("PASS 3: Dependents of broken formula columns", err=True)
        typer.echo(sep, err=True)

        for f in broken_formulas:
            fname = f["name"]
            fguid = _find_col_guid(client, fname, model_guid)
            if not fguid:
                typer.echo(f"\n  '{fname}': LOGICAL_COLUMN GUID not found", err=True)
                continue
            typer.echo(f"\n  '{fname}'  GUID={fguid}", err=True)
            raw = _fetch_dependents(client, fguid)
            fdep_list, fdep_inaccessible = parse_dependents(raw)
            fdep_list = _enrich_subtypes(client, fdep_list)
            formula_dep_results.append((fname, fguid, fdep_list, fdep_inaccessible))
            _print_deps(fdep_list, fdep_inaccessible)

    # ── PASS 4: table-level column dependents ───────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 4: Table column '{physical_col}' dependents (table GUID: {table_guid})",
               err=True)
    typer.echo(sep, err=True)

    table_col_guid = _find_col_guid(client, physical_col, table_guid)
    if not table_col_guid:
        typer.echo(
            f"  No LOGICAL_COLUMN '{physical_col}' owned by table {table_guid} found.", err=True)
        pass4_deps, pass4_inaccessible = [], False
    else:
        typer.echo(f"  GUID: {table_col_guid}", err=True)
        raw = _fetch_dependents(client, table_col_guid)
        pass4_deps, pass4_inaccessible = parse_dependents(raw)
        pass4_deps = _enrich_subtypes(client, pass4_deps)
        _print_deps(pass4_deps, pass4_inaccessible)

    # ── PASS 5: column security rules ───────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 5: Column security rules for '{physical_col}' on table {table_guid}",
               err=True)
    typer.echo(sep, err=True)

    col_security_rules: list[dict] = []
    try:
        csr_resp = _post(client, "/api/rest/2.0/security/column/rules/fetch", {
            "tables": [{"identifier": table_guid}],
        })
        for tbl_entry in (csr_resp or []):
            for rule in (tbl_entry.get("column_security_rules") or []):
                col = rule.get("column", {})
                if col.get("name", "").lower() == physical_col.lower():
                    col_security_rules.append(rule)
        if col_security_rules:
            for rule in col_security_rules:
                col = rule.get("column", {})
                groups = rule.get("groups") or []
                src = rule.get("source_table_details") or {}
                typer.echo(f"\n  Column : {col.get('name')}  (id={col.get('id')})", err=True)
                typer.echo(f"  Source : {src.get('name')}  ({src.get('id')})", err=True)
                if groups:
                    typer.echo(f"  Groups with access ({len(groups)}):", err=True)
                    for g in groups:
                        typer.echo(f"    {g.get('name')}  ({g.get('id')})", err=True)
                else:
                    typer.echo(
                        "  Groups with access: (none — column may be secured with no exceptions)",
                        err=True)
        else:
            typer.echo("  No column security rules found for this column.", err=True)
            typer.echo("  (Endpoint is beta/10.12.0.cl+ — may not be available on this instance)",
                       err=True)
    except Exception as exc:
        typer.echo(f"  Error fetching column security rules: {exc}", err=True)

    # ── PASS 6: RLS rules (table TML scan) ─────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 6: RLS rules in table TML referencing '{physical_col}'", err=True)
    typer.echo(sep, err=True)

    table_tml_resp = _post(client, "/api/rest/2.0/metadata/tml/export", {
        "metadata": [{"identifier": table_guid}],
        "export_associated": False,
        "export_fqn": False,
    })
    table_edoc_raw = table_tml_resp[0].get("edoc", "{}") if table_tml_resp else "{}"
    table_doc = json.loads(table_edoc_raw) if isinstance(table_edoc_raw, str) else table_edoc_raw
    rls_block = table_doc.get("table", {}).get("rls_rules", {})
    rls_rules_list = rls_block.get("rules", [])
    rls_paths = rls_block.get("table_paths", [])

    broken_rls, broken_paths = find_broken_rls(rls_rules_list, rls_paths, physical_col)

    if rls_rules_list:
        typer.echo(f"\n  Total RLS rules on table: {len(rls_rules_list)}", err=True)
        for rule in rls_rules_list:
            hit = physical_col.lower() in (rule.get("expr") or "").lower()
            marker = "  ← references column" if hit else ""
            typer.echo(f"  Rule: {rule.get('name', '(unnamed)')!r}  "
                       f"expr: {rule.get('expr')}{marker}", err=True)
        if broken_paths:
            typer.echo(f"\n  Table paths that include '{physical_col}':", err=True)
            for p in broken_paths:
                typer.echo(f"    id={p.get('id')}  table={p.get('table')}  "
                           f"columns={p.get('column')}", err=True)
    else:
        typer.echo("  No RLS rules found on this table.", err=True)

    # ── PASS 7: formula variables ───────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 7: Formula variables referencing '{physical_col}'", err=True)
    typer.echo(sep, err=True)

    broken_vars: list[tuple] = []
    try:
        var_resp = _post(client, "/api/rest/2.0/template/variables/search", {
            "variable_details": [{"type": "FORMULA_VARIABLE"}],
            "value_scope": [{"model_identifier": model_guid}],
            "response_content": "METADATA_AND_VALUES",
            "record_size": 50,
            "record_offset": 0,
        })
        for var in (var_resp or []):
            name_hit = physical_col.lower() in var.get("name", "").lower()
            val_hits = [
                v for v in (var.get("values") or [])
                if physical_col.lower() in (v.get("value") or "").lower()
                or any(physical_col.lower() in s.lower() for s in (v.get("value_list") or []))
            ]
            if name_hit or val_hits:
                broken_vars.append((var, val_hits))

        typer.echo(f"\n  Formula variables scoped to model {model_guid}: {len(var_resp or [])}",
                   err=True)
        if broken_vars:
            for var, val_hits in broken_vars:
                typer.echo(f"\n  Variable : {var.get('name')}  (id={var.get('id')})", err=True)
                for v in val_hits:
                    scope = (f"org={v.get('org_identifier')} "
                             f"principal={v.get('principal_identifier') or 'all'}")
                    typer.echo(f"    value  : {v.get('value') or v.get('value_list')}  [{scope}]",
                               err=True)
        elif var_resp:
            typer.echo(
                f"  None of the {len(var_resp)} variable(s) reference '{physical_col}'.", err=True)
        else:
            typer.echo("  No formula variables found for this model.", err=True)
            typer.echo(
                "  (Requires 26.4.0.cl+ and ADMINISTRATION or CAN_MANAGE_VARIABLES privilege)",
                err=True)
    except Exception as exc:
        typer.echo(f"  Error fetching formula variables: {exc}", err=True)

    # ── PASS 8: business terms / AI memory ─────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 8: Business terms (memory) referencing '{column}'", err=True)
    typer.echo(sep, err=True)

    broken_terms: list[tuple] = []
    broken_formula_names = [f["name"] for f in broken_formulas]
    targets = [column] + broken_formula_names

    try:
        feedback_resp = _post(client, "/api/rest/2.0/metadata/tml/export", {
            "metadata": [{"identifier": model_guid, "type": "FEEDBACK"}],
            "export_associated": False,
        })
        edoc_raw = feedback_resp[0].get("edoc", "") if feedback_resp else ""
        memory_doc = yaml.safe_load(edoc_raw) if edoc_raw else {}
        feedbacks = (memory_doc or {}).get("nls_feedback", {}).get("feedback", [])

        for fb in (feedbacks or []):
            tokens = fb.get("search_tokens", "") or ""
            phrase = fb.get("feedback_phrase", "") or ""
            ac_text = str(fb.get("axis_config") or "")
            haystack = f"{tokens} {phrase} {ac_text}".lower()
            hit_targets = [t for t in targets if t.lower() in haystack]
            if physical_col.lower() in haystack:
                hit_targets = list(set(hit_targets + [physical_col]))
            if hit_targets:
                broken_terms.append((fb, hit_targets))

        if broken_terms:
            for bt, hits in broken_terms:
                typer.echo(f"\n  type    : {bt.get('type')}", err=True)
                typer.echo(f"  phrase  : {bt.get('feedback_phrase')}", err=True)
                typer.echo(f"  tokens  : {bt.get('search_tokens')}", err=True)
                typer.echo(f"  matched : {hits}", err=True)
        else:
            total = len(feedbacks or [])
            typer.echo(
                f"  No NLS feedback entries reference '{column}' or its dependent formulas",
                err=True)
            typer.echo(f"  (Total NLS feedback entries: {total})", err=True)
    except Exception as exc:
        typer.echo(f"  Error fetching FEEDBACK TML: {exc}", err=True)

    typer.echo(f"\n  [AI memory rules/recipes]", err=True)
    try:
        ai_mem_resp = _post(client, "/api/rest/2.0/ai/memory/export", {
            "sources": [{"identifiers": [model_guid], "type": "DATA_MODEL"}],
        })
        ai_mem_content = ai_mem_resp.get("content", "") or ""
        ai_mem_doc = yaml.safe_load(ai_mem_content) or {}
        ai_memories = ai_mem_doc.get("memories", [])

        broken_ai_memory: list[tuple] = []
        for mem in (ai_memories or []):
            mem_type = mem.get("type", "")
            content = mem.get("content") or {}
            content_str = json.dumps(content)
            if mem_type == "RECIPE":
                try:
                    recipe_obj = json.loads(content.get("recipe", "{}"))
                    content_str += " " + json.dumps(recipe_obj)
                except Exception:
                    pass
            haystack = content_str.lower()
            hit_targets = [t for t in targets if t.lower() in haystack]
            if physical_col.lower() in haystack:
                hit_targets = list(set(hit_targets + [physical_col]))
            if hit_targets:
                broken_ai_memory.append((mem, hit_targets))

        if broken_ai_memory:
            for mem, hits in broken_ai_memory:
                mem_type = mem.get("type", "")
                content = mem.get("content") or {}
                label = (content.get("rule_definition") or content.get("user_query")
                         or str(content)[:120])
                typer.echo(f"\n    type    : {mem_type}", err=True)
                typer.echo(f"    content : {label}", err=True)
                typer.echo(f"    matched : {hits}", err=True)
        else:
            typer.echo(
                f"    No AI memory entries reference '{column}' or its dependent formulas",
                err=True)
            typer.echo(f"    (Total AI memory entries: {len(ai_memories)})", err=True)

        broken_terms.extend(broken_ai_memory)
    except Exception as exc:
        typer.echo(f"  Error fetching AI memory: {exc}", err=True)

    # ── PASS 9: SQL views ───────────────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 9: SQL views referencing '{physical_col}'", err=True)
    typer.echo(sep, err=True)

    sv_guids: list[tuple[str, str]] = []
    offset = 0
    PAGE = 50
    while True:
        page_resp = _post(client, "/api/rest/2.0/metadata/search", {
            "metadata": [{"type": "LOGICAL_TABLE"}],
            "include_headers": True,
            "record_size": PAGE,
            "record_offset": offset,
        })
        if not page_resp:
            break
        for r in page_resp:
            h = r.get("metadata_header", {})
            if (h.get("subType") or h.get("type", "")) == "SQL_VIEW":
                sv_guids.append((r["metadata_id"], h.get("name", "")))
        if len(page_resp) < PAGE:
            break
        offset += PAGE

    typer.echo(f"  SQL views in org: {len(sv_guids)}", err=True)
    broken_views: list[dict] = []
    BATCH = 10
    for i in range(0, len(sv_guids), BATCH):
        batch = sv_guids[i:i + BATCH]
        tml_batch = _post(client, "/api/rest/2.0/metadata/tml/export", {
            "metadata": [{"identifier": g} for g, _ in batch],
            "export_associated": False,
        })
        for item in (tml_batch or []):
            edoc_raw = item.get("edoc", "{}")
            doc = json.loads(edoc_raw) if isinstance(edoc_raw, str) else edoc_raw
            sv = doc.get("sql_view", {})
            if not sv:
                continue
            sql_query = sv.get("sql_query", "") or ""
            output_cols = [
                c.get("sql_output_column") or c.get("name", "")
                for c in (sv.get("sql_view_columns") or [])
            ]
            col_in_sql = physical_col.lower() in sql_query.lower()
            col_in_cols = any(physical_col.lower() in c.lower() for c in output_cols)
            if col_in_sql or col_in_cols:
                broken_views.append({
                    "guid": doc.get("guid", ""),
                    "name": sv.get("name", ""),
                    "sql": sql_query,
                    "out_cols": output_cols,
                    "in_sql": col_in_sql,
                    "in_cols": col_in_cols,
                })

    sv_downstream: list[dict] = []
    if broken_views:
        for v in broken_views:
            typer.echo(f"\n  [VIEW (SQL)] {v['name']}  ({v['guid']})", err=True)
            reasons = []
            if v["in_sql"]:
                reasons.append("sql_query")
            if v["in_cols"]:
                reasons.append("sql_view_columns")
            typer.echo(f"    found in  : {', '.join(reasons)}", err=True)
            typer.echo(f"    sql_query : {v['sql'][:300]}", err=True)
        typer.echo(f"\n  --- Downstream objects built on broken SQL views ---", err=True)
        typer.echo(
            "  (Note: dependency API rarely tracks SQL view usage; empty is expected)", err=True)
        for v in broken_views:
            sv_dep_resp = _post(client, "/api/rest/2.0/metadata/search", {
                "metadata": [{"identifier": v["guid"], "type": "LOGICAL_TABLE"}],
                "include_dependent_objects": True,
                "dependent_object_version": "V2",
                "dependent_objects_record_size": 200,
                "record_size": 1,
                "record_offset": 0,
            })
            dep_obj = (sv_dep_resp[0].get("dependent_objects") or {}) if sv_dep_resp else {}
            dep_list, dep_inacc = parse_dependents(dep_obj)
            dep_list = _enrich_subtypes(client, dep_list)
            if dep_list:
                for d in dep_list:
                    d["via_sv"] = v["guid"]
                    d["via_sv_name"] = v["name"]
                sv_downstream.extend(dep_list)
                for d in dep_list:
                    typer.echo(
                        f"    [{d['type']}] {d['name']}  ({d['guid']}) — via {v['name']!r}",
                        err=True)
            else:
                typer.echo(f"    {v['name']!r}: (none)", err=True)
    else:
        typer.echo(f"  No SQL views reference '{physical_col}'", err=True)

    # ── PASS 10: custom actions ─────────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo("PASS 10: Custom actions on affected objects", err=True)
    typer.echo(sep, err=True)

    affected_guids: set[str] = {d["guid"] for d in pass1_deps if d.get("guid")}
    for _, _, fdeps, _ in formula_dep_results:
        affected_guids.update(d["guid"] for d in fdeps if d.get("guid"))
    affected_guids.update(d["guid"] for d in pass4_deps if d.get("guid"))

    affected_actions: list[tuple] = []
    try:
        ca_resp = _post(client, "/api/rest/2.0/customization/custom-actions/search", {
            "include_metadata_associations": True,
            "include_group_associations": False,
        })
        for action in (ca_resp or []):
            is_global = (action.get("default_action_config") or {}).get("visibility", False)
            assoc_guids = {a["identifier"] for a in (action.get("metadata_association") or [])}
            matched_guids = assoc_guids & affected_guids
            if is_global or matched_guids:
                affected_actions.append((action, is_global, matched_guids))

        if affected_actions:
            for action, is_global, matched in affected_actions:
                scope = "GLOBAL (all visualizations)" if is_global else f"scoped to {len(matched)} affected object(s)"
                typer.echo(f"\n  [{action.get('id')}]  {action.get('name')!r}", err=True)
                typer.echo(f"    scope   : {scope}", err=True)
                if matched:
                    typer.echo(f"    objects : {matched}", err=True)
        else:
            typer.echo(
                f"  No custom actions are global or scoped to affected objects", err=True)
            typer.echo(f"  (Total custom actions checked: {len(ca_resp or [])})", err=True)
    except Exception as exc:
        typer.echo(f"  Error fetching custom actions: {exc}", err=True)

    # ── PASS 11: cohorts ────────────────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo(f"PASS 11: Cohorts (column/query sets) anchored to '{column}'", err=True)
    typer.echo(sep, err=True)

    broken_cohorts: list[dict] = []
    try:
        cohort_candidates: list[tuple[str, str, str]] = []
        lc_offset = 0
        LC_PAGE = 100
        while True:
            lc_resp = _post(client, "/api/rest/2.0/metadata/search", {
                "metadata": [{"type": "LOGICAL_COLUMN"}],
                "include_headers": True,
                "record_size": LC_PAGE,
                "record_offset": lc_offset,
            })
            if not lc_resp:
                break
            for r in lc_resp:
                h = r.get("metadata_header", {})
                col_type = h.get("type", "")
                if col_type in ("COHORT_SIMPLE", "COHORT_ADVANCED") and h.get("owner") == model_guid:
                    cohort_candidates.append((r["metadata_id"], h.get("name", ""), col_type))
            if len(lc_resp) < LC_PAGE:
                break
            lc_offset += LC_PAGE

        typer.echo(f"  Cohort columns in model: {len(cohort_candidates)}", err=True)
        if cohort_candidates:
            for i in range(0, len(cohort_candidates), BATCH):
                batch = cohort_candidates[i:i + BATCH]
                tml_resp2 = _post(client, "/api/rest/2.0/metadata/tml/export", {
                    "metadata": [{"identifier": g} for g, _, _ in batch],
                    "export_associated": False,
                })
                for item in (tml_resp2 or []):
                    edoc_raw = item.get("edoc", "{}")
                    doc = json.loads(edoc_raw) if isinstance(edoc_raw, str) else edoc_raw
                    cohort = doc.get("cohort", {})
                    config = cohort.get("config", {})
                    anchor = config.get("anchor_column_id", "")
                    name = cohort.get("name", "")
                    guid = doc.get("guid", "")
                    cohort_type = config.get("cohort_type", "")
                    full_text = edoc_raw if isinstance(edoc_raw, str) else json.dumps(doc)
                    if (anchor.lower() == column.lower()
                            or column.lower() in full_text.lower()
                            or physical_col.lower() in full_text.lower()):
                        broken_cohorts.append({
                            "guid": guid, "name": name,
                            "type": cohort_type, "anchor": anchor,
                        })

        if broken_cohorts:
            for c in broken_cohorts:
                typer.echo(f"\n  [{c['type']}] {c['name']!r}  ({c['guid']})", err=True)
                typer.echo(f"    anchor_column_id : {c['anchor']!r}", err=True)
        else:
            typer.echo(f"  No cohorts in model are anchored to '{column}'", err=True)
    except Exception as exc:
        typer.echo(f"  Error scanning cohorts: {exc}", err=True)

    # ── Collect LB/Answer GUIDs for passes 12/13 ───────────────────────
    all_dep_lists: list[list[dict]] = [pass1_deps, pass4_deps, sv_downstream]
    for _, _, fdeps, _ in formula_dep_results:
        all_dep_lists.append(fdeps)
    affected_lb_guids, affected_ans_guids = collect_affected_lb_ans_guids(all_dep_lists)

    # ── PASS 12: scheduled reports ──────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo("PASS 12: Scheduled reports on affected Liveboards", err=True)
    typer.echo(sep, err=True)

    broken_schedules: list[dict] = []
    try:
        if affected_lb_guids:
            sched_resp = _post(client, "/api/rest/2.0/schedules/search", {
                "metadata": [{"identifier": g, "type": "LIVEBOARD"} for g in affected_lb_guids],
                "record_size": -1,
                "record_offset": 0,
            })
            broken_schedules = sched_resp or []
        if broken_schedules:
            for s in broken_schedules:
                lb = s.get("metadata", {})
                rec = s.get("recipient_details", {}) or {}
                emails = rec.get("emails") or []
                principals = [p.get("identifier") for p in (rec.get("principals") or [])]
                all_recipients = emails + principals
                cron = s.get("frequency", {}).get("cron_expression", {})
                cron_str = (f"{cron.get('minute')} {cron.get('hour')} "
                            f"{cron.get('day_of_month')} {cron.get('month')} "
                            f"{cron.get('day_of_week')}")
                typer.echo(f"\n  [{s.get('id')}] {s.get('name')!r}", err=True)
                typer.echo(f"    liveboard : {lb.get('name') or lb.get('id')}", err=True)
                typer.echo(f"    format    : {s.get('file_format')}  status={s.get('status')}",
                           err=True)
                typer.echo(f"    schedule  : {cron_str}  tz={s.get('time_zone')}", err=True)
                typer.echo(
                    f"    recipients: {', '.join(all_recipients) or '(none listed)'}", err=True)
        else:
            if affected_lb_guids:
                typer.echo(
                    f"  No scheduled reports on the {len(affected_lb_guids)} affected Liveboard(s)",
                    err=True)
            else:
                typer.echo("  No affected Liveboards — skipped", err=True)
            typer.echo("  (POST /api/rest/2.0/schedules/search, requires 9.4.0.cl+)", err=True)
    except Exception as exc:
        typer.echo(f"  Error fetching schedules: {exc}", err=True)

    # ── PASS 13: monitor alerts ─────────────────────────────────────────
    typer.echo(f"\n{sep}", err=True)
    typer.echo("PASS 13: Monitor alerts on affected objects", err=True)
    typer.echo(sep, err=True)

    broken_alerts: list[dict] = []
    try:
        for lb_guid in affected_lb_guids:
            bundle = _post(client, "/api/rest/2.0/metadata/tml/export", {
                "metadata": [{"identifier": lb_guid}],
                "export_associated": True,
            })
            for item in (bundle or []):
                edoc_raw = item.get("edoc", "{}")
                doc = json.loads(edoc_raw) if isinstance(edoc_raw, str) else edoc_raw
                if "monitor_alert" not in doc:
                    continue
                for alert in (doc.get("monitor_alert") or []):
                    metric = alert.get("metric_id", {}) or {}
                    anchor_ans_id = metric.get("answer_id")
                    anchor_lb_id = (metric.get("pinboard_viz_id") or {}).get("pinboard_id")
                    pv_filters = (alert.get("personalised_view_info") or {}).get("filters") or []
                    col_refs: list[str] = []
                    for f in pv_filters:
                        col_refs.extend(f.get("column") or [])
                    col_in_filter = any(
                        physical_col.lower() in c.lower() or column.lower() in c.lower()
                        for c in col_refs
                    )
                    ans_affected = bool(anchor_ans_id and anchor_ans_id in affected_ans_guids)
                    if col_in_filter or ans_affected:
                        broken_alerts.append({
                            "guid": alert.get("guid"),
                            "name": alert.get("name"),
                            "anchor_ans": anchor_ans_id,
                            "anchor_lb": anchor_lb_id or lb_guid,
                            "col_in_filter": col_in_filter,
                            "ans_affected": ans_affected,
                            "subscribers": [u.get("user_email")
                                            for u in (alert.get("subscribed_user") or [])],
                        })
        if broken_alerts:
            for a in broken_alerts:
                reasons = []
                if a["col_in_filter"]:
                    reasons.append(f"personalised_view filter references '{physical_col}'")
                if a["ans_affected"]:
                    reasons.append(f"watched Answer is affected ({a['anchor_ans']})")
                typer.echo(f"\n  [{a['guid']}] {a['name']!r}", err=True)
                typer.echo(f"    reason     : {'; '.join(reasons)}", err=True)
                typer.echo(
                    f"    subscribers: {', '.join(a['subscribers']) or '(none)'}", err=True)
        else:
            if affected_lb_guids:
                typer.echo(
                    f"  No monitor alerts on the {len(affected_lb_guids)} affected Liveboard(s)",
                    err=True)
            else:
                typer.echo("  No affected Liveboards — skipped", err=True)
            typer.echo(
                "  (Scanned via export_associated=True on each affected Liveboard)", err=True)
    except Exception as exc:
        typer.echo(f"  Error scanning monitor alerts: {exc}", err=True)

    # ── SUMMARY ─────────────────────────────────────────────────────────
    from ts_cli.column_impact import build_impact_summary

    any_inaccessible = pass1_inaccessible or pass4_inaccessible
    summary = build_impact_summary(
        column_name=column,
        physical_col=physical_col,
        pass1_deps=pass1_deps,
        formula_dep_results=formula_dep_results,
        pass4_deps=pass4_deps,
        sv_downstream=sv_downstream,
        broken_formulas=broken_formulas,
        col_security_rules=col_security_rules,
        broken_rls=broken_rls,
        broken_paths=broken_paths,
        broken_vars=broken_vars,
        broken_terms=broken_terms,
        affected_actions=affected_actions,
        broken_views=broken_views,
        broken_cohorts=broken_cohorts,
        broken_schedules=broken_schedules,
        broken_alerts=broken_alerts,
        any_inaccessible=any_inaccessible,
    )

    typer.echo(f"\n{sep}", err=True)
    typer.echo("IMPACT SUMMARY", err=True)
    typer.echo(sep, err=True)
    typer.echo(
        f"Deleting '{physical_col}' from the database will affect "
        f"{summary['unique_affected_objects']} unique object(s).", err=True)
    if any_inaccessible:
        typer.echo(
            "\n  ⚠  hasInaccessibleDependents=true on one or more passes —\n"
            "     additional objects exist that this token cannot see.\n"
            "     Re-run with an admin token for full coverage.", err=True)
    typer.echo("\n  NOT CHECKED (no API coverage):", err=True)
    typer.echo("    - Personalized liveboard views (per-user saved filter state)", err=True)

    print(json.dumps(summary, indent=2))
