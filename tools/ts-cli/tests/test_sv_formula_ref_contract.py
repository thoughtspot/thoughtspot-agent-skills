"""BL-178 — the contract between `sv_translate`'s resolver and `sv_build_model`'s
minted formula ids, asserted end-to-end over a parsed Semantic View.

The regression this file exists to prevent: the resolver and the builder are each
well covered in isolation (`test_sv_translate.py`, `test_sv_build_model.py`) while
the contract *between* them — every ``[formula_X]`` a metric emits must match an
``id`` the builder declares — was asserted nowhere. Both sides passed their own
tests for five weeks while every measure in the emitted Model TML was unresolvable
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` F9).

These tests run the real documented pipeline — ``parse_sv_ddl`` ->
``translate_sv_formulas`` -> ``build_model_tml_sv`` — over DDL fixtures, so a
divergence in either half fails here. Pure functions; no ThoughtSpot connection.
"""
from __future__ import annotations

import re

import pytest

from ts_cli.sv_build_model import build_model_tml_sv
from ts_cli.sv_parse import parse_sv_ddl
from ts_cli.sv_translate import translate_sv_formulas
from ts_cli.tml_lint import lint_tml

_REF_RE = re.compile(r"\[([^\[\]]+)\]")


# ---------------------------------------------------------------------------
# Fixtures — DDL in, Model TML out
# ---------------------------------------------------------------------------

# The worked example's own SV (agents/shared/worked-examples/snowflake/
# ts-from-snowflake-identifier-resolution.md), trimmed to the constructs that
# exercise identifier resolution: a computed fact referenced by two metrics
# (metric-on-fact), and two cross-table metrics that reference other metrics
# (metric-on-metric double aggregation).
WORKFORCE_DDL = """
create or replace semantic view AGENT_SKILLS.TEST.COMPANY_WORKFORCE_SV
    tables (
        AGENT_SKILLS.TEST.COMPANIES primary key (COMPANY_ID)
            comment='Parent company master data',
        AGENT_SKILLS.TEST.EMPLOYEES primary key (EMPLOYEE_ID)
            comment='Employee records linked to companies'
    )
    relationships (
        EMPLOYEES_TO_COMPANIES as EMPLOYEES(COMPANY_ID) references COMPANIES(COMPANY_ID)
    )
    facts (
        EMPLOYEES.TENURE_MONTHS as DATEDIFF(month, HIRE_DATE, CURRENT_DATE())
            comment='Number of months since the employee was hired'
    )
    dimensions (
        COMPANIES.COMPANY_ID as companies.COMPANY_ID,
        COMPANIES.COMPANY_NAME as companies.COMPANY_NAME
            with synonyms=('Company','Organisation'),
        EMPLOYEES.EMPLOYEE_ID as employees.EMPLOYEE_ID,
        EMPLOYEES.HIRE_DATE as employees.HIRE_DATE
    )
    metrics (
        EMPLOYEES.HEADCOUNT as COUNT(EMPLOYEE_ID)
            with synonyms=('Employee Count','Staff Count')
            comment='Total number of employees',
        EMPLOYEES.TOTAL_SALARY as SUM(SALARY)
            comment='Sum of all employee salaries',
        EMPLOYEES.AVG_TENURE as AVG(employees.tenure_months)
            comment='Average employee tenure in months',
        EMPLOYEES.TOTAL_TENURE as SUM(employees.tenure_months)
            comment='Total accumulated tenure in months',
        COMPANIES.AVG_HEADCOUNT_PER_COMPANY as AVG(employees.headcount)
            comment='Average number of employees per company',
        COMPANIES.MAX_SALARY_BUDGET as MAX(employees.total_salary)
            comment='Highest total salary budget across all companies'
    )
    comment='Company workforce analytics';
"""

