"""Domo → ThoughtSpot conversion (pure functions).

Layout mirrors the family's converter contract:

    ir.py          — normalized intermediate representation (dataclasses)
    parsing.py     — offline bundle-dir (or live payloads) -> DomoApp IR + inventory
    functions.py   — Beast Mode expression -> ThoughtSpot formula translation
    build_model.py — IR -> Table TML(s) + Model TML + mapping report
    answers.py     — IR -> Answer + Liveboard TML

Everything here returns dicts/strings and never touches disk or the network; the
`ts domo` command module (ts_cli/commands/domo.py) does all I/O.
"""
