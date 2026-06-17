# Databricks Runtime — Setup Guide

Deploy the ThoughtSpot skills and client to a Databricks workspace using
Databricks Asset Bundles.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Databricks workspace | With Unity Catalog enabled |
| Databricks CLI | `pip install databricks-cli` (v0.18+) |
| Databricks authentication | CLI configured via `/ts-profile-databricks`, `databricks configure`, or env vars |
| Workspace permissions | The deploying identity (user or Service Principal) must have **CAN_MANAGE** on the bundle's workspace path — see Step 1b below |
| ThoughtSpot instance | Cloud or Software, with REST API v2 enabled |
| ThoughtSpot credentials | Bearer token, password, or secret key |

---

## What `databricks.yml` does

`agents/databricks/databricks.yml` is a
[Databricks Asset Bundle](https://docs.databricks.com/en/dev-tools/bundles/index.html)
configuration file. Running `databricks bundle deploy` reads this file and
deploys everything to your workspace in one command:

| Section | What it controls |
|---|---|
| `bundle.name` | Bundle identity (`thoughtspot-skills`) |
| `workspace.root_path` | Where files land in the workspace (`/Workspace/thoughtspot-skills`) |
| `sync.include` | Which local files are synced — notebooks, skills, and shared references |
| `resources.jobs.token_refresh` | A scheduled Databricks Workflow Job that runs `token_refresh.py` every 12 hours to keep ThoughtSpot auth tokens fresh (password and secret_key profiles only; bearer_token profiles are skipped) |
| `targets` | Named deployment targets (`dev`, `prod`) — each points to a workspace host URL |

You only need to edit the `targets` section (Step 1 below). Everything else
works out of the box.

---

## Step 1: Configure deployment target

If you've already run `/ts-profile-databricks`, you can pull the workspace host
from your existing profile instead of looking it up again:

```bash
python3 -c "
import json, os
profiles = json.load(open(os.path.expanduser('~/.claude/databricks-profiles.json')))
for p in profiles:
    print(f\"{p['name']:20s} {p['host']}\")
"
```

Copy the host URL for your target workspace and set it in
`agents/databricks/databricks.yml`:

```yaml
targets:
  dev:
    workspace:
      host: https://dbc-xxxxx.cloud.databricks.com  # from your profile
```

If you don't have a profile yet, find your workspace URL by logging into
Databricks and copying the URL from the browser address bar. It looks like
`https://dbc-abc123.cloud.databricks.com` (AWS) or
`https://adb-1234567890.1.azuredatabricks.net` (Azure). Use the
**workspace-level** URL, not the account-level `https://accounts.cloud.databricks.com`.

You can set up a full profile later with `/ts-profile-databricks`.

---

## Step 1b: Configure bundle permissions

The identity deploying the bundle (your user account or a Service Principal)
needs **CAN_MANAGE** permission on the workspace path `/Workspace/thoughtspot-skills`.
Without this, `databricks bundle deploy` fails with `access denied` on the
deployment lock file.

**Option A — Add permissions in `databricks.yml` (recommended)**

Uncomment and edit the `permissions` block in `agents/databricks/databricks.yml`:

```yaml
permissions:
  - level: CAN_MANAGE
    user_name: your-email@company.com
```

Or for a Service Principal:

```yaml
permissions:
  - level: CAN_MANAGE
    service_principal_name: your-service-principal-name
```

**Finding your identity:**

| Auth type | How to find your identity |
|---|---|
| User account | Your Databricks login email — run `databricks current-user me --profile {profile} -o json` and look for `userName` |
| Service Principal | The SP display name — run `databricks service-principals list --profile {profile} -o json` and find your SP by `applicationId` matching the `client_id` in your profile |

**Option B — Grant permissions in the Databricks UI**

1. Open your Databricks workspace in a browser
2. Navigate to **Workspace** in the left sidebar
3. If `/Workspace/thoughtspot-skills` already exists (from a prior deploy
   attempt), right-click it > **Permissions** > add your user or SP with
   **Can Manage**
4. If it doesn't exist yet, create the folder manually first, then set
   permissions

---

## Step 2: Deploy

Always use `deploy.sh` instead of raw `databricks bundle deploy`. The script
copies shared references from `agents/shared/` into a local `shared/` dir
(gitignored) so the bundle can include them, then runs the bundle deploy and
imports skills into your personal `.assistant/` path for Genie discovery.

The `-u` flag is **required** — it specifies the Databricks user whose
`.assistant/` directory receives the skills:

```bash
cd agents/databricks
./deploy.sh -u your-email@company.com -t dev
```

To deploy to production instead:

```bash
./deploy.sh -u your-email@company.com -t prod
```

This syncs the following files to `/Workspace/thoughtspot-skills` in the
target workspace and creates the token refresh job:

- **Notebooks:** `ts_client.py`, `ts_profile_setup.py`, `token_refresh.py`
- **Skills:** Two Genie Code conversion skills
- **Shared files:** Mappings and schemas copied from `agents/shared/` (single source of truth)
- **Token refresh job:** Scheduled every 12 hours (see `databricks.yml` section above)

> **Do not run `databricks bundle deploy` directly** — the shared references
> won't be included. Always use `deploy.sh`.

---

## Step 3: Manage ThoughtSpot profiles

Open `ts_profile_setup` in your workspace:
**Workspace > /Workspace/thoughtspot-skills/notebooks/ts_profile_setup**

Attach to any interactive compute (all-purpose cluster or serverless notebook).

The notebook displays an **ipywidgets button bar** with five actions:

| Button | What it does |
|---|---|
| **List** | Show all stored ThoughtSpot profiles in an HTML table |
| **Create** | Show form fields for a new profile; click Save to store in Secrets |
| **Update** | Select an existing profile, edit fields (rename supported); Save |
| **Delete** | Select a profile and click Confirm Delete |
| **Test** | Select a profile and click Run Test — calls ThoughtSpot `whoami()` |

### Workflow

1. **Run all cells** — the first cell installs dependencies, the second loads
   `ThoughtSpotClient`, the third defines functions, and the last renders the
   button UI
2. **Click a button** to perform an action — forms appear inline, results
   display in the output area below the buttons
3. Credentials are entered via a **password field** (masked) and stored
   directly in Databricks Secrets — they are never saved in the notebook

### Creating your first profile

1. Click **Create**
2. Fill in the form:
   - **Profile:** a short name (e.g. `default`, `production`)
   - **URL:** e.g. `https://mycompany.thoughtspot.cloud`
   - **Username:** your ThoughtSpot username or email
   - **Auth:** `bearer_token`, `password`, or `secret_key`
   - **Credential:** your token, password, or secret key (masked)
3. Click **Save** — credential is stored in Secrets and the form clears

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

Skills must live under your **personal** workspace path for Genie to discover them.
`deploy.sh` handles this automatically, or you can set it up manually.

### Target layout

```
/Workspace/Users/<your-email>/.assistant/
  skills/
    ts-convert-from-databricks-mv/SKILL.md
    ts-convert-to-databricks-mv/SKILL.md
    shared/                                ← under skills/ (SKILL.md uses ../shared/)
      mappings/ts-databricks/...
      schemas/...
  notebooks/
    ts_client                              ← notebook for %run (../../notebooks/ts_client)
```

> **Shared lives under `skills/`.** Each SKILL.md references shared files as `../shared/…`,
> which resolves to `.assistant/skills/shared/` (a sibling of the skill folders) — **not**
> `.assistant/shared/`. `deploy.sh` already places them there; the manual steps below match.

### Option A: CLI deploy (recommended)

`deploy.sh` copies skills, shared references, and `ts_client` into your
`.assistant/` path automatically. See [Step 2](#step-2-deploy).

### Option B: Manual setup (no Databricks CLI)

If you don't have the Databricks CLI installed, you can set up Genie skills
manually through the Databricks workspace UI:

1. In the workspace sidebar, navigate to your home folder
   (`/Workspace/Users/<your-email>/`)
2. Create the following folder structure:
   - `.assistant/skills/ts-convert-from-databricks-mv/`
   - `.assistant/skills/ts-convert-to-databricks-mv/`
   - `.assistant/skills/shared/mappings/ts-databricks/`
   - `.assistant/skills/shared/schemas/`
   - `.assistant/notebooks/`
3. Upload each skill's `SKILL.md` into its matching workspace folder
4. Upload the shared reference files from `agents/shared/` (note: under `skills/shared/`,
   so the skills' `../shared/…` references resolve):
   - `mappings/ts-databricks/*.md` → `.assistant/skills/shared/mappings/ts-databricks/`
   - `schemas/databricks-metric-view.md`, `thoughtspot-table-tml.md`,
     `thoughtspot-model-tml.md` → `.assistant/skills/shared/schemas/`
5. Import `agents/databricks/notebooks/ts_client.py` as a **Notebook** (not a
   file) into `.assistant/notebooks/` — this is required for `%run` to work
6. Similarly import `ts_profile_setup.py` and `token_refresh.py` as notebooks

### Verify

```bash
databricks workspace list /Workspace/Users/<your-email>/.assistant/skills
```

Each skill uses `ThoughtSpotClient` internally — you just need a profile configured
via Step 3 above.

---

## Updating

Re-run the deploy script after pulling changes:

```bash
cd agents/databricks
git pull
./deploy.sh -u your-email@company.com -t dev
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `Secret not found` | Re-run `ts_profile_setup` — the scope may not exist |
| `401 Unauthorized` | Token expired — run the refresh job or re-run setup |
| `databricks bundle deploy` fails | Check CLI auth: `databricks auth login` |
| `access denied` / `deployment lock` | The deploying identity lacks **CAN_MANAGE** on the workspace path — see Step 1b |
| Token refresh job fails | Check job logs — credential may have changed |