# The TPC-DS shape (docs/reviews/2026-07-29-ossie-tpcds-fidelity.md §3): every
# fact is a *passthrough* of a physical column — the shape upstream's converter
# emits for any field without a dimension block — and every metric aggregates one
# of those facts. This is the fixture on which defect 1 (inverted resolution
# order) fired: 5 of 5 metric formulas referenced ids that never existed.
TPCDS_DDL = """
create or replace semantic view TPCDS.PUBLIC.TPCDS_RETAIL_MODEL
    tables (
        TPCDS.PUBLIC.STORE_SALES primary key (SS_ITEM_SK),
        TPCDS.PUBLIC.CUSTOMER primary key (C_CUSTOMER_SK)
    )
    relationships (
        STORE_SALES_TO_CUSTOMER as STORE_SALES(SS_CUSTOMER_SK)
            references CUSTOMER(C_CUSTOMER_SK)
    )
    facts (
        STORE_SALES.ss_ext_sales_price as store_sales.ss_ext_sales_price
            with synonyms=('total price'),
        STORE_SALES.ss_net_profit as store_sales.ss_net_profit
    )
    dimensions (
        STORE_SALES.ss_item_sk as store_sales.ss_item_sk,
        CUSTOMER.c_customer_sk as customer.c_customer_sk
    )
    metrics (
        STORE_SALES.total_sales as SUM(store_sales.ss_ext_sales_price)
            with synonyms=('total revenue','gross sales'),
        STORE_SALES.total_profit as SUM(store_sales.ss_net_profit)
            with synonyms=('net profit'),
        STORE_SALES.customer_lifetime_value as
            SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)
            with synonyms=('CLV')
    )
    comment='TPC-DS retail model';
"""

# A Semantic View containing a COMPUTED fact — the shape on which defect 3 is not
# latent. `net_line`'s expression opens with a qualified reference to a *different*
# physical column, which is what poisoned the fact index.
COMPUTED_FACT_DDL = """
create or replace semantic view TPCDS.PUBLIC.PROBE
    tables (
        TPCDS.PUBLIC.STORE_SALES primary key (SS_ITEM_SK)
    )
    facts (
        STORE_SALES.net_line as
            store_sales.ss_ext_sales_price - store_sales.ss_net_profit
    )
    dimensions (
        STORE_SALES.ss_item_sk as store_sales.ss_item_sk
    )
    metrics (
        STORE_SALES.total_net as SUM(store_sales.net_line)
    )
    comment='Computed-fact probe';
"""


# A RENAMED passthrough — `AS` doing the job it exists for. The declared name
# (`revenue`) differs from the physical column it aliases
# (`ss_ext_sales_price`), and a metric references it by its DECLARED name, which
# is the only name the SV namespace gives it. PR #424 review F1: the construct was
# indexed only under its RHS column, so the reference missed both indexes, fell
# through to assumed-physical and emitted `column_id: STORE_SALES::revenue` — a
# column that does not exist, with every gate green (it is a `TABLE::col` ref, so
# I13 has nothing to say about it).
RENAMED_PASSTHROUGH_DDL = """
create or replace semantic view TPCDS.PUBLIC.RENAMED
    tables (
        TPCDS.PUBLIC.STORE_SALES primary key (SS_ITEM_SK)
    )
    facts (
        STORE_SALES.revenue as store_sales.ss_ext_sales_price
    )
    dimensions (
        STORE_SALES.ss_item_sk as store_sales.ss_item_sk
    )
    metrics (
        STORE_SALES.total_revenue as SUM(store_sales.revenue),
        STORE_SALES.max_revenue as MAX(store_sales.ss_ext_sales_price)
    )
    comment='Renamed passthrough fact';
"""


def _build(ddl: str, tables: dict, model_name: str = "Probe") -> dict:
    parsed = parse_sv_ddl(ddl)
    translated = translate_sv_formulas(parsed)
    doc, _info = build_model_tml_sv(
        model_name=model_name, parsed=parsed, translated_doc=translated,
        tables=tables, spotter_enabled=True)
    return doc


def _dangling_refs(doc: dict) -> list[str]:
    """Every `formula_*` reference in the document that matches no declared id.

    This is the machine check behind BL-178: the same property `ts tml lint`
    now enforces as I13, computed here independently so the contract test does
    not depend on the linter being wired in.
    """
    model = doc["model"]
    declared = {f["id"] for f in model.get("formulas") or []}
    missing: list[str] = []
    for f in model.get("formulas") or []:
        for ref in _REF_RE.findall(f.get("expr") or ""):
            if ref.startswith("formula_") and ref not in declared:
                missing.append(ref)
    for c in model.get("columns") or []:
        fid = c.get("formula_id")
        if fid and fid not in declared:
            missing.append(fid)
    return sorted(set(missing))


