"""Pure helpers behind `ts snowflake diff` and `ts snowflake lint-ddl` (no I/O).

Codifies logic that both Snowflake conversion skills previously duplicated as inline
Python in their SKILL.md files (BL-063 codification quick wins, 2026-07-03 audit rows
3 & 4):

- `ts-convert-to-snowflake-sv` Step 9.5C (Mode C diff) — compared generated SV columns
  against the existing SV, using SQL-expression normalisation that stashed
  double-quoted identifiers.
- `ts-convert-from-snowflake-sv` Step C3 (Mode C diff) — compared a ThoughtSpot Model's
  existing columns against the SV's translated columns, using the SAME normalisation
  shape but stashing ThoughtSpot formula bracket/brace references instead.

`normalise_expr`/`exprs_differ`/`compute_change_set` unify both call sites: the stash
pattern now covers BOTH quoted-identifier and bracket/brace tokens, so the same
function works whether the two expressions being compared are SQL (to-side) or
ThoughtSpot formula text (from-side). The two skills still do their own translation
(SV SQL -> ThoughtSpot formula) *before* calling this — that step is a judgment call
that stays in the skill; this module only compares whatever expression text it is given.

`lint_sv_ddl` codifies the deterministic subset of the to-skill's Step 11 DDL
checklist — the structural checks with no semantic judgment involved. See the
docstring on that function for exactly which checklist items are covered.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# normalise_expr / exprs_differ / compute_change_set
# ---------------------------------------------------------------------------

# Stashes BOTH double-quoted SQL identifiers ("Date") AND ThoughtSpot formula
# bracket/brace references ([Column Name], {Parameter}) so the combined function
# works for SQL expressions (to-side) and ThoughtSpot formula text (from-side) alike.
_STASH_RE = re.compile(r'"[^"]*"|\[[^\]]+\]|\{[^}]+\}')


def normalise_expr(expr: str) -> str:
    """Normalise an expression for equality comparison only — never use the output
    as actual SQL or formula text.

    Stashes quoted-identifier and bracket/brace tokens before whitespace-collapsing
    and lowercasing the rest, then restores the stashed tokens verbatim (unchanged
    case) so identifiers that are legitimately case-sensitive — a double-quoted SQL
    column, a ThoughtSpot `[Column Name]` reference — survive the lowering intact.

    The placeholder key is deliberately already-lowercase (`__normrefN__`) so that
    lowercasing the rest of the string never changes it — the original inline
    SKILL.md versions of this helper used an uppercase `__REFN__` placeholder, which
    `.lower()` then silently mangled, so the "restore" loop never matched and the
    stashed text stayed masked forever. Fixed here since this now has real test
    coverage instead of living as inline prose.
    """
    refs: dict[str, str] = {}
    counter = 0

    def _stash(m: "re.Match[str]") -> str:
        nonlocal counter
        key = f"__normref{counter}__"
        refs[key] = m.group(0)
        counter += 1
        return key

    out = _STASH_RE.sub(_stash, expr)
    out = re.sub(r"\s+", " ", out.strip()).lower()
    for key, val in refs.items():
        out = out.replace(key, val)
    return out


def exprs_differ(a: str, b: str) -> bool:
    """True if two expressions differ after normalisation."""
    return normalise_expr(a) != normalise_expr(b)


def compute_change_set(
    current: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    *,
    ignore_empty_new_description: bool = False,
) -> dict[str, Any]:
    """Diff two column maps and return a change set.

    `current` and `new` are `{col_name: {"expr": str, "description": str,
    "synonyms": [str, ...]}}` — `description` and `synonyms` are optional per entry.

    Returns:
        new_columns: columns in `new` not in `current` (sorted).
        removed_columns: columns in `current` not in `new` (sorted).
        modified_expressions: [{column, current, new}] where `exprs_differ` is True.
        modified_descriptions: [{column, current, new}] where descriptions differ.
        modified_synonyms: [{column, current, new, added, removed}] — only computed
            for a column when BOTH sides supply a "synonyms" entry; a caller that
            never tracks synonyms (e.g. the to-side diff) naturally gets an empty list.

    `ignore_empty_new_description=True` reproduces the from-side skill's behaviour:
    only flag a description change when the NEW description is non-empty (a blank
    new description is treated as "no opinion", not "clear the field"). The default
    `False` reproduces the to-side behaviour: any difference is flagged, including
    a new description going blank.
    """
    current_cols = set(current.keys())
    new_cols = set(new.keys())

    change_set: dict[str, Any] = {
        "new_columns": sorted(new_cols - current_cols),
        "removed_columns": sorted(current_cols - new_cols),
        "modified_expressions": [],
        "modified_descriptions": [],
        "modified_synonyms": [],
    }

    for col in sorted(current_cols & new_cols):
        cur_entry = current[col] or {}
        new_entry = new[col] or {}

        cur_expr = cur_entry.get("expr", "")
        new_expr = new_entry.get("expr", "")
        if exprs_differ(cur_expr, new_expr):
            change_set["modified_expressions"].append({
                "column": col, "current": cur_expr, "new": new_expr,
            })

        cur_desc = cur_entry.get("description", "")
        new_desc = new_entry.get("description", "")
        flag_desc = (bool(new_desc) if ignore_empty_new_description else True) and new_desc != cur_desc
        if flag_desc:
            change_set["modified_descriptions"].append({
                "column": col, "current": cur_desc, "new": new_desc,
            })

        if "synonyms" in cur_entry and "synonyms" in new_entry:
            cur_syns = set(cur_entry.get("synonyms") or [])
            new_syns = set(new_entry.get("synonyms") or [])
            if cur_syns != new_syns:
                change_set["modified_synonyms"].append({
                    "column": col,
                    "current": sorted(cur_syns),
                    "new": sorted(new_syns),
                    "added": sorted(new_syns - cur_syns),
                    "removed": sorted(cur_syns - new_syns),
                })

    return change_set


# ---------------------------------------------------------------------------
# lint_sv_ddl
# ---------------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
# Deliberately captures any run of non-whitespace/non-paren characters (not just
# valid-identifier characters) — a malformed name (e.g. containing a hyphen) must
# survive extraction intact so the identifier-format check below can catch it,
# rather than silently truncating at the first invalid character.
_VIEW_NAME_RE = re.compile(r"\bsemantic\s+view\s+([^\s(]+)", re.IGNORECASE)

_TABLE_ENTRY_RE = re.compile(
    r'^\s*(?:([A-Za-z_][A-Za-z0-9_]*)\s+as\s+)?([A-Za-z0-9_."]+)', re.IGNORECASE
)
# The alias group deliberately captures any non-space/non-dot run (not just valid
# identifier characters) — same rationale as _VIEW_NAME_RE: a malformed alias must
# survive extraction intact so the identifier-format check can catch it, rather
# than failing to match the whole entry and silently skipping it.
_DIM_METRIC_HEAD_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\.([^\s.]+)"
    r"(?:\s+non\s+additive\s+by\s*\([^)]*\))?"
    r"\s+as\s+(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RELATIONSHIP_RE = re.compile(
    r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s+references\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
_QUALIFIED_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")

_PLACEHOLDER_PATTERNS = ("-- TODO", "CAST(NULL AS TEXT)")

_COMMENT_START_RE = re.compile(r"\bcomment\s*=\s*'", re.IGNORECASE)
# What legitimately follows a closed comment='...' string in generated DDL: the next
# clause item (comma), the end of the clause (close paren), another `with ...`
# modifier, an `ai_*` top-level clause, a statement terminator, or end of string.
_VALID_CONTINUATION_RE = re.compile(r"^(,|\)|with\b|ai_\w|;|$)", re.IGNORECASE)


def _strip_string_literals(text: str) -> str:
    """Blank out single-quoted string literal contents (comments, synonyms, CA JSON)
    so later structural scans can never mistake quoted prose for SQL/identifier
    tokens. Preserves Snowflake's doubled-quote (`''`) escaping while scanning."""
    return _STRING_LITERAL_RE.sub("''", text)


