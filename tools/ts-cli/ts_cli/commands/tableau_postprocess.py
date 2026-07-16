"""ts tableau postprocess — deterministic TML fix-up (T4).

Port of the Tableau_TS_Migrator's post-processing pipeline (tools.py):
patch model joins/column-names, fix formula column refs, inject/resolve
object IDs, dedup files, and name-mapping persistence.

Runs on an existing directory of TML files + the source TWB, producing
corrected TML in-place.  No ThoughtSpot API calls — purely local.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

import yaml

logger = logging.getLogger("tableau_postprocess")

NAME_MAPPING_FILENAME = "name_mapping.json"
_TWB_SQL_REGISTRY_FILE = "_twb_sql_registry.json"


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, _data):
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.upper())


def _norm_sql(sql: str) -> str:
    s = re.sub(r"--[^\n]*", "", sql)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    return re.sub(r"\s+", " ", s).strip().lower()


def _sanitize_yaml_problem_chars(content: str) -> str:
    """Quote YAML scalar values containing %, {, }, @, or ': '."""
    problem_re = re.compile(r'[%{}@]|: ')
    result = []
    for line in content.split('\n'):
        m = re.match(r'^(\s*(?:-\s+)?[\w][\w\s\-]*:\s+)(?![\'"\|>])(.+)$', line)
        if m and problem_re.search(m.group(2)):
            prefix = m.group(1)
            value = m.group(2).rstrip()
            safe_value = value.replace("'", "''")
            result.append(f"{prefix}'{safe_value}'")
        else:
            result.append(line)
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Name-mapping persistence
# ---------------------------------------------------------------------------

def load_name_mapping(output_dir: str) -> dict:
    path = Path(output_dir) / NAME_MAPPING_FILENAME
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"formulas": {}, "columns": {}, "parameters": {}}


def save_name_mapping(output_dir: str, mapping: dict) -> None:
    path = Path(output_dir) / NAME_MAPPING_FILENAME
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def preassign_formula_name_mapping(twb_path: str, output_dir: str) -> None:
    """Pre-populate name_mapping.json with formula/parameter names from the TWB."""
    from ts_cli.commands.tableau_parse import parse_twb

    twb_data = parse_twb(twb_path)
    mapping = load_name_mapping(output_dir)

    for ds in twb_data.get("datasources", []):
        if ds.get("is_parameters"):
            for p in ds.get("parameters", []):
                cap = p.get("caption", "")
                if cap and cap not in mapping["parameters"]:
                    mapping["parameters"][cap] = cap
        else:
            for cf in ds.get("calculated_fields", []):
                cap = cf.get("caption", "")
                if cap and cap not in mapping["formulas"]:
                    mapping["formulas"][cap] = cap

    save_name_mapping(output_dir, mapping)


def update_name_mapping_from_model(filepath: Path, twb_path: str, output_dir: str) -> None:
    """Update name_mapping.json from a written model TML."""
    from ts_cli.commands.tableau_parse import parse_twb

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return

    twb_data = parse_twb(twb_path)
    mapping = load_name_mapping(output_dir)

    twb_captions: dict[str, str] = {}
    for ds in twb_data.get("datasources", []):
        if ds.get("is_parameters"):
            for p in ds.get("parameters", []):
                cap = p.get("caption", "")
                if cap:
                    twb_captions[cap.lower()] = cap
                    twb_captions[cap.lower().replace(" ", "")] = cap
        else:
            for cf in ds.get("calculated_fields", []):
                cap = cf.get("caption", "")
                if cap:
                    twb_captions[cap.lower()] = cap
                    twb_captions[cap.lower().replace(" ", "")] = cap
            for pc in ds.get("physical_columns", []):
                name = pc.get("name", "")
                if name:
                    twb_captions[name.lower()] = name
                    twb_captions[name.lower().replace(" ", "")] = name

    def find_twb_name(ts_name: str) -> str:
        return (
            twb_captions.get(ts_name.lower())
            or twb_captions.get(ts_name.lower().replace(" ", ""))
            or ts_name
        )

    model = tml.get("model", {})
    for formula in model.get("formulas") or []:
        if isinstance(formula, dict) and formula.get("name"):
            twb_name = find_twb_name(formula["name"])
            mapping["formulas"][twb_name] = formula["name"]

    for col in model.get("columns") or []:
        if isinstance(col, dict) and col.get("name") and "::" not in col["name"]:
            twb_name = find_twb_name(col["name"])
            mapping["columns"][twb_name] = col["name"]

    for param in model.get("parameters") or []:
        if isinstance(param, dict) and param.get("name"):
            twb_name = find_twb_name(param["name"])
            mapping["parameters"][twb_name] = param["name"]

    save_name_mapping(output_dir, mapping)


def _sanitize_formula_id(name: str) -> str:
    """Mirror tableau_generate._sanitize_formula_id for consistent IDs."""
    fid = re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_')
    if not fid or fid[0].isdigit():
        fid = 'f_' + fid
    return fid


def apply_name_mapping_to_all_models(output_dir: str) -> int:
    """Fix stale formula_id and [formula_X] cross-references in all model TMLs."""
    mapping = load_name_mapping(output_dir)
    formula_map = mapping.get("formulas", {})
    if not formula_map:
        return 0

    id_renames: dict[str, str] = {}
    for twb_name, ts_name in formula_map.items():
        stale_id = f"formula_{twb_name}"
        current_id = f"formula_{_sanitize_formula_id(ts_name)}"
        if stale_id != current_id:
            id_renames[stale_id] = current_id
            for variant in (
                f"formula_{twb_name.lower()}",
                f"formula_{twb_name.lower().replace(' ', '_')}",
                f"formula_{twb_name.lower().replace(' ', '')}",
            ):
                if variant != current_id:
                    id_renames[variant] = current_id

    if not id_renames:
        return 0

    changed_count = 0
    for model_file in Path(output_dir).glob("*.model.tml"):
        try:
            content = model_file.read_text(encoding="utf-8")
            tml = yaml.safe_load(content)
            if not isinstance(tml, dict) or "model" not in tml:
                continue

            model = tml["model"]
            changed = False

            for col in model.get("columns") or []:
                if isinstance(col, dict):
                    fid = col.get("formula_id", "")
                    if fid and fid in id_renames:
                        col["formula_id"] = id_renames[fid]
                        changed = True

            physical_col_names: set[str] = set()
            for col in model.get("columns") or []:
                if isinstance(col, dict) and not col.get("formula_id"):
                    cid = col.get("column_id", "")
                    if "::" in cid:
                        physical_col_names.add(cid.split("::")[-1])
                    name = col.get("name", "")
                    if name:
                        physical_col_names.add(name)

            param_names: set[str] = {
                p["name"] for p in (model.get("parameters") or [])
                if isinstance(p, dict) and p.get("name")
            }

            cur_fmap = load_name_mapping(output_dir).get("formulas", {})
            for formula in model.get("formulas") or []:
                if not isinstance(formula, dict):
                    continue
                expr = formula.get("expr", "")
                if not expr:
                    continue
                new_expr = expr
                for stale_id, current_id in id_renames.items():
                    stale_ref = f"[{stale_id}]"
                    current_ref = f"[{current_id}]"
                    if stale_ref.lower() in new_expr.lower():
                        new_expr = re.sub(
                            re.escape(stale_ref), current_ref, new_expr, flags=re.IGNORECASE
                        )
                for twb_n, ts_n in cur_fmap.items():
                    correct_ref = f"[formula_{_sanitize_formula_id(ts_n)}]"
                    pattern = r"(?<!\bformula_)\[" + re.escape(twb_n) + r"\]"
                    if re.search(pattern, new_expr, flags=re.IGNORECASE):
                        def _safe_replace(m, _param_names=param_names, _phys=physical_col_names, _ref=correct_ref):
                            bare = m.group(0)[1:-1]
                            if bare in _phys or bare in _param_names:
                                return m.group(0)
                            return _ref
                        new_expr = re.sub(pattern, _safe_replace, new_expr, flags=re.IGNORECASE)
                if new_expr != expr:
                    formula["expr"] = new_expr
                    changed = True

            if changed:
                model_file.write_text(
                    yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
                    encoding="utf-8",
                )
                changed_count += 1
        except Exception:
            continue

    return changed_count


def format_name_mapping(output_dir: str) -> str:
    """Return a formatted string of the current name mapping."""
    mapping = load_name_mapping(output_dir)
    formulas = mapping.get("formulas", {})
    columns = mapping.get("columns", {})
    parameters = mapping.get("parameters", {})
    if not formulas and not columns and not parameters:
        return ""

    lines = ["## Current ThoughtSpot Name Mapping", ""]
    if formulas:
        lines.append("### Formulas  (formula_id = formula_<TS Name>)")
        lines.append(f"{'Tableau Name':<40}  {'ThoughtSpot Name'}")
        lines.append("-" * 70)
        for twb, ts in sorted(formulas.items()):
            marker = "  <- RENAMED" if twb != ts else ""
            lines.append(f"{twb:<40}  {ts}{marker}")
        lines.append("")
    if columns:
        lines.append("### Columns")
        lines.append(f"{'Tableau Name':<40}  {'ThoughtSpot Name'}")
        lines.append("-" * 70)
        for twb, ts in sorted(columns.items()):
            marker = "  <- RENAMED" if twb != ts else ""
            lines.append(f"{twb:<40}  {ts}{marker}")
        lines.append("")
    if parameters:
        lines.append("### Parameters")
        lines.append(f"{'Tableau Name':<40}  {'ThoughtSpot Name'}")
        lines.append("-" * 70)
        for twb, ts in sorted(parameters.items()):
            marker = "  <- RENAMED" if twb != ts else ""
            lines.append(f"{twb:<40}  {ts}{marker}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQL registry (for sql_view name fixing)
# ---------------------------------------------------------------------------

def build_twb_sql_registry(twb_path: str, output_dir: str) -> None:
    """Build and persist a TWB-authoritative registry mapping SQL → source name."""
    from ts_cli.commands.tableau_parse import parse_twb

    registry_path = Path(output_dir) / _TWB_SQL_REGISTRY_FILE
    if registry_path.exists():
        return

    twb_data = parse_twb(twb_path)
    all_datasources = [
        ds for ds in twb_data.get("datasources", [])
        if not ds.get("is_sqlproxy") and not ds.get("is_parameters")
    ]

    sql_name_ds_count: dict[str, int] = {}
    for ds in all_datasources:
        seen: set[str] = set()
        for src in ds.get("custom_sql_sources", []):
            n = _norm_name(src.get("name", ""))
            if n and n not in seen:
                sql_name_ds_count[n] = sql_name_ds_count.get(n, 0) + 1
                seen.add(n)

    registry: dict[str, dict] = {}
    for ds in all_datasources:
        ds_name = ds.get("caption") or ds.get("name", "")
        for src in ds.get("custom_sql_sources", []):
            src_name = src.get("name", "")
            sql_query = src.get("sql_query", "")
            if not src_name or not sql_query:
                continue
            collision = sql_name_ds_count.get(_norm_name(src_name), 1) > 1
            target_name = f"{ds_name}_{src_name}" if collision else src_name
            registry[_norm_sql(sql_query)] = {
                "ds_name": ds_name,
                "sql_source_name": src_name,
                "target_name": target_name,
                "sql_view_file": None,
            }

    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Table TML fixes
# ---------------------------------------------------------------------------

def fix_table_tml_logical_name(filepath: Path, twb_path: str) -> bool:
    """Align a table TML's logical name and column names to TWB relation names."""
    from ts_cli.commands.tableau_parse import parse_twb

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "table" not in tml:
        return False

    current_name = tml["table"].get("name", "")
    if not current_name:
        return False

    twb_data = parse_twb(twb_path)
    twb_rel_name = None
    twb_col_map: dict[str, str] = {}
    for ds in twb_data.get("datasources", []):
        for tbl in ds.get("tables", []):
            rel_name = tbl.get("relation_name", "")
            if rel_name and _norm_name(rel_name) == _norm_name(current_name):
                twb_rel_name = rel_name
                for pc in ds.get("physical_columns", []):
                    if pc.get("parent_table") == rel_name:
                        col_name = pc.get("name", "")
                        if col_name:
                            twb_col_map[_norm_name(col_name)] = col_name
                break
        if twb_rel_name:
            break

    if not twb_rel_name:
        return False

    changed = False
    if twb_rel_name != current_name:
        tml["table"]["name"] = twb_rel_name
        changed = True

    if twb_col_map:
        for col in tml["table"].get("columns") or []:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name", "")
            if col_name:
                twb_col = twb_col_map.get(_norm_name(col_name))
                if twb_col and twb_col != col_name:
                    col["name"] = twb_col
                    changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


