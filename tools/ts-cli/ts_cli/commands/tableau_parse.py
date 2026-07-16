"""ts tableau — deterministic Tableau workbook (.twb/.twbx) parsing.

Self-contained, stdlib-only port of the Tableau_TS_Migrator parser
(``data_model_migration/webapp/backend/twb_parser.py``, verified against a live
cluster 2026-06-15). This is **T1** of the ts-convert-from-tableau Stage-1
toolchain: it replaces Claude hand-parsing TWB XML — the biggest error source —
with a deterministic structured-JSON extraction (tables, columns, joins,
calculated fields, parameters), with calculated fields topo-sorted and assigned
dependency levels so base formulas precede their dependents.

Output: JSON to stdout (a parsed datasource summary); diagnostics to stderr.
Pass ``--text`` for the human-readable summary instead of JSON.
"""
from __future__ import annotations

import html
import io as _io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile as _zf
from typing import Optional

import typer

app = typer.Typer(help="TWB workbook parsing & TML generation commands.")


# ─────────────────────────────────────────────────────────────────────────────
# Parser — ported verbatim from the Migrator (stdlib-only). Do not "improve"
# without re-checking parser-parity against the oracle.
# ─────────────────────────────────────────────────────────────────────────────

def decode_formula(raw: str) -> str:
    decoded = html.unescape(raw)
    decoded = re.sub(r"//[^\n]*", "", decoded)
    return decoded.strip()


def _clean_param_value(value: str, datatype: str) -> str:
    """Strip Tableau quote/hash wrappers from parameter values.

    Tableau stores string defaults as '"value"', dates as '#YYYY-MM-DD#',
    booleans as 'true'/'false'.  Returns the bare value string.
    For dates we also convert ISO YYYY-MM-DD → MM/DD/YYYY (TS format).
    """
    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    elif v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    elif v.startswith('#') and v.endswith('#'):
        v = v[1:-1]  # date: #2025-05-01# → 2025-05-01
    if datatype == "date":
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
        if m:
            v = f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    return v


def _ensure_trailing_else(formula: str) -> str:
    """Append ``else null`` when a translated if/then chain is missing a final else."""
    stripped = re.sub(r'\[.*?\]', '', formula)
    stripped = re.sub(r"'[^']*'", '', stripped)
    if_count = len(re.findall(r'\bif\b', stripped, re.IGNORECASE))
    else_count = len(re.findall(r'\belse\b', stripped, re.IGNORECASE))
    if if_count > 0 and if_count > else_count:
        return formula.rstrip() + ' else null'
    return formula


