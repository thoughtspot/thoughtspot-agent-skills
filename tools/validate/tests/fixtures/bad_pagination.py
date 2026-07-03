"""Known-bad pagination fixture (for test_known_bad_fixtures.py).

A hard-capped `record_size` literal with no pagination loop anywhere in the
function — check_pagination_convention.py must flag it.
"""


def search(client):
    return client.post(
        "/api/rest/2.0/widgets/search",
        json={"record_size": 50, "record_offset": 0},
    )