# ---------------------------------------------------------------------------
# SQL view TML fixes
# ---------------------------------------------------------------------------

def fix_sql_view_tml_logical_name(filepath: Path, twb_path: str) -> bool:
    """Fix a sql_view TML's name using the TWB SQL registry."""
    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "sql_view" not in tml:
        return False

    current_name = tml["sql_view"].get("name", "")
    sql_query = tml["sql_view"].get("sql_query", "")
    if not current_name or not sql_query:
        return False

    registry_path = filepath.parent / _TWB_SQL_REGISTRY_FILE
    if not registry_path.exists():
        return False

    registry: dict[str, dict] = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry.get(_norm_sql(sql_query))
    if not entry:
        norm_current = _norm_name(current_name)
        for reg_entry in registry.values():
            if _norm_name(reg_entry["target_name"]) == norm_current:
                entry = reg_entry
                break
        if not entry:
            return False

    target_name = entry["target_name"]
    if entry.get("sql_view_file") != filepath.name:
        entry["sql_view_file"] = filepath.name
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    if target_name == current_name:
        return False

    old_name = current_name
    tml["sql_view"]["name"] = target_name
    filepath.write_text(
        yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
        encoding="utf-8",
    )
    _propagate_sql_view_rename_to_models(filepath.parent, old_name, target_name)
    return True


