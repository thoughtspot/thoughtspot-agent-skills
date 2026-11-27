"""IN-set checks for the Power BI main DAX path (``translate_dax``).

``in_set_reason`` gives a NEEDS-REVIEW reason for an IN set ``translate_dax`` cannot write
exactly: one whose result is negated or compared (a blank is FALSE in DAX and NULL in
ThoughtSpot, BL-610), one spelled other than ``IN {…}`` or beside a comment, a set mixing
strings with other values, or a member that is not a literal. Split out of
``functions.py``, which imports it inside ``translate_dax`` (this module imports the
splitter helpers from there)."""
from __future__ import annotations

import re

from ts_cli.powerbi.functions import DAX_STRING, _opaque_end, _split_args

_IN_SET_AT = re.compile(r"IN\s*\{", re.I)
_NUMBER_LITERAL = re.compile(r"-?\d+(?:\.\d+)?")


def _in_sets(src: str):
    """``(start, end, members)`` for each ``IN { … }`` set in DAX ``src``: ``start`` is
    where the IN keyword begins, ``end`` just past the closing brace, ``members`` the set's
    trimmed members. Quoted text and [columns] are skipped, so an IN or a brace inside
    them is not a set."""
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'[":
            i = _opaque_end(src, i)
            continue
        m = _IN_SET_AT.match(src, i)
        if m and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            j = m.end()
            while j < n and src[j] != "}":
                j = _opaque_end(src, j) if src[j] in "\"'[" else j + 1
            yield i, min(j + 1, n), [a.strip() for a in _split_args(src[m.end():j])]
            i = j + 1
            continue
        i += 1


_WORD = re.compile(r"[A-Za-z_]\w*")
_COMPARISON = re.compile(r"<>|<=|>=|==|[=<>]")
# A bare paren and these calls hand on their operands' truth value, so a set inside one
# reaches whatever compares the group. Any other call gives a value of its own, except
# that the value arguments of these hand a set's truth on too: IF's then and else (not its
# condition), SWITCH's from its second, every argument of IFERROR and COALESCE.
_TRUTH_PASSING = frozenset({None, "AND", "OR", "NOT"})
_BRANCH_PASSING = {"IF": 1, "SWITCH": 1, "IFERROR": 0, "COALESCE": 0}
# A blank test over a set compares it: DAX's FALSE is not blank, ThoughtSpot's NULL is.
_BLANK_TESTS = frozenset({"ISBLANK", "ISEMPTY"})


class _Level:
    """One paren or brace level of ``_in_set_negated``'s scan."""
    __slots__ = ("inherited", "passes_truth", "fn", "arg", "nots", "compared",
                 "left_has_set", "has_set", "passes_out")

    def __init__(self, inherited: bool, fn=None, opener: str = "("):
        self.inherited = inherited          # an enclosing NOT or comparison covers it all
        self.fn = fn if opener == "(" else "{"   # the call's name; None for a bare paren
        self.passes_truth = opener == "(" and fn in _TRUTH_PASSING  # bare (, AND(, OR(, NOT(
        self.arg = 0                        # which argument the scan is in
        self.passes_out = False             # a set reached a value argument (IF's then/else)
        self.nots = 0                       # NOTs whose operand is still open here
        self.compared = False               # a comparison's right operand is open here
        self.left_has_set = False           # the operand since the last && || , holds a set
        self.has_set = False

    def negating(self) -> bool:
        return self.inherited or self.nots > 0 or self.compared

    def end_operand(self) -> None:          # && || or , on this level
        self.nots, self.compared, self.left_has_set = 0, False, False

    def mark_set(self) -> None:             # a set's truth value reaches this level
        self.left_has_set = self.has_set = True
        start = _BRANCH_PASSING.get(self.fn)
        if start is not None and self.arg >= start:
            self.passes_out = True


def _in_set_negated(src: str, spans) -> bool:
    """True when an IN set's result is negated or compared, however it is spelled: under a
    NOT (``NOT T[s] IN {…}``, ``NOT UPPER(T[s]) IN {…}``, ``NOT (x && T[s] IN {…})``,
    ``NOT OR(x, T[s] IN {…})``), or an operand of a comparison (``T[s] IN {…} = FALSE``,
    ``<> TRUE``, ``FALSE = (T[s] IN {…})``, ``(T[s] IN {…} && x) = FALSE``). A blank ``s``
    is not in the set: FALSE in DAX, NULL in ThoughtSpot. As a condition the two agree,
    both taking ``else``; negated or compared they do not.

    One linear pass over ``spans`` (``(start, end)`` of each set). DAX binds NOT looser than
    a comparison or IN and tighter than ``&&`` / ``||``, so the operand of a NOT, and the
    right operand of a comparison, run to the next ``&&``, ``||`` or ``,`` on their own
    level or to that level's end; a comparison's left operand runs back to the last of
    those. A bare paren, AND(, OR( and NOT( pass a set they hold out to that left operand;
    IF( and other calls do not, so ``IF(T[s] IN {…}, 1, 0) = 1`` still translates.
    Conservative: ``X = T[s] IN {…}``, which DAX reads ``(X = T[s]) IN {…}``, refuses."""
    ends = dict(spans)
    levels = [_Level(False)]
    word, i, n = None, 0, len(src)
    while i < n:
        lvl, ch = levels[-1], src[i]
        if i in ends:
            if lvl.negating():
                return True
            lvl.mark_set()
            word, i = None, ends[i]
        elif ch in "\"'[":
            word, i = None, _opaque_end(src, i)
        elif ch.isascii() and (ch.isalpha() or ch == "_"):   # _WORD's own first class
            m = _WORD.match(src, i)
            word = m.group(0).upper()
            lvl.nots += word == "NOT"
            i = m.end()
        elif ch.isspace():
            i += 1
        else:
            i = _scan_operator(src, i, levels, word)
            if i < 0:
                return True
            word = None
    return False


