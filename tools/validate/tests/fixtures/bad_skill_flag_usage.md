---
name: ts-bad-flag-fixture
description: known-bad fixture — documents a flag that does not exist on the real command
---

# Bad flag fixture

check_skill_flag_usage.py must flag this: `--this-flag-does-not-exist` is not a
registered option on `ts tml import`.

```bash
ts tml import --this-flag-does-not-exist model.tml
```

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-01-01 | fixture |
