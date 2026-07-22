"""Qlik Sense -> ThoughtSpot conversion — pure functions (no HTTP, no file writes).

Ported from the vendored ``qlik-migration-ts/q2t`` package. Layout mirrors the
Tableau converter subpackage:

  ir.py          — normalized intermediate representation (dataclasses)
  parsing.py     — offline (.qvf) + engine-artifacts extraction -> IR + inventory
  functions.py   — Qlik expression -> ThoughtSpot formula translation + coverage map
  build_model.py — IR -> Table TML(s) + Model TML + mapping report
  answers.py     — IR -> Answer + tabbed Liveboard TML

The ``ts qlik`` command module (ts_cli/commands/qlik.py) does all I/O; every
function here returns dicts/strings.
"""
