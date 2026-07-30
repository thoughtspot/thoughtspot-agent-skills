# Worked Example — Company Workforce SV → ThoughtSpot Model (Identifier Resolution)

End-to-end conversion of `AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANY_WORKFORCE_SV`
to a ThoughtSpot Model named `Company Workforce`.

This example complements [ts-from-snowflake.md](ts-from-snowflake.md) (BIRD example)
and [ts-from-snowflake-dunder.md](ts-from-snowflake-dunder.md) (Dunder Mifflin) by
exercising the **identifier resolution engine** — features the other examples do NOT
cover:

- **Facts block:** row-level expressions (`DATEDIFF`, `CASE/WHEN`) parsed as standalone
  formulas in the model
- **Metric-on-fact resolution:** metrics that reference facts by name — resolved via
  `[formula_<id>]` bracket references (using the formula `id`, NOT display name)
- **Double aggregation (metric-on-metric):** metrics that aggregate other metrics,
  translated via `group_count` / `group_sum` shorthands
- **Duplicate `column_id` avoidance:** when the same physical column is used as both
  an ATTRIBUTE dimension and a MEASURE metric, the metric must be a formula column
  (not an `aggregation:` column) to avoid the "duplicate column_id" import error
- **`if()` parenthesization:** CASE/WHEN → `if ( [cond] ) then ... else ...` requires
  parentheses around the condition

