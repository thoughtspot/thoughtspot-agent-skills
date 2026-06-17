"""Unit tests for check_secrets._is_placeholder_value placeholder anchoring.

Audit security fix: short markers ("test", "my", "xxx", "fake") must only match as
a whole token, never as an arbitrary substring/prefix — otherwise a genuine leaked
secret that merely *contains* those letters gets waved through.
"""
import check_secrets as cs


# ── still treated as placeholders (true) ────────────────────────────────────

def test_template_var_value_is_placeholder():
    assert cs._is_placeholder_value("{token}")
    assert cs._is_placeholder_value("<your-token-here>")
    assert cs._is_placeholder_value("[redacted]")


def test_short_value_is_placeholder():
    assert cs._is_placeholder_value("abc")


def test_identifier_value_is_placeholder():
    assert cs._is_placeholder_value("passphrase_bytes")


def test_long_word_prefix_is_placeholder():
    assert cs._is_placeholder_value("YOUR_REAL_TOKEN_HERE")
    assert cs._is_placeholder_value("example-secret-value")
    assert cs._is_placeholder_value("placeholder12345")


def test_short_word_as_whole_token_is_placeholder():
    assert cs._is_placeholder_value("my_db_value")     # "my" delimited by "_"
    assert cs._is_placeholder_value("test_key_value")  # "test" token
    assert cs._is_placeholder_value("some.fake.value")  # "fake" token
    assert cs._is_placeholder_value("xxx-xxxx-xxxx")    # "xxx" token


# ── now correctly NOT placeholders (false) — the tightening ──────────────────

def test_secret_merely_containing_short_word_is_not_placeholder():
    # Contains "my"/"test"/"fake" glued to other chars (not a whole token), and a
    # non-identifier char so the variable-name exemption doesn't apply. Before the
    # fix these were waved through by a naive substring/prefix match.
    assert not cs._is_placeholder_value("myReal!Secret9f3a2b")
    assert not cs._is_placeholder_value("testReal!Secret9f3a")
    assert not cs._is_placeholder_value("realFake!Secret9f3a")


def test_random_base64ish_value_is_not_placeholder():
    assert not cs._is_placeholder_value("Zk9$Lm2!Pq7@Rt4#Vx0")
