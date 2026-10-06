"""Read spreadsheet test corpora (LibreOffice ``.fods``, Excel ``.xlsx``) into literal cases.

Stdlib only, and nothing here executes anything from the files: they are parsed as XML
(``xml.etree``) and zip members. Third-party corpora stay OUTSIDE the repo (the data dir,
``literal.resolve_data_dir``); this module is the committed code that reads them.

A *raw case* is one formula cell plus everything needed to re-evaluate it elsewhere:

    {"formula": "=ROUND(A1,B1)",            # Excel syntax, inputs rewritten to row 1
     "inputs": [{"letter": "A", "cell": "K2", "kind": "num", "value": 2.5}, ...],
     "expected": {"t": "num", "v": "3"},    # canonical (compare.py) form
     "tolerance": {"rel": 1e-12},
     "functions": ["ROUND"], "flags": [...]}

or a refusal ``{"skip": "<reason>"}``. Skips are counted, never silently dropped.
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any, Optional

T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
CALC = "{urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0}"
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

EXCEL_EPOCH = _dt.date(1899, 12, 30)   # serial 60 is Excel's fictitious 1900-02-29
MIN_SAFE_DATE = _dt.date(1900, 3, 1)   # below this Excel and LibreOffice serials disagree
ERROR_CODES = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A")

# Never comparable with a ThoughtSpot formula: volatile, positional, or about the sheet.
EXCLUDED_FUNCTIONS = {
    "NOW", "TODAY", "RAND", "RANDBETWEEN", "INFO", "CELL", "INDIRECT", "OFFSET", "ROW",
    "COLUMN", "ROWS", "COLUMNS", "ISREF", "ADDRESS", "FORMULA", "ISFORMULA", "HYPERLINK",
    "SHEET", "SHEETS", "FORMULATEXT", "AREAS", "ERROR.TYPE", "CURRENT",
}


class Cell:
    __slots__ = ("formula", "kind", "value", "error")

    def __init__(self, formula: Optional[str], kind: str, value: Any, error: bool = False):
        self.formula, self.kind, self.value, self.error = formula, kind, value, error

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Cell({self.formula!r}, {self.kind}, {self.value!r})"


# =====================================================================================
# Cell addressing
# =====================================================================================

def col_letters(n: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def serial_to_date(serial: float) -> Optional[_dt.date]:
    """Excel 1900-system serial -> date; None below 1900-03-01, where the systems disagree."""
    if serial < 61:
        return None
    return EXCEL_EPOCH + _dt.timedelta(days=int(serial))


def date_to_serial(d: _dt.date) -> int:
    return (d - EXCEL_EPOCH).days


# =====================================================================================
# LibreOffice flat ODS
# =====================================================================================

def _fods_cell(c) -> Optional[Cell]:
    f = c.get(T + "formula")
    vt = c.get(O + "value-type")
    calc = c.get(CALC + "value-type")
    if vt is None and f is None:
        txt = "".join(c.itertext()).strip()
        return Cell(None, "str", txt) if txt else None
    err = calc == "error"
    if err:
        txt = "".join(c.itertext()).strip()
        return Cell(f, "error", txt, error=True)
    if vt in ("float", "percentage", "currency"):
        return Cell(f, "num", c.get(O + "value"))
    if vt == "date":
        return Cell(f, "date", c.get(O + "date-value"))
    if vt == "boolean":
        return Cell(f, "bool", c.get(O + "boolean-value") == "true")
    if vt == "time":
        return Cell(f, "time", c.get(O + "time-value"))
    if vt == "string":
        sv = c.get(O + "string-value")
        if sv is None:
            sv = "\n".join("".join(p.itertext()) for p in
                           c.findall("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"))
        return Cell(f, "str", sv)
    return Cell(f, "unknown", None)


def read_fods(path) -> dict[str, dict[str, Cell]]:
    """Every non-empty cell, per sheet, keyed by A1 address. Repeated runs are expanded
    (capped, since empty repeats can span a million rows)."""
    root = ET.parse(path).getroot()
    out: dict[str, dict[str, Cell]] = {}
    for t in root.iter(T + "table"):
        name = t.get(T + "name") or ""
        if name.startswith("'file:"):
            continue  # linked-sheet cache, not part of this test file
        cells: dict[str, Cell] = {}
        row = 0
        for r in t.iter(T + "table-row"):
            rrep = int(r.get(T + "number-rows-repeated", "1"))
            col = 0
            row_cells = []
            for c in r:
                if c.tag not in (T + "table-cell", T + "covered-table-cell"):
                    continue
                crep = int(c.get(T + "number-columns-repeated", "1"))
                cell = _fods_cell(c)
                if cell is not None:
                    for k in range(min(crep, 64)):
                        row_cells.append((col + k + 1, cell))
                col += crep
            for k in range(min(rrep, 64) if row_cells else 0):
                for cn, cell in row_cells:
                    cells[f"{col_letters(cn)}{row + k + 1}"] = cell
            row += rrep
        out[name] = cells
    return out


def lo_case_rows(sheet: dict[str, Cell]) -> list[int]:
    """Rows of a LibreOffice function-test sheet (header ``Function | Expected``)."""
    a1, b1 = sheet.get("A1"), sheet.get("B1")
    if not (a1 and b1 and a1.value == "Function" and b1.value == "Expected"):
        return []
    rows = sorted({int(re.sub(r"^[A-Z]+", "", k)) for k in sheet if k.startswith("A")})
    return [r for r in rows if r > 1 and sheet.get(f"A{r}") and sheet[f"A{r}"].formula]


# OpenFormula -> Excel syntax --------------------------------------------------------

_OF_TOKEN = re.compile(r'"(?:[^"]|"")*"|\[[^\]]*\]|.', re.S)
_OF_CELL = re.compile(r"^\$?\.\$?([A-Z]{1,3})\$?(\d+)$")


def of_tokens(formula: str) -> list[tuple[str, str]]:
    """OpenFormula text -> tokens ``(kind, text)``; kind is str|ref|badref|op."""
    body = formula[3:] if formula.startswith("of:") else formula
    body = body[1:] if body.startswith("=") else body
    out = []
    depth_brace = 0
    for m in _OF_TOKEN.finditer(body):
        tok = m.group(0)
        if tok.startswith('"'):
            out.append(("str", tok))
        elif tok.startswith("["):
            inner = tok[1:-1]
            cm = _OF_CELL.match(inner)
            out.append(("ref", cm.group(1) + cm.group(2)) if cm else ("badref", inner))
        elif tok == "{":
            depth_brace += 1
            out.append(("op", "{"))
        elif tok == "}":
            depth_brace -= 1
            out.append(("op", "}"))
        elif tok == ";":
            out.append(("op", ","))
        elif tok == "|" and depth_brace:
            out.append(("op", ";"))
        elif tok in ("~", "!"):
            out.append(("badop", tok))
        else:
            out.append(("op", tok))
    return _merge_ops(out)


_XL_TOKEN = re.compile(
    r'"(?:[^"]|"")*"'                                  # string literal
    r"|#(?:NULL!|DIV/0!|VALUE!|REF!|NAME\?|NUM!|N/A)"   # error literal
    r"|'[^']*'!\$?[A-Z]{1,3}\$?\d+|[A-Za-z0-9_]+!\$?[A-Z]{1,3}\$?\d+"  # sheet ref
    r"|\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![A-Za-z0-9_(])"   # cell / range
    r"|[A-Za-z_][A-Za-z0-9_.]*"                          # name / function
    r"|.", re.S)


def xl_tokens(formula: str) -> list[tuple[str, str]]:
    """Excel formula text -> tokens, the same shape as ``of_tokens``."""
    body = formula[1:] if formula.startswith("=") else formula
    out = []
    for m in _XL_TOKEN.finditer(body):
        tok = m.group(0)
        if tok.startswith('"'):
            out.append(("str", tok))
        elif "!" in tok and not tok.startswith("#"):
            out.append(("badref", tok))
        elif re.fullmatch(r"\$?[A-Z]{1,3}\$?\d+", tok):
            out.append(("ref", tok.replace("$", "")))
        elif ":" in tok and re.fullmatch(r"[$A-Z0-9:]+", tok):
            out.append(("badref", tok))
        else:
            out.append(("op", tok))
    return _merge_ops(out)


def _merge_ops(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for kind, text in tokens:
        if kind == "op" and merged and merged[-1][0] == "op":
            merged[-1] = ("op", merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return merged


_FUNC = re.compile(r"(?:_xlfn\.|_xlws\.|COM\.MICROSOFT\.)?([A-Za-z][A-Za-z0-9_.]*)\s*\(")


def functions_in(tokens: list[tuple[str, str]]) -> list[str]:
    names = []
    for kind, text in tokens:
        if kind == "op":
            names += [n.upper() for n in _FUNC.findall(text)]
    return names


def render(tokens: list[tuple[str, str]], letters: dict[str, str], row: int = 1) -> str:
    """Tokens back to an Excel formula with each input cell renamed (``K2`` -> ``A1``)."""
    out = []
    for kind, text in tokens:
        if kind == "ref":
            out.append(f"{letters[text]}{row}")
        elif kind == "op":
            out.append(re.sub(r"(?:_xlfn\.|_xlws\.|COM\.MICROSOFT\.)", "", text))
        else:
            out.append(text)
    return "=" + "".join(out)


# =====================================================================================
# Excel xlsx (cached values)
# =====================================================================================

_BUILTIN_DATE_FMTS = set(range(14, 23)) | {45, 46, 47}


def _is_date_format(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code or "")
    return bool(re.search(r"[dmyDMY]", code)) and not re.fullmatch(r"[0#.,%E+\-@ ]*", code)


def read_xlsx(path) -> dict[str, dict[str, Cell]]:
    """Every non-empty cell per sheet with its formula (if any) and Excel's cached value."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(X + "si"):
                shared.append("".join(t.text or "" for t in si.iter(X + "t")))
        date_styles: set[int] = set()
        if "xl/styles.xml" in names:
            st = ET.fromstring(z.read("xl/styles.xml"))
            custom = {int(n.get("numFmtId")): n.get("formatCode") or ""
                      for n in st.iter(X + "numFmt")}
            xfs = st.find(X + "cellXfs")
            for i, xf in enumerate(list(xfs) if xfs is not None else []):
                fid = int(xf.get("numFmtId", "0"))
                if fid in _BUILTIN_DATE_FMTS or (fid in custom and _is_date_format(custom[fid])):
                    date_styles.add(i)
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        out: dict[str, dict[str, Cell]] = {}
        for s in wb.iter(X + "sheet"):
            t = target[s.get(R + "id")].lstrip("/")
            t = t if t.startswith("xl/") else "xl/" + t
            cells: dict[str, Cell] = {}
            for c in ET.fromstring(z.read(t)).iter(X + "c"):
                ref, typ = c.get("r"), c.get("t", "n")
                fe, ve = c.find(X + "f"), c.find(X + "v")
                f = ("=" + fe.text) if fe is not None and fe.text else None
                if fe is not None and not fe.text:
                    f = "<shared>"
                v = ve.text if ve is not None else None
                if typ == "s" and v is not None:
                    cell = Cell(f, "str", shared[int(v)])
                elif typ in ("str", "inlineStr"):
                    if typ == "inlineStr":
                        v = "".join(x.text or "" for x in c.iter(X + "t"))
                    cell = Cell(f, "str", v or "")
                elif typ == "b":
                    cell = Cell(f, "bool", v == "1")
                elif typ == "e":
                    cell = Cell(f, "error", v, error=True)
                elif v is None:
                    if f is None:
                        continue
                    cell = Cell(f, "none", None)
                elif int(c.get("s", "0")) in date_styles:
                    cell = Cell(f, "serial-date", v)
                else:
                    cell = Cell(f, "num", v)
                cells[ref] = cell
            out[s.get("name")] = cells
    return out