def _extract_clause(text: str, keyword: str) -> str | None:
    """Return the text inside the balanced parens following `keyword (`, or None if
    the clause isn't present. Assumes string literals have already been blanked out
    (via `_strip_string_literals`) so no quote-tracking is needed here."""
    m = re.search(r"\b" + keyword + r"\s*\(", text, re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:]


def _split_top_level(text: str) -> list[str]:
    """Split clause body text on commas that are not nested inside parens."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


def _extract_view_name(working: str) -> str | None:
    m = _VIEW_NAME_RE.search(working)
    if not m:
        return None
    return m.group(1).split(".")[-1].strip('"')


def _parse_table_alias(entry: str) -> str | None:
    m = _TABLE_ENTRY_RE.match(entry)
    if not m:
        return None
    explicit_alias, qualified = m.group(1), m.group(2)
    if explicit_alias:
        return explicit_alias
    return qualified.split(".")[-1].strip('"')


def _finding(severity: str, check: str, message: str, detail: str = "") -> dict[str, str]:
    return {"severity": severity, "check": check, "message": message, "detail": detail}


def _check_placeholders(working: str) -> list[dict[str, str]]:
    """Check 5 (Step 11 item 14): untranslatable formula placeholders. Runs on the
    string-literal-stripped text so a comment that happens to mention "TODO" in
    prose is never flagged — only text that survives outside a quoted literal."""
    findings = []
    upper = working.upper()
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.upper() in upper:
            idx = upper.find(pattern.upper())
            findings.append(_finding(
                "error", "untranslatable-placeholder",
                f"Found untranslatable placeholder '{pattern}' in the DDL.",
                working[max(0, idx - 20):idx + len(pattern) + 20].strip(),
            ))
    return findings


def _check_comment_quotes(ddl_text: str) -> list[dict[str, str]]:
    """Check 6 (Step 11 item 15): a `comment='...'` value with an embedded,
    un-doubled single quote. Must run on the ORIGINAL text — the exact quote
    characters are what's being inspected, so string-literal stripping (which
    would blank the very thing we're checking) cannot be applied first.

    Moderate-confidence heuristic: walks the string using Snowflake's `''`
    escaping rule to find where the literal actually closes, then checks whether
    what immediately follows looks like a valid DDL continuation (`,`, `)`,
    `with ...`, another `ai_*` clause, `;`, or end of string). An unescaped
    embedded apostrophe closes the literal early, so what follows is normally
    mid-word leftover text that fails this check.
    """
    findings = []
    n = len(ddl_text)
    for m in _COMMENT_START_RE.finditer(ddl_text):
        i = m.end()
        closed_at = None
        while i < n:
            ch = ddl_text[i]
            if ch == "'":
                if i + 1 < n and ddl_text[i + 1] == "'":
                    i += 2
                    continue
                closed_at = i
                break
            i += 1
        if closed_at is None:
            findings.append(_finding(
                "warning", "unescaped-comment-quote",
                "comment= string literal is never terminated.",
                ddl_text[m.start():m.start() + 80].strip(),
            ))
            continue
        after = ddl_text[closed_at + 1:closed_at + 41].lstrip()
        if after and not _VALID_CONTINUATION_RE.match(after):
            findings.append(_finding(
                "warning", "unescaped-comment-quote",
                "comment= string may contain an unescaped embedded single quote — "
                "the text after the closing quote doesn't look like a valid DDL "
                "continuation.",
                ddl_text[m.start():closed_at + 41].strip(),
            ))
    return findings


def _check_view_name(working: str) -> list[dict[str, str]]:
    """Item 13 (partial): the view name itself must be a valid identifier."""
    view_name = _extract_view_name(working)
    if view_name and not _IDENTIFIER_RE.match(view_name):
        return [_finding(
            "error", "identifier-format",
            f"View name '{view_name}' is not a valid Snowflake identifier "
            "(must match ^[A-Za-z_][A-Za-z0-9_]*$).",
        )]
    return []


def _check_tables_clause(working: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Item 13 (partial): table alias identifier validity. Returns (findings,
    table_aliases) — table_aliases (lower(alias) -> alias as declared) feeds every
    other check that needs to know what's actually declared in tables()."""
    findings: list[dict[str, str]] = []
    table_aliases: dict[str, str] = {}
    tables_clause = _extract_clause(working, "tables")
    if not tables_clause:
        return findings, table_aliases
    for entry in _split_top_level(tables_clause):
        alias = _parse_table_alias(entry)
        if not alias:
            continue
        if not _IDENTIFIER_RE.match(alias):
            findings.append(_finding(
                "error", "identifier-format",
                f"Table alias '{alias}' is not a valid Snowflake identifier.",
                entry.strip(),
            ))
        table_aliases[alias.lower()] = alias
    return findings, table_aliases


