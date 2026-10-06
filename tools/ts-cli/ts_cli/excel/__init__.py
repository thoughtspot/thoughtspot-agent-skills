"""Excel / Google Sheets ⇄ ThoughtSpot formula translation (deterministic, BL-339 PR).

Modules (pure logic, no I/O, no typer):

- ``lexer``     — tokenizer for the Excel formula grammar
- ``parser``    — recursive-descent parser → the Excel AST (``nodes`` classes)
- ``nodes``     — Excel AST node types
- ``tsast``     — ThoughtSpot AST helpers and the canonical-spacing printer; the AST shape
                  is ``databricks.mv_emit_expr.parse_formula``'s, so a ThoughtSpot formula
                  is parsed by that one parser (reverse direction) and printed here
- ``rules``     — the function rule table: every Excel function the translator handles,
                  the map row it implements and the ThoughtSpot names it emits (checked
                  against the maps by ``tools/validate/check_mapping_code_sync.py``)
- ``functions`` — one handler per rule (Excel call → ThoughtSpot AST)
- ``criteria``  — ``*IF`` / ``*IFS`` criteria strings → conditions (Excel map E11)
- ``forward``   — ``Translator``: Excel AST → ThoughtSpot AST at row level
- ``measure``   — the intended-role pass (MEASURE: additive sums, ratio of totals)
- ``translate`` — ``translate_excel()``: the entry point the formula_translate adapter calls
- ``to_excel``  — the reverse direction, ThoughtSpot → Excel
- ``map_index`` — the Excel and Sheets maps' row inventory (name → section, class), vendored
                  so a NEEDS_REVIEW can cite its row; a test keeps it equal to the maps

Maps: docs/function-maps/ts-excel-function-mapping.md, ts-sheets-function-mapping.md.
"""