def _propagate_sql_view_rename_to_models(output_dir: Path, old_name: str, new_name: str) -> None:
    """Update formula column refs in model TMLs after a sql_view name change."""
    col_pattern = re.compile(re.escape(old_name) + r"::")
    name_pattern = re.compile(r"(?<!\w)" + re.escape(old_name) + r"(?!\w)")
    for model_path in output_dir.glob("*.model.tml"):
        try:
            content = model_path.read_text(encoding="utf-8")
            new_content = col_pattern.sub(new_name + "::", content)
            new_content = name_pattern.sub(new_name, new_content)
            if new_content != content:
                model_path.write_text(new_content, encoding="utf-8")
        except Exception:
            continue


def _to_upper_snake(name: str) -> str:
    """Convert a display name to UPPER_SNAKE_CASE (e.g. 'Sales Person' → 'SALES_PERSON')."""
    return re.sub(r"\s+", "_", name.strip()).upper()


def normalize_db_identifiers(filepath: Path) -> bool:
    """Convert db_table and db_column_name values to UPPER_SNAKE_CASE in table TMLs."""
    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "table" not in tml:
        return False

    table = tml["table"]
    changed = False

    db_table = table.get("db_table")
    if db_table:
        normalized = _to_upper_snake(db_table)
        if normalized != db_table:
            table["db_table"] = normalized
            changed = True

    for col in table.get("columns") or []:
        if not isinstance(col, dict):
            continue
        db_col = col.get("db_column_name")
        if db_col:
            normalized = _to_upper_snake(db_col)
            if normalized != db_col:
                col["db_column_name"] = normalized
                changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


# ---------------------------------------------------------------------------
# Model TML fixes
# ---------------------------------------------------------------------------