# =====================================================================================
# One formula cell -> raw case
# =====================================================================================

def _canon_number(text: str) -> dict:
    d = Decimal(text)
    if d == d.to_integral_value() and abs(d) < Decimal("1e15"):
        return {"t": "num", "v": str(int(d))}
    return {"t": "num", "v": format(d, "f") if abs(d) >= Decimal("1e-6") else str(d)}


def canon_cell(cell: Cell, date_hint: bool = False) -> Optional[dict]:
    """A cell's value in compare.py's canonical form; None if it cannot be represented."""
    k = cell.kind
    if k == "error":
        code = (cell.value or "").strip()
        return {"t": "error", "v": code if code in ERROR_CODES else (code or "#ERROR")}
    if k == "bool":
        return {"t": "bool", "v": bool(cell.value)}
    if k == "str":
        return {"t": "str", "v": cell.value}
    if k == "date":
        v = cell.value or ""
        if "T" in v:
            dt = _dt.datetime.fromisoformat(v)
            if dt.time() != _dt.time(0):
                return {"t": "datetime", "v": dt.isoformat(timespec="seconds")}
            v = dt.date().isoformat()
        d = _dt.date.fromisoformat(v)
        return {"t": "date", "v": d.isoformat()} if d >= MIN_SAFE_DATE else None
    if k in ("num", "serial-date"):
        if cell.value is None:
            return None
        if k == "serial-date" or date_hint:
            f = float(cell.value)
            if f != int(f):
                return None  # a date-time serial: not compared in M1
            d = serial_to_date(f)
            return {"t": "date", "v": d.isoformat()} if d else None
        return _canon_number(cell.value)
    return None


