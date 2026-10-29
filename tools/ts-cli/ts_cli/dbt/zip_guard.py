"""Should a generate call with no `--file` be refused? (ZIP_FILE connections.)

The API requires the artifact archive on every generate call for a ZIP_FILE
connection (intended), so every call must upload one. Without it ThoughtSpot
answers 400 "Error with the uploaded ZIP file.", which reads as a bad archive
and sends people regenerating artifacts that were fine (ts-convert-from-dbt
open-items #21).

Best effort by design: `dbt/search` is scoped by user and Org, so a connection
missing from the list may still exist. Only a positive ZIP_FILE match refuses;
an unreadable list, an unexpected shape or a miss lets the server decide.
The lookup itself is I/O and lives in commands/dbt.py (pure functions, no I/O).
"""
from __future__ import annotations

from typing import Any, Optional


def zip_file_refusal(connections: Any, connection_id: str) -> Optional[str]:
    """The refusal message when `connection_id` is listed as ZIP_FILE, else None.

    `connections` is the `dbt/search` response body, or None when it could not be read.
    """
    if not isinstance(connections, list):
        return None
    for connection in connections:
        if (isinstance(connection, dict)
                and connection.get("dbt_connection_identifier") == connection_id
                and str(connection.get("import_type", "")).upper() == "ZIP_FILE"):
            return (
                f"Connection {connection_id} is a ZIP_FILE connection: pass --file on every "
                "generate call (the `target/` directory, or a .zip of manifest.json + catalog.json). "
                "Without it ThoughtSpot returns a misleading 400 'Error with the uploaded ZIP file.'")
    return None
