# Setup Guide — Snowflake Cortex Skills

This guide walks you through connecting the skill's Git repository to your Snowflake
account so the skill files are available in Snowsight Workspaces.

> **Path note:** Skills in this repository are stored under `agents/coco/<skill-name>/`.
> Snowflake Cortex Code looks for skills at `.snowflake/cortex/skills/<skill-name>/`
> within a Workspace. These paths do not match — after connecting the Git repository
> and opening your Workspace, you must manually create the `.snowflake/cortex/skills/`
> folder structure and copy the skill files into it (see
> [Using the skill in a Workspace](#using-the-skill-in-a-workspace) below).

---

## Prerequisites

- A Snowflake account with a role that can create API integrations and Git repositories
  (typically `ACCOUNTADMIN` or a role with the required grants)
- The Git repository URL for this skill (HTTPS)

---

## Option A: Automated (Snowflake CLI)

The `snow git setup` command walks you through the full setup interactively. It creates
the secret, API integration, and Git repository clone in one flow.

```bash
snow git setup SKILL_REPO \
  --database SKILLS \
  --schema PUBLIC
```

You will be prompted for:
- **Origin URL:** `https://github.com/<your-org>/<your-repo>.git`
- **Use secret for authentication?** `y` for private repos, `n` for public
- **Username / token:** your GitHub username and a personal access token (if private)
- **API integration identifier:** press Enter to accept the default or provide an existing one

Once complete, fetch the latest files:

```bash
snow git execute @SKILLS.PUBLIC.SKILL_REPO fetch
```

---

## Option B: Snowsight UI (OAuth — GitHub only)

This is the simplest method if your repository is hosted on GitHub. It uses the
built-in Snowflake GitHub App for OAuth authentication — no secrets or tokens needed.

### Step 1: Create an API integration with OAuth

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE API INTEGRATION skill_git_api_integration
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com/<your-org>')
  API_USER_AUTHENTICATION = (TYPE = SNOWFLAKE_GITHUB_APP)
  ENABLED = TRUE;
```

Grant usage to the role that will use the skill:

```sql
GRANT USAGE ON INTEGRATION skill_git_api_integration TO ROLE <your_role>;
```

### Step 2: Create the Git repository in Snowsight

1. Open **Snowsight** → **Catalog** → **Database Explorer**
2. Navigate to the database and schema where you want the repository (e.g. `SKILLS.PUBLIC`)
3. Select **Create** → **Git Repository**
4. Fill in:
   - **Repository Name:** `SKILL_REPO`
   - **Origin:** `https://github.com/<your-org>/<your-repo>.git`
   - **API Integration:** select `SKILL_GIT_API_INTEGRATION`
5. Select **Create**
6. You will be prompted to authorize via GitHub OAuth

---

## Option C: Manual SQL (token-based auth)

Use this for private repos on any Git provider (GitHub, GitLab, Bitbucket, etc.).

### Step 1: Create a secret with your credentials

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE SECRET SKILLS.PUBLIC.SKILL_GIT_SECRET
  TYPE = password
  USERNAME = '<your_git_username>'
  PASSWORD = '<your_personal_access_token>';
```

> **GitHub PAT:** Generate one at GitHub → Settings → Developer settings →
> Personal access tokens → Fine-grained tokens. Grant `Contents: Read-only` access
> to the repository.
>
> **Bitbucket:** Use `x-token-auth` as the username value.

### Step 2: Create an API integration

```sql
CREATE OR REPLACE API INTEGRATION skill_git_api_integration
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com/<your-org>')
  ALLOWED_AUTHENTICATION_SECRETS = (SKILLS.PUBLIC.SKILL_GIT_SECRET)
  ENABLED = TRUE;
```

### Step 3: Grant access to your role

```sql
GRANT USAGE ON INTEGRATION skill_git_api_integration TO ROLE <your_role>;
GRANT USAGE ON SECRET SKILLS.PUBLIC.SKILL_GIT_SECRET TO ROLE <your_role>;
GRANT CREATE GIT REPOSITORY ON SCHEMA SKILLS.PUBLIC TO ROLE <your_role>;
```

### Step 4: Create the Git repository clone

```sql
USE ROLE <your_role>;

CREATE OR REPLACE GIT REPOSITORY SKILLS.PUBLIC.SKILL_REPO
  API_INTEGRATION = skill_git_api_integration
  GIT_CREDENTIALS = SKILLS.PUBLIC.SKILL_GIT_SECRET
  ORIGIN = 'https://github.com/<your-org>/<your-repo>.git';
```

### Step 5: Fetch and verify

```sql
ALTER GIT REPOSITORY SKILLS.PUBLIC.SKILL_REPO FETCH;

LS @SKILLS.PUBLIC.SKILL_REPO/branches/main;
```

You should see the skill files at `agents/coco/<skill-name>/SKILL.md`. They are not yet
at the `.snowflake/cortex/skills/` path — see [Using the skill in a Workspace](#using-the-skill-in-a-workspace)
for the copy step that makes them discoverable by Cortex Code.

---

## Option D: Public repository (no authentication)

If the repository is public, no secret is needed:

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE API INTEGRATION skill_git_api_integration
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com/<your-org>')
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION skill_git_api_integration TO ROLE <your_role>;

USE ROLE <your_role>;

CREATE OR REPLACE GIT REPOSITORY SKILLS.PUBLIC.SKILL_REPO
  API_INTEGRATION = skill_git_api_integration
  ORIGIN = 'https://github.com/<your-org>/<your-repo>.git';

ALTER GIT REPOSITORY SKILLS.PUBLIC.SKILL_REPO FETCH;
```

---

## Option E: Manual upload (no Git required)

If you don't want to connect a Git repository, you can create a Workspace from scratch
and add the skill files manually.

1. Open **Snowsight** → **Projects** → **Workspaces**
2. Select **Create Workspace** → **Create from scratch**
3. Create the following folder structure in the Workspace:
   ```
   .snowflake/
   └── cortex/
       └── skills/
           └── <skill-name>/
               ├── SKILL.md
               └── references/
                   └── ...
   ```
4. For each file, right-click the target folder → **New File** → paste the contents
5. Cortex Code will auto-detect the skill once all files are in place

> **Note:** With this approach there is no automatic update mechanism. To get newer
> versions of the skill, you must manually replace the files. Consider Options A–D
> if you want to stay up to date with `ALTER GIT REPOSITORY ... FETCH`.

---

## Using the skill in a Workspace

**From a Git repository (Options A–D):**

1. Open **Snowsight** → **Projects** → **Workspaces**
2. Select **Create Workspace** → **Create from existing Git repository**
3. Select your repository and branch
4. In the Workspace file tree, create the folder structure that Cortex Code expects:
   ```
   .snowflake/
   └── cortex/
       └── skills/
           └── <skill-name>/
   ```
5. Copy the files from `agents/coco/<skill-name>/` into the new folder. For each file,
   right-click the target folder → **New File** → paste the contents.
6. Cortex Code will auto-detect the skill once `SKILL.md` is in place.

> When a new version of the skill is available, fetch the repository
> (`ALTER GIT REPOSITORY ... FETCH`) to update the `agents/coco/` source files, then
> re-copy any changed files into `.snowflake/cortex/skills/<skill-name>/`.

**From manual upload (Option E):**

The skill is already in your Workspace at the correct path — no additional steps needed.

Cortex Code automatically detects skills in the `.snowflake/cortex/skills/` directory.

---

## Keeping the skill updated

**Git-backed Workspaces (Options A–D):**

To pull the latest version of the skill:

```sql
ALTER GIT REPOSITORY SKILLS.PUBLIC.SKILL_REPO FETCH;
```

In Snowsight Workspaces, you can also use the **Fetch** button on the Git Repository
details page.

**Manual Workspaces (Option E):**

Replace the files manually when a new version is available.
