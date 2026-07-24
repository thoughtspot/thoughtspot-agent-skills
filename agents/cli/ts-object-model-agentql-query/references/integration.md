# Calling AgentQL from your own product or agent

Reference material for invoking AgentQL directly over HTTP — when you are **not** using the
`ts` CLI but building AgentQL into your own product, agent, or script. The CLI
(`ts spotql generate-sql` / `fetch-data`) is the easier path; this doc is for everyone who
needs the raw API. Verified live on `champ-staging`, 2026-06-25.

> **These are callosum endpoints, not the public REST API.** AgentQL lives under
> `/callosum/v1/v2/data/spotql/`, not `/api/rest/2.0/`. It is **not** in the published
> ThoughtSpot REST API spec (the SpotterCode/dev-docs reference does not index it). The
> shapes below are empirical — confirm against your own build.

## 1. Authentication

Every call carries a bearer token:

```
Authorization: Bearer <token>
Content-Type: application/json
Accept: application/json
```

Three ways to get the token:

**A — Trusted-auth secret key (recommended for a service/agent).** If trusted auth is
enabled, mint a token server-side without a user password:

```
POST /api/rest/2.0/auth/token/full
{ "username": "<user>", "secret_key": "<trusted-auth-secret>", "validity_time_in_sec": 3600 }
→ { "token": "...", "expiration_time_in_millis": 1781234567890 }
```

**B — Username + password.**

```
POST /api/rest/2.0/auth/token/full
{ "username": "<user>", "password": "<password>", "validity_time_in_sec": 3600 }
→ { "token": "...", "expiration_time_in_millis": ... }
```

**C — Existing bearer token.** A browser-session token or a long-lived provisioned token
is used directly — no exchange.

Cache the token and refresh it before `expiration_time_in_millis` (option C tokens may
carry no API-derived expiry — refresh on 401).

## 2. Endpoints and request bodies

Both are POST, same base path:

```
POST {base_url}/callosum/v1/v2/data/spotql/generate-sql   — compile only, no execution
POST {base_url}/callosum/v1/v2/data/spotql/fetch-data     — compile + execute
```

`fetch-data` body:

```json
{ "spotql_query": "<AgentQL>", "model_identifier": "<Model GUID>" }
```

`generate-sql` body — the playground schema also lists `connection_type`. It is
**optional**: omit it for a standard CDW-backed Model (the `ts` CLI omits it and the call
succeeds). Include it only if your build requires it.

```json
{ "spotql_query": "<AgentQL>", "model_identifier": "<Model GUID>", "connection_type": "<optional>" }
```

The `model_identifier` is the Model's GUID — a `LOGICAL_TABLE` of subtype `WORKSHEET`,
found via `POST /api/rest/2.0/metadata/search`.

## 3. `generate-sql` response

Success — just the compiled warehouse SQL, **no `status` field**:

```json
{ "executable_sql": "SELECT \"ta_1\".\"CATEGORY_NAME\" ... GROUP BY \"ca_1\" LIMIT 100000" }
```

Error — HTTP **400** with a structured envelope; the validation code is bracketed inside
`debug`:

```json
{ "error": { "message": { "code": 400, "debug": "Error Code: COLUMN_NOT_FOUND — ..." } } }
```

Pull the `[CODE]` / `Error Code: CODE` out of `error.message.debug` to surface a meaningful
message (`code` here is the HTTP status, not the validation code — the validation code lives
inside `debug`). Do **not** `raise_for_status()` blindly — query errors are 400s you want to
parse, not crash on.

## 4. `fetch-data` response

Success is **columnar**, not row-major:

```json
{
  "query_result": { "results": [ {
    "tables": {
      "column": [
        { "name": "<per-query GUID>", "type": "CHAR",
          "value": [ { "stringVal": "Electronics", "int64Val": "0", "doubleVal": 0.0, "nullVal": false, ... }, ... ] },
        { "name": "<per-query GUID>", "type": "DOUBLE",
          "value": [ { "doubleVal": 31582220.11, "stringVal": "", "nullVal": false, ... }, ... ] },
        { "name": "<per-query GUID>", "type": "INT64",
          "value": [ { "int64Val": "1672107", "doubleVal": 0.0, "nullVal": false, ... }, ... ] }
      ],
      "numRowsReturned": "8", "numRowsTotal": "8"
    } } ] }
}
```

Four gotchas that the format forces:

1. **Columnar, not row-major.** All values for column 0, then all for column 1, … You must
   transpose to get rows.
2. **Column `name` is an unstable per-query GUID** — it changes every run. Use the **SELECT
   ordinal** (position 0, 1, 2, …) as the identifier and map it to your own column label.
3. **`INT64` arrives as a JSON string** (`"int64Val": "1672107"`, not a number) to avoid
   integer precision loss — parse with `int()`.
4. **Every cell carries all type fields** (`stringVal`, `int64Val`, `doubleVal`, `boolVal`,
   …) with zeros/empties for the irrelevant ones. Use the **column-level `type`** to pick
   which field to read; check `nullVal` first.

## 5. Minimal response parser

Transposes the columnar `fetch-data` result to rows, keyed to SELECT order. Mirrors
`extract_columns_and_rows` / `_cell_value` in `tools/ts-cli/ts_cli/commands/spotql.py`.

```python
TYPE_FIELD = {
    "CHAR": "stringVal", "VARCHAR": "stringVal", "STRING": "stringVal", "TYPE_STRING": "stringVal",
    "INT32": "int32Val", "TYPE_INT32": "int32Val",
    "INT64": "int64Val", "TYPE_INT64": "int64Val",
    "DOUBLE": "doubleVal", "TYPE_DOUBLE": "doubleVal",
    "FLOAT": "floatVal", "TYPE_FLOAT": "floatVal",
    "BOOL": "boolVal", "BOOLEAN": "boolVal", "TYPE_BOOL": "boolVal",
    "BYTES": "bytesVal", "TYPE_BYTES": "bytesVal",
}

def parse_fetch_data(resp_json):
    results = resp_json["query_result"]["results"][0]
    raw_cols = results["tables"]["column"]

    def cell_value(cell, col_type):
        if cell.get("nullVal"):
            return None
        field = TYPE_FIELD.get(col_type)
        if field is None:
            for f in ("stringVal", "int64Val", "int32Val", "doubleVal", "floatVal", "boolVal", "bytesVal"):
                v = cell.get(f)
                if v not in (None, "", 0, 0.0, False):
                    field = f
                    break
        if field is None:
            return None
        val = cell.get(field)
        if field == "int64Val" and isinstance(val, str):
            return int(val)          # int64 is JSON-encoded as a string
        return val

    col_types = [c["type"] for c in raw_cols]
    col_values = [c.get("value", []) for c in raw_cols]
    n_rows = max((len(v) for v in col_values), default=0)
    return [
        [cell_value(col_values[c][r] if r < len(col_values[c]) else {"nullVal": True}, col_types[c])
         for c in range(len(raw_cols))]
        for r in range(n_rows)
    ]
```

The returned `[[...], [...]]` rows are in SELECT order — label column 0, 1, 2 from the
SELECT list you wrote.
