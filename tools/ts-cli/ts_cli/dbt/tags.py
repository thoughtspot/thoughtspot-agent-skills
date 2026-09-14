"""ThoughtSpot `ts_*` dbt metadata tags <-> TML column properties.

The single source of truth for the tag vocabulary, in BOTH directions:
`_build_column_meta` (TML properties -> tags) and `tml_properties_from_ts_meta`
(tags -> TML properties) are exact inverses, asserted property-for-property by
`TestFullPropertyRoundTrip`.

Covers all 13 column tags ThoughtSpot documents
(docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags, verified
2026-09-09) plus the ts-cli extensions `ts_ai_context`, `ts_display_name`,
`ts_formula` and model-level `ts_rls_rules`.

Split out of `dbt_build_export.py` under the `check_file_size` gate; imported by
both `dbt/manifest.py` and `dbt/model_from_schema_yml.py`, which is why it must
not import either (pure functions, no I/O).
"""
from __future__ import annotations

import re


# TML property key -> entry field. All read from col["properties"]; the TML shape
# and warnings are per agents/shared/schemas/thoughtspot-model-tml.md.
_PASSTHROUGH_PROPS = (
    "format_pattern", "index_type", "index_priority",
    "is_attribution_dimension", "is_additive", "spotiq_preference",
    "is_hidden", "calendar", "currency_type", "geo_config",
    # No `ts_*` tag exists for these — carried only so they can be REPORTED in
    # unmapped_properties rather than vanishing. See _NO_TAG_PROPS.
    "value_casing", "custom_order", "default_date_bucket", "search_iq_preferred",
)

# Real Model-column properties (agents/shared/schemas/thoughtspot-model-tml.md)
# that ThoughtSpot's dbt tag vocabulary has no entry for at all — there is
# nothing to map them to, so they cannot round-trip. They are reported rather
# than dropped in silence, which is the module's standing contract.
_NO_TAG_PROPS = {
    "value_casing": "no ts_* tag exists; thoughtspot-model-tml.md says pass through "
                    "on round-trips only, and dbt has nowhere to hold it",
    "custom_order": "no ts_* tag exists for a custom attribute-value display order",
    "default_date_bucket": "no ts_* tag exists for a default date granularity",
    "search_iq_preferred": "no ts_* tag exists for the Search IQ preference flag",
}

_COL_TYPE_MAP = {"attribute": "ATTRIBUTE", "measure": "MEASURE"}
_AGG_MAP = {
    "sum": "SUM", "count": "COUNT", "count_distinct": "COUNT_DISTINCT",
    "min": "MIN", "max": "MAX", "average": "AVERAGE",
    "std_deviation": "STD_DEVIATION", "variance": "VARIANCE", "none": "NONE",
}


def _first_table_ref(expr: str) -> "str | None":
    """First ThoughtSpot table name from a formula expression.
    'sum([STG_ORDERS::AMOUNT])' → 'STG_ORDERS'."""
    m = re.search(r'\[([^\]]+)::', expr)
    return m.group(1).strip() if m else None


def _formula_id(name: str) -> str:
    """Stable formula ID from a display name: 'Rev per Cust' → 'formula_Rev_per_Cust'."""
    return "formula_" + re.sub(r'[^A-Za-z0-9_]', '_', name)
# ---------------------------------------------------------------------------
# ts_* metadata tags — column-level meta: block
# ---------------------------------------------------------------------------

# ts_index_type only supports two of TML's five index_type values (verified
# against docs.thoughtspot.com/.../dbt-integration-metadata-tags 2026-08-27).
_TS_INDEX_TYPE_MAP = {"DEFAULT": "default", "DONT_INDEX": "dont_index"}
_TS_INDEX_TYPE_REVERSE_MAP = {v: k for k, v in _TS_INDEX_TYPE_MAP.items()}