def _table_declared_finding(name: str, table_aliases: dict[str, str], context: str, detail: str) -> dict[str, str] | None:
    if name.lower() in table_aliases:
        return None
    return _finding(
        "error", "undeclared-table",
        f"Table '{name}' is referenced in {context} but not declared in tables().",
        detail,
    )


def _check_relationships_clause(working: str, table_aliases: dict[str, str]) -> list[dict[str, str]]:
    """Item 1 (partial): both endpoints of every relationship must be declared tables."""
    findings: list[dict[str, str]] = []
    relationships_clause = _extract_clause(working, "relationships")
    if not relationships_clause:
        return findings
    for entry in _split_top_level(relationships_clause):
        m = _RELATIONSHIP_RE.search(entry)
        if not m:
            continue
        for name in (m.group(1), m.group(2)):
            f = _table_declared_finding(name, table_aliases, "relationships()", entry.strip())
            if f:
                findings.append(f)
    return findings


def _check_one_dim_or_metric_entry(
    entry: str, clause_name: str, table_aliases: dict[str, str], seen_aliases: dict[str, str],
) -> tuple[list[dict[str, str]], str | None]:
    """Checks one dimensions()/metrics() entry: alias identifier validity (item 13),
    duplicate alias (item 4), and undeclared table references — both the declaring
    TABLE.ALIAS prefix and any table.col reference inside the expression (item 1).
    Returns (findings, alias_key) — alias_key is None when the entry doesn't match
    the expected TABLE.ALIAS shape at all (silently skipped, not flagged)."""
    findings: list[dict[str, str]] = []
    m = _DIM_METRIC_HEAD_RE.match(entry)
    if not m:
        return findings, None
    table_ref, alias, expr = m.group(1), m.group(2), m.group(3)

    if not _IDENTIFIER_RE.match(alias):
        findings.append(_finding(
            "error", "identifier-format",
            f"Alias '{alias}' in {clause_name}() is not a valid Snowflake identifier.",
            entry.strip(),
        ))

    alias_key = alias.lower()
    if alias_key in seen_aliases:
        findings.append(_finding(
            "error", "duplicate-alias",
            f"Alias '{alias}' is declared more than once across dimensions()/metrics() "
            "— aliases must be globally unique across the whole view.",
            f"first: {seen_aliases[alias_key]!r}; duplicate: {entry.strip()!r}",
        ))
    else:
        seen_aliases[alias_key] = entry.strip()

    f = _table_declared_finding(table_ref, table_aliases, f"{clause_name}()", entry.strip())
    if f:
        findings.append(f)

    for ref_m in _QUALIFIED_REF_RE.finditer(expr):
        ref_table = ref_m.group(1)
        if ref_table.lower() not in table_aliases:
            findings.append(_finding(
                "error", "undeclared-table",
                f"'{ref_table}' referenced in a {clause_name}() expression is not "
                "a declared table.",
                entry.strip(),
            ))

    return findings, alias_key