def fix_model_tml_joins(filepath: Path, twb_path: str) -> bool:
    """Fill in missing join on fields from TWB join conditions."""
    from ts_cli.commands.tableau_parse import parse_twb

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    def _norm_table(name: str) -> str:
        return name.strip().upper().replace(" ", "").replace("_", "")

    def _extract_col_pair(clause: str) -> tuple[str, str]:
        m = re.findall(r"\[[^\]]+\]\.\[([^\]]+)\]", clause)
        if len(m) == 2:
            return m[0], m[1]
        m = re.findall(r"\[([^\]()]+)(?:\s*\([^\)]*\))?\]", clause)
        if len(m) >= 2:
            return m[0].strip(), m[1].strip()
        return "", ""

    twb_join_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    try:
        twb_data = parse_twb(twb_path)
        for ds in twb_data.get("datasources", []):
            for j in ds.get("joins", []):
                lt = _norm_table(j.get("left_table") or "")
                rt = _norm_table(j.get("right_table") or "")
                on = (j.get("on_clause") or "").strip()
                if lt and rt and on:
                    left_col, right_col = _extract_col_pair(on)
                    if left_col and right_col:
                        twb_join_lookup[(lt, rt)] = (left_col, right_col)
                        twb_join_lookup[(rt, lt)] = (right_col, left_col)
    except Exception:
        return False

    model = tml["model"]
    changed = False

    _VALID_JOIN_KEYS = {"with", "on", "type", "cardinality", "referencing_join"}
    for table in model.get("model_tables") or []:
        if not isinstance(table, dict):
            continue
        for join in (table.get("joins") or []):
            if not isinstance(join, dict):
                continue
            bad_keys = [
                k for k in list(join.keys())
                if not isinstance(k, str) or k not in _VALID_JOIN_KEYS
            ]
            for k in bad_keys:
                del join[k]
                changed = True

    if not twb_join_lookup and not changed:
        return False

    # Build model table → column set for column-based fallback matching
    model_col_sets: dict[str, set[str]] = {}
    for col in model.get("columns", []):
        col_id = col.get("column_id", "")
        if "::" in col_id:
            tbl, c = col_id.rsplit("::", 1)
            model_col_sets.setdefault(tbl.upper(), set()).add(c.upper())

    if twb_join_lookup:
        for table in model.get("model_tables") or []:
            if not isinstance(table, dict):
                continue
            table_name = table.get("name", "")
            for join in table.get("joins") or []:
                if not isinstance(join, dict):
                    continue
                has_on = bool((join.get("on") or "").strip())
                has_ref = bool((join.get("referencing_join") or "").strip())
                if has_on or has_ref:
                    continue
                other = join.get("with", "")
                nt, no = _norm_table(table_name), _norm_table(other)
                col_pair = twb_join_lookup.get((nt, no))
                if not col_pair:
                    for (lt, rt), pair in twb_join_lookup.items():
                        if (lt.startswith(nt) or nt.startswith(lt)) and \
                           (rt.startswith(no) or no.startswith(rt)):
                            col_pair = pair
                            break
                if not col_pair:
                    left_cols = model_col_sets.get(table_name.upper(), set())
                    right_cols = model_col_sets.get(other.upper(), set())
                    if left_cols and right_cols:
                        candidates: set[tuple[str, str]] = set()
                        for (_lt, _rt), (lc, rc) in twb_join_lookup.items():
                            if lc.upper() in left_cols and rc.upper() in right_cols:
                                candidates.add((lc, rc))
                            elif rc.upper() in left_cols and lc.upper() in right_cols:
                                candidates.add((rc, lc))
                        if len(candidates) == 1:
                            col_pair = candidates.pop()
                if col_pair:
                    left_col, right_col = col_pair
                    join["on"] = f"[{table_name}::{left_col}] = [{other}::{right_col}]"
                    changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def fix_model_tml_column_names(filepath: Path, twb_path: str) -> bool:
    """Restore exact column/formula display names from the TWB."""
    from ts_cli.commands.tableau_parse import parse_twb

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    twb_data = parse_twb(twb_path)
    twb_lookup: dict[str, str] = {}
    for ds in twb_data.get("datasources", []):
        if ds.get("is_parameters"):
            continue
        for pc in ds.get("physical_columns", []):
            name = pc["name"]
            twb_lookup[name.lower()] = name
            twb_lookup[name.lower().replace(" ", "")] = name
        for cf in ds.get("calculated_fields", []):
            caption = cf["caption"]
            twb_lookup[caption.lower()] = caption
            twb_lookup[caption.lower().replace(" ", "")] = caption

    if not twb_lookup:
        return False

    def resolve(name: str) -> str:
        return twb_lookup.get(name.lower()) or twb_lookup.get(name.lower().replace(" ", "")) or name

    model = tml.get("model", {})
    changed = False
    formula_id_renames: dict[str, str] = {}

    for formula in model.get("formulas") or []:
        if not isinstance(formula, dict):
            continue
        old_name = formula.get("name", "")
        new_name = resolve(old_name)
        if new_name != old_name:
            old_id = formula.get("id", f"formula_{old_name}")
            new_id = f"formula_{new_name}"
            formula_id_renames[old_id] = new_id
            formula["name"] = new_name
            formula["id"] = new_id
            changed = True

    for col in model.get("columns") or []:
        if not isinstance(col, dict):
            continue
        fid = col.get("formula_id")
        if fid and fid in formula_id_renames:
            col["formula_id"] = formula_id_renames[fid]
            changed = True
        old_name = col.get("name", "")
        new_name = resolve(old_name)
        if new_name != old_name:
            col["name"] = new_name
            changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def inject_parameters_into_model_tml(filepath: Path, twb_path: str) -> bool:
    """Add parameters section from TWB and translate parameter refs in formulas."""
    from ts_cli.commands.tableau_parse import parse_twb, _translate_param_refs

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    twb_data = parse_twb(twb_path)
    parameter_map: dict[str, str] = twb_data.get("parameter_map", {})

    twb_params: list[dict] = []
    for ds in twb_data.get("datasources", []):
        if ds.get("is_parameters"):
            twb_params = ds.get("parameters", [])
            break

    if not twb_params and not parameter_map:
        return False

    _DT_MAP = {
        "string": "CHAR", "integer": "INT64", "real": "DOUBLE", "float": "DOUBLE",
        "date": "DATE", "datetime": "DATE_TIME", "boolean": "BOOL", "bool": "BOOL",
    }

    changed = False
    model = tml["model"]

    if twb_params:
        built_params = []
        for p in twb_params:
            caption = p.get("caption", "")
            if not caption:
                continue
            ts_dt = _DT_MAP.get(p.get("datatype", "string").lower(), "CHAR")
            raw_default = str(p.get("current_value", ""))
            while (
                (raw_default.startswith('"') and raw_default.endswith('"'))
                or (raw_default.startswith("'") and raw_default.endswith("'"))
            ) and len(raw_default) >= 2:
                raw_default = raw_default[1:-1]
            entry: dict = {
                "id": str(uuid.uuid4()),
                "name": caption,
                "data_type": ts_dt,
                "default_value": raw_default,
                "description": "",
            }
            domain = p.get("domain_type", "any")
            if domain == "list" and p.get("allowed_values"):
                entry["list_config"] = {
                    "list_choice": [
                        {"value": str(v["value"]), **({"display_name": v["display_name"]} if v.get("display_name") else {})}
                        for v in p["allowed_values"]
                    ]
                }
            elif domain == "range" and p.get("range"):
                r = p["range"]
                entry["range_config"] = {
                    "range_min": str(r["min"]),
                    "range_max": str(r["max"]),
                    "include_min": True,
                    "include_max": True,
                }
            built_params.append(entry)

        if built_params:
            ref_parts: list[str] = []
            for _f in model.get("formulas") or []:
                if isinstance(_f, dict):
                    ref_parts.append(str(_f.get("expr", "")))
            for _c in model.get("columns") or []:
                ref_parts.append(json.dumps(_c, default=str))
            ref_blob = " ".join(ref_parts)
            scoped_params = [
                bp for bp in built_params if f"[{bp['name']}]" in ref_blob
            ]
            if scoped_params:
                model["parameters"] = scoped_params
            elif "parameters" in model:
                del model["parameters"]
            changed = True

    if parameter_map:
        for formula in model.get("formulas") or []:
            if not isinstance(formula, dict):
                continue
            old_expr = formula.get("expr", "")
            new_expr = _translate_param_refs(old_expr, parameter_map)
            if new_expr != old_expr:
                formula["expr"] = new_expr
                changed = True

    if twb_params:
        param_captions = {p["caption"] for p in twb_params if p.get("caption")}
        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", (s or "").lower())

        model_norm = _norm(model.get("name", ""))
        owning_ds = None
        for _ds in twb_data.get("datasources", []):
            if _ds.get("is_parameters") or _ds.get("is_sqlproxy"):
                continue
            if _norm(_ds.get("caption") or _ds.get("name")) == model_norm:
                owning_ds = _ds
                break
        twb_formula_map: dict[str, str] = {}
        if owning_ds is not None:
            for _cf in owning_ds.get("calculated_fields", []):
                _cap = _cf.get("caption", "")
                _expr = _cf.get("formula", "")
                if _cap and any(f"[{c}]" in _expr for c in param_captions):
                    twb_formula_map[_cap] = _expr

        for formula in model.get("formulas") or []:
            if not isinstance(formula, dict):
                continue
            fname = formula.get("name", "")
            twb_expr = twb_formula_map.get(fname)
            if not twb_expr:
                continue
            current_expr = formula.get("expr", "")
            missing = [
                c for c in param_captions
                if f"[{c}]" in twb_expr and f"[{c}]" not in current_expr
            ]
            if missing:
                formula["expr"] = twb_expr
                changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def translate_formula_refs_in_model_tml(filepath: Path, twb_path: str) -> bool:
    """Translate remaining [Calculation_*] refs to [formula_<caption>] in model TML."""
    from ts_cli.commands.tableau_parse import parse_twb, _translate_formula_refs, _translate_tableau_to_ts_functions

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    twb_data = parse_twb(twb_path)
    formula_column_map: dict[str, str] = twb_data.get("formula_column_map", {})

    model = tml["model"]
    changed = False

    for formula in model.get("formulas") or []:
        if not isinstance(formula, dict):
            continue
        old_expr = formula.get("expr", "")
        new_expr = old_expr
        if formula_column_map:
            new_expr = _translate_formula_refs(new_expr, formula_column_map)
        new_expr = _translate_tableau_to_ts_functions(new_expr)
        new_expr = re.sub(
            r'(?<!\[)\bformula_([\w]+(?:\s[\w]+)*)',
            r'[formula_\1]',
            new_expr,
        )
        if new_expr != old_expr:
            formula["expr"] = new_expr
            changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def fix_model_table_references(filepath: Path, output_dir: str) -> bool:
    """Align model_tables names and column_id references to actual table/sql_view TMLs."""
    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    output_path = Path(output_dir)
    actual_objects: dict[str, tuple[str, dict[str, str]]] = {}
    for f in list(output_path.glob("*.table.tml")) + list(output_path.glob("*.sql_view.tml")):
        if f == filepath:
            continue
        try:
            obj_tml = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(obj_tml, dict):
                continue
            if "table" in obj_tml:
                name = obj_tml["table"].get("name", "")
                cols = {
                    _norm_name(c.get("name", "")): c.get("name", "")
                    for c in (obj_tml["table"].get("columns") or [])
                    if isinstance(c, dict) and c.get("name")
                }
            elif "sql_view" in obj_tml:
                name = obj_tml["sql_view"].get("name", "")
                cols = {
                    _norm_name(c.get("name", "")): c.get("name", "")
                    for c in (obj_tml["sql_view"].get("sql_view_columns") or [])
                    if isinstance(c, dict) and c.get("name")
                }
            else:
                continue
            if name:
                actual_objects[_norm_name(name)] = (name, cols)
        except Exception:
            continue

    if not actual_objects:
        return False

    model = tml["model"]
    changed = False
    model_stem_norm = _norm_name(filepath.name.replace(".model.tml", ""))

    def _resolve_table(ref: str):
        norm_ref = _norm_name(ref)
        match = actual_objects.get(norm_ref)
        if match:
            return match
        suffix_candidates = [
            (norm_key, actual_objects[norm_key])
            for norm_key in actual_objects
            if (norm_key.endswith(norm_ref) or norm_ref.endswith(norm_key))
            and norm_key != norm_ref
        ]
        if not suffix_candidates:
            return None
        for norm_key, candidate in suffix_candidates:
            if norm_key.startswith(model_stem_norm):
                return candidate
        return suffix_candidates[0][1]

    for mt in model.get("model_tables") or []:
        if not isinstance(mt, dict):
            continue
        ref = mt.get("name", "")
        if not ref:
            continue
        match = _resolve_table(ref)
        if match and match[0] != ref:
            mt["name"] = match[0]
            changed = True

    for col in model.get("columns") or []:
        if not isinstance(col, dict):
            continue
        col_id = col.get("column_id", "")
        if not col_id or "::" not in col_id:
            continue
        table_part, col_part = col_id.split("::", 1)
        match = _resolve_table(table_part)
        if not match:
            continue
        new_table, col_lookup = match
        new_col = col_lookup.get(_norm_name(col_part), col_part)
        new_col_id = f"{new_table}::{new_col}"
        if new_col_id != col_id:
            col["column_id"] = new_col_id
            changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def fix_formula_column_refs(filepath: Path) -> bool:
    """No-op — preserve TABLE::COL qualification in formula exprs.

    Keeping qualified refs is always safe and prevents ambiguity errors
    (ThoughtSpot error 14516) if a second table is added to the model later.
    """
    return False


