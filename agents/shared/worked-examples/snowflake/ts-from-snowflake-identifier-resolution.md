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

Verified end-to-end against `se-thoughtspot` on 2026-06-13. Final model GUID:
`a8803bc3-f4c7-45f1-8f20-36924e57a2ef`.

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
| AVG_TENURE | `AVG(employees.tenure_months)` | `tenure_months` = fact → formula ref | `average ( [formula_Tenure Months] )` |
| TOTAL_TENURE | `SUM(employees.tenure_months)` | `tenure_months` = fact → formula ref | `sum ( [formula_Tenure Months] )` |

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
| Tenure Months | `DATEDIFF(month, HIRE_DATE, CURRENT_DATE())` | `diff_months ( today () , [EMPLOYEES::HIRE_DATE] )` | MEASURE (numeric) |
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

**Fix:** convert all three simple metrics to formula columns (`formulas[]` entries) instead
of `aggregation:`-based `columns[]` entries. This eliminates the duplicate `column_id`.

---

## Output — ThoughtSpot Model TML

```yaml
model:
  name: Company Workforce
  description: >-
    Company workforce analytics exercising facts, double aggregation,
    and metric-on-fact resolution
  properties:
    is_bypass_rls: false
    join_progressive: true
    spotter_config:
      is_spotter_enabled: true
  model_tables:
  - name: COMPANIES
    fqn: "829f2a7d-aa1a-4475-ac28-4b3955eea3b7"
    joins:
    - name: employees_to_companies
      with: EMPLOYEES
      on: "[EMPLOYEES::COMPANY_ID] = [COMPANIES::COMPANY_ID]"
      type: LEFT_OUTER
      cardinality: ONE_TO_MANY
  - name: EMPLOYEES
    fqn: "5341e282-7259-4727-bb88-c186105a048c"
  formulas:
  # --- Facts (row-level expressions) ---
  - id: formula_Tenure Months
    name: Tenure Months
    expr: "diff_months ( today () , [EMPLOYEES::HIRE_DATE] )"
    properties:
      column_type: MEASURE
  - id: formula_Salary Band
    name: Salary Band
    expr: >-
      if ( [EMPLOYEES::SALARY] >= 90000 ) then 'Senior'
      else if ( [EMPLOYEES::SALARY] >= 70000 ) then 'Mid'
      else 'Junior'
    properties:
      column_type: ATTRIBUTE
  # --- Simple metrics (as formulas to avoid duplicate column_id) ---
  - id: formula_Headcount
    name: Headcount
    expr: "count ( [EMPLOYEES::EMPLOYEE_ID] )"
    properties:
      column_type: MEASURE
  - id: formula_Total Salary
    name: Total Salary
    expr: "sum ( [EMPLOYEES::SALARY] )"
    properties:
      column_type: MEASURE
  - id: formula_Avg Salary
    name: Avg Salary
    expr: "average ( [EMPLOYEES::SALARY] )"
    properties:
      column_type: MEASURE
  # --- Metric-on-fact (reference fact by formula id, NOT display name) ---
  - id: formula_Avg Tenure
    name: Avg Tenure
    expr: "average ( [formula_Tenure Months] )"
    properties:
      column_type: MEASURE
  - id: formula_Total Tenure
    name: Total Tenure
    expr: "sum ( [formula_Tenure Months] )"
    properties:
      column_type: MEASURE
  # --- Double aggregation (metric-on-metric via group_* shorthands) ---
  - id: formula_Avg Headcount Per Company
    name: Avg Headcount Per Company
    expr: "average ( group_count ( [EMPLOYEES::EMPLOYEE_ID] , [COMPANIES::COMPANY_ID] ) )"
    properties:
      column_type: MEASURE
  - id: formula_Max Salary Budget
    name: Max Salary Budget
    expr: "max ( group_sum ( [EMPLOYEES::SALARY] , [COMPANIES::COMPANY_ID] ) )"
    properties:
      column_type: MEASURE
  columns:
  # --- COMPANIES dimensions ---
  - name: Company Id
    column_id: COMPANIES::COMPANY_ID
    properties:
      column_type: ATTRIBUTE
  - name: Company Name
    column_id: COMPANIES::COMPANY_NAME
    description: The registered company name
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - Organisation
      synonym_type: USER_DEFINED
  - name: Founded Date
    column_id: COMPANIES::FOUNDED_DATE
    description: Date the company was founded
    properties:
      column_type: ATTRIBUTE
  - name: Headquarters City
    column_id: COMPANIES::HEADQUARTERS_CITY
    description: City where the company headquarters is located
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - City
      - HQ City
      - Location
      synonym_type: USER_DEFINED
  - name: Industry
    column_id: COMPANIES::INDUSTRY
    description: Industry classification of the company
    properties:
      column_type: ATTRIBUTE
  # --- EMPLOYEES dimensions ---
  - name: Employee Id
    column_id: EMPLOYEES::EMPLOYEE_ID
    properties:
      column_type: ATTRIBUTE
  - name: Employee Name
    column_id: EMPLOYEES::EMPLOYEE_NAME
    description: Full name of the employee
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - Name
      - Staff Member
      synonym_type: USER_DEFINED
  - name: Hire Date
    column_id: EMPLOYEES::HIRE_DATE
    description: Date the employee was hired
    properties:
      column_type: ATTRIBUTE
  - name: Department
    column_id: EMPLOYEES::DEPARTMENT
    description: Department the employee belongs to
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - Team
      - Division
      synonym_type: USER_DEFINED
  # --- Fact formula columns ---
  - name: Tenure Months
    formula_id: formula_Tenure Months
    description: Number of months since the employee was hired
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
  - name: Salary Band
    formula_id: formula_Salary Band
    description: Salary classification band based on annual salary
    properties:
      column_type: ATTRIBUTE
  # --- Simple metric formula columns ---
  - name: Headcount
    formula_id: formula_Headcount
    description: Total number of employees
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
      synonyms:
      - Employee Count
      - Number of Employees
      - Staff Count
      synonym_type: USER_DEFINED
  - name: Total Salary
    formula_id: formula_Total Salary
    description: Sum of all employee salaries
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
      synonyms:
      - Payroll
      - Total Compensation
      synonym_type: USER_DEFINED
  - name: Avg Salary
    formula_id: formula_Avg Salary
    description: Average employee salary
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
  # --- Metric-on-fact formula columns ---
  - name: Avg Tenure
    formula_id: formula_Avg Tenure
    description: Average employee tenure in months
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
  - name: Total Tenure
    formula_id: formula_Total Tenure
    description: Total accumulated tenure across all employees in months
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
  # --- Double aggregation formula columns ---
  - name: Avg Headcount Per Company
    formula_id: formula_Avg Headcount Per Company
    description: Average number of employees per company
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
  - name: Max Salary Budget
    formula_id: formula_Max Salary Budget
    description: Highest total salary budget across all companies
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
```

---

## Verification

Exported model after import confirms all 9 formulas, 18 columns, 1 join, and Spotter
enabled. Formula expressions round-trip correctly through export.

| Check | Result |
|---|---|
| Formulas count | 9 (2 facts + 3 simple + 2 metric-on-fact + 2 double agg) |
| Columns count | 18 (9 dimensions + 2 facts + 3 simple metrics + 2 metric-on-fact + 2 double agg) |
| Joins | COMPANIES → EMPLOYEES (LEFT_OUTER on COMPANY_ID) |
| Spotter | enabled |
| Synonyms preserved | Company Name (1), Headquarters City (3), Employee Name (2), Department (2), Headcount (3), Total Salary (2) |
| Descriptions preserved | 13 columns |

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