def _check_dimensions_and_metrics(
    working: str, table_aliases: dict[str, str],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Runs _check_one_dim_or_metric_entry over both clauses. Returns (findings,
    metric_alias_order) — metric_alias_order (lower(alias) -> index within
    metrics()) feeds the forward-reference check below."""
    findings: list[dict[str, str]] = []
    seen_aliases: dict[str, str] = {}
    metric_alias_order: dict[str, int] = {}

    for clause_name in ("dimensions", "metrics"):
        clause = _extract_clause(working, clause_name)
        if not clause:
            continue
        for idx, entry in enumerate(_split_top_level(clause)):
            entry_findings, alias_key = _check_one_dim_or_metric_entry(
                entry, clause_name, table_aliases, seen_aliases,
            )
            findings.extend(entry_findings)
            if clause_name == "metrics" and alias_key is not None:
                metric_alias_order[alias_key] = idx

    return findings, metric_alias_order


def _check_metric_forward_references(working: str, metric_alias_order: dict[str, int]) -> list[dict[str, str]]:
    """Item 6: a metric referencing another metric alias must appear AFTER that
    alias in the metrics() clause."""
    findings: list[dict[str, str]] = []
    metrics_clause = _extract_clause(working, "metrics")
    if not metrics_clause:
        return findings
    for idx, entry in enumerate(_split_top_level(metrics_clause)):
        m = _DIM_METRIC_HEAD_RE.match(entry)
        if not m:
            continue
        own_alias_key, expr = m.group(2).lower(), m.group(3)
        for ref_m in _QUALIFIED_REF_RE.finditer(expr):
            ref_key = ref_m.group(2).lower()
            if ref_key == own_alias_key:
                continue  # self-reference (e.g. re-stating its own table.alias)
            ref_idx = metric_alias_order.get(ref_key)
            if ref_idx is not None and ref_idx >= idx:
                findings.append(_finding(
                    "error", "metric-forward-reference",
                    f"Metric alias '{ref_m.group(2)}' is referenced before it is "
                    "defined in the metrics() clause — Snowflake requires a "
                    "referenced metric to appear earlier in the clause.",
                    entry.strip(),
                ))
    return findings


def _check_structure(working: str) -> list[dict[str, str]]:
    """Checks 1-4 (Step 11 items 13, 4, 1, 6): identifier validity, globally-unique
    dimension/metric aliases, undeclared table references, and metrics referencing
    a metric alias not yet defined earlier in the metrics() clause. Runs on the
    string-literal-stripped text (`working`). Thin orchestrator — each check lives
    in its own helper so this stays easy to read and low-complexity."""
    findings = list(_check_view_name(working))

    table_findings, table_aliases = _check_tables_clause(working)
    findings.extend(table_findings)

    findings.extend(_check_relationships_clause(working, table_aliases))

    dim_metric_findings, metric_alias_order = _check_dimensions_and_metrics(working, table_aliases)
    findings.extend(dim_metric_findings)

    findings.extend(_check_metric_forward_references(working, metric_alias_order))

    return findings


def _dedupe_findings(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, str]] = []
    for f in findings:
        key = (f["severity"], f["check"], f["message"], f.get("detail", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def lint_sv_ddl(ddl_text: str) -> list[dict[str, str]]:
    """Lint a `CREATE SEMANTIC VIEW` DDL string for the deterministic subset of the
    ts-convert-to-snowflake-sv Step 11 checklist.

    Each finding is `{"severity": "error"|"warning", "check": "<slug>", "message":
    str, "detail": str}`. Covers checklist items (see agents/cli/ts-convert-to-
    snowflake-sv/SKILL.md Step 11 for the full 15-item list):

    - identifier-format       (item 13) — view name / every dimension / metric /
                                table alias matches ^[A-Za-z_][A-Za-z0-9_]*$
    - duplicate-alias          (item 4)  — dimension/metric aliases globally unique
    - undeclared-table         (item 1)  — every table referenced in relationships(),
                                dimensions(), or metrics() is declared in tables()
    - metric-forward-reference (item 6)  — a metric referencing another metric alias
                                appears after that alias in metrics()
    - untranslatable-placeholder (item 14) — `-- TODO`, `CAST(NULL AS TEXT)`
    - unescaped-comment-quote  (item 15, warning) — comment='...' with a likely
                                unescaped embedded apostrophe

    Deliberately does NOT attempt the remaining checklist items (primary-key-on-
    join-target, FK-column-as-dimension-alias, nested-SUM-in-derived-metric,
    LOD/window base-metric-alias, non-additive-by modifier shape, formula-dimension
    table_lower.ALIAS references, reserved-word quoting, CA-extension-JSON category
    placement) — those require semantic judgment about aggregation intent or a
    reserved-word list broad enough to risk false positives on legitimate column
    names, so they stay a manual review step in the skill.
    """
    working = _strip_string_literals(ddl_text)
    findings: list[dict[str, str]] = []
    findings.extend(_check_placeholders(working))
    findings.extend(_check_comment_quotes(ddl_text))
    findings.extend(_check_structure(working))
    return _dedupe_findings(findings)


# ---------------------------------------------------------------------------
# SQL variable substitution (BL-079 — `ts snowflake exec`)
# ---------------------------------------------------------------------------
#
# The ts-recipe-formula-*-snowflake skills used to embed their UDF DDL as
# markdown fences the LLM transcribed into Python strings each run — a class of
# silent transcription slip (a `-1` vs `-2` DATEDIFF offset is syntactically
# valid and wrong). The DDL now lives in `references/*.sql` template files with
# `{name}` placeholders that `ts snowflake exec --var name=value` fills in
# deterministically. These two helpers are the pure substitution logic behind
# that command (the connect/execute path is I/O and lives in commands/snowflake.py,
# reusing the load.py connector).

# A `{identifier}` placeholder token: `{` + a Python-style identifier + `}`.
# UDF bodies use `$$ ... $$` with SQL punctuation but no `{ident}` braces, so a
# leftover match after substitution is an unfilled placeholder, not real SQL.
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_var_assignment(assignment: str) -> tuple[str, str]:
    """Parse a single ``--var key=value`` assignment into ``(key, value)``.

    Splits on the FIRST ``=`` only, so a value may itself contain ``=``. The key
    must be a valid ``{placeholder}`` identifier (letters, digits, underscore;
    not starting with a digit). The value may be empty. Raises ``ValueError`` on
    a missing ``=`` or an invalid key.
    """
    if "=" not in assignment:
        raise ValueError(
            f"Invalid --var {assignment!r}: expected key=value (missing '=')."
        )
    key, value = assignment.split("=", 1)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError(
            f"Invalid --var key {key!r}: must be a valid placeholder identifier "
            "(letters, digits, underscore; not starting with a digit)."
        )
    return key, value


def substitute_sql_vars(sql: str, variables: dict[str, str]) -> str:
    """Fill ``{name}`` placeholders in ``sql`` from ``variables`` and verify none remain.

    Every ``{name}`` occurrence is replaced with ``variables[name]`` (all
    occurrences of each name). After substitution, any remaining ``{identifier}``
    token is an unfilled placeholder — a missing ``--var`` — and raises
    ``ValueError`` naming the offenders, so the command fails loudly instead of
    shipping a literal ``{target_schema}`` to Snowflake. Extra variables with no
    matching placeholder are ignored. SQL with no placeholders is returned
    verbatim.
    """
    out = sql
    for name, value in variables.items():
        out = out.replace("{" + name + "}", value)

    leftover = sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(out)})
    if leftover:
        raise ValueError(
            "Unsubstituted placeholder(s) remain after applying --var: "
            + ", ".join("{" + n + "}" for n in leftover)
            + ". Supply each with --var <name>=<value>."
        )
    return out


def json_safe_value(obj: Any) -> Any:
    """`json.dumps(default=...)` coercer for Snowflake result values.

    `ts snowflake exec` serialises query results to JSON, but the snowflake
    connector returns types the stdlib encoder rejects — `Decimal` for NUMBER,
    `datetime`/`date`/`time` for temporal columns, `bytes` for BINARY. Without
    this, `SELECT CURRENT_TIMESTAMP()` (or any decimal/timestamp result) crashes
    the command. Native JSON types never reach here (the encoder only calls
    `default` for objects it can't handle), so ints/floats/strings/bools are
    untouched.

    - `Decimal` → `int` when integral (so a scalar like `4` compares as a number),
      else `float`.
    - `date`/`datetime`/`time` → ISO 8601 string.
    - `bytes`/`bytearray` → hex string.
    - anything else → `str(obj)` as a last resort.
    """
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    return str(obj)
