"""Excel's implicit type coercion, written out (BL-352, BL-353, BL-355; fidelity M1).

Excel converts an argument to the type its slot expects; ThoughtSpot type-checks at import and
rejects the formula instead (error_code 14516). Each helper takes an EMITTED ThoughtSpot node and
returns it in the slot's type, or raises NEEDS_REVIEW where no exact form exists. Types come
from ``typecheck`` (``int`` and ``double`` kept apart — ThoughtSpot's "Numeric" slots take an
integer only).

Live facts these rely on (probe record §7, se-thoughtspot, 2026-10-07):
- ``to_date ( 'text' , '%Y-%m-%d' )`` compiles to ``TO_DATE('text','YYYY-MM-DD')`` (the
  strftime pattern is translated; a Java-style ``'yyyy-MM-dd'`` is passed through verbatim).
- ``diff_days ( d , to_date ( '1899-12-30' , '%Y-%m-%d' ) )`` is Excel's serial number for any
  date from 1900-03-01 on (2000-01-01 → 36526).
- ``floor`` / ``ceil`` return INT64, so they fit an integer slot; ``to_integer`` ROUNDS
  (2.7 → 3, −2.7 → −3), so it is never Excel's truncation.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from ts_cli.excel import tsast as T

EPOCH_TEXT = "1899-12-30"   # Excel serial 0 for dates from 1900-03-01 on
ISO = "%Y-%m-%d"
SERIAL_NOTE = ("Excel's serial numbers: the translation counts days from 1899-12-30, exact for "
               "dates from 1900-03-01 on; Excel's serials 1–60 follow its fictitious 29 Feb "
               "1900 and differ by one day")


LOCALE_TRAP = ("'{text}' was read {order}, the only order that makes it a real date; Excel "
               "reads a slashed date in the workbook's locale, and in the other locale it "
               "returns #VALUE! — an ISO date (yyyy-mm-dd) has no such dependence")


def _call(fn: str, *args: dict) -> dict:
    """A call node this module adds, tagged ``via: coerce`` so ``check_mapping_code_sync``
    can tell a coercion's names (``rules.COERCION_EMITS``) from the handler's own ``emits``."""
    node = T.call(fn, *args)
    node["via"] = "coerce"
    return node


def epoch() -> dict:
    return _call("to_date", T.lit_string(EPOCH_TEXT), T.lit_string(ISO))


def to_date_literal(text: str, pattern: str = ISO) -> dict:
    return _call("to_date", T.lit_string(text), T.lit_string(pattern))


def string_value(node: dict) -> Optional[str]:
    """The text of a string literal node, unquoted, else None."""
    if T.is_lit(node, "string"):
        return node["value"][1:-1].replace("''", "'")
    return None


# ---------------------------------------------------------------------------
# Text that is a date (BL-352)
# ---------------------------------------------------------------------------

_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_ISO_TIME = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})([T ])(\d{1,2}):(\d{2})(?::(\d{2}))?")
_SLASHED = re.compile(r"(\d{1,2})([/.-])(\d{1,2})\2(\d{4})")
_YMD_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def date_pattern(text: str) -> tuple[Optional[str], str]:
    """``(pattern, why)``: the ``to_date`` pattern a date text literal is written in, or
    ``(None, reason)`` when it is not a date, or its day / month order is ambiguous."""
    s = text.strip()
    m = _ISO_TIME.fullmatch(s)
    if m:
        pat = "%Y-%m-%d" + m.group(4) + "%H:%M" + (":%S" if m.group(7) else "")
        return (pat, "") if _valid(s, pat) else (None, f"'{text}' is not a real date-time")
    if _ISO_DATE.fullmatch(s):
        return (ISO, "") if _valid(s, ISO) else (None, f"'{text}' is not a real date")
    if _YMD_SLASH.fullmatch(s):
        return ("%Y/%m/%d", "") if _valid(s, "%Y/%m/%d") else (None, f"'{text}' is not a real "
                                                                     "date")
    m = _SLASHED.fullmatch(s)
    if m:
        a, sep, b = int(m.group(1)), m.group(2), int(m.group(3))
        md, dm = f"%m{sep}%d{sep}%Y", f"%d{sep}%m{sep}%Y"
        if a <= 12 and b <= 12 and a != b:
            return None, (f"'{text}' reads as day/month or month/day — Excel takes the order "
                          "from the workbook's locale, which the formula does not say")
        pat = md if a <= 12 else dm
        return (pat, "") if _valid(s, pat) else (None, f"'{text}' is not a real date")
    return None, (f"'{text}' is not a date Excel would read in every locale (Excel returns "
                  "#VALUE! for text that is not a date)")


def _valid(text: str, pattern: str) -> bool:
    try:
        _dt.datetime.strptime(text, pattern)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Serial numbers (BL-353: a number in a date slot)
# ---------------------------------------------------------------------------

def serial_to_iso(value: Decimal) -> Optional[str]:
    """Excel serial → ISO date, for serials whose Excel date is a real one. Serial 60 is
    Excel's fictitious 29 Feb 1900 and 0 is "1900-01-00": None for both and below 0."""
    whole = int(value.to_integral_value(rounding="ROUND_FLOOR"))
    if whole < 1 or whole == 60:
        return None
    base = _dt.date(1899, 12, 31) if whole < 60 else _dt.date(1899, 12, 30)
    try:
        return (base + _dt.timedelta(days=whole)).isoformat()
    except OverflowError:
        return None


