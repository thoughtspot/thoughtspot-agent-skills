"""ts spotter — ask Spotter (ThoughtSpot AI) a natural-language question over a Model.

Wraps the V2 endpoint `POST /api/rest/2.0/ai/answer/create` (`singleAnswer`,
Beta / 10.4.0.cl+; verified via `get-rest-api-reference(apiName: "singleAnswer")`
2026-07-14). It processes a single natural-language `query` against one Model/Worksheet
and returns Spotter's answer — crucially its **search tokens** (`tokens` /
`display_tokens`), the ThoughtSpot Search expression Spotter chose to answer the
question. No conversation session is created.

This is the "Spotter last-mile" used by the conversion skills (Tableau / Power BI →
ThoughtSpot): after a model is built, a measure that could not be translated
deterministically is phrased in plain English, handed to Spotter, and the returned
tokens are shown to the human to verify against the source numbers, then flagged or
adopted. It is generic — any converter (or a person) can call it.

Requires `CAN_USE_SPOTTER` privilege and at least view access to the target Model;
the cluster must have Spotter enabled. A 403 means one of those is missing.

Conventions (.claude/rules/ts-cli.md): structured JSON to stdout, diagnostics to
stderr, auth via --profile, metadata referenced by GUID (identifier), no raw requests
in skill code — skills call this command.
"""
from __future__ import annotations

import json as _json
from typing import Any, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Ask Spotter (ThoughtSpot AI) a natural-language question over a Model.")

_ANSWER_PATH = "/api/rest/2.0/ai/answer/create"

_profile_option = typer.Option(
    None, "--profile", "-p", envvar="TS_PROFILE",
    help="Profile name (default: first profile or TS_PROFILE env var)",
)
_model_option = typer.Option(
    ..., "--model", "-m",
    help="Model identifier — the Model/Worksheet GUID (from `ts metadata search --subtype WORKSHEET`)",
)


# ──────────────────────────────────────────────────────────────────────────────
# Pure response normalisation (unit-tested without a live connection)
# ──────────────────────────────────────────────────────────────────────────────

def normalise_answer_response(data: Any, http_status: int = 200) -> dict:
    """Normalise a raw `ai/answer/create` response into a stable shape.

    The endpoint returns 200 on success and, per its spec, may surface failures as a
    201 "Common error response" (same body shape, no useful answer fields) or a 4xx/5xx
    `{"error": {...}}` envelope. We collapse all of these to one shape:

    {status, message_type, visualization_type, session_identifier, generation_number,
     tokens, display_tokens, errors: [{code, message}]}

    - `status` is "SUCCESS" when tokens were produced, else an error code
      ("SPOTTER_ERROR" / "FORBIDDEN" / "UNAUTHORIZED" / "HTTP_<code>" / "PARSE_ERROR").
    - `tokens` / `display_tokens` are the Search expression Spotter chose — the field the
      last-mile workflow inspects.
    - a non-empty `errors` list means Spotter did not return a usable answer.
    """
    if not isinstance(data, dict):
        return {
            "status": "PARSE_ERROR",
            "message_type": None,
            "visualization_type": None,
            "session_identifier": None,
            "generation_number": None,
            "tokens": None,
            "display_tokens": None,
            "errors": [{"code": "PARSE_ERROR", "message": "Unexpected response format"}],
        }

    errors: list[dict] = []

    # 4xx/5xx error envelope: {"error": {...}} (message may be a str or a nested object).
    err = data.get("error")
    if err is not None:
        if isinstance(err, dict):
            msg = err.get("message")
            message = msg if isinstance(msg, str) else _json.dumps(msg) if msg is not None else str(err)
            code = str(err.get("code") or "")
        else:
            message, code = str(err), ""
        if not code:
            code = {401: "UNAUTHORIZED", 403: "FORBIDDEN"}.get(http_status, f"HTTP_{http_status}")
        errors.append({"code": code, "message": message})

    tokens = data.get("tokens")
    display_tokens = data.get("display_tokens")

    if errors:
        status = errors[0]["code"]
    elif http_status not in (200, 201):
        status = f"HTTP_{http_status}"
        errors.append({"code": status, "message": data.get("message") or "Request failed"})
    elif tokens or display_tokens or data.get("session_identifier"):
        status = "SUCCESS"
    else:
        # 201 error response, or a 200 with no answer payload — no usable answer.
        status = "SPOTTER_ERROR"
        errors.append({"code": status, "message": "Spotter returned no answer for this query"})

    return {
        "status": status,
        "message_type": data.get("message_type"),
        "visualization_type": data.get("visualization_type"),
        "session_identifier": data.get("session_identifier"),
        "generation_number": data.get("generation_number"),
        "tokens": tokens,
        "display_tokens": display_tokens,
        "errors": errors,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Command
# ──────────────────────────────────────────────────────────────────────────────

@app.command("answer")
def answer_cmd(
    query: str = typer.Argument(..., help="Natural-language question, e.g. 'total sales by region last quarter'"),
    model: str = _model_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Ask Spotter a single natural-language question over a Model and return its answer.

    Output: JSON {status, message_type, visualization_type, session_identifier,
    generation_number, tokens, display_tokens, errors}. `tokens` / `display_tokens` are
    the ThoughtSpot Search expression Spotter chose — the "last-mile" workflow shows
    these to a human to verify against the source measure, then flags or adopts them.

    A non-SUCCESS status with populated errors[] means no usable answer:
    FORBIDDEN (missing CAN_USE_SPOTTER / no view access), UNAUTHORIZED (bad token),
    or SPOTTER_ERROR (Spotter could not answer / Spotter not enabled).

    Examples:

    \\b
      ts spotter answer "total sales by region last quarter" -m <model-guid> --profile prod
      ts spotter answer "count of distinct customers this year" -m <model-guid>
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        _ANSWER_PATH,
        json={"query": query, "metadata_identifier": model},
        raise_for_status=False,  # surface structured 400/403 answer errors instead of crashing
    )
    try:
        data = resp.json() if resp.text else {}
    except ValueError:
        data = {}
    print(_json.dumps(normalise_answer_response(data, resp.status_code)))
