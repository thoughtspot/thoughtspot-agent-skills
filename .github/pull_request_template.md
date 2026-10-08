## Summary

<!-- What changes and why. -->

## Test plan

<!-- What you ran, and against what (no hostnames: name the cluster by profile or role). -->

## Checklist

- [ ] **Public-repo content is synthetic.** No customer names, tenant URLs (Jira, SharePoint/OneDrive, Slack, Google Docs, ThoughtSpot clusters), employee names or customer data in code, examples, fixtures, screenshots, commit messages or this description. AI-assistant output pasted from a customer tenant has had its citation links removed. See `.claude/rules/security.md` → "Customer data and confidentiality".
- [ ] Validators pass locally (`bash scripts/install-hooks.sh` once installs the pre-commit and commit-msg hooks).
- [ ] Skill version bumped and `## Changelog` updated for any changed `SKILL.md`; `CHANGELOG.md` updated for repo-level changes (`.claude/rules/versioning.md`).
