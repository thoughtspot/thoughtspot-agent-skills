"""The translator's function rule table — one entry per Excel / Sheets function it handles.

Each entry names the map row it implements (``map``: ``excel`` or ``sheets``; ``row`` when the
row's name differs from the key) and every ThoughtSpot function name the handler can emit
(``emits``). The rule data is a plain literal so ``tools/validate/check_mapping_code_sync.py``
can read it with ``ast`` and assert, for every entry:

- the map has the row;
- every name in ``emits`` appears in that row's text (the code emits only what the row says);
- the map's *Translator coverage* list names exactly these keys (the doc says which rows the
  translator backs, and cannot claim more or fewer).

``functions.HANDLERS`` / ``SHEETS_HANDLERS`` must have exactly these keys (a test asserts it).
A function without an entry is never guessed: the translator returns NEEDS_REVIEW citing the
map row (``map_index.cite``).
"""
from __future__ import annotations

FUNCTION_RULES = {
    # --- Math and trigonometry
    "ABS": {"map": "excel", "emits": ("abs",)},
    "CEILING": {"map": "excel", "emits": ("ceil",)},
    "CEILING.MATH": {"map": "excel", "emits": ("ceil",)},
    "EXP": {"map": "excel", "emits": ("exp",)},
    "FLOOR": {"map": "excel", "emits": ("floor",)},
    "INT": {"map": "excel", "emits": ("floor",)},
    "LN": {"map": "excel", "emits": ("ln",)},
    "LOG10": {"map": "excel", "emits": ("log10",)},
    "MOD": {"map": "excel", "emits": ("floor",)},
    "MROUND": {"map": "excel", "emits": ("round", "abs")},
    "POWER": {"map": "excel", "emits": ("pow",)},
    "ROUND": {"map": "excel", "emits": ("round", "sql_double_op")},
    "ROUNDDOWN": {"map": "excel", "emits": ("floor", "ceil")},
    "ROUNDUP": {"map": "excel", "emits": ("ceil", "floor", "quarter_number")},
    "SIGN": {"map": "excel", "emits": ()},
    "SQRT": {"map": "excel", "emits": ("sqrt",)},
    "SUM": {"map": "excel", "emits": ("sum",)},
    "SUMIF": {"map": "excel", "emits": ("sum_if",)},
    "SUMIFS": {"map": "excel", "emits": ("sum_if",)},
    # --- Statistical
    "AVERAGE": {"map": "excel", "emits": ("average",)},
    "AVERAGEIF": {"map": "excel", "emits": ("average_if",)},
    "AVERAGEIFS": {"map": "excel", "emits": ("average_if",)},
    "COUNT": {"map": "excel", "emits": ("count",)},
    "COUNTA": {"map": "excel", "emits": ("count",)},
    "COUNTIF": {"map": "excel", "emits": ("count_if",)},
    "COUNTIFS": {"map": "excel", "emits": ("count_if",)},
    "MAX": {"map": "excel", "emits": ("max", "greatest")},
    "MAXIFS": {"map": "excel", "emits": ("max_if",)},
    "MEDIAN": {"map": "excel", "emits": ("median",)},
    "MIN": {"map": "excel", "emits": ("min", "least")},
    "MINIFS": {"map": "excel", "emits": ("min_if",)},
    "STDEV.S": {"map": "excel", "emits": ("stddev",)},
    "VAR.S": {"map": "excel", "emits": ("variance",)},
    # --- Text
    "CONCAT": {"map": "excel", "emits": ("concat", "to_string")},
    "CONCATENATE": {"map": "excel", "emits": ("concat",)},
    "EXACT": {"map": "excel", "emits": ("sql_bool_op",)},
    "FIND": {"map": "excel", "emits": ("sql_int_op",)},
    "LEFT": {"map": "excel", "emits": ("left",)},
    "LEN": {"map": "excel", "emits": ("strlen",)},
    "LOWER": {"map": "excel", "emits": ("sql_string_op",)},
    "MID": {"map": "excel", "emits": ("substr",)},
    "RIGHT": {"map": "excel", "emits": ("right",)},
    "SEARCH": {"map": "excel", "emits": ("strpos",)},
    "SUBSTITUTE": {"map": "excel", "emits": ("sql_string_op",)},
    "TEXTJOIN": {"map": "excel", "emits": ("concat",)},
    "TRIM": {"map": "excel", "emits": ("sql_string_op",)},
    "UPPER": {"map": "excel", "emits": ("sql_string_op",)},
    "VALUE": {"map": "excel", "emits": ("to_double",)},
    # --- Date and time
    "DATEDIF": {"map": "excel", "emits": ("diff_days", "diff_months", "day", "floor")},
    "DAY": {"map": "excel", "emits": ("day",)},
    "DAYS": {"map": "excel", "emits": ("diff_days",)},
    "EDATE": {"map": "excel", "emits": ("add_months",)},
    "EOMONTH": {"map": "excel", "emits": ("add_days", "add_months", "start_of_month")},
    "MONTH": {"map": "excel", "emits": ("month_number",)},
    "NETWORKDAYS": {"map": "excel", "emits": ("diff_days", "floor", "mod", "day_number_of_week")},
    "NETWORKDAYS.INTL": {"map": "excel",
                         "emits": ("diff_days", "floor", "mod", "day_number_of_week")},
    "NOW": {"map": "excel", "emits": ("now",)},
    "TODAY": {"map": "excel", "emits": ("today",)},
    "WEEKDAY": {"map": "excel", "emits": ("day_number_of_week", "mod")},
    "YEAR": {"map": "excel", "emits": ("year",)},
    # --- Logical
    "AND": {"map": "excel", "emits": ()},
    "FALSE": {"map": "excel", "emits": ()},
    "IF": {"map": "excel", "emits": ("safe_divide",)},
    "IFERROR": {"map": "excel", "emits": ("safe_divide", "ifnull")},
    "IFS": {"map": "excel", "emits": ()},
    "NOT": {"map": "excel", "emits": ("not",)},
    "OR": {"map": "excel", "emits": ()},
    "SWITCH": {"map": "excel", "emits": ()},
    "TRUE": {"map": "excel", "emits": ()},
    # --- Information
    "ISBLANK": {"map": "excel", "emits": ("isnull",)},
    "ISNUMBER": {"map": "excel", "emits": ("contains", "not", "isnull", "to_double")},
}