WORKFORCE_TABLES = {
    "COMPANIES": {"name": "COMPANIES", "fqn": "guid-companies"},
    "EMPLOYEES": {"name": "EMPLOYEES", "fqn": "guid-employees"},
}
TPCDS_TABLES = {
    "STORE_SALES": {"name": "STORE_SALES", "fqn": "guid-ss"},
    "CUSTOMER": {"name": "CUSTOMER", "fqn": "guid-cust"},
}
PROBE_TABLES = {"STORE_SALES": {"name": "STORE_SALES", "fqn": "guid-ss"}}


# ---------------------------------------------------------------------------
# The contract: emitted refs == minted ids
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ddl,tables", [
    (WORKFORCE_DDL, WORKFORCE_TABLES),
    (TPCDS_DDL, TPCDS_TABLES),
    (COMPUTED_FACT_DDL, PROBE_TABLES),
])
def test_no_dangling_formula_references(ddl, tables):
    """Every `[formula_X]` emitted matches a declared `formulas[].id` (BL-178)."""
    assert _dangling_refs(_build(ddl, tables)) == []


@pytest.mark.parametrize("ddl,tables", [
    (WORKFORCE_DDL, WORKFORCE_TABLES),
    (TPCDS_DDL, TPCDS_TABLES),
    (COMPUTED_FACT_DDL, PROBE_TABLES),
])
def test_emitted_tml_passes_lint(ddl, tables):
    """The same TML is clean under `ts tml lint`, I13 included (BL-183)."""
    assert lint_tml(_build(ddl, tables)) == []


# ---------------------------------------------------------------------------
# Defect 1 — the documented resolution order, end to end
# ---------------------------------------------------------------------------

def test_passthrough_fact_metric_uses_physical_column():
    """A metric aggregating a passthrough fact resolves to the physical column.

    Defect 1: the fact `ss_ext_sales_price` IS a physical column, so step 1 of
    the documented resolution order applies and the metric must aggregate
    `[STORE_SALES::ss_ext_sales_price]`, never a formula id.
    """
    doc = _build(TPCDS_DDL, TPCDS_TABLES, "Tpcds Retail Model")
    exprs = {f["name"]: f["expr"] for f in doc["model"]["formulas"]}
    # `total revenue` shares its physical column with the `total price` fact
    # column, so I8 promotion re-expresses it as an aggregation formula.
    assert "[STORE_SALES::ss_ext_sales_price]" in exprs["total revenue"]
    assert "formula_ss_ext_sales_price" not in exprs["total revenue"]


# ---------------------------------------------------------------------------
# Defect 2 — metric-on-fact and metric-on-metric against the worked example
# ---------------------------------------------------------------------------

def test_metric_on_fact_matches_worked_example():
    """`AVG(employees.tenure_months)` -> `average ( [formula_Tenure Months] )`.

    Ground truth: agents/shared/worked-examples/snowflake/
    ts-from-snowflake-identifier-resolution.md:233.
    """
    doc = _build(WORKFORCE_DDL, WORKFORCE_TABLES, "Company Workforce")
    exprs = {f["id"]: f["expr"] for f in doc["model"]["formulas"]}
    assert exprs["formula_Avg Tenure"] == "average ( [formula_Tenure Months] )"
    assert exprs["formula_Total Tenure"] == "sum ( [formula_Tenure Months] )"


def test_metric_on_metric_double_aggregation_matches_worked_example():
    """Metric-on-metric resolves to a `group_*` shorthand, not a formula ref.

    Ground truth: ts-from-snowflake-identifier-resolution.md:244/249 and
    ts-from-snowflake-rules.md "Double Aggregation (Metric-on-Metric)".
    """
    doc = _build(WORKFORCE_DDL, WORKFORCE_TABLES, "Company Workforce")
    exprs = {f["id"]: f["expr"] for f in doc["model"]["formulas"]}
    assert exprs["formula_Avg Headcount Per Company"] == (
        "average ( group_count ( [EMPLOYEES::EMPLOYEE_ID] , "
        "[COMPANIES::COMPANY_ID] ) )")
    assert exprs["formula_Max Salary Budget"] == (
        "max ( group_sum ( [EMPLOYEES::SALARY] , [COMPANIES::COMPANY_ID] ) )")


