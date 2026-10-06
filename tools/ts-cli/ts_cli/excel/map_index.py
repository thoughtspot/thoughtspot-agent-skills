"""The Excel and Google Sheets maps' row inventory: function name → (section, class).

Vendored from ``docs/function-maps/ts-excel-function-mapping.md`` (415 rows) and
``ts-sheets-function-mapping.md`` (63 rows) so a NEEDS_REVIEW result can cite the row the user
should read, without the repo on disk. ``tests/test_excel_translate.py::TestMapIndex`` fails if
either drifts from its map. Regenerate by re-parsing the maps' ``| `NAME(…)` | class |`` rows.
"""
from __future__ import annotations

EXCEL_MAP = "docs/function-maps/ts-excel-function-mapping.md"
SHEETS_MAP = "docs/function-maps/ts-sheets-function-mapping.md"


def _expand(groups: dict) -> dict:
    out: dict[str, tuple[str, str]] = {}
    for (section, cls), names in groups.items():
        for name in names.split():
            out[name] = (section, cls)
    return out


EXCEL_ROWS = _expand({
    ('Database', 'direct'): (
        'DAVERAGE DCOUNT DCOUNTA DGET DMAX DMIN DPRODUCT DSTDEV DSTDEVP DSUM DVAR DVARP '
    ),
    ('Date and time', 'direct'): (
        'DATE DATEDIF DATEVALUE DAY DAYS DAYS360 EDATE EOMONTH HOUR MONTH NETWORKDAYS '
        'NETWORKDAYS.INTL NOW TODAY WEEKDAY WEEKNUM WORKDAY WORKDAY.INTL YEAR YEARFRAC '
    ),
    ('Date and time', 'passthrough'): (
        'ISOWEEKNUM MINUTE SECOND TIME TIMEVALUE '
    ),
    ('Dynamic arrays, LET and LAMBDA', 'direct'): (
        'BYCOL BYROW ISOMITTED LAMBDA LET MAP TRIMRANGE '
    ),
    ('Dynamic arrays, LET and LAMBDA', 'structural'): (
        'CHOOSECOLS FILTER GROUPBY PIVOTBY SORT SORTBY TAKE UNIQUE '
    ),
    ('Dynamic arrays, LET and LAMBDA', 'unmappable'): (
        'CHOOSEROWS DROP EXPAND HSTACK MAKEARRAY RANDARRAY REDUCE SCAN SEQUENCE TOCOL '
        'TOROW VSTACK WRAPCOLS WRAPROWS '
    ),
    ('Financial', 'direct'): (
        'ACCRINTM CUMIPMT CUMPRINC DB DDB DISC DOLLARDE DOLLARFR EFFECT FV FVSCHEDULE '
        'INTRATE IPMT ISPMT MIRR NOMINAL NPER NPV PDURATION PMT PPMT PRICEDISC PRICEMAT '
        'PV RECEIVED RRI SLN SYD TBILLEQ TBILLPRICE TBILLYIELD XNPV YIELDDISC YIELDMAT '
    ),
    ('Financial', 'unmappable'): (
        'ACCRINT AMORDEGRC AMORLINC COUPDAYBS COUPDAYS COUPDAYSNC COUPNCD COUPNUM COUPPCD '
        'DURATION IRR MDURATION ODDFPRICE ODDFYIELD ODDLPRICE ODDLYIELD PRICE RATE VDB '
        'XIRR YIELD '
    ),
    ('Information', 'direct'): (
        'ISBLANK ISERR ISERROR ISEVEN ISLOGICAL ISNA ISNONTEXT ISNUMBER ISODD ISTEXT N NA '
        'TYPE '
    ),
    ('Information', 'unmappable'): (
        'CELL ERROR.TYPE INFO ISFORMULA ISREF SHEET SHEETS STOCKHISTORY '
    ),
    ('Logical', 'direct'): (
        'AND FALSE IF IFERROR IFNA IFS NOT OR SWITCH TRUE XOR '
    ),
    ('Lookup and reference', 'direct'): (
        'CHOOSE GETPIVOTDATA HYPERLINK ROWS '
    ),
    ('Lookup and reference', 'structural'): (
        'HLOOKUP INDEX LOOKUP MATCH VLOOKUP XLOOKUP XMATCH '
    ),
    ('Lookup and reference', 'unmappable'): (
        'ADDRESS AREAS COLUMN COLUMNS FORMULATEXT IMAGE INDIRECT OFFSET ROW RTD TRANSPOSE '
    ),
    ('Math and trigonometry', 'direct'): (
        'ABS ACOS ACOSH ACOT ACOTH AGGREGATE ASIN ASINH ATAN ATANH CEILING CEILING.MATH '
        'CEILING.PRECISE COS COSH COT COTH CSC CSCH DEGREES EVEN EXP FLOOR FLOOR.MATH '
        'FLOOR.PRECISE INT ISO.CEILING LN LOG LOG10 MOD MROUND ODD PERCENTOF PI POWER '
        'PRODUCT QUOTIENT RADIANS ROUND ROUNDDOWN ROUNDUP SEC SECH SIGN SIN SINH SQRT '
        'SQRTPI SUBTOTAL SUM SUMIF SUMIFS SUMPRODUCT SUMSQ SUMX2MY2 SUMX2PY2 SUMXMY2 TAN '
        'TANH TRUNC '
    ),
    ('Math and trigonometry', 'passthrough'): (
        'ATAN2 BASE COMBIN COMBINA DECIMAL FACT MULTINOMIAL RAND RANDBETWEEN '
    ),
    ('Math and trigonometry', 'unmappable'): (
        'ARABIC FACTDOUBLE GCD LCM MDETERM MINVERSE MMULT MUNIT ROMAN SERIESSUM '
    ),
    ('Statistical', 'direct'): (
        'AVEDEV AVERAGE AVERAGEA AVERAGEIF AVERAGEIFS CONFIDENCE.NORM CORREL COUNT COUNTA '
        'COUNTBLANK COUNTIF COUNTIFS COVARIANCE.P COVARIANCE.S DEVSQ EXPON.DIST FISHER '
        'FISHERINV FORECAST FORECAST.LINEAR GEOMEAN HARMEAN INTERCEPT MAX MAXA MAXIFS '
        'MEDIAN MIN MINA MINIFS PEARSON PERCENTRANK.INC PERMUTATIONA PHI PROB RANK.EQ RSQ '
        'SLOPE STANDARDIZE STDEV.P STDEV.S STDEVA STDEVPA STEYX VAR.P VAR.S VARA VARPA '
        'WEIBULL.DIST '
    ),
    ('Statistical', 'passthrough'): (
        'KURT LARGE MODE.SNGL PERCENTILE.EXC PERCENTILE.INC PERCENTRANK.EXC PERMUT '
        'QUARTILE.EXC QUARTILE.INC RANK.AVG SKEW SKEW.P SMALL TRIMMEAN '
    ),
    ('Statistical', 'unmappable'): (
        'BETA.DIST BETA.INV BINOM.DIST BINOM.DIST.RANGE BINOM.INV CHISQ.DIST '
        'CHISQ.DIST.RT CHISQ.INV CHISQ.INV.RT CHISQ.TEST CONFIDENCE.T F.DIST F.DIST.RT '
        'F.INV F.INV.RT F.TEST FORECAST.ETS FORECAST.ETS.CONFINT FORECAST.ETS.SEASONALITY '
        'FORECAST.ETS.STAT FREQUENCY GAMMA GAMMA.DIST GAMMA.INV GAMMALN GAMMALN.PRECISE '
        'GAUSS GROWTH HYPGEOM.DIST LINEST LOGEST LOGNORM.DIST LOGNORM.INV MODE.MULT '
        'NEGBINOM.DIST NORM.DIST NORM.INV NORM.S.DIST NORM.S.INV POISSON.DIST T.DIST '
        'T.DIST.2T T.DIST.RT T.INV T.INV.2T T.TEST TREND Z.TEST '
    ),
    ('Text', 'direct'): (
        'CONCAT CONCATENATE LEFT LEFTB LEN LENB MID MIDB NUMBERVALUE REPLACE REPLACEB '
        'RIGHT RIGHTB SEARCH SEARCHB T TEXTAFTER TEXTBEFORE VALUE VALUETOTEXT '
    ),
    ('Text', 'passthrough'): (
        'CHAR CLEAN CODE DOLLAR EXACT FIND FINDB FIXED LOWER PROPER REGEXEXTRACT '
        'REGEXREPLACE REGEXTEST REPT SUBSTITUTE TEXT TEXTJOIN TRANSLATE TRIM UNICHAR '
        'UNICODE UPPER '
    ),
    ('Text', 'unmappable'): (
        'ARRAYTOTEXT ASC BAHTTEXT DBCS DETECTLANGUAGE PHONETIC TEXTSPLIT '
    ),
})