def inject_model_obj_ids(filepath: Path, output_dir: str) -> bool:
    """Inject obj_id into every model_tables entry and add top-level guid/obj_id."""
    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    output_path = Path(output_dir)
    obj_id_lookup: dict[str, str] = {}
    for f in list(output_path.glob("*.table.tml")) + list(output_path.glob("*.sql_view.tml")):
        try:
            other = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(other, dict):
                continue
            top_obj_id = other.get("obj_id", "")
            if "table" in other:
                name = other["table"].get("name", "")
            elif "sql_view" in other:
                name = other["sql_view"].get("name", "")
            else:
                continue
            if name and top_obj_id:
                obj_id_lookup[_norm_name(name)] = top_obj_id
        except Exception:
            continue

    model = tml["model"]
    changed = False

    def _resolve_obj_id(ref_name: str):
        norm_ref = _norm_name(ref_name)
        hit = obj_id_lookup.get(norm_ref)
        if hit:
            return hit
        candidates = [
            obj_id_lookup[k] for k in obj_id_lookup
            if (k.endswith(norm_ref) or norm_ref.endswith(k)) and k != norm_ref
        ]
        return candidates[0] if len(candidates) == 1 else None

    for mt in model.get("model_tables") or []:
        if not isinstance(mt, dict):
            continue
        ref_name = mt.get("name", "")
        found_obj_id = _resolve_obj_id(ref_name)
        if found_obj_id:
            current = mt.get("obj_id", "")
            if current != found_obj_id:
                mt["obj_id"] = found_obj_id
                changed = True

    if "guid" not in tml:
        model_guid = str(uuid.uuid4())
        safe_stem = re.sub(r"\s+", "_", filepath.stem.replace(".model", ""))
        model_obj_id = f"{safe_stem}-{model_guid.split('-')[0]}"
        new_tml: dict = {"guid": model_guid, "obj_id": model_obj_id}
        new_tml.update(tml)
        tml = new_tml
        changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )
    return changed