def as_date(tr, node: dict) -> dict:
    """``node`` in a date slot, the way Excel reads it (a date, date text, or a serial)."""
    t = tr.fine_type(node)
    if t in ("date", "datetime") or t is None:
        return node
    text = string_value(node)
    if text is not None:
        pattern, why = date_pattern(text)
        if pattern is None:
            tr.review(f"a text date in a date function: {why}")
        when = _dt.datetime.strptime(text.strip(), pattern).date()
        if when.year < 1900:
            tr.review(f"'{text}' is before 1900: Excel does not read it as a date (#VALUE!)")
        if when < _dt.date(1900, 3, 1):
            tr.trap(SERIAL_NOTE)
        if pattern.startswith(("%d", "%m")):
            tr.trap(LOCALE_TRAP.format(text=text, order="day first" if pattern.startswith("%d")
                                       else "month first"), downgrade=True)
        if "%H" in pattern:
            tr.note(f"'{text}' has a time of day; to_date keeps the date, which is all this "
                    "date function reads")
        return to_date_literal(text, pattern)
    if t in ("int", "double", "number"):
        value = T.number_value(node)
        if value is not None:
            iso = serial_to_iso(value)
            if iso is None:
                tr.review(f"the serial number {value} is a date only in Excel's own 1900 "
                          "calendar (serial 0 is \"1900-01-00\", 60 is 29 Feb 1900, a negative "
                          "serial is #NUM!) — no real date to translate it to")
            return to_date_literal(iso)
        tr.trap(SERIAL_NOTE)
        whole = node if t == "int" else _call("floor", node)
        return _call("add_days", epoch(), whole)
    if t == "text":
        tr.review("a text column in a date function: Excel parses it with the workbook's "
                  "locale, which the formula does not say — convert it with to_date ( x , "
                  "'<pattern>' ) for the column's format")
    tr.review(f"a {t} in a date function has no Excel reading ThoughtSpot can express")


def serial(tr, node: dict) -> dict:
    """A date's Excel serial number (exact from 1900-03-01 on)."""
    tr.trap(SERIAL_NOTE)
    return _call("diff_days", node, epoch())


# ---------------------------------------------------------------------------
# Numbers (BL-353: text and booleans in arithmetic)
# ---------------------------------------------------------------------------