def _scan_operator(src: str, i: int, levels: list, word) -> int:
    """``_in_set_negated``'s step over the bracket or operator at ``i``, updating
    ``levels``: the index after it, or -1 when it compares an operand holding a set.
    ``word`` is the name just before it, if any, to tell AND( from IF(."""
    lvl, ch = levels[-1], src[i]
    if ch in "({":
        levels.append(_Level(lvl.negating(), word, ch))
    elif ch in ")}":
        if len(levels) > 1:
            done = levels.pop()
            if done.fn in _BLANK_TESTS and done.has_set:
                return -1
            if (done.passes_truth and done.has_set) or done.passes_out:
                if levels[-1].negating():
                    return -1
                levels[-1].mark_set()
    elif ch == "," or src.startswith(("&&", "||"), i):
        lvl.end_operand()
        lvl.arg += ch == ","
        return i + (1 if ch == "," else 2)
    else:
        m = _COMPARISON.match(src, i)
        if m:
            if lvl.left_has_set:
                return -1
            lvl.compared = True
            return m.end()
    return i + 1


_IN_WORD = re.compile(r"IN\b", re.I)
_IN_THEN_BRACE = re.compile(r"IN\s*\{", re.I)
_COMMENT_START = re.compile(r"//|--|/\*")


def _in_not_before_brace(src: str) -> bool:
    """True when an IN keyword outside quoted text is not followed by optional whitespace
    and ``{``. ``_in_sets`` and the negation scan read only that spelling; ThoughtSpot's
    ``in`` needs it too, so anything else (``IN ({…})``, ``IN /*c*/ {…}``, ``IN VALUES(…)``)
    is refused rather than passed through unchecked."""
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'[":
            i = _opaque_end(src, i)
            continue
        if (_IN_WORD.match(src, i) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_"))
                and not _IN_THEN_BRACE.match(src, i)):
            return True
        i += 1
    return False


def in_set_reason(src: str):
    """A NEEDS-REVIEW reason for an IN set ``translate_dax`` cannot write exactly, else
    None. Three shapes (the gated parser reads only literal sets with nothing negating or
    comparing them, so it refuses the first and third, and writes the second exactly):

    * The set's result negated or compared (``_in_set_negated``): ``NOT T[s] IN {"a"}``,
      ``T[s] IN {"a"} = FALSE``. A blank ``s`` is not in the set, so DAX gives FALSE and
      its negation TRUE; ThoughtSpot's ``NULL in { … }`` is NULL, and so is its negation,
      which falls to ``else``. Inferred from DAX and SQL semantics, not probed (BL-610).
    * A set mixing a string with anything else (``{"a", 1}``, ``{"a", TRUE}``). DAX
      compares it as text, each number in its own canonical form (``1.50`` as ``"1.5"``).
      The gated parser writes a plain integer as its text (``plain_int64``); this path
      rewrites no literal, so it would emit the bare value against a text column, and it
      refuses every mixed set.
    * A member that is not a string or number literal: a row constructor
      (``(T[a], T[b]) IN {("x", 1)}``), a column, or an expression. ThoughtSpot's ``in``
      takes a list of literals."""
    if _in_not_before_brace(src):
        return ("an IN keyword is not followed directly by its { } set (IN ({ }), a "
                "comment between them, or a table expression); rebuild by hand")
    sets = list(_in_sets(src))
    if sets and _COMMENT_START.search(DAX_STRING.sub('""', src)):
        return ("an IN set in a measure that carries a comment, which can hide an operator "
                "the IN checks rely on; rebuild by hand")
    if _in_set_negated(src, ((start, end) for start, end, _ in sets)):
        return ("an IN set's result is negated or compared (NOT, = FALSE, <> TRUE): a blank "
                "value is FALSE in DAX but NULL in ThoughtSpot (BL-610); rebuild by hand")
    for _, _, members in sets:
        strings = [bool(DAX_STRING.fullmatch(v)) for v in members if v]
        if any(strings) and not all(strings):
            return ("an IN set mixes strings with other values, which DAX compares as "
                    "text (1.50 as \"1.5\"); rebuild by hand")
        if not all(DAX_STRING.fullmatch(v) or _NUMBER_LITERAL.fullmatch(v) for v in members):
            return ("an IN set member is not a string or number literal (a row "
                    "constructor, a column or an expression), and ThoughtSpot's in takes a "
                    "list of literals; rebuild by hand")
    return None