def strip_invalid_identifiers(filepath: Path) -> bool:
    """Remove guid at root and fqn from model_tables — both break fresh imports."""
    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict):
        return False

    changed = False

    if "guid" in tml:
        del tml["guid"]
        changed = True

    obj_key = None
    for key in ("model", "table", "liveboard", "answer"):
        if key in tml and isinstance(tml[key], dict):
            obj_key = key
            break
    if not obj_key:
        return changed

    obj = tml[obj_key]

    if "guid" in obj:
        del obj["guid"]
        changed = True

    for tbl in obj.get("model_tables") or []:
        if isinstance(tbl, dict) and "fqn" in tbl:
            del tbl["fqn"]
            changed = True

    if changed:
        filepath.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
            encoding="utf-8",
        )

    return changed


def deduplicate_model_tml(filepath: Path, twb_path: str | None = None) -> bool:
    """Normalize a model TML: collapse duplicate keys and remove duplicate list entries."""
    from ts_cli.commands.tableau_parse import parse_twb

    content = filepath.read_text(encoding="utf-8")
    tml = yaml.safe_load(content)
    if not isinstance(tml, dict) or "model" not in tml:
        return False

    model = tml["model"]
    changed = False

    cols = model.get("columns")
    if isinstance(cols, list):
        seen_fids: set[str] = set()
        deduped: list = []
        for col in cols:
            if not isinstance(col, dict):
                deduped.append(col)
                continue
            fid = col.get("formula_id", "")
            if fid:
                if fid in seen_fids:
                    changed = True
                    continue
                seen_fids.add(fid)
            deduped.append(col)
        if changed:
            model["columns"] = deduped

    formulas = model.get("formulas")
    if isinstance(formulas, list):
        seen_ids: set[str] = set()
        deduped_f: list = []
        for formula in formulas:
            if not isinstance(formula, dict):
                deduped_f.append(formula)
                continue
            fid = formula.get("id", "")
            if fid:
                if fid in seen_ids:
                    changed = True
                    continue
                seen_ids.add(fid)
            deduped_f.append(formula)
        if len(deduped_f) != len(formulas or []):
            model["formulas"] = deduped_f
            changed = True

    tables = model.get("model_tables")
    if isinstance(tables, list):
        seen_names: set[str] = set()
        deduped_t: list = []
        for tbl in tables:
            if not isinstance(tbl, dict):
                deduped_t.append(tbl)
                continue
            if "connection" in tbl and tbl.get("connection") is None:
                del tbl["connection"]
                changed = True
            name = tbl.get("name", "")
            if not name:
                changed = True
                continue
            if name in seen_names:
                changed = True
                continue
            seen_names.add(name)
            deduped_t.append(tbl)
        if len(deduped_t) != len(tables):
            model["model_tables"] = deduped_t
            changed = True

    param_names: set[str] = {
        str(p.get("name", "")) for p in (model.get("parameters") or []) if p.get("name")
    }
    if twb_path and not param_names:
        try:
            twb_data = parse_twb(twb_path)
            for ds in twb_data.get("datasources", []):
                if ds.get("is_parameters"):
                    for p in ds.get("parameters", []):
                        if p.get("caption"):
                            param_names.add(p["caption"])
                    break
        except Exception:
            pass

    if param_names:
        formula_renames: dict[str, str] = {}
        for col in model.get("columns") or []:
            if isinstance(col, dict) and col.get("name", "") in param_names:
                col["name"] = col["name"] + " Value"
                changed = True
        for formula in model.get("formulas") or []:
            if not isinstance(formula, dict):
                continue
            fname = formula.get("name", "")
            if fname in param_names:
                new_name = fname + " Value"
                old_id = formula.get("id", f"formula_{fname}")
                new_id = f"formula_{new_name}"
                formula["name"] = new_name
                formula["id"] = new_id
                formula_renames[old_id] = new_id
                changed = True
        if formula_renames:
            for col in model.get("columns") or []:
                if isinstance(col, dict):
                    fid = col.get("formula_id", "")
                    if fid in formula_renames:
                        col["formula_id"] = formula_renames[fid]
                    if col.get("name", "") in param_names:
                        col["name"] = col["name"] + " Value"
            for formula in model.get("formulas") or []:
                if not isinstance(formula, dict):
                    continue
                expr = formula.get("expr", "")
                for old_id, new_id in formula_renames.items():
                    expr = re.sub(re.escape(f"[{old_id}]"), f"[{new_id}]", expr, flags=re.IGNORECASE)
                formula["expr"] = expr

    filepath.write_text(
        yaml.dump(tml, default_flow_style=False, allow_unicode=True, Dumper=_NoAliasDumper, width=9999),
        encoding="utf-8",
    )
    return changed


