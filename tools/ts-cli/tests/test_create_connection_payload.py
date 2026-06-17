"""Unit tests for _build_create_payload() in ts_cli/commands/connections.py.

Verifies the Snowflake key-pair connection/create payload shape:
  - authenticationType is KEY_PAIR (not the SERVICE_ACCOUNT default)
  - the private key sits under the `private_key` attribute (not `privateKey`)
  - validate is false and externalDatabases is empty (no-tables create)
  - the optional database attribute is included only when provided
No live ThoughtSpot connection required.
"""
from ts_cli.commands.connections import _build_create_payload

# Stand-in for PEM key material — deliberately NOT a real PEM header so the
# secrets scanner doesn't flag the test. The builder treats the key as an opaque
# string, so any sentinel exercises the pass-through path.
PRIVATE_KEY_SENTINEL = "FAKE-PKCS8-KEY-BODY-FOR-TEST"


def _base():
    return _build_create_payload(
        name="APJ_SKILLS",
        account="thoughtspot_partner.ap-southeast-2",
        user="APJPOC",
        role="SE_ROLE",
        warehouse="DEMO_WH",
        private_key=PRIVATE_KEY_SENTINEL,
    )


def test_top_level_shape():
    p = _base()
    assert p["name"] == "APJ_SKILLS"
    assert p["data_warehouse_type"] == "SNOWFLAKE"
    assert p["validate"] is False


def test_key_pair_auth_type():
    p = _base()
    assert p["data_warehouse_config"]["authenticationType"] == "KEY_PAIR"


def test_private_key_attribute_name():
    p = _base()
    config = p["data_warehouse_config"]["configuration"]
    # The API requires `private_key`; `privateKey` is rejected with code 12124.
    assert "private_key" in config
    assert "privateKey" not in config
    assert config["private_key"] == PRIVATE_KEY_SENTINEL


def test_no_tables_on_create():
    p = _base()
    assert p["data_warehouse_config"]["externalDatabases"] == []


def test_config_credentials():
    config = _base()["data_warehouse_config"]["configuration"]
    assert config["accountName"] == "thoughtspot_partner.ap-southeast-2"
    assert config["user"] == "APJPOC"
    assert config["role"] == "SE_ROLE"
    assert config["warehouse"] == "DEMO_WH"


def test_database_omitted_when_absent():
    config = _base()["data_warehouse_config"]["configuration"]
    assert "database" not in config


def test_database_included_when_present():
    p = _build_create_payload(
        name="C", account="a", user="u", role="r", warehouse="w",
        private_key="k", database="AGENT_SKILLS",
    )
    assert p["data_warehouse_config"]["configuration"]["database"] == "AGENT_SKILLS"
