"""Single-formula translation for `ts formula translate` / `ts formula detect`.

Modules (pure logic, no typer):

- ``context``  — the three column-context levels and the recording resolver (spec §5)
- ``refs``     — reference extraction and the post-translation qualification pass
- ``adapters`` — one adapter per existing translator; wraps, never forks (BL-217)
- ``traps``    — the semantic-difference lines (round increment, diff order, OI-2/3/4, …)
- ``engine``   — ``translate()``: the dialect-independent pipeline and TML snippet
- ``detect``   — scored dialect detection with must-ask ties (spec §4)
- ``validate`` — VALIDATE_ONLY compile and scratch-Model execute, with cleanup (spec §5.1)

Design: docs/superpowers/specs/2026-10-06-ts-object-formula-translate-design.md
"""