# ---------------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------------

def local_cross_reference_check(tml_files: list[Path]) -> list[str]:
    """Validate cross-references within the TML set."""
    errors: list[str] = []
    available_objects: dict[str, str] = {}
    object_columns: dict[str, list[str]] = {}

    for f in tml_files:
        try:
            obj = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                continue
            if "table" in obj:
                name = obj["table"].get("name", "")
                cols = [c.get("name", "") for c in (obj["table"].get("columns") or []) if c.get("name")]
            elif "sql_view" in obj:
                name = obj["sql_view"].get("name", "")
                cols = [c.get("name", "") for c in (obj["sql_view"].get("sql_view_columns") or []) if c.get("name")]
            else:
                continue
            if name:
                available_objects[name] = f.name
                object_columns[name] = cols
        except Exception:
            continue

    for f in tml_files:
        try:
            obj = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(obj, dict) or "model" not in obj:
                continue
            model = obj["model"]
            model_name = model.get("name", f.name)

            for mt in model.get("model_tables") or []:
                if isinstance(mt, dict):
                    ref = mt.get("name", "")
                    if ref and ref not in available_objects:
                        errors.append(
                            f"Model '{model_name}': model_tables references '{ref}' "
                            f"but no table/sql_view with that name exists. "
                            f"Available: {sorted(available_objects.keys())}"
                        )

            for col in model.get("columns") or []:
                if not isinstance(col, dict):
                    continue
                col_id = col.get("column_id", "")
                if not col_id or "::" not in col_id:
                    continue
                table_part, col_part = col_id.split("::", 1)
                if table_part not in available_objects:
                    errors.append(
                        f"Model '{model_name}': column_id '{col_id}' references "
                        f"table '{table_part}' which doesn't exist. "
                        f"Available: {sorted(available_objects.keys())}"
                    )
                elif col_part not in object_columns.get(table_part, []):
                    errors.append(
                        f"Model '{model_name}': column_id '{col_id}' — table "
                        f"'{table_part}' has no column '{col_part}'. "
                        f"Available: {object_columns.get(table_part, [])}"
                    )
        except Exception:
            continue

    return errors