Verified end-to-end against `se-thoughtspot` on 2026-06-13 (model GUID
`a8803bc3-f4c7-45f1-8f20-36924e57a2ef`) and **re-verified 2026-07-30** — see
[Re-verification](#re-verification--2026-07-30) for what the re-run changed and why.
The output below is the 2026-07-30 output.

---

## Input — Semantic View DDL

```sql
create or replace semantic view AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANY_WORKFORCE_SV
    tables (
        AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANIES primary key (COMPANY_ID)
            comment='Parent company master data',
        AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.EMPLOYEES primary key (EMPLOYEE_ID)
            comment='Employee records linked to companies'
    )
    relationships (
        EMPLOYEES_TO_COMPANIES as EMPLOYEES(COMPANY_ID) references COMPANIES(COMPANY_ID)
    )
    facts (
        EMPLOYEES.TENURE_MONTHS as DATEDIFF(month, HIRE_DATE, CURRENT_DATE())
            comment='Number of months since the employee was hired',
        EMPLOYEES.SALARY_BAND as CASE
                WHEN SALARY >= 90000 THEN 'Senior'
                WHEN SALARY >= 70000 THEN 'Mid'
                ELSE 'Junior'
            END comment='Salary classification band based on annual salary'
    )
    dimensions (
        COMPANIES.COMPANY_ID as companies.COMPANY_ID,
        COMPANIES.COMPANY_NAME as companies.COMPANY_NAME
            with synonyms=('Company','Organisation')
            comment='The registered company name',
        COMPANIES.FOUNDED_DATE as companies.FOUNDED_DATE
            comment='Date the company was founded',
        COMPANIES.HEADQUARTERS_CITY as companies.HEADQUARTERS_CITY
            with synonyms=('City','HQ City','Location')
            comment='City where the company headquarters is located',
        COMPANIES.INDUSTRY as companies.INDUSTRY
            comment='Industry classification of the company',
        EMPLOYEES.EMPLOYEE_ID as employees.EMPLOYEE_ID,
        EMPLOYEES.EMPLOYEE_NAME as employees.EMPLOYEE_NAME
            with synonyms=('Name','Staff Member')
            comment='Full name of the employee',
        EMPLOYEES.HIRE_DATE as employees.HIRE_DATE
            comment='Date the employee was hired',
        EMPLOYEES.DEPARTMENT as employees.DEPARTMENT
            with synonyms=('Team','Division')
            comment='Department the employee belongs to'
    )
    metrics (
        EMPLOYEES.HEADCOUNT as COUNT(EMPLOYEE_ID)
            with synonyms=('Employee Count','Number of Employees','Staff Count')
            comment='Total number of employees',
        EMPLOYEES.TOTAL_SALARY as SUM(SALARY)
            with synonyms=('Payroll','Total Compensation')
            comment='Sum of all employee salaries',
        EMPLOYEES.AVG_SALARY as AVG(SALARY)
            comment='Average employee salary',
        EMPLOYEES.AVG_TENURE as AVG(employees.tenure_months)
            comment='Average employee tenure in months',
        EMPLOYEES.TOTAL_TENURE as SUM(employees.tenure_months)
            comment='Total accumulated tenure across all employees in months',
        COMPANIES.AVG_HEADCOUNT_PER_COMPANY as AVG(employees.headcount)
            comment='Average number of employees per company',
        COMPANIES.MAX_SALARY_BUDGET as MAX(employees.total_salary)
            comment='Highest total salary budget across all companies'
    )
    comment='Company workforce analytics exercising facts, double aggregation, and metric-on-fact resolution';
```

---

## Parsing Summary

| Category | Items |
|---|---|
| Tables | 2: COMPANIES (PK: COMPANY_ID), EMPLOYEES (PK: EMPLOYEE_ID) |
| Relationships | 1: EMPLOYEES(COMPANY_ID) → COMPANIES(COMPANY_ID) |
| Facts | 2: TENURE_MONTHS (DATEDIFF), SALARY_BAND (CASE/WHEN) |
| Dimensions | 9 (5 from COMPANIES, 4 from EMPLOYEES) |
| Metrics | 7: 3 simple, 2 metric-on-fact, 2 double aggregation |
| Facts (passthrough vs computed) | 0 passthrough, 2 computed — so both take resolution step 2, not step 1 |

---

## Identifier Resolution Trace

Each metric expression is resolved before translation. The resolution order is:
physical column → fact → metric → FAIL.

### Simple metrics (step 1: physical column)

| Metric | SV Expression | Resolution | ThoughtSpot Formula |
|---|---|---|---|
| HEADCOUNT | `COUNT(EMPLOYEE_ID)` | `EMPLOYEE_ID` = physical col on EMPLOYEES | `count ( [EMPLOYEES::EMPLOYEE_ID] )` |
| TOTAL_SALARY | `SUM(SALARY)` | `SALARY` = physical col on EMPLOYEES | `sum ( [EMPLOYEES::SALARY] )` |
| AVG_SALARY | `AVG(SALARY)` | `SALARY` = physical col on EMPLOYEES | `average ( [EMPLOYEES::SALARY] )` |

### Metric-on-fact (step 2: fact → inline expression)

| Metric | SV Expression | Resolution | ThoughtSpot Formula |
|---|---|---|---|
| AVG_TENURE | `AVG(employees.tenure_months)` | `tenure_months` = **computed** fact → formula ref | `average ( [formula_Tenure Months] )` |
| TOTAL_TENURE | `SUM(employees.tenure_months)` | `tenure_months` = **computed** fact → formula ref | `sum ( [formula_Tenure Months] )` |

**Key finding:** `[Tenure Months]` (display name) fails during TML import with
"Search did not find 'Tenure Months' in your data or metadata." The correct syntax
is `[formula_Tenure Months]` — using the formula's `id` value, which includes the
`formula_` prefix. ThoughtSpot resolves formula-to-formula references by `id`, not
by display name.

### Double aggregation (step 3: metric → group_* shorthand)

| Metric | SV Expression | Resolution | ThoughtSpot Formula |
|---|---|---|---|
| AVG_HEADCOUNT_PER_COMPANY | `AVG(employees.headcount)` | `headcount` = metric (COUNT(EMPLOYEE_ID)) → double agg | `average ( group_count ( [EMPLOYEES::EMPLOYEE_ID] , [COMPANIES::COMPANY_ID] ) )` |
| MAX_SALARY_BUDGET | `MAX(employees.total_salary)` | `total_salary` = metric (SUM(SALARY)) → double agg | `max ( group_sum ( [EMPLOYEES::SALARY] , [COMPANIES::COMPANY_ID] ) )` |

The grouping key is `COMPANIES::COMPANY_ID` — the PK on the TO (parent) side of the
`EMPLOYEES_TO_COMPANIES` relationship.

---

## Fact Formulas

| Fact | SV Expression | Translation | Column Type |
|---|---|---|---|
| Tenure Months | `DATEDIFF(month, HIRE_DATE, CURRENT_DATE())` | `diff_months ( today ( ) , [EMPLOYEES::HIRE_DATE] )` | ATTRIBUTE (facts are classified ATTRIBUTE unconditionally — BL-181) |
| Salary Band | `CASE WHEN SALARY >= 90000 THEN 'Senior' WHEN SALARY >= 70000 THEN 'Mid' ELSE 'Junior' END` | `if ( [EMPLOYEES::SALARY] >= 90000 ) then 'Senior' else if ( [EMPLOYEES::SALARY] >= 70000 ) then 'Mid' else 'Junior'` | ATTRIBUTE (string) |

**Note:** `DATEDIFF(month, start, end)` → `diff_months(end, start)` — arguments are reversed.
`CURRENT_DATE()` → `today()`.

---

## Duplicate Column ID Problem

Three simple metrics reference physical columns that also appear as ATTRIBUTE dimensions:

| Column | ATTRIBUTE use | MEASURE use |
|---|---|---|
| `EMPLOYEES::EMPLOYEE_ID` | Employee Id (dimension) | Headcount (COUNT) |
| `EMPLOYEES::SALARY` | — | Total Salary (SUM) AND Avg Salary (AVG) |

ThoughtSpot rejects TML with duplicate `column_id` values:
> "Field worksheet->columns should have unique column_id values. 12th worksheet->columns
> has duplicate column_id 'EMPLOYEES::EMPLOYEE_ID'."

**Fix:** every duplicate occupant of a `TABLE::col` becomes a formula column
(`formulas[]` entry) instead of an `aggregation:`-based `columns[]` entry, which
eliminates the duplicate `column_id`.

Since ts-cli v0.92.0 (2026-07-24) this is `formula_common.promote_duplicate_column_ids`,
and it keeps the **first** occupant of each `column_id` as a plain column rather than
promoting all of them. So on this fixture:

| Column | First occupant (stays a `column_id` entry) | Promoted to a formula |
|---|---|---|
| `EMPLOYEES::EMPLOYEE_ID` | `Employee Id` (dimension) | `Employee Count` → `count ( [EMPLOYEES::EMPLOYEE_ID] )` |
| `EMPLOYEES::SALARY` | `Payroll` (`aggregation: SUM`) | `Avg Salary` → `average ( [EMPLOYEES::SALARY] )` |

That is why the output has 8 formulas, not the 9 the 2026-06-13 baseline recorded — see
[Re-verification](#re-verification--2026-07-30).

---

## Output — ThoughtSpot Model TML

```yaml
model:
  columns:
  - column_id: "COMPANIES::COMPANY_ID"
    name: Company Id
    properties:
      column_type: ATTRIBUTE
  - column_id: "COMPANIES::COMPANY_NAME"
    name: Company
    properties:
      column_type: ATTRIBUTE
      description: The registered company name
      synonym_type: USER_DEFINED
      synonyms:
      - Organisation
  - column_id: "COMPANIES::FOUNDED_DATE"
    name: Founded Date
    properties:
      column_type: ATTRIBUTE
      description: Date the company was founded
  - column_id: "COMPANIES::HEADQUARTERS_CITY"
    name: City
    properties:
      column_type: ATTRIBUTE
      description: City where the company headquarters is located
      synonym_type: USER_DEFINED
      synonyms:
      - HQ City
      - Location
  - column_id: "COMPANIES::INDUSTRY"
    name: Industry
    properties:
      column_type: ATTRIBUTE
      description: Industry classification of the company
  - column_id: "EMPLOYEES::EMPLOYEE_ID"
    name: Employee Id
    properties:
      column_type: ATTRIBUTE
  - column_id: "EMPLOYEES::EMPLOYEE_NAME"
    name: Name
    properties:
      column_type: ATTRIBUTE
      description: Full name of the employee
      synonym_type: USER_DEFINED
      synonyms:
      - Staff Member
  - column_id: "EMPLOYEES::HIRE_DATE"
    name: Hire Date
    properties:
      column_type: ATTRIBUTE
      description: Date the employee was hired
  - column_id: "EMPLOYEES::DEPARTMENT"
    name: Team
    properties:
      column_type: ATTRIBUTE
      description: Department the employee belongs to
      synonym_type: USER_DEFINED
      synonyms:
      - Division
  - formula_id: formula_Tenure Months
    name: Tenure Months
    properties:
      column_type: ATTRIBUTE
      description: Number of months since the employee was hired
  - formula_id: formula_Salary Band
    name: Salary Band
    properties:
      column_type: ATTRIBUTE
      description: Salary classification band based on annual salary
  - formula_id: formula_Employee Count
    name: Employee Count
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Total number of employees
      index_type: DONT_INDEX
      synonym_type: USER_DEFINED
      synonyms:
      - Number of Employees
      - Staff Count
  - column_id: "EMPLOYEES::SALARY"
    name: Payroll
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Sum of all employee salaries
      synonym_type: USER_DEFINED
      synonyms:
      - Total Compensation
  - formula_id: formula_Avg Salary
    name: Avg Salary
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Average employee salary
      index_type: DONT_INDEX
  - formula_id: formula_Avg Tenure
    name: Avg Tenure
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Average employee tenure in months
      index_type: DONT_INDEX
  - formula_id: formula_Total Tenure
    name: Total Tenure
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Total accumulated tenure across all employees in months
      index_type: DONT_INDEX
  - formula_id: formula_Avg Headcount Per Company
    name: Avg Headcount Per Company
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Average number of employees per company
      index_type: DONT_INDEX
  - formula_id: formula_Max Salary Budget
    name: Max Salary Budget
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Highest total salary budget across all companies
      index_type: DONT_INDEX
  description: Company workforce analytics exercising facts, double aggregation, and metric-on-fact resolution Converted from Snowflake Semantic View AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANY_WORKFORCE_SV.
  formulas:
  - expr: "diff_months ( today ( ) , [EMPLOYEES::HIRE_DATE] )"
    id: formula_Tenure Months
    name: Tenure Months
    properties:
      column_type: ATTRIBUTE
  - expr: "if ( [EMPLOYEES::SALARY] >= 90000 ) then 'Senior' else if ( [EMPLOYEES::SALARY] >= 70000 ) then 'Mid' else 'Junior'"
    id: formula_Salary Band
    name: Salary Band
    properties:
      column_type: ATTRIBUTE
  - expr: "count ( [EMPLOYEES::EMPLOYEE_ID] )"
    id: formula_Employee Count
    name: Employee Count
  - expr: "average ( [EMPLOYEES::SALARY] )"
    id: formula_Avg Salary
    name: Avg Salary
  - expr: "average ( [formula_Tenure Months] )"
    id: formula_Avg Tenure
    name: Avg Tenure
  - expr: "sum ( [formula_Tenure Months] )"
    id: formula_Total Tenure
    name: Total Tenure
  - expr: "average ( group_count ( [EMPLOYEES::EMPLOYEE_ID] , [COMPANIES::COMPANY_ID] ) )"
    id: formula_Avg Headcount Per Company
    name: Avg Headcount Per Company
  - expr: "max ( group_sum ( [EMPLOYEES::SALARY] , [COMPANIES::COMPANY_ID] ) )"
    id: formula_Max Salary Budget
    name: Max Salary Budget
  model_tables:
  - fqn: 5341e282-7259-4727-bb88-c186105a048c
    id: EMPLOYEES
    joins:
    - cardinality: MANY_TO_ONE
      name: EMPLOYEES_TO_COMPANIES
      'on': "[EMPLOYEES::COMPANY_ID] = [COMPANIES::COMPANY_ID]"
      type: LEFT_OUTER
      with: COMPANIES
    name: EMPLOYEES
  - fqn: 829f2a7d-aa1a-4475-ac28-4b3955eea3b7
    id: COMPANIES
    name: COMPANIES
  name: Company Workforce
  properties:
    is_bypass_rls: false
    join_progressive: true
    spotter_config:
      is_spotter_enabled: true
```

---

## Verification

| Check | Result |
|---|---|
| Formulas count | 8 (2 facts + 2 simple + 2 metric-on-fact + 2 double agg) |
| Columns count | 18 (9 dimensions + 2 facts + 3 simple metrics + 2 metric-on-fact + 2 double agg) |
| Joins | EMPLOYEES → COMPANIES (LEFT_OUTER on COMPANY_ID, MANY_TO_ONE) |
| Spotter | enabled |
| Dangling `[formula_*]` references | **0 of 8** (`ts tml lint` clean, I13 included) |
| Synonyms preserved | Company (1), City (2), Name (1), Team (1), Employee Count (2), Payroll (1) |
| Descriptions preserved | 13 columns |
| Live import | `--policy VALIDATE_ONLY` on `se-thoughtspot` 2026-07-30 → `status_code: OK`, nothing persisted |

---

## Re-verification — 2026-07-30

Re-running this example's own DDL through `parse-sv → translate-formulas → build-model`
found **4 of its 8 formulas dangling** (BL-178; `docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`
F9). The regression was introduced by the v1.17.0 rewire onto deterministic CLI commands
(2026-07-22), which postdated the 2026-06-13 verification, and it is now fixed
(ts-cli v0.126.0). The pre-fix output was **confirmed to be a hard import failure**, not a
silently-broken measure — the open question the review could not settle:

```
$ ts tml import --file 'Company Workforce.model.tml' --policy VALIDATE_ONLY --create-new
error_code 14516  status_code ERROR
Formula addition failed. Formula: Avg Tenure, Error: Search did not find
"formula_tenure_months )" in your data or metadata. Expecting one of the valid
keywords, such as, "(", "-", "abs" etc..
```

The same command on the post-fix output returns `status_code: OK`. The dangling-reference
class is now gated by `ts tml lint` invariant **I13** (BL-183), which fires on the pre-fix
TML with exactly those 4 findings.

**The output above is the 2026-07-30 output, and it differs from the 2026-06-13 baseline
in four places. Only the first is BL-178's fix; the other three are later documented
features acting on a stale document, not regressions:**

| Divergence from 2026-06-13 | Cause | Verdict |
|---|---|---|
| `average ( [formula_Tenure Months] )` / `sum ( [formula_Tenure Months] )` restored, and the two double-aggregation metrics now emit `group_count` / `group_sum` instead of dangling refs | BL-178 fix | **the regression, repaired** — matches the 2026-06-13 baseline exactly |
| 6 of 18 display names changed (`Company Name`→`Company`, `Headquarters City`→`City`, `Employee Name`→`Name`, `Department`→`Team`, `Headcount`→`Employee Count`, `Total Salary`→`Payroll`), and the corresponding formula ids with them | first-synonym→display-name promotion, coverage row 14, landed **2026-06-15** — two days after the baseline | current documented behaviour; the baseline names predate it. Whether the promotion is *right* on a foreign SV is **BL-179**, open |
| `Payroll` is a `column_id` entry with `aggregation: SUM` rather than a `formula_Total Salary` formula, so the formula count is 8 not 9 | duplicate-`column_id` → formula promotion, coverage row 29 / ts-cli v0.92.0 (2026-07-24): the FIRST occupant of a `TABLE::col` keeps the `column_id` and later ones are promoted. `EMPLOYEES::SALARY` is claimed by `Payroll` first, so `Avg Salary` is the one promoted | current documented behaviour |
| `Tenure Months` is `ATTRIBUTE`, not `MEASURE` | facts are classified `ATTRIBUTE` unconditionally, coverage row 16 | current behaviour; that it is *wrong* is **BL-181**, open |

Nothing was persisted by the re-verification: an object search for `Company Workforce%`
returned 0 rows before and after, and the guid the `VALIDATE_ONLY` response echoed
(`3e36b8b0-…`) does not exist on the instance.

---

## Lessons Learned

### 1. Formula references use `id`, not display name

`average ( [Tenure Months] )` fails with "Search did not find 'Tenure Months' in your
data or metadata." The display name does not resolve during TML import. The correct
syntax is `average ( [formula_Tenure Months] )` — using the formula's `id` field value,
which includes the `formula_` prefix. ThoughtSpot resolves formula-to-formula references
by the `id` field, not by display name or column name.

### 2. Duplicate `column_id` requires formula columns

When the same physical column serves as both ATTRIBUTE (dimension) and MEASURE (metric),
using `aggregation:` on a `columns[]` entry creates a duplicate `column_id`. Moving the
metric to a `formulas[]` entry eliminates this. The `COUNT(EMPLOYEE_ID)` metric and the
`Employee Id` dimension both reference `EMPLOYEES::EMPLOYEE_ID` — the metric must be a
formula.

### 2b. The reference and the minted id must come from ONE naming function

The `formula_` id is derived from the construct's **display name** (first synonym, else
the title-cased declared name). Anything that emits a reference to that formula must call
the *same* function that mints the id, not re-derive the name. When they diverged, the
resolver emitted `[formula_tenure_months]` against a declared `formula_Tenure Months`, and
every metric in this model became unimportable — with `ts tml lint` and `check_tml.py` both
reporting clean (BL-178, 2026-07-22 → 2026-07-30). `sv_translate.display_title` /
`construct_formula_id` is now that single function, and `sv_build_model` imports it rather
than restating the rule. Invariant **I13** gates the outcome.

### 2c. A passthrough fact is a column, not a formula

Resolution step 1 (physical column) comes before step 2 (fact). A fact whose right-hand
side is a bare physical-column reference merely *aliases* that column, so it is emitted as
a `columns[]` entry and a reference to it must be `[TABLE::col]`. Both facts in this
example are computed, so both correctly take step 2 — which is exactly why this example
did not surface the inverted order on its own, and a Cortex-Analyst-shaped SV (every fact
a passthrough) did.

### 3. `if()` conditions require parentheses

`if [col] >= 90000 then ...` fails. `if ( [col] >= 90000 ) then ...` works. The
parentheses around the condition are required by the ThoughtSpot formula parser.

### 4. `joins:` not `joins_with:` on model_tables entries

Inline joins on a `model_tables[]` entry use the `joins:` key. `joins_with:` is for
model-level data augmentation (a different concept). Using `joins_with:` on a
`model_tables[]` entry causes a schema validation error.

### 5. `ts tables create` may match existing tables by name

The `ts tables create` command returned the GUID of a pre-existing EMPLOYEES table
(from `DEMO_DB.HRDATA`) instead of creating a new one for
`AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.EMPLOYEES`. Always verify the returned GUID's
`db`/`schema`/`db_table` match the intended target before proceeding.
