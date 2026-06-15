# Databricks Runtime — Setup Guide

Deploy the ThoughtSpot skills and client to a Databricks workspace using
Databricks Asset Bundles.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Databricks workspace | With Unity Catalog enabled |
| Databricks CLI | `pip install databricks-cli` (v0.18+) |
| Databricks authentication | CLI configured: `databricks configure` or env vars |
| ThoughtSpot instance | Cloud or Software, with REST API v2 enabled |
| ThoughtSpot credentials | Bearer token, password, or secret key |

---

## Step 1: Configure deployment target

Edit `databricks.yml` and set the workspace host for your target:

```yaml
targets:
  dev:
    workspace:
      host: https://your-workspace.cloud.databricks.com
```

---

## Step 2: Deploy

```bash
cd agents/databricks
databricks bundle deploy -t dev
```

This deploys:
- **Notebooks:** `ts_client.py`, `ts_profile_setup.py`, `token_refresh.py`
- **Skills:** Two Genie Code conversion skills
- **Shared files:** Mappings, schemas, worked examples from `agents/shared/`
- **Token refresh job:** Scheduled every 12 hours

---

## Step 3: Create a ThoughtSpot profile

1. Open `ts_profile_setup` notebook in your Databricks workspace
2. Attach to any cluster
3. Run all cells — widgets appear at the top
4. Fill in:
   - **Profile name:** a short name (e.g. `production`, `staging`)
   - **ThoughtSpot URL:** your instance URL (e.g. `https://mycompany.thoughtspot.cloud`)
   - **Auth method:** `bearer_token`, `password`, or `secret_key`
   - **Username:** your ThoughtSpot username or email
   - **Credential:** your token, password, or secret key
5. Run all cells again to store the profile

The credential is stored in Databricks Secrets scope `thoughtspot-{profile}` and
never appears in notebook output.

---

## Step 4: Test the connection

In any notebook:

```python
%run ./ts_client
client = ThoughtSpotClient("production")
print(client.whoami())
```

Expected output: your ThoughtSpot user details (display name, org, privileges).

---

## Step 5: Verify the token refresh job

1. In Databricks, go to **Workflows > Jobs**
2. Find "ThoughtSpot Token Refresh"
3. Click **Run Now** to trigger a test run
4. Check the output — each profile should show `OK` or `SKIPPED`

The job runs every 12 hours automatically. Only `password` and `secret_key`
profiles are refreshed; `bearer_token` profiles are skipped.

---

## Using ThoughtSpotClient in notebooks

```python
%run ./ts_client
client = ThoughtSpotClient("my-profile")

# Search for models
models = client.metadata_search(type="LOGICAL_TABLE", name="%revenue%")

# Export TML
tml = client.tml_export(["abc-123"], fqn=True, associated=True, parse=True)

# Full method list: see docs/superpowers/specs/2026-06-11-databricks-ts-client-design.md
```

---

## Genie Code usage

In Genie Code Agent mode, skills are invoked as conversation commands:

```
/ts-convert-to-databricks-mv
/ts-convert-from-databricks-mv
```

Each skill uses `ThoughtSpotClient` internally — you just need a profile configured
via Step 3 above.

---

## Updating

Re-run the deploy command after pulling changes:

```bash
cd agents/databricks
git pull
databricks bundle deploy -t dev
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `Secret not found` | Re-run `ts_profile_setup` — the scope may not exist |
| `401 Unauthorized` | Token expired — run the refresh job or re-run setup |
| `databricks bundle deploy` fails | Check CLI auth: `databricks auth login` |
| Token refresh job fails | Check job logs — credential may have changed |