TEXT_NUMBER_TRAP = ("numeric text as a number: Excel converts it, and so does to_double — but "
                    "a value that is not a number FAILS THE WHOLE QUERY (Snowflake: Numeric "
                    "value '…' is not recognized; live 2026-10-07, probe record §7) where Excel "
                    "shows #VALUE! in one cell, and Excel also reads currency, percentages and "
                    "dates in text, which to_double does not")
TRY_DOUBLE = "TRY_TO_DOUBLE({0})"   # NULL for text that is not a number (live 2026-10-07)


def as_number(tr, node: dict) -> dict:
    t = tr.fine_type(node)
    if t == "bool":
        return T.ifelse(node, T.lit_number("1"), T.lit_number("0"))
    if t != "text":
        return node
    text = string_value(node)
    if text is not None:
        try:
            value = Decimal(text.strip())
        except InvalidOperation:
            tr.review(f"the text '{text}' in arithmetic is not a number: Excel returns #VALUE!")
        if not value.is_finite():
            tr.review(f"the text '{text}' in arithmetic is not a number")
        return number_literal(value)
    tr.trap(TEXT_NUMBER_TRAP, downgrade=True)
    return _call("to_double", node)


def number_literal(value) -> dict:
    """A literal for ``value``; a negative one is ``- n``, as the printer writes it."""
    text = format(abs(Decimal(value)), "f")
    return T.unop("-", T.lit_number(text)) if value < 0 else T.lit_number(text)


# ---------------------------------------------------------------------------
# Integer slots (BL-355)
# ---------------------------------------------------------------------------

def as_int(tr, node: dict, signed: bool = False) -> dict:
    """A count or position: Excel truncates a fractional one toward zero. ThoughtSpot's
    integer slots reject a DOUBLE, so it is written out — ``floor ( x )`` (equal to the
    truncation for x ≥ 0; a negative count or position is #VALUE! in Excel), or, for a slot
    that takes negatives (a month offset), ``if ( x < 0 ) then ceil ( x ) else floor ( x )``."""
    node = as_number(tr, node)
    t = tr.fine_type(node)
    if t in ("int", None):
        return node
    value = T.number_value(node)
    if value is not None:
        return number_literal(int(value))      # int() truncates toward zero, like Excel
    if t not in ("double", "number"):
        return node                            # the type checker reports it
    if signed:
        return T.ifelse(T.binop("<", node, T.lit_number("0")), _call("ceil", node),
                        _call("floor", node))
    return _call("floor", node)


# ---------------------------------------------------------------------------
# Text (BL-349, BL-350, BL-353: numbers, booleans and dates in text functions)
# ---------------------------------------------------------------------------

def bool_text(node: dict) -> dict:
    """Excel's TRUE / FALSE as text (``to_string`` gives lower case)."""
    if T.is_lit(node, "bool"):
        return T.lit_string(node["value"].upper())
    return T.ifelse(node, T.lit_string("TRUE"), T.lit_string("FALSE"))


def bool_number(node: dict) -> dict:
    if T.is_lit(node, "bool"):
        return T.lit_number("1" if node["value"] == "true" else "0")
    return T.ifelse(node, T.lit_number("1"), T.lit_number("0"))


def as_text(tr, node: dict, quiet: bool = False) -> dict:
    """``node`` where Excel expects text. ``quiet``: an unknown type is left bare without a
    question (a text function's argument is text in the common case)."""
    t = tr.fine_type(node)
    if t == "text":
        return node
    if t is None:
        if not quiet:
            tr.unknown_text(node)
        return node
    if t == "bool":
        return bool_text(node)                 # BL-349: Excel's TRUE / FALSE
    if t == "date":
        # BL-350: Excel's text functions and & read a date as its serial number
        tr.note("Excel reads a date as its serial number where text is expected (UPPER, LEN, "
                "LEFT, &…), so the translation does too; for the date's text write TEXT() in "
                "the sheet")
        return _call("to_string", serial(tr, node))
    if t == "datetime":
        tr.review("a date-time where Excel expects text is its serial number with a time "
                  "fraction; ThoughtSpot's to_string needs a format for a date-time and has no "
                  "serial form — use TEXT() semantics deliberately (Excel map, TEXT row)")
    value = T.number_value(node)
    if value is not None:
        return T.lit_string(excel_number_text(tr, value))
    if t in ("double", "number"):
        tr.trap(DOUBLE_TEXT_TRAP, downgrade=True)
    return _call("to_string", node)


