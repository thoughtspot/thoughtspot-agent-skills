"""A profile's slug names its CREDENTIAL, so two names sharing one slug is a leak.

`slugify` is lossy — lowercase, every non-`[a-z0-9]` run to a hyphen, collapse, strip
— and the result becomes both the keychain service (`derive_keychain_service`) and the
env var (`derive_env_var`). `add_profile` dedupes by NAME, so two profiles with one
slug coexist in the JSON while sharing a credential: tenant B's token is sent to
tenant A's host, with nothing in any output revealing it.

The refusal is at WRITE time on purpose. Changing `slugify` would silently orphan
every keychain entry and env var already in use on every machine — a worse failure
than the one being fixed, and unfixable from inside the CLI.
"""
import pytest
from typer.testing import CliRunner

from ts_cli import client as client_module, profile_ops
from ts_cli.commands.profiles import app

runner = CliRunner()

# Every one of these reduces to 'acme-prod'.
COLLIDING = [
    "Acme Prod", "Acme/Prod", "ACME  PROD", "Acme-Prod", "acme prod",
    "Acme_Prod", "Acme.Prod", "  Acme Prod  ", "Acme  ///  Prod", "ACME PROD!!!",
]


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    paths = {
        "thoughtspot": tmp_path / "thoughtspot-profiles.json",
        "snowflake": tmp_path / "snowflake-profiles.json",
        "databricks": tmp_path / "databricks-profiles.json",
        "tableau": tmp_path / "tableau-profiles.json",
    }
    monkeypatch.setattr(profile_ops, "PROFILE_PATHS", paths)
    monkeypatch.setattr(client_module, "PROFILES_PATH", paths["thoughtspot"])
    return paths


# --- the pure rules ---------------------------------------------------------

def test_all_ten_variants_share_one_slug():
    """The premise. If this ever stops being true the refusal is over-strict."""
    assert len({profile_ops.slugify(n) for n in COLLIDING}) == 1


def test_slug_conflicts_finds_every_variant():
    conflicts = profile_ops.slug_conflicts("Acme Prod", COLLIDING[1:])
    assert conflicts == sorted(COLLIDING[1:])


def test_slug_conflicts_excludes_the_name_itself():
    """An exact-name match is a REPLACE — which `ts profiles update` does every call."""
    assert profile_ops.slug_conflicts("Acme Prod", ["Acme Prod"]) == []


def test_slug_conflicts_ignores_genuinely_distinct_names():
    assert profile_ops.slug_conflicts("Acme Prod 2", COLLIDING) == []


@pytest.mark.parametrize("name", ["ドモ 本番", "日本語", "---", "", "   ", "!!!", "。。"])
def test_names_with_no_ascii_alphanumeric_have_no_usable_slug(name):
    assert profile_ops.has_usable_slug(name) is False


@pytest.mark.parametrize("name", ["Acme", "a", "1", "Acme Prod (ドモ)", "café"])
def test_names_with_ascii_are_usable(name):
    assert profile_ops.has_usable_slug(name) is True


def test_accents_are_dropped_not_folded():
    """Documented so the surprise is on the record: `café` -> `caf`, not `cafe`.

    That means `café` collides with a profile literally named `Caf`, which is why the
    refusal is name-pair-based rather than a normalisation.
    """
    assert profile_ops.slugify("café") == "caf"
    assert profile_ops.slugify("Ünïcödé") == "n-c-d"
    assert profile_ops.slug_conflicts("café", ["Caf"]) == ["Caf"]


# --- the write-time refusal -------------------------------------------------

@pytest.mark.parametrize("second", COLLIDING[1:])
def test_second_colliding_name_is_refused(profile_dir, second):
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://a"})
    with pytest.raises(profile_ops.SlugCollisionError) as e:
        profile_ops.add_profile("thoughtspot", {"name": second, "url": "https://b"})
    assert "acme-prod" in str(e.value)
    assert "Acme Prod" in str(e.value)          # names the profile it clashes with
    assert "thoughtspot-acme-prod" in str(e.value)  # and the shared keychain service


def test_the_first_name_still_works(profile_dir):
    """Non-breaking: an existing profile keeps resolving exactly as before."""
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://a"})
    assert profile_ops.get_profile("thoughtspot", "Acme Prod")["url"] == "https://a"


def test_replacing_the_same_name_is_not_a_collision(profile_dir):
    """`ts profiles update` re-saves under the same name on every call."""
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://a"})
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://b"})
    assert profile_ops.get_profile("thoughtspot", "Acme Prod")["url"] == "https://b"


def test_empty_slug_is_refused_on_its_own(profile_dir):
    """Not a pair collision — an unusable slug clashes with every other unusable one.

    So it is refused the first time, not only when a second appears.
    """
    with pytest.raises(profile_ops.SlugCollisionError) as e:
        profile_ops.add_profile("thoughtspot", {"name": "ドモ 本番", "url": "https://a"})
    assert "no ASCII letter or digit" in str(e.value)


def test_a_refused_write_leaves_the_file_untouched(profile_dir):
    path = profile_dir["thoughtspot"]
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://a"})
    before = path.read_text()
    with pytest.raises(profile_ops.SlugCollisionError):
        profile_ops.add_profile("thoughtspot", {"name": "Acme/Prod", "url": "https://b"})
    assert path.read_text() == before


def test_collisions_are_per_platform(profile_dir):
    """The keychain service is `{platform}-{slug}`, so the same slug in two platforms
    is two different services and must NOT be refused."""
    profile_ops.add_profile("thoughtspot", {"name": "Acme Prod", "url": "https://a"})
    profile_ops.add_profile("tableau", {"name": "Acme/Prod", "server": "https://b"})
    assert profile_ops.get_profile("tableau", "Acme/Prod") is not None


# --- surfaced through the CLI, not as a traceback --------------------------

def test_cli_add_reports_the_collision_cleanly(profile_dir):
    runner.invoke(app, ["add", "--platform", "thoughtspot", "--name", "Acme Prod",
                        "--auth-type", "token", "--field", "url=https://a"])
    result = runner.invoke(app, ["add", "--platform", "thoughtspot", "--name", "Acme/Prod",
                                 "--auth-type", "token", "--field", "url=https://b"])
    assert result.exit_code == 1
    assert "acme-prod" in result.output
    assert "Traceback" not in result.output