# The criteria-string table (Excel map E11, "Criteria strings") that every *IF / *IFS rule
# translates its criteria through (``criteria.py``) — checked against that table's text.
CRITERIA_EMITS = ("isnull", "not", "contains", "strpos", "sql_bool_op")

# Google Sheets delta rules (the Sheets map). A Sheets formula is handled by these first, then
# by FUNCTION_RULES for every name the Sheets map does not row (its rule E1).
SHEETS_RULES = {
    "ADD": {"map": "sheets", "emits": ()},
    "ARRAYFORMULA": {"map": "sheets", "emits": ()},
    "CONCAT": {"map": "sheets", "emits": ("concat",)},
    "COUNTUNIQUE": {"map": "sheets", "emits": ("unique count",)},
    "DIVIDE": {"map": "sheets", "emits": ()},
    "EQ": {"map": "sheets", "emits": ()},
    "GT": {"map": "sheets", "emits": ()},
    "GTE": {"map": "sheets", "emits": ()},
    "IFERROR": {"map": "sheets", "emits": ()},
    "LT": {"map": "sheets", "emits": ()},
    "LTE": {"map": "sheets", "emits": ()},
    "MINUS": {"map": "sheets", "emits": ()},
    "MULTIPLY": {"map": "sheets", "emits": ()},
    "NE": {"map": "sheets", "emits": ()},
    "POW": {"map": "sheets", "emits": ("pow",)},
    "QUERY": {"map": "sheets", "emits": ()},
    "REGEXEXTRACT": {"map": "sheets", "emits": ("sql_string_op",)},
    "REGEXMATCH": {"map": "sheets", "emits": ("sql_bool_op",)},
    "REGEXREPLACE": {"map": "sheets", "emits": ("sql_string_op",)},
    "UMINUS": {"map": "sheets", "emits": ()},
    "UNARY_PERCENT": {"map": "sheets", "emits": ()},
    "UPLUS": {"map": "sheets", "emits": ()},
}
