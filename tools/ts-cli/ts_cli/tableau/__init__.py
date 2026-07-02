"""Tableau → ThoughtSpot conversion pipeline, split module-per-concern (BL-069).

Public entry points remain ts_cli.tableau_translate (translate_single,
translate_formulas) and ts_cli.model_builder (parse_twb, build_model_tml, ...);
both re-export from these modules for backward compatibility.
"""
