<!-- currency: powerbi — 2026-07 (verified on ps-internal) -->
# Worked example — SPLY / YoY via a Reference Date parameter

Power BI computes `SAMEPERIODLASTYEAR` natively; ThoughtSpot has no direct formula equivalent.
Rebuild it with one model **parameter** that every comparison measure reads. Verified live
(per-month numbers matched) on the Employee Hiring and History migration.

## The parameter
```yaml
model:
  parameters:
  - name: Reference Date
    data_type: DATE
    default_value: 12/31/2024     # MM/DD/YYYY
```

## The measures (id-referenced, topo-sorted)
```
Month Of Year    = month([Date::Date])                              # ATTRIBUTE, sorts 1-12
New Hires Ref Yr = sum_if(year([Date::Date]) = year([Reference Date]),     [formula_isNewHire])
New Hires SPLY   = sum_if(year([Date::Date]) = year([Reference Date]) - 1, [formula_isNewHire])
New Hires YoY    = [formula_New Hires Ref Yr] - [formula_New Hires SPLY]
New Hires YoY %  = safe_divide([formula_New Hires YoY], [formula_New Hires SPLY])
```

## Cascade bonus
Give the SPLY override measures the **same names** as the Power BI measures. The author's own
`... YoY Var` / `... YoY % Change` measures then auto-translate through the `[formula_<name>]`
id-references — no per-measure override needed.

## Why a parameter, not Spotter's `vs`
Spotter answers the same ask with the `vs` token (`[New Hires] [Year]=2024 vs [Year]=2023
[Date].'month of year'`). The parameter path is chosen for dynamism: change one Reference Date
and every comparison chart re-points. Use Spotter's `vs` for a one-off answer; the parameter for
a migrated board.
