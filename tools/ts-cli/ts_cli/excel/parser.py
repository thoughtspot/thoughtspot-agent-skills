"""Tokenizer and recursive-descent parser for Excel / Google Sheets formulas.

Grammar covered: a leading ``=``; numbers (``1``, ``1.5``, ``1E3``, ``.5``); strings with doubled
quotes (``"a""b"`` is a"b); ``TRUE`` / ``FALSE``; error literals (``#DIV/0!``); the operators
``+ - * / ^ & = <> < <= > >=``, postfix ``%`` and unary ``-`` / ``+``; function calls, dotted
names included (``STDEV.S``, ``NETWORKDAYS.INTL``; Excel's ``_xlfn.`` / ``_xlws.`` storage
prefixes are stripped); array constants ``{1,2;3,4}``; structured references (``[@Col]``,
``[@[Col Name]]``, ``Table[@Col]``, ``Table[Col]``, ``[Col]``, ``Table[[#This Row],[Col]]``);
A1 references and ranges (``B2``, ``$B$2``, ``B2:B100``, ``B:B``, ``Sheet1!A1``,
``'My Sheet'!A:A``); and bare defined names.

Excel precedence, loosest first: comparison < ``&`` < ``+ -`` < ``* /`` < ``^`` < ``%`` < unary
minus (so ``-2^2`` is 4, as in Excel). All binary operators are left-associative.

``ExcelSyntaxError`` is raised for anything outside that grammar; the caller turns it into
``NEEDS_REVIEW``.
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.excel.nodes import (
    Array, Binary, Bool, Call, Err, Missing, Num, Percent, Ref, Str, Unary,
)


class ExcelSyntaxError(ValueError):
    pass


_NUM = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_ERR = re.compile(r"#(?:DIV/0!|N/A|NAME\?|NULL!|NUM!|REF!|VALUE!|GETTING_DATA|SPILL!|CALC!)", re.I)
_WORD = re.compile(r"[A-Za-z_\\][A-Za-z0-9_.\\]*")
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_A1 = re.compile(rf"({_CELL})(?::({_CELL}))?(?![\w(\[!])")
_COLRANGE = re.compile(r"\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})(?![\w(\[!])")
# Google Sheets' open-ended range: A2:A (from row 2 to the end of column A).
_OPENRANGE = re.compile(rf"({_CELL}):\$?([A-Za-z]{{1,3}})(?![\w(\[!])")
_SHEET = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))!")
_OPS = ("<=", ">=", "<>", "+", "-", "*", "/", "^", "&", "=", "<", ">", "%")
_PREFIXES = ("_XLFN._XLWS.", "_XLFN.", "_XLWS.")


def _bracket_end(text: str, i: int) -> int:
    """Index just past the ``]`` matching the ``[`` at ``i`` (``'`` escapes one char)."""
    depth = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ExcelSyntaxError("unbalanced '[' in a structured reference")


def _unescape(name: str) -> str:
    return re.sub(r"'(.)", r"\1", name).strip()


def _structured(table: Optional[str], inner: str, raw: str) -> Ref:
    """``inner`` is the text between the outer brackets."""
    s = inner.strip()
    if s.startswith("@"):
        col = s[1:].strip()
        if col.startswith("[") and col.endswith("]"):
            col = col[1:-1]
        return Ref(_unescape(col), "row", table, "structured", raw)
    if not s.startswith("["):
        return Ref(_unescape(s), "column", table, "structured", raw)
    parts = [p.strip() for p in re.findall(r"\[((?:[^\[\]']|'.)*)\]", s)]
    if ":" in re.sub(r"\[(?:[^\[\]']|'.)*\]", "", s):
        raise ExcelSyntaxError(f"a multi-column structured reference has no single-column "
                               f"reading: {raw}")
    specials = [p for p in parts if p.startswith("#")]
    cols = [p for p in parts if not p.startswith("#")]
    if len(cols) != 1:
        raise ExcelSyntaxError(f"unsupported structured reference: {raw}")
    grain = "column"
    for sp in specials:
        key = sp.lower()
        if key == "#this row":
            grain = "row"
        elif key not in ("#data",):
            raise ExcelSyntaxError(f"structured-reference item {sp} has no column reading: {raw}")
    return Ref(_unescape(cols[0]), grain, table, "structured", raw)


def _col_letters(cell: str) -> str:
    return re.match(r"\$?([A-Za-z]{1,3})", cell).group(1).upper()


def _a1_ref(m: "re.Match", sheet: Optional[str]) -> Ref:
    start, end = m.group(1), m.group(2)
    col = _col_letters(start)
    if end and _col_letters(end) != col:  # a 2-D block: refused when translated (E5)
        return Ref(col, "block", None, "a1", m.group(0), sheet=sheet)
    return Ref(col, "column" if end else "row", None, "a1", m.group(0), sheet=sheet,
               absolute=start.count("$") == 2 and not end)


def _open_range(m: "re.Match", sheet: Optional[str]) -> Ref:
    col = _col_letters(m.group(1))
    grain = "column" if m.group(2).upper() == col else "block"
    return Ref(col, grain, None, "a1", m.group(0), sheet=sheet)


class _Lexer:
    def __init__(self, text: str):
        self.text = text
        self.i = 0
        self.toks: list[tuple[str, object]] = []

    def run(self) -> list[tuple[str, object]]:
        t = self.text
        while self.i < len(t):
            ch = t[self.i]
            if ch.isspace():
                self.i += 1
            elif ch == '"':
                self._string()
            elif ch.isdigit() or (ch == "." and t[self.i + 1:self.i + 2].isdigit()):
                self._number()
            elif ch == "#":
                self._error()
            elif ch in "{}(),;":
                self.toks.append((ch, ch))
                self.i += 1
            elif ch == "[":
                self._struct(None)
            elif ch in "'$" or ch.isalpha() or ch in "_\\":
                self._word()
            else:
                self._op()
        return self.toks

    def _string(self) -> None:
        m = re.compile(r'"((?:[^"]|"")*)"').match(self.text, self.i)
        if not m:
            raise ExcelSyntaxError("unterminated string literal")
        self.toks.append(("STR", m.group(1).replace('""', '"')))
        self.i = m.end()

    def _number(self) -> None:
        m = _NUM.match(self.text, self.i)
        if self.text[m.end():m.end() + 1] == ":":
            raise ExcelSyntaxError("a whole-row range (1:1) has no column reading")
        self.toks.append(("NUM", m.group(0)))
        self.i = m.end()

    def _error(self) -> None:
        m = _ERR.match(self.text, self.i)
        if not m:
            raise ExcelSyntaxError(f"unexpected '#' at {self.i}")
        self.toks.append(("ERR", m.group(0).upper()))
        self.i = m.end()

    def _op(self) -> None:
        for op in _OPS:
            if self.text.startswith(op, self.i):
                self.toks.append(("OP", op))
                self.i += len(op)
                return
        raise ExcelSyntaxError(f"unexpected character {self.text[self.i]!r} at {self.i}")

    def _struct(self, table: Optional[str], start: Optional[int] = None) -> None:
        begin = self.i if start is None else start
        end = _bracket_end(self.text, self.i)
        inner = self.text[self.i + 1:end - 1]
        self.toks.append(("REF", _structured(table, inner, self.text[begin:end])))
        self.i = end

    def _word(self) -> None:
        t, i = self.text, self.i
        sm = _SHEET.match(t, i)
        if sm:
            sheet = (sm.group(1) or sm.group(2)).replace("''", "'")
            self.i = sm.end()
            self._a1_or_fail(sheet)
            return
        if t[i] == "$":
            self._a1_or_fail(None)
            return
        m = _WORD.match(t, i)
        if not m:
            raise ExcelSyntaxError(f"unexpected character {t[i]!r} at {i}")
        word = m.group(0)
        rest = t[m.end():]
        if re.match(r"\s*\(", rest):
            name = word.upper()
            for p in _PREFIXES:
                if name.startswith(p):
                    name = name[len(p):]
            self.toks.append(("FUNC", name))
            self.i = m.end()
            return
        if word.upper() in ("TRUE", "FALSE"):
            self.toks.append(("BOOL", word.upper() == "TRUE"))
            self.i = m.end()
            return
        if rest.startswith("["):
            self.i = m.end()
            self._struct(word, start=i)
            return
        if self._try_a1(None):
            return
        self.toks.append(("REF", Ref(word, "row", None, "name", word)))
        self.i = m.end()

    def _try_a1(self, sheet: Optional[str]) -> bool:
        for pat, build in ((_COLRANGE, self._colrange), (_OPENRANGE, _open_range),
                           (_A1, _a1_ref)):
            m = pat.match(self.text, self.i)
            if m:
                self.toks.append(("REF", build(m, sheet)))
                self.i = m.end()
                return True
        return False

    @staticmethod
    def _colrange(m: "re.Match", sheet: Optional[str]) -> Ref:
        a, b = m.group(1).upper(), m.group(2).upper()
        return Ref(a, "column" if a == b else "block", None, "a1", m.group(0), sheet=sheet)

    def _a1_or_fail(self, sheet: Optional[str]) -> None:
        if not self._try_a1(sheet):
            raise ExcelSyntaxError(f"expected a cell or range reference at {self.i}")


def tokenize(text: str) -> list[tuple[str, object]]:
    return _Lexer(text).run()


_CMP = ("=", "<>", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        if self.i >= len(self.toks):
            raise ExcelSyntaxError("unexpected end of formula")
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect(self, kind: str):
        tok = self.take()
        if tok[0] != kind:
            raise ExcelSyntaxError(f"expected {kind!r}, got {tok[1]!r}")
        return tok

    def _binary(self, ops, sub):
        left = sub()
        while self.peek()[0] == "OP" and self.peek()[1] in ops:
            op = self.take()[1]
            left = Binary(op, left, sub())
        return left

    def comparison(self):
        return self._binary(_CMP, self.concat)

    def concat(self):
        return self._binary(("&",), self.additive)

    def additive(self):
        return self._binary(("+", "-"), self.multiplicative)

    def multiplicative(self):
        return self._binary(("*", "/"), self.power)

    def power(self):
        return self._binary(("^",), self.percent)

    def percent(self):
        node = self.unary()
        while self.peek() == ("OP", "%"):
            self.take()
            node = Percent(node)
        return node

    def unary(self):
        if self.peek()[0] == "OP" and self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            return Unary(op, self.unary())
        return self.primary()

    def primary(self):
        kind, val = self.peek()
        simple = {"NUM": Num, "STR": Str, "BOOL": Bool, "ERR": Err}
        if kind in simple:
            self.take()
            return simple[kind](val)
        if kind == "REF":
            self.take()
            return val
        if kind == "FUNC":
            return self.call()
        if kind == "(":
            self.take()
            node = self.comparison()
            self.expect(")")
            return node
        if kind == "{":
            return self.array()
        raise ExcelSyntaxError(f"unexpected {val!r}")

    def call(self):
        name = self.take()[1]
        self.expect("(")
        args = []
        if self.peek()[0] != ")":
            args.append(self.argument())
            while self.peek()[0] == ",":
                self.take()
                args.append(self.argument())
        self.expect(")")
        return Call(name, args)

    def argument(self):
        if self.peek()[0] in (",", ")"):
            return Missing()
        return self.comparison()

    def array(self):
        self.expect("{")
        rows, row = [], [self.comparison()]
        while self.peek()[0] in (",", ";"):
            sep = self.take()[0]
            if sep == ";":
                rows.append(row)
                row = []
            row.append(self.comparison())
        rows.append(row)
        self.expect("}")
        return Array(rows)


def parse(text: str):
    """Parse an Excel / Sheets formula (leading ``=`` optional) into a node."""
    src = (text or "").strip()
    if src.startswith("="):
        src = src[1:]
    if not src.strip():
        raise ExcelSyntaxError("empty formula")
    p = _Parser(tokenize(src))
    node = p.comparison()
    if p.i != len(p.toks):
        raise ExcelSyntaxError(f"unexpected {p.toks[p.i][1]!r} after the formula")
    return node