_ROUND_IN_CHECK = re.compile(r"ROUND\([^;,]*\[\.?[A-Z]+\d+\][;,]\s*(-?\d+)\)", re.I)


def tolerance_from_check(check_formula: Optional[str]) -> dict:
    """LibreOffice's ``Correct`` cell states the comparison the corpus itself uses: a
    ``ROUND(result; n) = expected`` check means agreement to n decimals."""
    if check_formula:
        m = _ROUND_IN_CHECK.search(check_formula)
        if m:
            n = int(m.group(1))
            return {"abs": float(Decimal("0.5") * Decimal(10) ** -n), "rel": 1e-12}
    return {"rel": 1e-12}


DATE_RESULT_FUNCTIONS = {"DATE", "EDATE", "EOMONTH", "WORKDAY", "WORKDAY.INTL", "DATEVALUE"}


# A bare identifier that is not a function call: a defined name / named expression.
_BARE_NAME = re.compile(r"(?<![A-Za-z0-9_.#/])([A-Za-z_][A-Za-z0-9_.]*)(?![A-Za-z0-9_.]|\s*\()")


def build_case(tokens: list[tuple[str, str]], sheet: dict[str, Cell], expected: Optional[dict],
               tolerance: dict, max_inputs: int = 6) -> dict:
    """Common tail: inputs resolved from the sheet, refs renamed, refusals named."""
    kinds = {k for k, _ in tokens}
    if "badref" in kinds:
        return {"skip": "range or other-sheet reference"}
    if "badop" in kinds:
        return {"skip": "union / intersection operator"}
    fns = functions_in(tokens)
    if any(f in EXCLUDED_FUNCTIONS for f in fns):
        return {"skip": "volatile or sheet-positional function"}
    if any(f.startswith(("ORG.", "LEGACY.")) for f in fns):
        return {"skip": "LibreOffice-only function"}
    if any("{" in t for k, t in tokens if k == "op"):
        return {"skip": "inline array"}
    if any(n.upper() not in ("TRUE", "FALSE") for k, t in tokens if k == "op"
           for n in _BARE_NAME.findall(t)):
        return {"skip": "named expression (a defined name, not a cell)"}
    if expected is None:
        return {"skip": "expected value not representable"}
    refs = []
    for k, t in tokens:
        if k == "ref" and t not in refs:
            refs.append(t)
    if len(refs) > max_inputs:
        return {"skip": f"more than {max_inputs} input cells"}
    inputs, letters = [], {}
    for i, ref in enumerate(refs):
        letters[ref] = col_letters(i + 1)
        cell = sheet.get(ref)
        if cell is None:
            inputs.append({"letter": letters[ref], "cell": ref, "kind": "blank", "value": None})
            continue
        if cell.kind == "error":
            return {"skip": "an input cell holds an error value"}
        if cell.kind in ("date",):
            c = canon_cell(cell)
            if c is None or c["t"] != "date":
                return {"skip": "input date not representable"}
            inputs.append({"letter": letters[ref], "cell": ref, "kind": "date", "value": c["v"]})
        elif cell.kind == "serial-date":
            c = canon_cell(cell)
            if c is None:
                return {"skip": "input date not representable"}
            inputs.append({"letter": letters[ref], "cell": ref, "kind": "date", "value": c["v"]})
        elif cell.kind == "num":
            inputs.append({"letter": letters[ref], "cell": ref, "kind": "num",
                           "value": float(cell.value)})
        elif cell.kind == "bool":
            inputs.append({"letter": letters[ref], "cell": ref, "kind": "bool",
                           "value": bool(cell.value)})
        elif cell.kind == "str":
            if cell.value == "":
                inputs.append({"letter": letters[ref], "cell": ref, "kind": "str", "value": ""})
            else:
                inputs.append({"letter": letters[ref], "cell": ref, "kind": "str",
                               "value": cell.value})
        else:
            return {"skip": f"input cell kind {cell.kind}"}
    flags = []
    if any(i["kind"] == "blank" for i in inputs):
        flags.append("blank-input")
    if expected["t"] == "error":
        flags.append("error-expected")
    return {"formula": render(tokens, letters), "tokens": tokens, "letters": letters,
            "inputs": inputs, "expected": expected, "tolerance": tolerance,
            "functions": sorted(set(fns)), "flags": flags}