# Every `ts_*` key this module is CAPABLE of writing into a column's
# `config.meta`, and the one it writes at model level. This is the generator's
# ownership boundary, and it is what makes `ts dbt-export sync
# --update-metadata` safe: a key in here may be overwritten or cleared (absent
# from a fresh generation means the property was removed in ThoughtSpot, so it
# should go from schema.yml too), and a `ts_*` key NOT in here is left strictly
# alone.
#
# The tags outside the boundary are the reason it has to exist. ThoughtSpot
# documents `ts_hidden`, `ts_calendar_type`, `ts_currency_type` and
# `ts_geo_config`, but this generator deliberately never emits them (is_hidden
# and calendar carry explicit "never emit during generation" warnings in
# agents/shared/schemas/thoughtspot-model-tml.md; currency_type and geo_config
# have no verified value mapping — see ts-convert-to-dbt open-items #9).
# `ts_column_exclude` is hand-authored by definition. A blanket "clear every
# `ts_*` key" merge therefore deleted hand-written tags with no diagnostic.
#
# Keep in sync with `_build_column_meta` / `_build_schema_columns` /
# `_build_schema_docs`; `test_dbt_build_export.py::TestGeneratedMetaKeyBoundary`
# fails if an emitter starts writing a key that is not declared here.
GENERATED_COLUMN_META_KEYS = frozenset({
    # ThoughtSpot's 13 documented column tags
    # (docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags, 2026-09-09)
    "ts_column_type",
    "ts_aggregation",
    "ts_synonym",
    "ts_format_pattern",
    "ts_index_type",
    "ts_index_priority",
    "ts_attr_dim",
    "ts_additive",
    "ts_spotiq_pref",
    "ts_hidden",
    "ts_calendar_type",
    "ts_currency_type",
    "ts_geo_config",
    # ts-cli extensions (read by `ts dbt build-model`, not by ThoughtSpot's
    # server-side generate-tml)
    "ts_ai_context",
    "ts_display_name",
    "ts_formula",
})

GENERATED_MODEL_META_KEYS = frozenset({"ts_rls_rules"})


# --- Nested-value tags: ts_currency_type / ts_geo_config --------------------
#
# Both carry a structured value on BOTH sides, with different shapes. dbt uses a
# `type` discriminator plus siblings; TML uses mutually-exclusive keys. Shapes
# verified against docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags
# (2026-09-09, verbatim YAML examples) and agents/shared/schemas/thoughtspot-model-tml.md
# (the 2026-07-30 500-document census).

_TRUE_WORDS = {"yes", "true", "1", "y"}