DOUBLE_TEXT_TRAP = (
    "a DOUBLE or DECIMAL as text: Excel writes the number in General format (up to 15 "
    "significant digits, no trailing zeros, E+ notation from 1E+15); ThoughtSpot's to_string "
    "follows the warehouse type — the column's scale ('95000.00' for a NUMBER(10,2), probe "
    "record §7), Snowflake's float form ('1e+20') or binary noise in the last digits — so "
    "LEN / LEFT / & of it can differ. Exact for an integer column")


def excel_number_text(tr, value: Decimal) -> str:
    """A number literal as Excel's text (General format), for the range where that is plain
    digits: integers below 1E+15 and decimals of at most 15 significant digits from 1E-4.
    Anything else — Excel switches to E+ notation or rounds to 15 digits — is NEEDS_REVIEW."""
    v = Decimal(value)
    digits = len(v.normalize().as_tuple().digits)
    if v == 0:
        return "0"
    if abs(v) >= Decimal("1E15") or digits > 15 or abs(v) < Decimal("1E-4"):
        tr.review(f"the number {v} as text: Excel writes it in General format, with E+ "
                  "notation or rounded to 15 significant digits, which the translator does not "
                  "reproduce — write it as text in the sheet")
    text = format(v.normalize(), "f")
    return text


# ---------------------------------------------------------------------------
# Branches of one IF / IFERROR (BL-354)
# ---------------------------------------------------------------------------

BRANCH_TRAP = ("{fn} branches of different types: an Excel cell holds either, a ThoughtSpot "
               "formula one type, so the {what} became {to} — compare or aggregate it as {to}")


def unify_branches(tr, a: dict, b: dict, fn: str = "IF") -> tuple[dict, dict]:
    """``(a, b)`` in one type. Number beside text: the number as text; boolean beside text:
    'TRUE' / 'FALSE'; boolean beside number: 1 / 0 — each APPROXIMATED with a trap. A date
    beside anything else is left for the type checker (NEEDS_REVIEW)."""
    ta, tb = tr.fine_type(a), tr.fine_type(b)
    for x, tx, other, to in ((a, ta, b, tb), (b, tb, a, ta)):
        if tx is None and x.get("node") in ("col", "ref") and to is not None and \
                not T.is_lit(other, "string", "''"):
            # review of #574: an unknown column beside a typed branch decides the import
            note = (f"column type unknown: {T.to_text(x)} is an {fn} branch beside "
                    f"{T.to_text(other)} ({to}); ThoughtSpot branches must share a type — "
                    "pass data_type in --columns (or --model) to decide")
            tr.note(note)
            tr.need_type(x, "mixed branches", note)
    fam = {"int": "number", "double": "number", "number": "number", "text": "text",
           "bool": "bool"}
    fa, fb = fam.get(ta), fam.get(tb)
    if fa is None or fb is None or fa == fb:
        return a, b
    pair = {fa, fb}
    if pair == {"number", "text"}:
        what, to, conv = "number", "text", lambda x: as_text(tr, x, quiet=True)
        target = "number"
    elif pair == {"bool", "text"}:
        what, to, conv, target = "boolean", "text ('TRUE' / 'FALSE')", bool_text, "bool"
    else:
        what, to, target = "boolean", "a number (1 / 0)", "bool"
        conv = bool_number
    tr.trap(BRANCH_TRAP.format(fn=fn, what=what, to=to), downgrade=True)
    return (conv(a) if fa == target else a), (conv(b) if fb == target else b)