# LibreOffice stores Excel's CEILING / FLOOR as COM.MICROSOFT.CEILING / .FLOOR; the bare
# names are the ODF functions, whose sign and mode rules differ. Only the prefixed ones are
# Excel cases.
_ODF_ONLY_SEMANTICS = re.compile(r"(?<![A-Za-z0-9_.])(?:CEILING|FLOOR)\s*\(")


def lo_case(sheets: dict[str, dict[str, Cell]], sheet_name: str, row: int) -> dict:
    sheet = sheets.get(sheet_name) or {}
    fcell, ecell = sheet.get(f"A{row}"), sheet.get(f"B{row}")
    if fcell is None or not fcell.formula:
        return {"skip": "no formula at locator"}
    if ecell is None or ecell.formula:
        return {"skip": "expected value is computed in-sheet, not literal"}
    if _ODF_ONLY_SEMANTICS.search(fcell.formula):
        return {"skip": "OpenFormula CEILING/FLOOR (ODF semantics, not Excel's)"}
    tokens = of_tokens(fcell.formula)
    fns = functions_in(tokens)
    if fcell.kind == "error":
        expected = canon_cell(fcell)  # LibreOffice's own result is the error the test pins
        if ecell.kind == "str" and ecell.value in ERROR_CODES:
            expected = {"t": "error", "v": ecell.value}
        elif ecell.kind != "str":
            return {"skip": "error result against a non-error expected"}
        # Err:502 is "invalid argument" (Excel's #NUM! / #VALUE! class). Other Err:5xx codes
        # (e.g. 511, a missing argument) mark formulas Excel would not accept at all.
        if expected and expected["v"].startswith("Err:") and expected["v"] != "Err:502":
            return {"skip": "LibreOffice-specific error code (not a valid Excel formula)"}
    elif fcell.kind == "time" or ecell.kind == "time":
        return {"skip": "time-of-day value"}
    else:
        date_hint = fcell.kind == "date" or (fns and fns[0] in DATE_RESULT_FUNCTIONS
                                             and ecell.kind == "num")
        expected = canon_cell(ecell, date_hint=date_hint)
        if expected and fcell.kind == "bool" and expected["t"] == "num":
            expected = {"t": "bool", "v": Decimal(expected["v"]) != 0}
        if expected and fcell.kind == "num" and expected["t"] == "bool":
            expected = {"t": "num", "v": "1" if expected["v"] else "0"}
    check = sheet.get(f"C{row}")
    return build_case(tokens, sheet, expected, tolerance_from_check(check.formula if check else None))


def xlsx_case(sheets: dict[str, dict[str, Cell]], sheet_name: str, ref: str) -> dict:
    sheet = sheets.get(sheet_name) or {}
    cell = sheet.get(ref)
    if cell is None or not cell.formula or cell.formula == "<shared>":
        return {"skip": "no formula text at locator"}
    tokens = xl_tokens(cell.formula)
    fns = functions_in(tokens)
    if cell.kind == "none":
        return {"skip": "no cached value"}
    date_hint = bool(fns) and fns[0] in DATE_RESULT_FUNCTIONS and cell.kind == "num"
    expected = canon_cell(cell, date_hint=date_hint)
    return build_case(tokens, sheet, expected, {"rel": 1e-12})


def tokens_text(tokens: list[tuple[str, str]]) -> str:
    return "".join(t for _, t in tokens)