def _is_yes(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_WORDS if value is not None else False


def ts_currency_type_from_tml(currency_type) -> "dict | None":
    """TML `properties.currency_type` -> the nested `ts_currency_type` value.

        {iso_code: USD}     -> {type: from_isocode, isocode: USD}
        {column: CCY}       -> {type: from_column,  column: CCY}
        {is_browser: true}  -> {type: from_browser}
    """
    if not isinstance(currency_type, dict):
        return None
    if currency_type.get("iso_code"):
        return {"type": "from_isocode", "isocode": currency_type["iso_code"]}
    if currency_type.get("column"):
        return {"type": "from_column", "column": currency_type["column"]}
    if currency_type.get("is_browser"):
        return {"type": "from_browser"}
    return None


def tml_currency_type_from_ts(tag_value) -> "dict | None":
    """Inverse of :func:`ts_currency_type_from_tml`. `none`/unknown -> None."""
    if not isinstance(tag_value, dict):
        return None
    kind = str(tag_value.get("type") or "").strip().lower()
    if kind == "from_isocode" and tag_value.get("isocode"):
        return {"iso_code": tag_value["isocode"]}
    if kind == "from_column" and tag_value.get("column"):
        return {"column": tag_value["column"]}
    if kind == "from_browser":
        return {"is_browser": True}
    return None


def ts_geo_config_from_tml(geo) -> "tuple[dict | None, str | None]":
    """TML `properties.geo_config` -> nested `ts_geo_config`, or `(None, reason)`.

    Four of TML's five census-observed role shapes have a `ts_geo_config` type::

        {latitude: true}                            -> {type: latitude}
        {longitude: true}                           -> {type: longitude}
        {country: true}                             -> {type: country}
        {region_name: {country: C, region_name: R}} -> {type: sub_nation_region,
                                                        country: C, region_type: R}

    The fifth — a custom-map role (`custom_file_guid` + `geometryType`) — has no
    `ts_geo_config` type, and thoughtspot-model-tml.md records it as
    instance-local ("a portable document must not carry it — the geo role has to
    be dropped rather than translated"), so it is reported unmapped.

    Note `country: true` is a BARE BOOLEAN role and is not the same field as
    `region_name.country`, which is a string naming the region's country.
    """
    if not isinstance(geo, dict):
        return None, None
    if geo.get("latitude"):
        return {"type": "latitude"}, None
    if geo.get("longitude"):
        return {"type": "longitude"}, None
    if geo.get("country") is True:
        return {"type": "country"}, None
    region = geo.get("region_name")
    if isinstance(region, dict):
        out: dict = {"type": "sub_nation_region"}
        if region.get("country"):
            out["country"] = region["country"]
        if region.get("region_name"):
            out["region_type"] = region["region_name"]
        return out, None
    if geo.get("custom_file_guid"):
        return None, ("custom-map geo role (custom_file_guid + geometryType) has no "
                      "ts_geo_config type and is instance-local — dropped, not translated")
    return None, "unrecognized geo_config shape — no ts_geo_config type matches"


def tml_geo_config_from_ts(tag_value) -> "dict | None":
    """Inverse of :func:`ts_geo_config_from_tml`. `none`/unknown -> None."""
    if not isinstance(tag_value, dict):
        return None
    kind = str(tag_value.get("type") or "").strip().lower()
    if kind in ("latitude", "longitude"):
        return {kind: True}
    if kind == "country":
        return {"country": True}
    if kind == "sub_nation_region":
        inner: dict = {}
        if tag_value.get("country"):
            inner["country"] = tag_value["country"]
        if tag_value.get("region_type"):
            inner["region_name"] = tag_value["region_type"]
        return {"region_name": inner} if inner else None
    return None


def _build_column_meta(entry: dict, unmapped_props: list[dict]) -> dict:
    """Build the `meta:` dict of `ts_*` tags for one column.

    Covers every column tag ThoughtSpot documents
    (docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags, verified
    2026-09-09) plus the ts-cli extensions. :func:`tml_properties_from_ts_meta`
    is the exact inverse — change one and the round-trip test fails.

    Only genuinely untranslatable residue reaches ``unmapped_props``: an
    `index_type` outside the two-value tag vocabulary, and a geo role with no
    `ts_geo_config` type.
    """
    meta: dict = {}
    if entry["kind"] == "metric":
        meta["ts_column_type"] = "measure"
        if entry.get("agg"):
            meta["ts_aggregation"] = entry["agg"].lower()
    else:
        meta["ts_column_type"] = "attribute"

    display = entry.get("display_name") or entry.get("name") or ""
    synonyms = [s for s in (entry.get("synonyms") or []) if s and s != display]
    if synonyms:
        meta["ts_synonym"] = ", ".join(str(s) for s in synonyms)
    if entry.get("format_pattern"):
        meta["ts_format_pattern"] = entry["format_pattern"]
    if entry.get("index_priority") is not None:
        meta["ts_index_priority"] = entry["index_priority"]
    if entry.get("is_attribution_dimension"):
        meta["ts_attr_dim"] = "yes"
    if entry.get("is_additive"):
        meta["ts_additive"] = "yes"
    if entry.get("spotiq_preference") == "EXCLUDE":
        meta["ts_spotiq_pref"] = "exclude"
    if entry.get("is_hidden"):
        meta["ts_hidden"] = "yes"
    if entry.get("calendar"):
        meta["ts_calendar_type"] = entry["calendar"]

    currency = ts_currency_type_from_tml(entry.get("currency_type"))
    if currency:
        meta["ts_currency_type"] = currency

    geo, geo_reason = ts_geo_config_from_tml(entry.get("geo_config"))
    if geo:
        meta["ts_geo_config"] = geo
    elif geo_reason:
        unmapped_props.append({
            "column": display, "property": "geo_config",
            "value": entry.get("geo_config"), "reason": geo_reason,
        })

    _collect_unmapped_column_props(entry, unmapped_props)
    return meta


def _collect_unmapped_column_props(entry: dict, unmapped_props: list[dict]) -> None:
    """Residue with no tag equivalent. `is_hidden`, `calendar`, `currency_type`
    and `geo_config` used to land here; all four are emitted now, so only an
    out-of-vocabulary `index_type` remains (the geo custom-map case is reported
    by `_build_column_meta`, which is where that shape is inspected)."""
    label = entry.get("display_name") or entry.get("name") or ""
    index_type = entry.get("index_type")
    if index_type and str(index_type).upper() not in _TS_INDEX_TYPE_MAP:
        unmapped_props.append({
            "column": label,
            "property": "index_type",
            "value": index_type, "reason": "no ts_index_type equivalent for this value",
        })
    for prop, reason in _NO_TAG_PROPS.items():
        if entry.get(prop) not in (None, "", [], {}):
            unmapped_props.append({
                "column": label, "property": prop,
                "value": entry.get(prop), "reason": reason,
            })


def tml_properties_from_ts_meta(meta: dict) -> dict:
    """dbt column `config.meta` `ts_*` tags -> a ThoughtSpot Model column's
    `properties` dict. The exact inverse of :func:`_build_column_meta`.

    ONE implementation, called by every read path (`build_model_tml_from_schema_yml`
    and `build_model_tml_from_manifest`, for physical and formula columns alike).
    They previously each inlined a partial version, which is how `ts_index_priority`,
    `ts_attr_dim`, `ts_additive` and `ts_spotiq_pref` came to be written by
    `build` and then silently dropped on the way back.
    """
    meta = meta or {}
    props: dict = {}

    col_type = _COL_TYPE_MAP.get(str(meta.get("ts_column_type") or "").lower())
    if col_type:
        props["column_type"] = col_type
    agg = _AGG_MAP.get(str(meta.get("ts_aggregation") or "").lower())
    if agg:
        props["aggregation"] = agg

    synonyms = [s.strip() for s in str(meta.get("ts_synonym") or "").split(",") if s.strip()]
    if synonyms:
        props["synonyms"] = synonyms
        # thoughtspot-model-tml.md: "Set to USER_DEFINED whenever you populate
        # properties.synonyms." Derived, not round-tripped — there is no
        # ts_synonym_type tag and no need for one.
        props["synonym_type"] = "USER_DEFINED"
    if meta.get("ts_format_pattern"):
        props["format_pattern"] = meta["ts_format_pattern"]

    index_type = _TS_INDEX_TYPE_REVERSE_MAP.get(str(meta.get("ts_index_type") or "").lower())
    if index_type:
        props["index_type"] = index_type
    if meta.get("ts_index_priority") is not None:
        props["index_priority"] = meta["ts_index_priority"]
    if _is_yes(meta.get("ts_attr_dim")):
        props["is_attribution_dimension"] = True
    if _is_yes(meta.get("ts_additive")):
        props["is_additive"] = True
    if str(meta.get("ts_spotiq_pref") or "").strip().lower() == "exclude":
        props["spotiq_preference"] = "EXCLUDE"
    if _is_yes(meta.get("ts_hidden")):
        props["is_hidden"] = True

    calendar = meta.get("ts_calendar_type")
    if calendar and str(calendar).strip().lower() != "none":
        props["calendar"] = calendar

    currency = tml_currency_type_from_ts(meta.get("ts_currency_type"))
    if currency:
        props["currency_type"] = currency
    geo = tml_geo_config_from_ts(meta.get("ts_geo_config"))
    if geo:
        props["geo_config"] = geo

    if meta.get("ts_ai_context"):
        props["ai_context"] = meta["ts_ai_context"]
    return props


def _apply_index_type(meta: dict, entry: dict) -> None:
    mapped = _TS_INDEX_TYPE_MAP.get(str(entry.get("index_type") or "").upper())
    if mapped:
        meta["ts_index_type"] = mapped
# Tokens kept fully upper-case when prettifying warehouse column names —
# "Customer ID" reads better on a chart than "Customer Id".
_PRETTY_KEEP_UPPER = {"ID", "URL", "SKU", "ZIP", "API", "UTC", "USD", "EUR", "GBP", "SSN", "VAT", "PO"}


_NUMERIC_TYPE_RE = re.compile(
    r"^(NUMBER|NUMERIC|DECIMAL|INT|INTEGER|BIGINT|SMALLINT|TINYINT|FLOAT|FLOAT4|FLOAT8|DOUBLE|REAL|"
    r"DOUBLE PRECISION|MONEY)\b", re.I)


_ID_LIKE_NAME_RE = re.compile(r"(^|_)(ID|KEY|CODE|NUMBER|NUM|NO)$", re.I)


def infer_column_meta(catalog_type: str, *, is_mf_attribute: bool = False,
                      column_name: str = "") -> dict:
    """Default ts_* meta for a column that carries none in schema.yml.

    ``catalog_type`` is the warehouse type from catalog.json (``NUMBER(38,2)``,
    ``TEXT``, ``DATE`` …). Numeric types become ``measure``/``sum``; everything
    else — any column that is a MetricFlow entity or dimension, and any column
    whose name ends in an identifier-like suffix (``_ID``, ``_KEY``, ``_CODE``,
    ``_NUMBER``/``_NUM``/``_NO``) — becomes ``attribute``. Keys mirror the
    schema.yml tags so the rest of the pipeline treats inferred and declared
    columns identically.
    """
    if is_mf_attribute or _ID_LIKE_NAME_RE.search(column_name or ""):
        return {"ts_column_type": "attribute"}
    if _NUMERIC_TYPE_RE.match(catalog_type or ""):
        return {"ts_column_type": "measure", "ts_aggregation": "sum"}
    return {"ts_column_type": "attribute"}


def is_column_excluded(meta: dict) -> bool:
    """True when a column's meta carries ``ts_column_exclude`` set to a truthy
    value (``yes``/``true``/``1``, or YAML booleans). A ts-cli extension tag:
    the column stays on the ThoughtSpot Table (Tables are generated server-side
    by `generate-tml`, which doesn't read it) but is left out of the Model
    `ts dbt build-model` assembles. Distinct from ThoughtSpot's own ``ts_hidden``,
    which keeps the column in the Model and only hides it in the UI.
    """
    v = (meta or {}).get("ts_column_exclude")
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"yes", "true", "1", "y"} if v is not None else False