# ---------------------------------------------------------------------------
# Orchestrator — run_postprocess
# ---------------------------------------------------------------------------

def run_postprocess(directory: str, twb_path: str) -> dict:
    """Run all postprocess operations on TML files in directory.

    Returns a report dict with counts of fixes applied and any errors.
    """
    output_dir = directory
    output_path = Path(output_dir)
    report: dict = {"fixes": [], "errors": [], "files_changed": set()}

    def _note(fix_type: str, filepath: Path, detail: str = ""):
        msg = f"{fix_type}: {filepath.name}"
        if detail:
            msg += f" — {detail}"
        report["fixes"].append(msg)
        report["files_changed"].add(filepath.name)

    # Phase 0: Pre-assign name mapping and build SQL registry
    try:
        preassign_formula_name_mapping(twb_path, output_dir)
        report["fixes"].append("name_mapping: pre-assigned from TWB")
    except Exception as e:
        report["errors"].append(f"name_mapping pre-assign failed: {e}")

    try:
        build_twb_sql_registry(twb_path, output_dir)
        report["fixes"].append("sql_registry: built from TWB")
    except Exception as e:
        report["errors"].append(f"sql_registry build failed: {e}")

    # Phase 1: Fix sql_view TMLs
    for sv_file in sorted(output_path.glob("*.sql_view.tml")):
        try:
            if fix_sql_view_tml_logical_name(sv_file, twb_path):
                _note("sql_view_name_fix", sv_file)
        except Exception as e:
            report["errors"].append(f"sql_view_name_fix {sv_file.name}: {e}")

        # sanitize_sql_quoted_identifiers removed: sql_query contains raw SQL
        # for the target warehouse and must not be rewritten. The TWB column
        # mappings use bracket notation which is invalid SQL.

    # Phase 2: Fix table TMLs
    for tbl_file in sorted(output_path.glob("*.table.tml")):
        try:
            if fix_table_tml_logical_name(tbl_file, twb_path):
                _note("table_name_fix", tbl_file)
        except Exception as e:
            report["errors"].append(f"table_name_fix {tbl_file.name}: {e}")

        try:
            if normalize_db_identifiers(tbl_file):
                _note("db_identifier_normalize", tbl_file)
        except Exception as e:
            report["errors"].append(f"db_identifier_normalize {tbl_file.name}: {e}")

    # Phase 3: Fix model TMLs (order matters)
    for mdl_file in sorted(output_path.glob("*.model.tml")):
        try:
            if fix_model_tml_joins(mdl_file, twb_path):
                _note("join_fix", mdl_file)
        except Exception as e:
            report["errors"].append(f"join_fix {mdl_file.name}: {e}")

        try:
            if fix_model_tml_column_names(mdl_file, twb_path):
                _note("column_name_fix", mdl_file)
        except Exception as e:
            report["errors"].append(f"column_name_fix {mdl_file.name}: {e}")

        try:
            if inject_parameters_into_model_tml(mdl_file, twb_path):
                _note("parameter_inject", mdl_file)
        except Exception as e:
            report["errors"].append(f"parameter_inject {mdl_file.name}: {e}")

        try:
            if translate_formula_refs_in_model_tml(mdl_file, twb_path):
                _note("formula_ref_translate", mdl_file)
        except Exception as e:
            report["errors"].append(f"formula_ref_translate {mdl_file.name}: {e}")

        try:
            if fix_model_table_references(mdl_file, output_dir):
                _note("table_ref_fix", mdl_file)
        except Exception as e:
            report["errors"].append(f"table_ref_fix {mdl_file.name}: {e}")

        try:
            if fix_formula_column_refs(mdl_file):
                _note("formula_col_ref_fix", mdl_file)
        except Exception as e:
            report["errors"].append(f"formula_col_ref_fix {mdl_file.name}: {e}")

        try:
            if strip_invalid_identifiers(mdl_file):
                _note("strip_guid_fqn", mdl_file)
        except Exception as e:
            report["errors"].append(f"strip_guid_fqn {mdl_file.name}: {e}")

        try:
            if inject_model_obj_ids(mdl_file, output_dir):
                _note("obj_id_inject", mdl_file)
        except Exception as e:
            report["errors"].append(f"obj_id_inject {mdl_file.name}: {e}")

        try:
            update_name_mapping_from_model(mdl_file, twb_path, output_dir)
        except Exception:
            pass

        try:
            if deduplicate_model_tml(mdl_file, twb_path):
                _note("dedup", mdl_file)
        except Exception as e:
            report["errors"].append(f"dedup {mdl_file.name}: {e}")

    # Phase 4: Apply name mapping cross-refs across all models
    try:
        n = apply_name_mapping_to_all_models(output_dir)
        if n:
            report["fixes"].append(f"name_mapping_apply: updated {n} model file(s)")
    except Exception as e:
        report["errors"].append(f"name_mapping_apply: {e}")

    # Phase 5: Cross-reference check
    all_tml_files = sorted(output_path.glob("*.tml"))
    xref_errors = local_cross_reference_check(all_tml_files)
    report["cross_ref_errors"] = xref_errors

    report["files_changed"] = sorted(report["files_changed"])
    return report
