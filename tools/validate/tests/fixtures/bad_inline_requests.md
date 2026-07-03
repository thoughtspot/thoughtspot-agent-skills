# Known-bad inline-requests fixture (for test_known_bad_fixtures.py)

This fenced example instructs the `requests`/`ts-cli` anti-pattern directly —
check_no_inline_requests.py must flag it (`.claude/rules/ts-cli.md`).

```python
import requests

resp = requests.post(
    "https://example.thoughtspot.cloud/api/rest/2.0/metadata/tml/export",
    headers={"Authorization": "Bearer TOKEN"},
    json={"metadata": [{"identifier": "abc-123"}]},
)
```