SHEETS_ROWS = _expand({
    ('Arrays and filtering', 'direct'): (
        'ARRAYFORMULA '
    ),
    ('Arrays and filtering', 'structural'): (
        'ARRAY_CONSTRAIN FILTER SORT SORTN '
    ),
    ('Arrays and filtering', 'unmappable'): (
        'CONTINUE FLATTEN '
    ),
    ('Date, parser and type tests', 'direct'): (
        'ISDATE NETWORKDAYS NETWORKDAYS.INTL TO_DATE TO_DOLLARS TO_PERCENT TO_PURE_NUMBER '
        'TO_TEXT '
    ),
    ('Date, parser and type tests', 'passthrough'): (
        'EPOCHTODATE ISEMAIL '
    ),
    ('Date, parser and type tests', 'unmappable'): (
        'ISURL '
    ),
    ('Google, web and AI services', 'unmappable'): (
        'AI GOOGLEFINANCE GOOGLETRANSLATE IMPORTDATA IMPORTFEED IMPORTHTML IMPORTRANGE '
        'IMPORTXML SPARKLINE '
    ),
    ('Logical', 'direct'): (
        'IFERROR '
    ),
    ('Math and statistical', 'direct'): (
        'AVERAGE.WEIGHTED COUNTUNIQUE COUNTUNIQUEIFS FLOOR ROUND ROUNDDOWN ROUNDUP '
    ),
    ('Math and statistical', 'unmappable'): (
        'MARGINOFERROR '
    ),
    ('Operators', 'direct'): (
        'ADD DIVIDE EQ GT GTE ISBETWEEN LT LTE MINUS MULTIPLY NE POW UMINUS UNARY_PERCENT '
        'UPLUS '
    ),
    ('QUERY', 'structural'): (
        'QUERY '
    ),
    ('Text', 'direct'): (
        'CONCAT CONCATENATE SEARCH '
    ),
    ('Text', 'passthrough'): (
        'CHAR CODE JOIN REGEXEXTRACT REGEXMATCH REGEXREPLACE SPLIT TEXT '
    ),
})


def cite(name: str, dialect: str = "excel") -> str:
    """``Excel map, Lookup and reference, `VLOOKUP` — structural`` or a no-row line."""
    name = name.upper()
    if dialect == "google_sheets" and name in SHEETS_ROWS:
        section, cls = SHEETS_ROWS[name]
        return f"Sheets map ({SHEETS_MAP}), {section}, `{name}` — {cls}"
    if name in EXCEL_ROWS:
        section, cls = EXCEL_ROWS[name]
        via = " (via Sheets E1)" if dialect == "google_sheets" else ""
        return f"Excel map ({EXCEL_MAP}){via}, {section}, `{name}` — {cls}"
    return f"no map row for `{name}` (Excel map E1 inventory)"