def _translate_case_when(formula: str) -> str:
    """Convert CASE WHEN/ELSE/END blocks to ThoughtSpot if/then/else."""
    if not re.search(r'\bCASE\b', formula, re.IGNORECASE):
        return formula

    result = formula
    for _ in range(10):
        case_m = re.search(r'\bCASE\b', result, re.IGNORECASE)
        if not case_m:
            break
        depth = 0
        end_pos = -1
        i = case_m.end()
        while i < len(result):
            if re.match(r'\bCASE\b', result[i:], re.IGNORECASE):
                depth += 1
                i += 4
            elif re.match(r'\bEND\b', result[i:], re.IGNORECASE):
                if depth == 0:
                    end_pos = i
                    break
                depth -= 1
                i += 3
            elif re.match(r'\bIF\b', result[i:], re.IGNORECASE):
                j = i + 2
                if_depth = 1
                while j < len(result):
                    if re.match(r'\bIF\b', result[j:], re.IGNORECASE) and not re.match(r'\bIFNULL\b', result[j:], re.IGNORECASE) and not re.match(r'\bIIF\b', result[j:], re.IGNORECASE):
                        if_depth += 1
                        j += 2
                    elif re.match(r'\bEND\b', result[j:], re.IGNORECASE):
                        if_depth -= 1
                        if if_depth == 0:
                            j += 3
                            break
                        j += 3
                    else:
                        j += 1
                i = j
            else:
                i += 1
        if end_pos == -1:
            break
        inner = result[case_m.end():end_pos].strip()
        if re.match(r'\bWHEN\b', inner, re.IGNORECASE):
            branches = re.findall(
                r'\bWHEN\b\s+((?:(?!\bTHEN\b).)+?)\s+\bTHEN\b\s+((?:(?!\bWHEN\b|\bELSE\b).)+)',
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            else_m = re.search(r'\bELSE\b\s+(.+?)$', inner, re.IGNORECASE | re.DOTALL)
            else_val = else_m.group(1).strip() if else_m else None
        else:
            expr_m = re.match(r'((?:(?!\bWHEN\b).)+)\bWHEN\b', inner, re.IGNORECASE | re.DOTALL)
            expr = expr_m.group(1).strip() if expr_m else ''
            raw = re.findall(
                r'\bWHEN\b\s+((?:(?!\bTHEN\b).)+?)\s+\bTHEN\b\s+((?:(?!\bWHEN\b|\bELSE\b).)+)',
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            branches = [(f'{expr} = {v.strip()}', r.strip()) for v, r in raw]
            else_m = re.search(r'\bELSE\b\s+(.+?)$', inner, re.IGNORECASE | re.DOTALL)
            else_val = else_m.group(1).strip() if else_m else None

        if not branches:
            break

        ts_expr = else_val if else_val is not None else 'null'
        for cond, val in reversed(branches):
            cond, val = cond.strip(), val.strip()
            ts_expr = f'if ({cond}) then {val} else {ts_expr}'

        result = result[:case_m.start()] + ts_expr + result[end_pos + 3:]

    return result


def _split_args(text: str) -> list:
    """Split a comma-separated arg string respecting nested parens and brackets."""
    args = []
    depth = 0
    bracket = 0
    current = []
    for ch in text:
        if ch == '(' :
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '[':
            bracket += 1
        elif ch == ']':
            bracket -= 1
        if ch == ',' and depth == 0 and bracket == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = ''.join(current).strip()
    if tail:
        args.append(tail)
    return args


def _find_func_args(text: str, start: int) -> tuple:
    """Given text and the index of '(', return (end_index, args_string).

    end_index is the position AFTER the closing ')'.
    Returns (-1, '') if no balanced close is found.
    """
    if start >= len(text) or text[start] != '(':
        return -1, ''
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1, text[start + 1:i]
    return -1, ''


def _replace_func_cs(text: str, func_name: str, handler) -> str:
    """Case-sensitive variant of _replace_func."""
    pattern = re.compile(rf'\b{func_name}\s*\(')
    result = text
    offset = 0
    for m in pattern.finditer(text):
        adj_start = m.start() + offset
        paren_pos = adj_start + len(m.group()) - 1
        end, args_str = _find_func_args(result, paren_pos)
        if end == -1:
            continue
        args = _split_args(args_str)
        replacement = handler(args)
        if replacement is None:
            continue
        result = result[:adj_start] + replacement + result[end:]
        offset += len(replacement) - (end - adj_start)
    return result


def _replace_func(text: str, func_name: str, handler) -> str:
    """Find all calls to func_name(...) and replace via handler(args_list) -> str."""
    pattern = re.compile(rf'\b{func_name}\s*\(', re.IGNORECASE)
    result = text
    offset = 0
    for m in pattern.finditer(text):
        adj_start = m.start() + offset
        paren_pos = adj_start + len(m.group()) - 1
        end, args_str = _find_func_args(result, paren_pos)
        if end == -1:
            continue
        args = _split_args(args_str)
        replacement = handler(args)
        if replacement is None:
            continue
        result = result[:adj_start] + replacement + result[end:]
        offset += len(replacement) - (end - adj_start)
    return result


_DATEDIFF_MAP = {
    'day': 'diff_days', 'month': 'diff_months',
    'quarter': 'diff_quarters', 'year': 'diff_years',
    'week': 'diff_days',
}

_DATETRUNC_MAP = {
    'day': 'date', 'month': 'start_of_month', 'quarter': 'start_of_quarter',
    'week': 'start_of_week', 'year': 'start_of_year',
}

_DATEADD_MAP = {
    'day': 'add_days', 'month': 'add_months', 'year': 'add_years',
    'week': 'add_weeks',
}

_DATEPART_MAP = {
    'year': 'year', 'month': 'month_number', 'day': 'day',
    'quarter': 'quarter_number', 'week': 'week_number_of_year',
    'weekday': 'day_of_week', 'dayofyear': 'day_number_of_year',
    'hour': 'hour_of_day',
}


_LOD_PH_OPEN = '\x00GA_OPEN\x00'
_LOD_PH_CLOSE = '\x00GA_CLOSE\x00'


def _translate_lod_expressions(formula: str) -> str:
    """Convert Tableau LOD expressions to ThoughtSpot group_aggregate().

    Handles FIXED (with/without dims), INCLUDE, EXCLUDE, and bare-aggregate
    shorthand.  Uses placeholder tokens for already-converted braces so nested
    LOD expressions are processed inside-out without re-matching.
    """
    if not formula or '{' not in formula:
        return formula

    expr = formula
    for _ in range(10):
        m = re.search(r'\{([^{}]+)\}', expr)
        if not m:
            break
        inner = m.group(1).strip()

        # FIXED [dim1], [dim2] : EXPR
        fixed_dims = re.match(
            r'FIXED\s+((?:\[[^\]]+\](?:\s*,\s*\[[^\]]+\])*)\s*):\s*(.+)',
            inner, re.DOTALL | re.IGNORECASE)
        if fixed_dims:
            dims = fixed_dims.group(1).strip()
            body = fixed_dims.group(2).strip()
            repl = f'group_aggregate({body}, {_LOD_PH_OPEN}{dims}{_LOD_PH_CLOSE}, {_LOD_PH_OPEN}{_LOD_PH_CLOSE})'
            expr = expr[:m.start()] + repl + expr[m.end():]
            continue

        # FIXED : EXPR (no dimensions)
        fixed_no = re.match(r'FIXED\s*:\s*(.+)', inner, re.DOTALL | re.IGNORECASE)
        if fixed_no:
            body = fixed_no.group(1).strip()
            repl = f'group_aggregate({body}, {_LOD_PH_OPEN}{_LOD_PH_CLOSE}, {_LOD_PH_OPEN}{_LOD_PH_CLOSE})'
            expr = expr[:m.start()] + repl + expr[m.end():]
            continue

        # INCLUDE [dim] : EXPR
        include_m = re.match(
            r'INCLUDE\s+((?:\[[^\]]+\](?:\s*,\s*\[[^\]]+\])*)\s*):\s*(.+)',
            inner, re.DOTALL | re.IGNORECASE)
        if include_m:
            dims = include_m.group(1).strip()
            body = include_m.group(2).strip()
            repl = (f'group_aggregate({body}, '
                    f'query_groups() + {_LOD_PH_OPEN}{dims}{_LOD_PH_CLOSE}, '
                    f'query_filters())')
            expr = expr[:m.start()] + repl + expr[m.end():]
            continue

        # EXCLUDE [dim] : EXPR
        exclude_m = re.match(
            r'EXCLUDE\s+((?:\[[^\]]+\](?:\s*,\s*\[[^\]]+\])*)\s*):\s*(.+)',
            inner, re.DOTALL | re.IGNORECASE)
        if exclude_m:
            dims = exclude_m.group(1).strip()
            body = exclude_m.group(2).strip()
            repl = (f'group_aggregate({body}, '
                    f'query_groups() - {_LOD_PH_OPEN}{dims}{_LOD_PH_CLOSE}, '
                    f'query_filters())')
            expr = expr[:m.start()] + repl + expr[m.end():]
            continue

        # Bare aggregate: {AGG_FUNC(...)}
        bare_agg = re.match(
            r'((?:MAX|MIN|SUM|AVG|COUNT|COUNTD|unique\s+count)\s*\(.+)',
            inner, re.DOTALL | re.IGNORECASE)
        if bare_agg:
            body = bare_agg.group(1).strip()
            repl = f'group_aggregate({body}, {_LOD_PH_OPEN}{_LOD_PH_CLOSE}, {_LOD_PH_OPEN}{_LOD_PH_CLOSE})'
            expr = expr[:m.start()] + repl + expr[m.end():]
            continue

        # Not an LOD expression (e.g. set literal {1, 2, 3}) — stop
        break

    expr = expr.replace(_LOD_PH_OPEN, '{').replace(_LOD_PH_CLOSE, '}')
    return expr


def _translate_total(formula: str) -> str:
    """Convert TOTAL(expr) to group_aggregate(expr, {}, query_filters())."""
    if not formula:
        return formula
    result = []
    i = 0
    upper = formula.upper()
    while i < len(formula):
        if (upper[i:i + 6] == 'TOTAL('
                and (i == 0 or not formula[i - 1].isalpha())):
            depth = 1
            j = i + 6
            while j < len(formula) and depth > 0:
                if formula[j] == '(':
                    depth += 1
                elif formula[j] == ')':
                    depth -= 1
                j += 1
            inner = formula[i + 6:j - 1]
            result.append(f'group_aggregate({inner}, {{}}, query_filters())')
            i = j
        else:
            result.append(formula[i])
            i += 1
    return ''.join(result)


def _convert_string_plus_to_concat(formula: str) -> str:
    """Convert string + concatenation to concat().

    Detects + between string literals or [bracket refs] and rewrites to concat().
    Numeric + (both operands are numbers/numeric functions) is left alone.
    """
    if '+' not in formula:
        return formula

    token_pat = re.compile(
        r"'[^']*'"          # string literal
        r'|\[[^\]]+\]'      # bracketed column ref
        r'|\b\w+\s*\('      # function call start
        r'|\b[\w.]+\b'      # identifier or number
        r'|\+|-|\*|/|,'     # operators
        r'|\(|\)'           # parens
        r'|\s+'             # whitespace
    )

    tokens = token_pat.findall(formula)
    has_string_plus = False
    for i, t in enumerate(tokens):
        if t.strip() == '+':
            left = next((tokens[j] for j in range(i - 1, -1, -1) if tokens[j].strip()), '')
            right = next((tokens[j] for j in range(i + 1, len(tokens)) if tokens[j].strip()), '')
            if (left.startswith("'") or left.startswith('[') or
                    right.startswith("'") or right.startswith('[')):
                has_string_plus = True
                break

    if not has_string_plus:
        return formula

    parts = []
    current = []
    depth = 0
    i = 0
    while i < len(formula):
        if formula[i] == '(':
            depth += 1
            current.append(formula[i])
            i += 1
        elif formula[i] == ')':
            depth -= 1
            current.append(formula[i])
            i += 1
        elif formula[i] == '+' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            i += 1
        else:
            current.append(formula[i])
            i += 1
    parts.append(''.join(current).strip())

    if len(parts) <= 1:
        return formula

    return 'concat ( ' + ' , '.join(parts) + ' )'


def _lowercase_formula(formula: str) -> str:
    """Lowercase function names/keywords/operators while preserving the case of
    column/parameter/formula references (inside ``[...]``) and string literals
    (inside ``'...'`` / ``"..."``).

    ThoughtSpot function names are case-insensitive and the docs/house style use
    lowercase, so lowercasing the language tokens is safe. Bracketed refs are
    column names (case-sensitive) and quoted text includes display strings AND
    date format patterns where case is meaningful (``MM`` month vs ``mm`` minute,
    ``HH`` vs ``hh``) — those must NOT be touched.
    """
    if not formula:
        return formula
    out = []
    i, n = 0, len(formula)
    while i < n:
        c = formula[i]
        if c == '[':                      # reference — preserve verbatim
            j = formula.find(']', i)
            if j == -1:
                out.append(formula[i:]); break
            out.append(formula[i:j + 1]); i = j + 1
        elif c in ("'", '"'):             # string literal — preserve verbatim
            q = c; j = i + 1
            while j < n and formula[j] != q:
                j += 1
            end = j + 1 if j < n else n
            out.append(formula[i:end]); i = end
        else:                             # language token — safe to lowercase
            out.append(c.lower()); i += 1
    return ''.join(out)


def _translate_functions(formula: str, on_fallback=None, on_unknown=None) -> str:
    """Translate a formula's LOD + TOTAL + functions to ThoughtSpot syntax.

    Primary path is the Lark AST translator (``tableau_formula_ast``), which does
    LOD, TOTAL, and function translation in one parse and handles nested/quoted
    constructs the regex passes miss. If the grammar can't parse a given formula,
    it falls back — for that one formula only — to the regex pipeline
    (``_translate_lod_expressions`` → ``_translate_total`` →
    ``_translate_tableau_to_ts_functions``), i.e. today's behaviour.

    ``on_unknown(func_name)`` is called for each Tableau function that has no
    ThoughtSpot mapping — these should be routed to judgment.
    """
    from ts_cli.commands.tableau_formula_ast import translate_with_fallback
    return _lowercase_formula(translate_with_fallback(
        formula, on_fallback=on_fallback, on_unknown=on_unknown,
    ))


def _translate_tableau_to_ts_functions(formula: str) -> str:
    """Translate Tableau-specific function names/syntax to ThoughtSpot equivalents."""
    if not formula:
        return formula
    result = formula

    result = _translate_case_when(result)

    # ── Tier 2: date functions with unit dispatch ────────────────────────
    # Must run BEFORE simple renames so inner args are still in Tableau form.

    def _handle_datediff(args):
        if len(args) < 3:
            return None
        unit = args[0].strip().strip("'\"").lower()
        fn = _DATEDIFF_MAP.get(unit)
        if not fn:
            return None
        a, b = args[1].strip(), args[2].strip()
        if unit == 'week':
            return f'floor ( {fn} ( {a} , {b} ) / 7 )'
        return f'{fn} ( {a} , {b} )'

    result = _replace_func(result, 'DATEDIFF', _handle_datediff)

    def _handle_datetrunc(args):
        if len(args) < 2:
            return None
        unit = args[0].strip().strip("'\"").lower()
        fn = _DATETRUNC_MAP.get(unit)
        if not fn:
            return None
        d = args[1].strip()
        return f'{fn} ( {d} )'

    result = _replace_func(result, 'DATETRUNC', _handle_datetrunc)

    def _handle_dateadd(args):
        if len(args) < 3:
            return None
        unit = args[0].strip().strip("'\"").lower()
        n, d = args[1].strip(), args[2].strip()
        fn = _DATEADD_MAP.get(unit)
        if fn:
            return f'{fn} ( {d} , {n} )'
        if unit == 'quarter':
            return f'add_months ( {d} , {n} * 3 )'
        return None

    result = _replace_func(result, 'DATEADD', _handle_dateadd)

    def _handle_datepart(args):
        if len(args) < 2:
            return None
        part = args[0].strip().strip("'\"").lower()
        fn = _DATEPART_MAP.get(part)
        if not fn:
            return None
        d = args[1].strip()
        return f'{fn} ( {d} )'

    result = _replace_func(result, 'DATEPART', _handle_datepart)
    result = _replace_func(result, 'DATENAME', _handle_datepart)

    # ── Tier 1: simple function renames ──────────────────────────────────

    result = re.sub(r'\bSTR\s*\(', 'to_string(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bSTRING\s*\(', 'to_string(', result, flags=re.IGNORECASE)
    result = re.sub(r",\s*'#'\s*\)", ')', result)

    result = re.sub(r'\bINT\s*\(', 'to_integer(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bINTEGER\s*\(', 'to_integer(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bFLOAT\s*\(', 'to_double(', result, flags=re.IGNORECASE)

    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:INT|INTEGER)\s*\)',
                    r'to_integer(\1)', result, flags=re.IGNORECASE)
    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL)\s*\)',
                    r'to_double(\1)', result, flags=re.IGNORECASE)
    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:VARCHAR|STRING|TEXT|CHAR)\s*\)',
                    r'to_string(\1)', result, flags=re.IGNORECASE)

    def _cast_date_handler(m, fmt):
        inner = m.group(1).strip()
        if re.match(r'^\[.+\]$', inner):
            return inner
        return f"to_date({inner}, '{fmt}')"

    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:DATE)\s*\)',
                    lambda m: _cast_date_handler(m, '%Y-%m-%d'),
                    result, flags=re.IGNORECASE)
    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:DATETIME|TIMESTAMP)\s*\)',
                    lambda m: _cast_date_handler(m, '%Y-%m-%d %H:%M:%S'),
                    result, flags=re.IGNORECASE)
    result = re.sub(r'\bCAST\s*\((.+?)\s+AS\s+(?:BOOL|BOOLEAN)\s*\)',
                    r'\1', result, flags=re.IGNORECASE)

    result = re.sub(r'\bdatetime\s*\((.+?)\)',
                    r"to_date(\1, '%Y-%m-%d')", result, flags=re.IGNORECASE)

    def _handle_dateparse(args):
        if len(args) < 2:
            return None
        fmt = args[0].strip().strip('"').strip("'")
        val = args[1].strip()
        return f"to_date ( {val} , '{fmt}' )"

    result = _replace_func(result, 'DATEPARSE', _handle_dateparse)

    def _handle_date(args):
        inner = args[0].strip()
        if re.match(r'^\[.+\]$', inner):
            return inner
        return f"to_date ( {inner} , 'yyyy-MM-dd' )"

    # Case-sensitive: only match Tableau's uppercase DATE(), not the
    # ThoughtSpot lowercase `date (` output from DATETRUNC('day').
    result = _replace_func_cs(result, 'DATE', _handle_date)

    result = re.sub(
        r'\bSUM\s*\(\s*IF\s+(.+?)\s+THEN\s+(.+?)\s+ELSE\s+0\s+END\s*\)',
        r'sum_if(\1, \2)',
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    result = re.sub(r'\bCOUNTD\s*\(', 'unique count(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bAVG\s*\(', 'average(', result, flags=re.IGNORECASE)
    # Lowercase the standard aggregates for consistency with the docs/house style
    # (the TS parser is case-insensitive, so this is cosmetic, not a fix).
    # COUNTD is already handled above; \bCOUNT\b won't match COUNTD( (D breaks it).
    result = re.sub(r'\bSUM\s*\(', 'sum(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bMIN\s*\(', 'min(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bMAX\s*\(', 'max(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bCOUNT\s*\(', 'count(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bSTDEV\s*\(', 'stddev(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bSTDEVP\s*\(', 'stddev(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bLEN\s*\(', 'strlen(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bFIND\s*\(', 'strpos(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bCEILING\s*\(', 'ceil(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bLOG\s*\(', 'log10(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bPOWER\s*\(', 'pow(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bMONTH\s*\(', 'month_number(', result, flags=re.IGNORECASE)

    # ── String functions ───────────────────────────────────────────────
    result = re.sub(r'\bISNULL\s*\(', 'isnull(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bCONTAINS\s*\(', 'contains(', result, flags=re.IGNORECASE)

    def _handle_left(args):
        if len(args) < 2:
            return None
        s, n = args[0].strip(), args[1].strip()
        return f'substr ( {s} , 0 , {n} )'

    result = _replace_func(result, 'LEFT', _handle_left)

    def _handle_right(args):
        if len(args) < 2:
            return None
        s, n = args[0].strip(), args[1].strip()
        return f'substr ( {s} , strlen ( {s} ) - {n} , {n} )'

    result = _replace_func(result, 'RIGHT', _handle_right)

    def _handle_mid(args):
        if len(args) < 3:
            return None
        s, start, length = args[0].strip(), args[1].strip(), args[2].strip()
        return f'substr ( {s} , {start} - 1 , {length} )'

    result = _replace_func(result, 'MID', _handle_mid)

    def _handle_upper(args):
        if len(args) != 1:
            return None
        return f'sql_string_op ( "upper({{0}})" , {args[0].strip()} )'

    result = _replace_func(result, 'UPPER', _handle_upper)

    def _handle_lower(args):
        if len(args) != 1:
            return None
        return f'sql_string_op ( "lower({{0}})" , {args[0].strip()} )'

    result = _replace_func(result, 'LOWER', _handle_lower)

    def _handle_trim(args):
        if len(args) != 1:
            return None
        return f'sql_string_op ( "trim({{0}})" , {args[0].strip()} )'

    result = _replace_func(result, 'TRIM', _handle_trim)

    def _handle_replace(args):
        if len(args) < 3:
            return None
        s, old, new = args[0].strip(), args[1].strip(), args[2].strip()
        return f'sql_string_op ( "replace({{0}}, {old}, {new})" , {s} )'

    result = _replace_func(result, 'REPLACE', _handle_replace)

    def _handle_zn(args):
        if len(args) != 1:
            return None
        return f'ifnull ( {args[0].strip()} , 0 )'

    result = _replace_func(result, 'ZN', _handle_zn)

    def _handle_square(args):
        if len(args) != 1:
            return None
        return f'pow ( {args[0].strip()} , 2 )'

    result = _replace_func(result, 'SQUARE', _handle_square)

    def _handle_attr(args):
        if len(args) != 1:
            return None
        return args[0].strip()

    result = _replace_func(result, 'ATTR', _handle_attr)

    def _handle_iif(args):
        if len(args) < 3:
            return None
        test, a, b = args[0].strip(), args[1].strip(), args[2].strip()
        return f'if ( {test} ) then {a} else {b}'

    result = _replace_func(result, 'IIF', _handle_iif)

    result = re.sub(r'\bWINDOW_AVG\s*\(', 'moving_average(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bWINDOW_SUM\s*\(', 'moving_sum(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bWINDOW_MIN\s*\(', 'moving_min(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bWINDOW_MAX\s*\(', 'moving_max(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bRUNNING_SUM\s*\(', 'cumulative_sum(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bRUNNING_AVG\s*\(', 'cumulative_average(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bRUNNING_MIN\s*\(', 'cumulative_min(', result, flags=re.IGNORECASE)
    result = re.sub(r'\bRUNNING_MAX\s*\(', 'cumulative_max(', result, flags=re.IGNORECASE)

    result = re.sub(r'(?<!["\'\w])TRUE(?!["\'\w])', 'true', result)
    result = re.sub(r'(?<!["\'\w])FALSE(?!["\'\w])', 'false', result)

    result = re.sub(r'"([^"\[\]\r\n]*)"', r"'\1'", result)

    result = _convert_string_plus_to_concat(result)

    # Tableau NOT IN ('a', 'b') → ThoughtSpot not in { 'a' , 'b' }
    result = re.sub(
        r'\bNOT\s+IN\s*\(([^)]+)\)',
        lambda m: f'not in {{ {m.group(1).strip()} }}',
        result,
        flags=re.IGNORECASE,
    )
    # Tableau IN ('a', 'b') → ThoughtSpot in { 'a' , 'b' }
    result = re.sub(
        r'\bIN\s*\(([^)]+)\)',
        lambda m: f'in {{ {m.group(1).strip()} }}',
        result,
        flags=re.IGNORECASE,
    )

    # ELSEIF → else if (must be BEFORE the IF regex)
    result = re.sub(r'\bELSEIF\b', 'else if', result, flags=re.IGNORECASE)

    result = re.sub(
        r'\bIF\s+(?!\s*\()(.+?)\s+THEN\b',
        lambda m: f'if ({m.group(1).strip()}) then',
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Lookahead prevents matching inside [bracket refs] like [Custom Date End]
    result = re.sub(r'\bELSE\b(?![^\[]*\])', 'else', result, flags=re.IGNORECASE)
    result = re.sub(r'\s*\bEND\b(?![^\[]*\])', '', result, flags=re.IGNORECASE)

    result = _ensure_trailing_else(result)

    def _fix_to_date_args(args):
        if len(args) == 1:
            return f"to_date ( {args[0].strip()} , 'yyyy-MM-dd' )"
        return None

    result = _replace_func(result, 'to_date', _fix_to_date_args)

    return result


def _translate_formula_refs(formula: str, formula_ref_map: dict) -> str:
    """Replace [Calculation_*] internal names with [formula_<caption>] in a formula."""
    if not formula_ref_map or not formula:
        return formula
    result = formula
    for internal, caption in formula_ref_map.items():
        result = re.sub(
            rf"\[{re.escape(internal)}\]",
            f"[formula_{caption}]",
            result,
        )
    return result


def _topo_sort_formulas(calculated_fields: list) -> list:
    """Return calculated fields sorted so every dependency appears before its dependent."""
    name_to_field = {cf["internal_name"]: cf for cf in calculated_fields}

    def _get_deps(cf: dict) -> list:
        formula = cf.get("formula", "")
        deps = []
        for m in re.finditer(r"\[Calculation_\d+\]", formula):
            dep = m.group(0).strip("[]")
            if dep in name_to_field and dep != cf["internal_name"]:
                deps.append(dep)
        return deps

    in_degree = {cf["internal_name"]: 0 for cf in calculated_fields}
    dependents = {cf["internal_name"]: [] for cf in calculated_fields}

    for cf in calculated_fields:
        for dep in _get_deps(cf):
            dependents[dep].append(cf["internal_name"])
            in_degree[cf["internal_name"]] += 1

    queue = [cf for cf in calculated_fields if in_degree[cf["internal_name"]] == 0]
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dep_name in dependents[node["internal_name"]]:
            in_degree[dep_name] -= 1
            if in_degree[dep_name] == 0:
                result_field = name_to_field.get(dep_name)
                if result_field:
                    queue.append(result_field)

    reached = {cf["internal_name"] for cf in result}
    for cf in calculated_fields:
        if cf["internal_name"] not in reached:
            result.append(cf)

    return result


def _compute_formula_levels(calculated_fields: list) -> dict:
    """Compute the dependency level for each formula using raw [Calculation_*] refs."""
    name_to_field = {cf["internal_name"]: cf for cf in calculated_fields}

    def _raw_deps(name: str) -> list:
        cf = name_to_field.get(name)
        if not cf:
            return []
        return [
            m.group(0).strip("[]")
            for m in re.finditer(r"\[Calculation_\d+\]", cf.get("formula", ""))
            if m.group(0).strip("[]") in name_to_field and m.group(0).strip("[]") != name
        ]

    memo: dict = {}

    def _level(name: str, visiting: set) -> int:
        if name in memo:
            return memo[name]
        if name in visiting:
            return 0  # cycle guard
        visiting.add(name)
        deps = _raw_deps(name)
        lvl = (max(_level(d, visiting) for d in deps) + 1) if deps else 0
        visiting.discard(name)
        memo[name] = lvl
        return lvl

    for cf in calculated_fields:
        if cf["internal_name"] not in memo:
            _level(cf["internal_name"], set())

    return memo


def _translate_param_refs(formula: str, parameter_map: dict) -> str:
    """Replace [Parameters].[InternalName] with [Caption] in a formula string."""
    if not parameter_map or not formula:
        return formula
    result = formula
    for internal, caption in parameter_map.items():
        result = re.sub(
            rf"\[Parameters\]\.\[{re.escape(internal)}\]",
            f"[{caption}]",
            result,
        )
        result = re.sub(
            rf"(?<!\w)\[{re.escape(internal)}\](?!\s*\.\s*\[)",
            f"[{caption}]",
            result,
        )
    return result


def _normalize_parent_name(raw: str) -> str:
    """Strip object-model hash suffix from parent-name values.

    Tableau writes parent names in several formats:
      TABLE (DB.TABLE)_76512E787548459E8D76C71D908B06DF   → TABLE
      Chocolate Sales 2_0014C22500CA4C7FBDF90410EFA405F9  → Chocolate Sales 2
      _9BBB096D8D91453E94133E5DAB1262E7                    → (unchanged — pure
        extract hash with no name part; see _is_extract_parent)
    """
    m = re.match(r"^(.+?)\s+\(.*\)_[0-9A-Fa-f]+$", raw)
    if m:
        return m.group(1)
    m = re.match(r"^(.+?)_[0-9A-Fa-f]{32}$", raw)
    if m:
        return m.group(1)
    return raw


def _is_extract_parent(parent: str) -> bool:
    """True when a parent-name refers to an extract, not a real relation.

    Covers the literal "Extract" and Tableau's pure-hash extract object
    names like "_9BBB096D8D91453E94133E5DAB1262E7" (columns under these
    are extract copies of another relation's columns).
    """
    return parent == "Extract" or bool(re.fullmatch(r"_?[0-9A-Fa-f]{32}", parent))


# ─────────────────────────────────────────────────────────────────────────────
# Table mapping file loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_table_map_file(path: str) -> dict:
    """Parse a table mapping file (Step 2.5 format).

    Each line: SOURCE : TARGET  or  SOURCE - TARGET
    Both sides are reduced to their last dot-segment (the table name) —
    ThoughtSpot column refs use ``[TableName::Column]``, not the full
    ``DB.SCHEMA.TABLE`` path.
    Returns {source_last_segment_upper: target_last_segment}.
    """
    mapping: dict = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for sep in (":", "-"):
                if sep in line:
                    parts = line.split(sep, 1)
                    if len(parts) == 2:
                        src = parts[0].strip().split(".")[-1].strip()
                        tgt = parts[1].strip().split(".")[-1].strip()
                        if src and tgt:
                            mapping[src.upper()] = tgt
                    break
    return mapping


# ─────────────────────────────────────────────────────────────────────────────
# Column qualification — resolve bare [Column] refs to [Table::Column]
# ─────────────────────────────────────────────────────────────────────────────

def _build_column_to_table_map(datasource: dict) -> dict:
    """Build {ref_name → relation_name} from column_mappings + physical_columns.

    column_mappings: {"internal_name": "[TableName].[ColumnName]"}
    physical_columns: [{"name": "COL", "parent_table": "TableName", "local_name": "..."}]
    column_roles: {"internal_name": {"caption": "Display Name", ...}}

    Returns: {"ref_name": "relation_name", ...} where ref_name includes both
    the column name (used in formula expressions) and the caption (display name).
    """
    col_to_table: dict = {}

    col_roles = datasource.get("column_roles", {})
    column_mappings = datasource.get("column_mappings", {})
    physical_columns = datasource.get("physical_columns", [])
    tables = datasource.get("tables", [])

    relation_to_physical = {}
    for t in tables:
        relation_to_physical[t.get("relation_name", "")] = t.get("physical_table", "")

    caption_map = {}
    for internal, info in col_roles.items():
        caption_map[internal] = info.get("caption", internal)

    for pc in physical_columns:
        name = pc.get("name", "")
        local_name = pc.get("local_name", "")
        parent = pc.get("parent_table", "")
        caption = caption_map.get(local_name, name)
        if parent:
            if caption:
                col_to_table[caption] = parent
            if name and name != caption:
                col_to_table.setdefault(name, parent)
            if local_name and local_name != caption and local_name != name:
                col_to_table.setdefault(local_name, parent)

    for internal, value in column_mappings.items():
        parts = value.strip("[]").split("].[")
        if len(parts) >= 2:
            table_part = parts[0]
            col_name = parts[1]
            caption = caption_map.get(internal, internal)
            if table_part:
                if caption:
                    col_to_table.setdefault(caption, table_part)
                if col_name and col_name != caption:
                    col_to_table.setdefault(col_name, table_part)
                if internal and internal != caption and internal != col_name:
                    col_to_table.setdefault(internal, table_part)

    return col_to_table


def _qualify_column_refs(
    formula: str,
    col_to_table: dict,
    table_map: dict,
    formula_names: set | None = None,
) -> tuple:
    """Qualify bare [Column] refs in a translated formula to [TSTable::Column].

    Args:
        formula: translated formula (output of _translate_tableau_to_ts_functions)
        col_to_table: {column_caption: tableau_relation_name} from _build_column_to_table_map
        table_map: {tableau_relation_name: thoughtspot_table_name} from Step 4.5
        formula_names: set of calculated-field captions to skip (these are formula
            refs, not column refs — they should stay as bare [Caption])

    Returns:
        (qualified_formula, unresolved_list)
        unresolved_list: column names that couldn't be mapped (for Claude to handle)
    """
    if not formula:
        return formula, []

    unresolved = []
    _formula_names = formula_names or set()

    def _replace_ref(m):
        ref = m.group(1)

        if ref.startswith("formula_"):
            return m.group(0)
        if "::" in ref:
            return m.group(0)
        if ref in _formula_names:
            return m.group(0)

        tableau_table = col_to_table.get(ref)
        if not tableau_table:
            unresolved.append(ref)
            return m.group(0)

        ts_table = table_map.get(tableau_table)
        if not ts_table:
            ts_table = table_map.get(tableau_table.split(".")[-1])
        if not ts_table:
            for tkey, tval in table_map.items():
                if tkey.endswith(tableau_table) or tableau_table.endswith(tkey):
                    ts_table = tval
                    break
        if not ts_table:
            unresolved.append(ref)
            return m.group(0)

        return f"[{ts_table}::{ref}]"

    bracket_ref = re.compile(r"\[([^\[\]]+)\]")
    qualified = bracket_ref.sub(_replace_ref, formula)

    return qualified, unresolved


def qualify_parsed_formulas(
    parsed: dict,
    table_map: dict,
) -> dict:
    """Qualify column refs in all formulas from a parse output.

    Args:
        parsed: output of parse_twb() (the full datasource JSON)
        table_map: {tableau_relation_name: thoughtspot_table_name}

    Returns:
        {
            "formulas": [
                {
                    "caption": "...",
                    "original": "raw tableau formula",
                    "translated": "function-translated with bare refs",
                    "qualified": "fully qualified [Table::Col] formula",
                    "unresolved": ["col names that couldn't be mapped"],
                    "level": 0,
                    "fully_resolved": true/false,
                }
            ],
            "summary": {
                "total": N,
                "fully_resolved": N,
                "partially_resolved": N,
                "unresolved_columns": ["col1", "col2"]
            }
        }
    """
    results = []
    all_unresolved = set()
    fully_resolved_count = 0

    all_formula_captions: set = set()
    for ds in parsed.get("datasources", []):
        if ds.get("is_parameters"):
            for p in ds.get("parameters", []):
                cap = p.get("caption", "")
                if cap:
                    all_formula_captions.add(cap)
            continue
        for cf in ds.get("calculated_fields", []):
            cap = cf.get("caption", "")
            if cap:
                all_formula_captions.add(cap)

    for ds in parsed.get("datasources", []):
        if ds.get("is_parameters"):
            continue

        col_to_table = _build_column_to_table_map(ds)

        for cf in ds.get("calculated_fields", []):
            translated = cf.get("formula", "")
            raw = cf.get("formula_raw", translated)
            if not translated:
                continue

            qualified, unresolved = _qualify_column_refs(
                translated, col_to_table, table_map,
                formula_names=all_formula_captions,
            )

            fully_resolved = len(unresolved) == 0
            if fully_resolved:
                fully_resolved_count += 1
            all_unresolved.update(unresolved)

            results.append({
                "caption": cf.get("caption", ""),
                "level": cf.get("level", 0),
                "original": raw,
                "translated": translated,
                "qualified": qualified,
                "unresolved": unresolved,
                "fully_resolved": fully_resolved,
            })

    return {
        "formulas": results,
        "summary": {
            "total": len(results),
            "fully_resolved": fully_resolved_count,
            "partially_resolved": len(results) - fully_resolved_count,
            "unresolved_columns": sorted(all_unresolved),
        },
    }


def _extract_joins(relation_elem) -> list:
    """Recursively extract join info from nested <relation> elements."""
    joins = []
    if relation_elem is None:
        return joins

    join_type = relation_elem.get("join")
    rel_type = relation_elem.get("type")

    if rel_type == "join" and join_type:
        clause = relation_elem.find("clause")
        on_clause = ""
        if clause is not None:
            expr = clause.find("expression")
            if expr is not None:
                ops = expr.findall("expression")
                if len(ops) == 2:
                    on_clause = f"{ops[0].get('op', '')} = {ops[1].get('op', '')}"

        child_relations = relation_elem.findall("relation")
        table_names = []
        for child in child_relations:
            child_type = child.get("type", "")
            if child_type in ("table", "text"):
                table_names.append(child.get("name", ""))
            elif child_type == "join":
                sub_joins = _extract_joins(child)
                joins.extend(sub_joins)
                for sj in sub_joins:
                    if sj.get("left_table"):
                        table_names.append(sj["left_table"])
                    if sj.get("right_table"):
                        table_names.append(sj["right_table"])

        left_table = table_names[0] if len(table_names) > 0 else ""
        right_table = table_names[-1] if len(table_names) > 1 else ""

        joins.append({
            "left_table": left_table,
            "right_table": right_table,
            "join_type": join_type,
            "on_clause": on_clause,
        })

    elif rel_type == "collection":
        for child in relation_elem.findall("relation"):
            joins.extend(_extract_joins(child))

    return joins


_XML_OP_ARTIFACTS = re.compile(r'>>=|<<=|==')


def _clean_sql_text(sql: str) -> str:
    """Fix XML-entity decoding artifacts in SQL extracted from TWB.

    Tableau stores comparison operators as XML entities (``&gt;=``,
    ``&lt;=``).  Double-encoding or parser quirks can produce
    ``>>=`` / ``<<=`` in the decoded text.  ``==`` can appear from
    ``&gt;&gt;=`` or literal double-equals — standard SQL uses ``=``.
    """
    return _XML_OP_ARTIFACTS.sub(lambda m: m.group(0)[1:], sql)


def _extract_tables_from_relation(relation_elem) -> list:
    """Extract physical table definitions from nested relation elements."""
    tables = []
    if relation_elem is None:
        return tables

    rel_type = relation_elem.get("type", "")
    if rel_type in ("table", "text"):
        name = relation_elem.get("name", "")
        table_ref = relation_elem.get("table", "")
        sql_text = _clean_sql_text(relation_elem.text.strip()) if relation_elem.text else ""

        physical_table = name
        db = ""
        schema = ""
        if table_ref:
            parts = table_ref.strip("[]").split("].[")
            physical_table = parts[-1] if parts else name
            if len(parts) >= 3:
                db, schema = parts[0], parts[1]
            elif len(parts) == 2:
                schema = parts[0]

        if sql_text:
            match = re.search(r'FROM\s+"[^"]*"\."[^"]*"\."([^"]+)"', sql_text)
            if match:
                physical_table = match.group(1)

        entry = {
            "relation_name": name,
            "physical_table": physical_table,
            "type": rel_type,
        }
        if db:
            entry["db"] = db
        if schema:
            entry["schema"] = schema
        if rel_type == "text" and sql_text:
            entry["sql_query"] = sql_text
        tables.append(entry)
    elif rel_type in ("join", "collection"):
        for child in relation_elem.findall("relation"):
            tables.extend(_extract_tables_from_relation(child))

    return tables


def _objid_hash(object_id: str) -> str:
    """Return the stable trailing hash of a Tableau logical object-id.

    Object-ids look like ``NAME (db.NAME)_<hash>``. The leading ``db`` portion
    can differ between where the id is declared (e.g. ``CS_DWH``) and where it
    is referenced (e.g. ``CS_DATA_ENGINEERING_PUBLISHED``), but the trailing
    hash is stable, so it is the reliable key for matching.
    """
    m = re.search(r"\)_([0-9A-Fa-f]{8,})$", object_id or "")
    return m.group(1) if m else (object_id or "")


def _extract_objectgraph_joins(ds_elem) -> list:
    """Extract joins from Tableau's object-model ``<relationships>`` graph.

    Newer Tableau workbooks (object model, 2020.2+) record joins in an
    ``<object-graph>`` (under a feature-flagged tag) instead of as
    ``<relation type='join'>`` elements, so ``_extract_joins`` misses them.
    Relationship endpoints reference logical object-ids; we map those back to
    the owning relation name via the ``<object-id>`` recorded on each
    ``<metadata-record>`` (matched on the stable trailing hash).
    """
    joins: list = []

    # Map object-id hash -> owning relation name (from metadata-records).
    hash_to_relation: dict = {}
    for mr in ds_elem.iter("metadata-record"):
        parent = (mr.findtext("parent-name") or "").strip().strip("[]")
        if not parent:
            continue
        for child in mr:
            if child.tag.endswith("object-id"):
                oid = (child.text or "").strip().strip("[]")
                h = _objid_hash(oid)
                if h and h not in hash_to_relation:
                    hash_to_relation[h] = parent
                break

    # Walk every object-graph and emit one join per relationship.
    for og in ds_elem.iter():
        if not og.tag.endswith("object-graph"):
            continue
        for rel in og.iter("relationship"):
            expr = rel.find("expression")
            on_clause = ""
            if expr is not None:
                ops = expr.findall("expression")
                if len(ops) == 2:
                    on_clause = f"{ops[0].get('op', '')} = {ops[1].get('op', '')}"
            fep = rel.find("first-end-point")
            sep = rel.find("second-end-point")
            first_oid = fep.get("object-id", "").strip("[]") if fep is not None else ""
            second_oid = sep.get("object-id", "").strip("[]") if sep is not None else ""
            left_table = hash_to_relation.get(_objid_hash(first_oid), "")
            right_table = hash_to_relation.get(_objid_hash(second_oid), "")
            if on_clause and (left_table or right_table):
                joins.append({
                    "left_table": left_table,
                    "right_table": right_table,
                    "join_type": "left",
                    "on_clause": on_clause,
                    "source": "object-graph",
                })
    return joins


def parse_twb(path: str) -> dict:
    """Parse a TWB or TWBX file and return a structured summary.

    TWBX files are zip archives; the embedded .twb XML is extracted automatically.
    """
    if path.lower().endswith(".twbx"):
        with _zf.ZipFile(path, "r") as zf:
            twb_names = [n for n in zf.namelist() if n.lower().endswith(".twb")]
            if not twb_names:
                return {"datasources": []}
            with zf.open(twb_names[0]) as fh:
                tree = ET.parse(_io.BytesIO(fh.read()))
    else:
        tree = ET.parse(path)
    root = tree.getroot()

    ds_container = root.find("datasources")
    if ds_container is None:
        return {"datasources": []}

    result: dict = {"datasources": []}

    for ds_elem in ds_container.findall("datasource"):
        ds_name = ds_elem.get("name", "")
        ds_caption = ds_elem.get("caption", ds_name)
        is_params = ds_name.lower() == "parameters"

        ds_info: dict = {
            "name": ds_name,
            "caption": ds_caption,
            "is_parameters": is_params,
            "physical_columns": [],
            "calculated_fields": [],
            "tables": [],
            "joins": [],
            "column_mappings": {},
            "connection_type": "",
            "is_sqlproxy": False,
            "custom_sql_sources": [],
        }

        if is_params:
            params = []
            param_map: dict = {}
            for col_elem in ds_elem.findall("column"):
                internal_name = col_elem.get("name", "").strip("[]")
                caption = col_elem.get("caption", internal_name)
                datatype = col_elem.get("datatype", "string")
                domain_type = col_elem.get("param-domain-type", "any")
                raw_value = col_elem.get("value", "")
                current_value = _clean_param_value(raw_value, datatype)

                allowed_values = []
                members_elem = col_elem.find("members")
                if members_elem is not None:
                    for m in members_elem.findall("member"):
                        raw_v = m.get("value", "")
                        cleaned_v = _clean_param_value(raw_v, datatype)
                        alias = m.get("aliasname", m.get("alias", ""))
                        entry = {"value": cleaned_v}
                        if alias:
                            entry["display_name"] = alias
                        allowed_values.append(entry)

                range_info = None
                range_elem = col_elem.find("range")
                if range_elem is not None:
                    range_info = {
                        "min": _clean_param_value(range_elem.get("min", ""), datatype),
                        "max": _clean_param_value(range_elem.get("max", ""), datatype),
                    }

                params.append({
                    "internal_name": internal_name,
                    "caption": caption,
                    "datatype": datatype,
                    "domain_type": domain_type,
                    "current_value": current_value,
                    "allowed_values": allowed_values,
                    "range": range_info,
                })
                if internal_name and caption:
                    param_map[internal_name] = caption

            ds_info["parameters"] = params
            ds_info["parameter_map"] = param_map
            result["datasources"].append(ds_info)
            result["parameter_map"] = param_map
            continue

        conn = ds_elem.find("connection")
        if conn is not None:
            conn_class = conn.get("class", "")
            ds_info["connection_type"] = conn_class

            if conn_class == "sqlproxy":
                ds_info["is_sqlproxy"] = True
                ds_info["sqlproxy_info"] = {
                    "channel": conn.get("channel", ""),
                    "dbname": conn.get("dbname", ""),
                    "server": conn.get("server", ""),
                    "caption": conn.get("caption", ""),
                }

            col_maps = {}
            cols_elem = conn.find("cols")
            if cols_elem is not None:
                for m in cols_elem.findall("map"):
                    key = m.get("key", "").strip("[]")
                    value = m.get("value", "")
                    col_maps[key] = value
            ds_info["column_mappings"] = col_maps

            for tag in conn:
                tag_name = tag.tag
                if "relation" not in tag_name:
                    continue
                rel_type = tag.get("type", "")
                if rel_type in ("join", "collection"):
                    ds_info["tables"] = _extract_tables_from_relation(tag)
                    ds_info["joins"] = _extract_joins(tag)
                    if rel_type == "collection":
                        ds_info["is_collection"] = True
                    for t in ds_info["tables"]:
                        if t.get("sql_query"):
                            ds_info["custom_sql_sources"].append({
                                "name": t["relation_name"],
                                "sql_query": t["sql_query"],
                            })
                    break
                elif rel_type == "table":
                    existing_tables = {t["relation_name"] for t in ds_info["tables"]}
                    for entry in _extract_tables_from_relation(tag):
                        if entry["relation_name"] not in existing_tables:
                            ds_info["tables"].append(entry)
                            existing_tables.add(entry["relation_name"])
                elif rel_type == "text":
                    sql_text = _clean_sql_text(tag.text.strip()) if tag.text else ""
                    if sql_text:
                        rel_name = tag.get("name", "Custom SQL Query")
                        existing_sql = {c["name"] for c in ds_info["custom_sql_sources"]}
                        if rel_name not in existing_sql:
                            ds_info["custom_sql_sources"].append({
                                "name": rel_name,
                                "sql_query": sql_text,
                            })
                        # A single-relation custom-SQL datasource has no
                        # <collection> wrapper, so the collection branch above
                        # never adds it to `tables`. Add it here, de-duplicating
                        # the legacy (.false) and object-model (.true) copies
                        # that Tableau writes for the same query (matched by name).
                        existing_tables = {t["relation_name"] for t in ds_info["tables"]}
                        for entry in _extract_tables_from_relation(tag):
                            if entry["relation_name"] not in existing_tables:
                                ds_info["tables"].append(entry)
                                existing_tables.add(entry["relation_name"])

            # Older-style <relation type='join'> populate joins above; newer
            # workbooks use the object-model <relationships> graph instead.
            # Fall back to that when no classic joins were found.
            if not ds_info["joins"]:
                ds_info["joins"] = _extract_objectgraph_joins(ds_elem)

        # Collect metadata-records with normalized parent names, then
        # deduplicate: non-Extract entries win; Extract-only records kept
        # as fallback (pure-extract datasources with no live connection).
        raw_records: list = []
        for mr in ds_elem.iter("metadata-record"):
            mr_class = mr.get("class", "")
            if mr_class in ("column", "measure"):
                remote_name = mr.findtext("remote-name", "")
                local_type = mr.findtext("local-type", "")
                local_name = mr.findtext("local-name", "").strip("[]")
                parent_name = _normalize_parent_name(
                    mr.findtext("parent-name", "").strip("[]")
                )
                aggregation = mr.findtext("aggregation", "")

                if remote_name.startswith("Calculation_") or remote_name == "Number of Records":
                    continue

                raw_records.append({
                    "name": remote_name,
                    "local_name": local_name,
                    "parent_table": parent_name,
                    "local_type": local_type,
                    "aggregation": aggregation,
                })

        seen_physical: set = set()
        non_extract_names: set = set()
        for rec in raw_records:
            if _is_extract_parent(rec["parent_table"]):
                continue
            col_key = f"{rec['parent_table']}::{rec['name']}"
            if col_key not in seen_physical:
                seen_physical.add(col_key)
                non_extract_names.add(rec["name"])
                ds_info["physical_columns"].append(rec)
        for rec in raw_records:
            if not _is_extract_parent(rec["parent_table"]):
                continue
            if rec["name"] not in non_extract_names:
                ds_info["physical_columns"].append(rec)
                non_extract_names.add(rec["name"])

        col_roles: dict = {}
        for col_elem in ds_elem.findall("column"):
            col_name = col_elem.get("name", "").strip("[]")
            col_roles[col_name] = {
                "caption": col_elem.get("caption", col_name),
                "role": col_elem.get("role", "dimension"),
                "datatype": col_elem.get("datatype", "string"),
            }
        ds_info["column_roles"] = col_roles

        for pc in ds_info["physical_columns"]:
            local_name = pc.get("local_name", "")
            if local_name in col_roles:
                pc["role"] = col_roles[local_name].get("role", "dimension")

        seen_calcs: set = set()
        for col_elem in ds_elem.findall("column"):
            calc_elem = col_elem.find("calculation")
            if calc_elem is not None and calc_elem.get("class") == "tableau":
                col_name = col_elem.get("name", "").strip("[]")
                col_caption = col_elem.get("caption", col_name)
                col_datatype = col_elem.get("datatype", "string")
                col_role = col_elem.get("role", "dimension")
                formula_raw = calc_elem.get("formula", "")
                formula = decode_formula(formula_raw)

                if col_caption not in seen_calcs:
                    seen_calcs.add(col_caption)
                    ds_info["calculated_fields"].append({
                        "internal_name": col_name,
                        "caption": col_caption,
                        "datatype": col_datatype,
                        "role": col_role,
                        "formula": formula,
                    })

        for col_elem in ds_elem.iter():
            tag = col_elem.tag
            if "column" in tag and col_elem.tag != "column":
                calc_elem = col_elem.find("calculation")
                if calc_elem is not None and calc_elem.get("class") == "tableau":
                    col_name = col_elem.get("name", "").strip("[]")
                    col_caption = col_elem.get("caption", col_name)
                    col_datatype = col_elem.get("datatype", "string")
                    col_role = col_elem.get("role", "dimension")
                    formula_raw = calc_elem.get("formula", "")
                    formula = decode_formula(formula_raw)

                    if col_caption not in seen_calcs:
                        seen_calcs.add(col_caption)
                        ds_info["calculated_fields"].append({
                            "internal_name": col_name,
                            "caption": col_caption,
                            "datatype": col_datatype,
                            "role": col_role,
                            "formula": formula,
                        })

        result["datasources"].append(ds_info)

    ws_calcs: dict = {}
    for dep in root.iter("datasource-dependencies"):
        dep_ds = dep.get("datasource", "")
        if not dep_ds:
            continue
        for col_elem in dep.findall("column"):
            calc_elem = col_elem.find("calculation")
            if calc_elem is not None and calc_elem.get("class") == "tableau":
                formula_raw = calc_elem.get("formula", "")
                formula = decode_formula(formula_raw)
                col_caption = col_elem.get("caption", col_elem.get("name", "").strip("[]"))
                col_name = col_elem.get("name", "").strip("[]")
                if col_caption and formula:
                    if dep_ds not in ws_calcs:
                        ws_calcs[dep_ds] = {}
                    ws_calcs[dep_ds][col_caption] = {
                        "internal_name": col_name,
                        "formula": formula,
                        "datatype": col_elem.get("datatype", "string"),
                        "role": col_elem.get("role", "dimension"),
                    }

    for ds_info in result["datasources"]:
        if ds_info.get("is_parameters"):
            continue
        existing = {cf["caption"] for cf in ds_info["calculated_fields"]}
        ws = ws_calcs.get(ds_info["name"], {})
        for caption, info in ws.items():
            if caption not in existing:
                ds_info["calculated_fields"].append({
                    "internal_name": info["internal_name"],
                    "caption": caption,
                    "datatype": info["datatype"],
                    "role": info["role"],
                    "formula": info["formula"],
                    "source": "worksheet",
                })

    parameter_map: dict = result.get("parameter_map", {})
    formula_column_map: dict = {}
    for ds_info in result["datasources"]:
        if ds_info.get("is_parameters"):
            continue
        for cf in ds_info.get("calculated_fields", []):
            internal = cf.get("internal_name", "")
            caption = cf.get("caption", "")
            if internal and caption:
                formula_column_map[internal] = caption
    result["formula_column_map"] = formula_column_map

    for ds_info in result["datasources"]:
        if ds_info.get("is_parameters"):
            continue
        calcs = ds_info.get("calculated_fields", [])

        levels = _compute_formula_levels(calcs)
        for cf in calcs:
            cf["level"] = levels.get(cf["internal_name"], 0)

        ds_info["calculated_fields"] = _topo_sort_formulas(calcs)

        for cf in ds_info["calculated_fields"]:
            formula = cf.get("formula", "")
            # Preserve the decoded raw Tableau formula before mechanical
            # translation so downstream consumers (e.g. `ts tableau verify`)
            # can detect untranslatable patterns and compare raw↔TML fidelity.
            cf["formula_raw"] = formula
            if not formula:
                continue
            formula = _translate_formula_refs(formula, formula_column_map)
            if parameter_map:
                formula = _translate_param_refs(formula, parameter_map)
            formula = _translate_functions(formula)
            cf["formula"] = formula

    # --- Worksheets -----------------------------------------------------------
    worksheets_out: list[dict] = []
    ws_container = root.find("worksheets")
    if ws_container is not None:
        for ws_elem in ws_container.findall("worksheet"):
            ws_name = ws_elem.get("name", "")
            ds_refs: set[str] = set()
            ws_fields: set[str] = set()
            for dep in ws_elem.iter("datasource-dependencies"):
                ds_ref = dep.get("datasource", "")
                if ds_ref and ds_ref.lower() != "parameters":
                    ds_refs.add(ds_ref)
                for col in dep.findall("column"):
                    col_name = (col.get("name") or "").strip("[]")
                    if col_name:
                        ws_fields.add(col_name)

            def _shelf_text(tag: str) -> str:
                el = ws_elem.find(f".//table/{tag}")
                return (el.text or "").strip() if el is not None else ""

            worksheets_out.append({
                "name": ws_name,
                "datasources": sorted(ds_refs),
                "fields": sorted(ws_fields),
                "rows": _shelf_text("rows"),
                "cols": _shelf_text("cols"),
            })
    result["worksheets"] = worksheets_out

    # --- Dashboards ----------------------------------------------------------
    dashboards_out: list[dict] = []
    db_container = root.find("dashboards")
    if db_container is not None:
        for db_elem in db_container.findall("dashboard"):
            db_name = db_elem.get("name", "")
            size_el = db_elem.find("size")
            size = {}
            if size_el is not None:
                size = {
                    "width": int(size_el.get("maxwidth", "0")),
                    "height": int(size_el.get("maxheight", "0")),
                }
            sheet_refs: list[str] = []
            seen_sheets: set[str] = set()
            for zone in db_elem.iter("zone"):
                zname = zone.get("name", "")
                ztype = zone.get("type-v2", "")
                if zname and ztype != "filter" and zname not in seen_sheets:
                    seen_sheets.add(zname)
                    sheet_refs.append(zname)
            dashboards_out.append({
                "name": db_name,
                "size": size,
                "worksheets": sheet_refs,
            })
    result["dashboards"] = dashboards_out

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Summary counts — lightweight metadata for skill orchestration / audit mode.
# ─────────────────────────────────────────────────────────────────────────────

def _counts(parsed: dict) -> dict:
    ds_list = parsed.get("datasources", [])
    data_ds = [d for d in ds_list if not d.get("is_parameters")]
    n_params = sum(len(d.get("parameters", [])) for d in ds_list if d.get("is_parameters"))

    seen_tables: set = set()
    seen_sql: set = set()
    for d in data_ds:
        for t in d.get("tables", []):
            if t.get("type") == "text":
                sql = t.get("sql_query", "").strip()
                if sql:
                    seen_sql.add(sql)
            else:
                key = (
                    t.get("db", ""),
                    t.get("schema", ""),
                    t.get("physical_table", t.get("relation_name", "")),
                )
                seen_tables.add(key)
        for cs in d.get("custom_sql_sources", []):
            sql = cs.get("sql_query", "").strip()
            if sql:
                seen_sql.add(sql)

    return {
        "datasources": len(data_ds),
        "physical_tables": len(seen_tables),
        "custom_sql_sources": len(seen_sql),
        "joins": sum(len(d.get("joins", [])) for d in data_ds),
        "calculated_fields": sum(len(d.get("calculated_fields", [])) for d in data_ds),
        "parameters": n_params,
        "worksheets": len(parsed.get("worksheets", [])),
        "dashboards": len(parsed.get("dashboards", [])),
    }


def _parse_summary(parsed: dict, out_file: str) -> dict:
    """Compact, token-cheap summary of a parsed workbook for skill orchestration.

    Emitted to stdout when ``ts tableau parse --out`` writes the full JSON to a
    file. Carries the counts the skill announces at Step 3 plus per-datasource
    breakdown, so the orchestrator never has to ingest the full parse blob just
    to report structure. The full JSON on disk remains the source of truth for
    every downstream tool (translate-formula, postprocess, generate-tml).
    """
    ds_list = parsed.get("datasources", [])
    data_ds = [d for d in ds_list if not d.get("is_parameters")]
    return {
        "out_file": out_file,
        "counts": _counts(parsed),
        "datasources": [
            {
                "name": d.get("name", ""),
                "type": d.get("type", ""),
                "tables": len(d.get("tables", [])),
                "custom_sql_sources": len(d.get("custom_sql_sources", [])),
                "joins": len(d.get("joins", [])),
                "calculated_fields": len(d.get("calculated_fields", [])),
            }
            for d in data_ds
        ],
        "dashboards": [d.get("name", "") for d in parsed.get("dashboards", [])],
    }


def _extract_parameters(parsed: dict) -> list:
    """Flatten every parameter (from the ``is_parameters`` datasource) to a
    compact list. Names/types only — enough for the orchestrator to resolve
    ``[Parameters].[X]`` references and build ``model.parameters[]`` without
    re-reading the full parse. Values stay in the on-disk JSON."""
    params: list = []
    for d in parsed.get("datasources", []):
        if not d.get("is_parameters"):
            continue
        for p in d.get("parameters", []):
            params.append({
                "caption": p.get("caption", ""),
                "internal_name": p.get("internal_name", ""),
                "datatype": p.get("datatype", ""),
                "domain_type": p.get("domain_type", ""),
            })
    return params


def _compact_translation(output: dict, parsed: dict, out_file: str) -> dict:
    """Token-cheap view of a batch formula translation.

    Returns the formulas that genuinely need model judgment in FULL, plus a
    compact reference table for EVERY formula (caption → translated, with tier
    and topo level). The reference table is what keeps cross-formula references,
    parameter references, and multi-level dependency order intact: any judgment
    formula that references another formula or a parameter can be resolved by
    looking it up here, in dependency (level) order — without loading the full
    translation blob. The full ``{formulas, summary}`` is written to ``out_file``.
    """
    formulas = output.get("formulas", [])
    judgment = [f for f in formulas if not f.get("deterministic")]
    reference = sorted(
        (
            {
                "caption": f.get("caption", ""),
                "level": f.get("level", 0),
                "tier": f.get("tier", ""),
                "translated": f.get("translated", ""),
            }
            for f in formulas
        ),
        key=lambda r: (r["level"], r["caption"]),
    )
    summary = dict(output.get("summary", {}))
    summary["judgment"] = len(judgment)
    summary["out_file"] = out_file
    return {
        "summary": summary,
        "judgment": judgment,
        "reference": reference,
        "parameters": _extract_parameters(parsed),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

@app.command("parse")
def parse(
    file: str = typer.Argument(..., help="Path to a .twb or .twbx workbook file"),
    text: bool = typer.Option(False, "--text", help="Emit the human-readable summary instead of JSON"),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Write full JSON to this file; print a compact summary to stdout instead of the full blob"),
    indent: Optional[int] = typer.Option(None, "--indent", help="Pretty-print JSON with this indent"),
) -> None:
    """Parse a Tableau workbook into structured JSON (T1 — deterministic).

    Extracts datasources → physical tables, joins, physical columns, calculated
    fields (topo-sorted with dependency levels), parameters, and custom SQL.
    Calculated-field formulas are pre-translated to ThoughtSpot syntax for the
    mechanical tier (CASE→if/else, function renames, etc.).

    Output: full JSON to stdout by default. With --out FILE, the full JSON is
    written to FILE and only a compact structural summary is printed to stdout
    (so the orchestrator never has to ingest the full parse blob just to report
    structure). The on-disk JSON stays the source of truth for downstream tools.
    """
    import os
    if not os.path.exists(file):
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(code=2)
    if not file.lower().endswith((".twb", ".twbx")):
        typer.echo(f"Error: not a .twb/.twbx file: {file}", err=True)
        raise typer.Exit(code=2)

    try:
        parsed = parse_twb(file)
    except (ET.ParseError, _zf.BadZipFile) as e:
        typer.echo(f"Error: failed to parse workbook: {e}", err=True)
        raise typer.Exit(code=1)

    if text:
        print(twb_to_summary_text_from_parsed(parsed))
        return

    parsed["_summary"] = _counts(parsed)

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(parsed, fh, indent=indent)
        typer.echo(f"Full parse written to: {out}", err=True)
        print(json.dumps(_parse_summary(parsed, os.path.abspath(out)), indent=2))
        return

    print(json.dumps(parsed, indent=indent))


@app.command("verify")
def verify(
    file: str = typer.Argument(..., help="Path to the source .twb or .twbx workbook"),
    directory: str = typer.Argument(..., help="Directory of generated TML files"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Include side-by-side formula detail"),
    save: bool = typer.Option(False, "--save", help="Also write MIGRATION_ACCURACY_REPORT.md into the directory"),
) -> None:
    """Audit migration fidelity: diff a TWB against its generated TML (T1 — deterministic).

    Parses both sides and checks that every table, join, formula, and parameter
    is accounted for; runs a tokenized TWB↔TS formula comparison; and confirms
    untranslatable formulas are documented. Catches silent drops and structural
    gaps that a server-side VALIDATE_ONLY import cannot.

    Report to stdout. Exits non-zero when fidelity errors are found.
    """
    import os
    from ts_cli.commands import tableau_verify

    if not os.path.exists(file):
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(code=2)
    if not file.lower().endswith((".twb", ".twbx")):
        typer.echo(f"Error: not a .twb/.twbx file: {file}", err=True)
        raise typer.Exit(code=2)
    if not os.path.isdir(directory):
        typer.echo(f"Error: not a directory: {directory}", err=True)
        raise typer.Exit(code=2)

    try:
        report, n_errors = tableau_verify.run_verify(file, directory, verbose=verbose)
    except (ET.ParseError, _zf.BadZipFile) as e:
        typer.echo(f"Error: failed to parse workbook: {e}", err=True)
        raise typer.Exit(code=1)

    print(report)
    if save:
        out = os.path.join(directory, "MIGRATION_ACCURACY_REPORT.md")
        with open(out, "w") as fh:
            fh.write(report)
        typer.echo(f"\nReport saved to: {out}", err=True)
    if n_errors:
        raise typer.Exit(code=1)


@app.command("translate-formula")
def translate_formula(
    formula: Optional[str] = typer.Option(None, "--formula", "-f", help="Single Tableau formula to translate"),
    input_file: Optional[str] = typer.Option(None, "--input", "-i", help="Path to parsed JSON (from ts tableau parse) for batch mode"),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Batch mode: write the full translation to this file; print only the judgment formulas + a compact reference table to stdout"),
    table_map_file: Optional[str] = typer.Option(None, "--table-map", "-m", help="Table mapping file (Tableau→TS name mapping) — when provided, qualifies all [Column] refs to [Table::Column]"),
    indent: Optional[int] = typer.Option(2, "--indent", help="Pretty-print JSON indent"),
) -> None:
    """Translate Tableau formula(s) to ThoughtSpot syntax and classify (T2 — deterministic).

    Single mode: pass --formula "IF [Sales] > 100 THEN 'High' END"
    Batch mode: pass --input parsed.json (output of ts tableau parse)

    Each formula is translated (CASE→if/else, function renames, ref cleanup)
    and classified as deterministic / query_time / untranslatable.

    When --table-map is provided, column references are qualified to
    [ThoughtSpotTable::Column] format so T3 receives fully prefixed refs.

    Output: full JSON to stdout by default. In batch mode with --out FILE, the
    full translation is written to FILE and stdout carries only what needs model
    judgment — the non-deterministic formulas in full, plus a compact reference
    table (caption → translated, tier, topo level) for EVERY formula and the
    parameter list. That reference table is what keeps cross-formula references,
    parameter references, and multi-level dependency order resolvable without
    loading the full blob.
    """
    import os
    from ts_cli.commands.tableau_verify import classify

    if not formula and not input_file:
        typer.echo("Error: provide --formula or --input", err=True)
        raise typer.Exit(code=2)

    if formula:
        unknown_fns: list[str] = []
        translated = _translate_functions(formula, on_unknown=lambda fn: unknown_fns.append(fn))
        tier, reason = classify(formula)
        if tier == "translatable" and unknown_fns:
            tier = "judgment"
            reason = f"Unknown Tableau functions with no ThoughtSpot mapping: {', '.join(unknown_fns)}"
        result = {
            "original": formula,
            "translated": translated,
            "tier": tier,
            "deterministic": tier == "translatable",
            "reason": reason,
        }
        print(json.dumps(result, indent=indent))
        return

    if not os.path.exists(input_file):
        typer.echo(f"Error: file not found: {input_file}", err=True)
        raise typer.Exit(code=2)

    table_map: dict = {}
    if table_map_file:
        if not os.path.exists(table_map_file):
            typer.echo(f"Error: table map file not found: {table_map_file}", err=True)
            raise typer.Exit(code=2)
        table_map = _load_table_map_file(table_map_file)

    with open(input_file, "r", encoding="utf-8") as fh:
        parsed = json.load(fh)

    formula_column_map: dict = parsed.get("formula_column_map", {})
    parameter_map: dict = parsed.get("parameter_map", {})

    # Build set of names to skip during column qualification: formula captions
    # (formula-to-formula refs stay as bare [Caption]) and parameter captions
    # (parameter refs also stay as bare [Caption]).
    all_formula_captions: set = set()
    for ds in parsed.get("datasources", []):
        if ds.get("is_parameters"):
            for p in ds.get("parameters", []):
                cap = p.get("caption", "")
                if cap:
                    all_formula_captions.add(cap)
            continue
        for cf in ds.get("calculated_fields", []):
            cap = cf.get("caption", "")
            if cap:
                all_formula_captions.add(cap)

    results: list = []
    summary = {"deterministic": 0, "query_time": 0, "untranslatable": 0,
               "judgment": 0, "total": 0}
    qualify_summary = {"qualified": 0, "unresolved_columns": set()}
    fallback_count = {"n": 0}

    def _note_fallback(_f, _reason):
        fallback_count["n"] += 1

    for ds in parsed.get("datasources", []):
        if ds.get("is_parameters"):
            continue

        col_to_table = _build_column_to_table_map(ds) if table_map else {}

        for cf in ds.get("calculated_fields", []):
            raw = cf.get("formula_raw") or cf.get("formula", "")
            if not raw:
                continue

            unknown_fns: list[str] = []
            translated = raw
            if formula_column_map:
                translated = _translate_formula_refs(translated, formula_column_map)
            if parameter_map:
                translated = _translate_param_refs(translated, parameter_map)
            translated = _translate_functions(
                translated, on_fallback=_note_fallback,
                on_unknown=lambda fn: unknown_fns.append(fn),
            )

            if table_map and col_to_table:
                translated, unresolved = _qualify_column_refs(
                    translated, col_to_table, table_map,
                    formula_names=all_formula_captions,
                )
                if not unresolved:
                    qualify_summary["qualified"] += 1
                qualify_summary["unresolved_columns"].update(unresolved)

            tier, reason = classify(raw)
            if tier == "translatable" and unknown_fns:
                tier = "judgment"
                reason = (f"Unknown Tableau functions with no ThoughtSpot "
                          f"mapping: {', '.join(unknown_fns)}")
            summary[tier] = summary.get(tier, 0) + 1
            summary["total"] += 1

            results.append({
                "caption": cf.get("caption", ""),
                "level": cf.get("level", 0),
                "original": raw,
                "translated": translated,
                "tier": tier,
                "deterministic": tier == "translatable",
                "reason": reason,
            })

    summary["regex_fallbacks"] = fallback_count["n"]
    output = {"formulas": results, "summary": summary}

    if table_map:
        unresolved_sorted = sorted(qualify_summary["unresolved_columns"])
        output["qualify_summary"] = {
            "qualified": qualify_summary["qualified"],
            "unresolved_columns": unresolved_sorted,
        }
        typer.echo(
            f"Qualified column refs using table map: "
            f"{qualify_summary['qualified']}/{summary['total']} fully resolved"
            + (f", unresolved: {', '.join(unresolved_sorted)}" if unresolved_sorted else ""),
            err=True,
        )

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=indent)
        typer.echo(f"Full translation written to: {out}", err=True)
        print(json.dumps(_compact_translation(output, parsed, os.path.abspath(out)), indent=indent))
        return

    print(json.dumps(output, indent=indent))


@app.command("qualify")
def qualify(
    input_file: str = typer.Option(..., "--input", "-i", help="Path to parsed JSON (from ts tableau parse)"),
    table_map_str: str = typer.Option(..., "--table-map", "-m",
                                      help="Comma-separated Tableau=ThoughtSpot table pairs, e.g. 'Orders=ORDERS,Customers=CUSTOMER'"),
    indent: Optional[int] = typer.Option(2, "--indent", help="Pretty-print JSON indent"),
) -> None:
    """Qualify bare [Column] refs to [Table::Column] in translated formulas (T3 — deterministic).

    Takes the parse output (from ts tableau parse) and a table mapping (from Step 4.5),
    and produces formulas with fully qualified column references. Calc field refs
    ([formula_*]) and already-qualified refs ([Table::Col]) are left untouched.

    Columns that can't be resolved are listed in the 'unresolved' field for Claude
    to handle.

    Output: JSON to stdout.
    """
    import os

    if not os.path.exists(input_file):
        typer.echo(f"Error: file not found: {input_file}", err=True)
        raise typer.Exit(code=2)

    table_map = {}
    for pair in table_map_str.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        table_map[k.strip()] = v.strip()

    if not table_map:
        typer.echo("Error: --table-map must have at least one Tableau=ThoughtSpot pair", err=True)
        raise typer.Exit(code=2)

    with open(input_file, "r", encoding="utf-8") as fh:
        parsed = json.load(fh)

    result = qualify_parsed_formulas(parsed, table_map)
    print(json.dumps(result, indent=indent))

    summary = result["summary"]
    typer.echo(
        f"\nQualified {summary['fully_resolved']}/{summary['total']} formulas fully. "
        f"{summary['partially_resolved']} have unresolved columns: "
        f"{', '.join(summary['unresolved_columns']) or 'none'}.",
        err=True,
    )


@app.command("postprocess")
def postprocess(
    directory: str = typer.Argument(..., help="Directory containing generated TML files"),
    twb_file: str = typer.Argument(..., help="Path to the source .twb or .twbx workbook"),
) -> None:
    """Deterministic TML fix-up on generated files (T4 — deterministic).

    Patches model joins, column names, formula refs, injects parameters and
    obj_ids, deduplicates entries, and validates cross-references. Operates
    in-place on TML files in the directory.

    Output: JSON report to stdout.
    """
    import os
    from ts_cli.commands import tableau_postprocess

    if not os.path.isdir(directory):
        typer.echo(f"Error: not a directory: {directory}", err=True)
        raise typer.Exit(code=2)
    if not os.path.exists(twb_file):
        typer.echo(f"Error: file not found: {twb_file}", err=True)
        raise typer.Exit(code=2)

    try:
        report = tableau_postprocess.run_postprocess(directory, twb_file)
    except Exception as e:
        typer.echo(f"Error: postprocess failed: {e}", err=True)
        raise typer.Exit(code=1)

    print(json.dumps(report, indent=2))

    n_fixes = len(report.get("fixes", []))
    n_errors = len(report.get("errors", []))
    n_xref = len(report.get("cross_ref_errors", []))
    typer.echo(
        f"\nPostprocess complete: {n_fixes} fix(es), {n_errors} error(s), "
        f"{n_xref} cross-ref issue(s).",
        err=True,
    )
    if n_errors or n_xref:
        raise typer.Exit(code=1)


@app.command("generate-tml")
def generate_tml(
    input_file: str = typer.Option(..., "--input", "-i", help="Path to parsed.json (from ts tableau parse)"),
    translated_file: str = typer.Option(..., "--translated", "-t", help="Path to translated.json (from ts tableau translate-formula)"),
    connection: str = typer.Option(..., "--connection", "-c", help="ThoughtSpot connection name"),
    database: str = typer.Option(..., "--database", "-d", help="Target database"),
    schema: str = typer.Option(..., "--schema", "-s", help="Target schema"),
    table_map_file: Optional[str] = typer.Option(None, "--table-map", "-m", help="Table mapping file (Tableau→TS name mapping)"),
    connection_tables_file: Optional[str] = typer.Option(None, "--connection-tables", help="JSON file with list of table names from the connection hierarchy — used for fuzzy matching when no --table-map is provided"),
    out: str = typer.Option(..., "--out", "-o", help="Output directory for generated TML files"),
    decisions_file: Optional[str] = typer.Option(None, "--decisions", help="decisions.json answering a prior decisions-needed.json (LLM-resolved formulas)"),
) -> None:
    """Generate Table, SQL View, and Model TMLs from parsed workbook (T3 — deterministic).

    Reads parsed.json and translated.json, generates all TML files in batch.
    No LLM reasoning — purely mechanical mapping from parsed data to YAML.
    Formulas the translator could not resolve are listed in a
    decisions-needed.json questions file; answer it with decisions.json and
    re-run with --decisions to have T3 apply them under the TML schema rules.
    """
    from ts_cli.commands import tableau_generate

    if not os.path.exists(input_file):
        typer.echo(f"Error: input file not found: {input_file}", err=True)
        raise typer.Exit(code=2)
    if not os.path.exists(translated_file):
        typer.echo(f"Error: translated file not found: {translated_file}", err=True)
        raise typer.Exit(code=2)

    with open(input_file, encoding="utf-8") as fh:
        parsed = json.load(fh)
    with open(translated_file, encoding="utf-8") as fh:
        translated = json.load(fh)

    table_map = None
    sql_table_map = None
    if table_map_file:
        if not os.path.exists(table_map_file):
            typer.echo(f"Error: table map file not found: {table_map_file}", err=True)
            raise typer.Exit(code=2)
        table_map = tableau_generate._load_table_map(table_map_file)
        sql_table_map = tableau_generate._load_full_table_map(table_map_file)

    decisions = None
    if decisions_file:
        if not os.path.exists(decisions_file):
            typer.echo(f"Error: decisions file not found: {decisions_file}", err=True)
            raise typer.Exit(code=2)
        decisions = tableau_generate._load_decisions(decisions_file)

    conn_tables = None
    if connection_tables_file:
        if not os.path.exists(connection_tables_file):
            typer.echo(f"Error: connection tables file not found: {connection_tables_file}", err=True)
            raise typer.Exit(code=2)
        with open(connection_tables_file, encoding="utf-8") as fh:
            conn_tables = json.load(fh)

    summary = tableau_generate.run_generate(
        parsed=parsed,
        translated=translated,
        connection=connection,
        database=database,
        schema=schema,
        table_map=table_map,
        out_dir=out,
        decisions=decisions,
        sql_table_map=sql_table_map,
        connection_tables=conn_tables,
    )

    typer.echo(f"Generated {len(summary['tables'])} table(s), "
               f"{len(summary['sql_views'])} sql_view(s), "
               f"{len(summary['models'])} model(s) in {out}", err=True)
    if summary.get('connection_matched'):
        typer.echo(f"Matched {len(summary['connection_matched'])} table(s) from connection hierarchy (UPPER_SNAKE normalization)", err=True)
    if summary.get('omitted_formulas'):
        typer.echo(f"Omitted {len(summary['omitted_formulas'])} untranslatable formula(s)", err=True)
    if summary.get('sql_remaps'):
        table_remaps = [w for w in summary['sql_remaps'] if w['type'] == 'table_remapped_in_sql']
        param_remaps = [w for w in summary['sql_remaps'] if w['type'] == 'param_removed_from_sql']
        if table_remaps:
            typer.echo(f"Remapped {len(table_remaps)} table reference(s) in SQL view queries", err=True)
        if param_remaps:
            typer.echo(f"Replaced {len(param_remaps)} Tableau parameter ref(s) with NULL in SQL views", err=True)
    if summary.get('decisions_needed'):
        typer.echo(f"{summary['decisions_needed']['count']} formula(s) need LLM decisions — "
                   f"see {summary['decisions_needed']['file']}", err=True)

    print(json.dumps(summary, indent=2))


@app.command("validate")
def validate(
    directory: str = typer.Argument(..., help="Directory of TML files to validate"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="ThoughtSpot profile for VALIDATE_ONLY import"),
    proofread_only: bool = typer.Option(False, "--proofread-only", help="Run local lint only — skip the API call"),
    reset: bool = typer.Option(False, "--reset", help="Reset the attempt counter before validating"),
) -> None:
    """Validate TML files: local proofread + VALIDATE_ONLY import (T5 — deterministic).

    Phase 1 (always): local invariant lint — catches FULL_OUTER, INT (not INT64),
    CASE WHEN in formulas, fqn: in model_tables, missing db_column_properties.

    Phase 2 (with --profile): sends TMLs to ThoughtSpot with VALIDATE_ONLY policy.
    Classifies each per-object error as fixable / locked / warning. Tracks attempt
    count with a hard cap (15).

    Output: JSON report to stdout with {status, attempt, exhausted, fixable, locked, warnings}.
    """
    import os
    from ts_cli.commands import tableau_validate

    if not os.path.isdir(directory):
        typer.echo(f"Error: not a directory: {directory}", err=True)
        raise typer.Exit(code=2)

    if reset:
        tableau_validate.reset_attempts(directory)

    if proofread_only or not profile:
        report = tableau_validate.run_validate(directory, api_response=None)
        print(json.dumps(report, indent=2))
        n_fixable = len(report.get("fixable", []))
        typer.echo(
            f"\nProofread: {n_fixable} fixable issue(s) found. "
            f"(attempt {report['attempt']}/{tableau_validate.HARD_CAP})",
            err=True,
        )
        if n_fixable:
            raise typer.Exit(code=1)
        if not profile:
            typer.echo("Pass --profile to also run VALIDATE_ONLY against the cluster.", err=True)
        return

    # Phase 2: build payload and call VALIDATE_ONLY
    from ts_cli.client import ThoughtSpotClient
    from ts_cli.client import resolve_profile

    payload = tableau_validate.build_payload(directory)
    if not payload:
        typer.echo("Error: no TML files found in directory", err=True)
        raise typer.Exit(code=2)

    has_guid = any("guid:" in tml_str for tml_str in payload)
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={
            "metadata_tmls": payload,
            "import_policy": "VALIDATE_ONLY",
            "create_new": not has_guid,
        },
        timeout=300,
    )
    api_response = resp.json()

    report = tableau_validate.run_validate(directory, api_response=api_response)
    print(json.dumps(report, indent=2))

    n_fixable = len(report.get("fixable", []))
    locked_summary = report.get("locked_summary", {})
    n_locked = locked_summary.get("count", 0)
    n_warnings = len(report.get("warnings", []))
    typer.echo(
        f"\nValidation {report['status']}: {n_fixable} fixable, {n_locked} locked, "
        f"{n_warnings} warning(s). (attempt {report['attempt']}/{tableau_validate.HARD_CAP}"
        f"{', EXHAUSTED' if report['exhausted'] else ''})",
        err=True,
    )
    if n_locked:
        typer.echo(
            f"Locked errors documented in {locked_summary.get('documented_in', 'MIGRATION_LIMITATIONS.md')}",
            err=True,
        )
    if report["status"] != "VALID":
        raise typer.Exit(code=1)


def twb_to_summary_text_from_parsed(parsed: dict) -> str:
    """Render a compact human-readable summary from an already-parsed dict."""
    lines: list = []
    c = _counts(parsed)
    lines.append(
        f"Parsed workbook: {c['datasources']} datasource(s), "
        f"{c['physical_tables']} table(s), {c['custom_sql_sources']} custom-SQL, "
        f"{c['joins']} join(s), {c['calculated_fields']} calc field(s), "
        f"{c['parameters']} parameter(s), "
        f"{c['worksheets']} worksheet(s), {c['dashboards']} dashboard(s)"
    )
    for ds in parsed.get("datasources", []):
        if ds.get("is_parameters"):
            lines.append(f"\n=== Parameters ({len(ds.get('parameters', []))}) ===")
            for p in ds.get("parameters", []):
                lines.append(f"  - {p['caption']} ({p['datatype']}/{p['domain_type']}) = {p['current_value']}")
            continue
        lines.append(f"\n=== Datasource: {ds.get('caption')} ===")
        if ds.get("is_sqlproxy"):
            lines.append("  *** SQLPROXY (published datasource) — no embedded SQL; record as a limitation ***")
            continue
        for t in ds.get("tables", []):
            lines.append(f"  Table: {t['relation_name']} → {t['physical_table']} ({t['type']})")
        for cs in ds.get("custom_sql_sources", []):
            preview = cs["sql_query"][:120].replace("\n", " ")
            lines.append(f"  Custom SQL: {cs['name']}: {preview}")
        for j in ds.get("joins", []):
            lines.append(f"  Join: {j['left_table']} {j['join_type'].upper()} {j['right_table']} ON {j['on_clause']}")
        for cf in ds.get("calculated_fields", []):
            lines.append(f"  Calc [L{cf.get('level', 0)}] {cf['caption']}: {cf['formula'][:120]}")
    if parsed.get("worksheets"):
        lines.append(f"\n=== Worksheets ({len(parsed['worksheets'])}) ===")
        for ws in parsed["worksheets"]:
            lines.append(f"  - {ws['name']}")
    if parsed.get("dashboards"):
        lines.append(f"\n=== Dashboards ({len(parsed['dashboards'])}) ===")
        for db in parsed["dashboards"]:
            sheets = ", ".join(db["worksheets"]) if db["worksheets"] else "(empty)"
            lines.append(f"  - {db['name']} [{db['size'].get('width','?')}x{db['size'].get('height','?')}]: {sheets}")
    return "\n".join(lines)