# ---------------------------------------------------------------------------
# Defect 3 — a computed fact is indexed under its declared name
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PR #424 review F1 — a renamed passthrough must be referenceable by its
# DECLARED name, and must never emit a column_id that does not exist
# ---------------------------------------------------------------------------

def _column_ids(doc: dict) -> set[str]:
    return {c["column_id"] for c in doc["model"]["columns"] if c.get("column_id")}


def test_double_aggregation_marker_reaches_the_translated_entry():
    """The 🔄 marker is worthless if it stops at the resolver — it has to land on
    the entry `translate-formulas` emits, which is what the skill surfaces
    (ts-from-snowflake-rules.md:723-726; PR #424 review F5)."""
    translated = translate_sv_formulas(parse_sv_ddl(WORKFORCE_DDL))
    marked = {t["name"] for t in translated["translated"]
              if any(a.startswith("🔄") for a in t["annotations"])}
    assert marked == {"AVG_HEADCOUNT_PER_COMPANY", "MAX_SALARY_BUDGET"}


def test_renamed_passthrough_reference_is_annotated_end_to_end():
    """The ⚑ ambiguity warning must reach the translated entry too."""
    translated = translate_sv_formulas(parse_sv_ddl(RENAMED_PASSTHROUGH_DDL))
    entry = next(t for t in translated["translated"]
                 if t["name"] == "total_revenue")
    assert any(a.startswith("⚑") and "revenue" in a
               for a in entry["annotations"]), entry
    # referencing the same fact by its physical name is unambiguous
    other = next(t for t in translated["translated"]
                 if t["name"] == "max_revenue")
    assert other["annotations"] == []


def test_renamed_passthrough_referenced_by_declared_name():
    """`SUM(store_sales.revenue)` must aggregate the physical column it aliases.

    The declared name is not a column on the table, so emitting
    `STORE_SALES::revenue` is a reference to nothing — rejected at import, and
    invisible to every existing gate.
    """
    doc = _build(RENAMED_PASSTHROUGH_DDL, PROBE_TABLES, "Renamed")
    ids = _column_ids(doc)
    assert "STORE_SALES::revenue" not in ids
    exprs = {f["name"]: f["expr"] for f in doc["model"]["formulas"]}
    assert exprs["Total Revenue"] == "sum ( [STORE_SALES::ss_ext_sales_price] )"


def test_renamed_passthrough_referenced_by_physical_name_still_resolves():
    """The pre-existing RHS-keyed route must keep working alongside the fix."""
    doc = _build(RENAMED_PASSTHROUGH_DDL, PROBE_TABLES, "Renamed")
    exprs = {f["name"]: f["expr"] for f in doc["model"]["formulas"]}
    assert exprs["Max Revenue"] == "max ( [STORE_SALES::ss_ext_sales_price] )"


def test_renamed_passthrough_emits_no_unknown_column_ids():
    """Every emitted column_id must name a column the SV actually references."""
    doc = _build(RENAMED_PASSTHROUGH_DDL, PROBE_TABLES, "Renamed")
    known = {"ss_item_sk", "ss_ext_sales_price"}
    for cid in _column_ids(doc):
        assert cid.split("::", 1)[1] in known, f"unknown column in {cid}"


def test_computed_fact_reference_is_internally_consistent():
    """`SUM(store_sales.net_line)` resolves the fact, not a physical column.

    Defect 3 poisoned the fact index with the first qualified token of the
    fact's own expression, producing `[formula_ss_ext_sales_price] -
    [STORE_SALES::ss_net_profit]` — two different resolutions of the same
    construct class inside one expression — plus a metric self-reference.
    """
    doc = _build(COMPUTED_FACT_DDL, PROBE_TABLES)
    exprs = {f["id"]: f["expr"] for f in doc["model"]["formulas"]}
    assert exprs["formula_Net Line"] == (
        "[STORE_SALES::ss_ext_sales_price] - [STORE_SALES::ss_net_profit]")
    assert exprs["formula_Total Net"] == "sum ( [formula_Net Line] )"
