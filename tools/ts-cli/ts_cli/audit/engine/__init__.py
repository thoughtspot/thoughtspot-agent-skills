"""The audit rule engine: runs catalog rules (ts_cli/audit/catalog/) over an AuditContext.

    scopes.py      what a rule iterates over, and which data each item has
    fields.py      field paths and the derived-field registry (`@name`)
    predicates.py  `where` / `match` expressions
    bands.py       severity bands and override layering (catalog -> profile -> layers)
    messages.py    message templates and name lists
    modes.py       the six aggregation modes, each producing findings for one rule
    code_rules.py  the code-rule registry (`implementation: code:<name>`) and its contract
    run.py         `run_rules` — selection, layering, and the finding contract

Deliberately imports nothing: the catalog gate loads `engine.fields` and
`engine.code_rules` without the rest of ts_cli (see catalog_expr.known_derived_fields
and catalog_validate.known_code_rules).
"""