def prettify_column_name(name: str) -> str:
    """WAREHOUSE_STYLE → "Warehouse Style" for Model column display names.

    Splits on underscores / runs of whitespace, title-cases each token and
    keeps a short list of acronyms upper-case (``CUSTOMER_ID`` → ``Customer ID``).
    Tokens that already mix case (e.g. ``iPhone``) are left as written.
    """
    tokens = [t for t in re.split(r"[_\s]+", name.strip()) if t]
    out: list[str] = []
    for t in tokens:
        if t.upper() in _PRETTY_KEEP_UPPER:
            out.append(t.upper())
        elif t.isupper() or t.islower():
            out.append(t.capitalize())
        else:
            out.append(t)
    return " ".join(out) or name


def find_display_name_collisions(model_tml: dict) -> list[tuple[str, list[str]]]:
    """Return [(display_name_lower, [column_id or formula id, ...])] for names used twice.

    ThoughtSpot rejects a Model whose columns share a display name, compared
    case-insensitively ("Multiple columns with the same name found"). Physical
    columns are keyed by ``column_id`` (TABLE::COLUMN), formula columns by
    ``formula:<formula_id>``.
    """
    seen: dict[str, list[str]] = {}
    for c in model_tml.get("model", {}).get("columns", []):
        key = (c.get("name") or "").strip().lower()
        ref = c.get("column_id") or f"formula:{c.get('formula_id')}"
        seen.setdefault(key, []).append(ref)
    return sorted((k, v) for k, v in seen.items() if len(v) > 1)
