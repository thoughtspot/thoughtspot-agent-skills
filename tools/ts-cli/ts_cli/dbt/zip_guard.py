"""Explain the 400 a ZIP_FILE connection returns when a generate call has no `--file`.

The API requires the artifact archive on every generate call for a ZIP_FILE
connection (intended), so every call must upload one. Without it ThoughtSpot
answers 400 "Error with the uploaded ZIP file.", which reads as a bad archive
and sends people regenerating artifacts that were fine (ts-convert-from-dbt
open-items #21).

The 400 is read after the fact rather than predicted by looking the connection
up first: no extra request, nothing to stall on a slow `dbt/search`, and no
dependence on that list's user/Org scoping, which hid connections created by
someone else. Pure function, no I/O; the caller in commands/dbt.py sends the
request.
"""
from __future__ import annotations

from typing import Optional

_MISSING_ARCHIVE_ERROR = "error with the uploaded zip file"


def missing_archive_message(status_code: int, body: str, connection_id: str) -> Optional[str]:
    """The explanation for a no-`--file` generate call's 400, else None.

    Only that exact 400 is explained; any other failure keeps its own error.
    """
    if status_code != 400 or _MISSING_ARCHIVE_ERROR not in (body or "").lower():
        return None
    return (
        f"ThoughtSpot answered 400 'Error with the uploaded ZIP file.' for connection "
        f"{connection_id}, and no --file was given. That 400 means the archive is missing, "
        "not that it is bad: a ZIP_FILE connection needs --file on every generate call "
        "(the `target/` directory, or a .zip of manifest.json + catalog.json).")
