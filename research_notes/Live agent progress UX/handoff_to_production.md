# Handing a generated app to the user for real-world use (as of Nov 2026)

Scope: how AI app builders hand off generated code (GitHub sync, export), what a small production-ready repo contains per stack, the cheapest deploy targets and what each needs, and the minimal CI. The goal is a checklist H.E.X Mind can run after a mission. Research date: 2026-11-22. Pages fetched on that date unless marked otherwise.

## What does a "production-ready" small repo contain, per stack (Streamlit, Node/React, FastAPI)?

### Takeaway
No single standard exists. The docs agree on a core set: a dependency manifest and lockfile at the root, a `.env`/secrets file kept out of git plus an example of the keys it needs, a README with run and deploy steps, tests, a CI workflow under `.github/workflows/`, a `dependabot.yml`, and, for container hosts, a Dockerfile that listens on `$PORT`. Per-stack additions: Streamlit needs `.streamlit/config.toml`, a gitignored `.streamlit/secrets.toml` and the entrypoint run from the repo root. React SPAs need an SPA rewrite file for the chosen host. FastAPI needs an `app` object at a conventional entrypoint.

### Cited Findings
**Cross-stack**
- Lovable leaves secrets out of exports, so users must recreate them locally. Guides say `.env` must never be committed and belongs in `.gitignore`. — [Lovable FAQ: export/download code](https://lovable.dev/faq/code-export/export-download-code); [DEV: moving a Lovable/Replit project](https://dev.to/pawel_reszka/how-to-move-your-lovable-or-replit-project-to-your-own-infrastructure-step-by-step-50oi)
- Lovable tells users to read the Supabase URL and publishable key from the project's `.env`, then set them as host environment variables. `VITE_`-prefixed variables are built into the bundle, so the app must be rebuilt after they change. — [Lovable docs: external deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)
- Lovable's export contains application source and DB migration files (`supabase/migrations/` or `drizzle/migrations/`, `supabase/functions/`), but no database records or storage files. — [Lovable docs: external deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)
- Lovable has two exported stacks: TanStack Start (projects created from May 13, 2026) and older React + Vite. Its build settings are `npm run build`, output `dist` (Vite), Node 22 recommended, and `package-lock.json` assumed. A repo with only `bun.lock` needs Bun or a newly generated lockfile. — [Lovable docs: external deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)
- `npm ci` installs exactly the versions in the lockfile, so a committed lockfile is what makes CI reproducible. — [GitHub Docs: Node.js CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/nodejs)
- `actions/setup-python` with `cache: 'pip'` expects a `requirements.txt` in the repo. — [GitHub Docs: Python CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- Dependabot config goes in `.github/dependabot.yml` (`version: 2`). It supports the ecosystems `pip`, `uv`, `npm`, `docker` and `github-actions`, each with `directory: "/"` and a `schedule.interval` such as `weekly`. — [GitHub Docs: Dependabot options reference](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)

**Streamlit**
- Community Cloud builds a new Python environment, so dependencies must be declared (`requirements.txt` in the examples; other formats are supported). The entrypoint can be anywhere in the repo. `streamlit run` runs from the repo root, so test locally from there. Paths must use forward slashes. — [Streamlit: file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- Only one `.streamlit/config.toml` is allowed, at the repo root. A subdirectory app may have its own, which overrides the root one. — [Streamlit: file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- Secrets go in `.streamlit/secrets.toml`, read with `st.secrets`. This file "should never be committed to your repository." — [Streamlit: secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
- Streamlit's example Dockerfile: `FROM python:3.12-slim`, apt-get `build-essential curl git`, `WORKDIR /app`, `pip3 install -r requirements.txt`, `EXPOSE 8501`, `HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health`, `ENTRYPOINT ["streamlit","run","streamlit_app.py","--server.port=8501","--server.address=0.0.0.0"]`. The example uses `git clone`; `COPY . .` can replace it. There is no official Streamlit base image. — [Streamlit: deploy with Docker](https://docs.streamlit.io/deploy/tutorials/docker)
- Community Cloud requires `protobuf>=5.26.1,<8` compatibility and runs on Debian 11. — [Streamlit: status and limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status)

**Node/React (Vite SPA)**
- A client-routed SPA needs an "unmatched route returns `index.html`" rule in a host-specific file: `_redirects` for Netlify and Cloudflare Pages, `vercel.json` for Vercel, `staticwebapp.config.json` for Azure, `firebase.json` for Firebase, and `try_files $uri $uri/ /index.html;` for Nginx. Storage-level error pages are not suitable because they return 404. — [Lovable docs: external deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)

**FastAPI**
- Vercel zero-config looks for a `FastAPI` instance named `app` in `app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py` or `asgi.py`, at the root or under `src/` or `app/`. Otherwise set `[tool.vercel] entrypoint = "module:app"` in `pyproject.toml`. It accepts `pyproject.toml`, `requirements.txt` or Pipenv. — [Vercel: FastAPI](https://vercel.com/docs/frameworks/backend/fastapi) (page last updated 2026-11-14)
- Cloud Run's Python sample reads `port=int(os.environ.get("PORT", 8080))`. Listening on `$PORT` is part of the Cloud Run container contract. — [Cloud Run Python quickstart](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service)

### Inferences
- H.E.X Mind's minimal handoff set, which every stack should have:
  - What it already writes: `README.md`, `.gitignore`, the manifest, `tests/`.
  - What to add: `.env.example` (variable names only, never values), a lockfile, `.github/workflows/ci.yml`, `.github/dependabot.yml` (the app's ecosystem plus `github-actions`), a `LICENSE` only if the user picks one, and a "Deploy" section in the README.
- Per stack:
  - Streamlit: add `.streamlit/config.toml`, plus `.streamlit/secrets.toml` in `.gitignore` and `.streamlit/secrets.toml.example`. Make sure the app runs from the repo root with forward-slash paths.
  - React/Vite: add the SPA rewrite file for the host the user picks, document `VITE_*` variables as build-time and public, and use Node 22.
  - FastAPI: keep `app` at `main.py`/`app/main.py` and read `$PORT`.
  - CLI: add a `pyproject.toml` `[project.scripts]` entry (from general packaging practice; not researched here).
- A Dockerfile is only needed for container hosts (Cloud Run with a custom build, Fly, Render Docker, Railway). It should listen on `$PORT` (default 8080 for Cloud Run, 8501 for Streamlit) and include a healthcheck.
- The `.hex/project.json` run contract should probably stay in the repo but be documented in the README. Alternatively it can be added to `.gitignore` if it holds local-only data (decision for H.E.X Mind).

### Gaps
- I did not fetch Bolt's or Replit's exported project layout in detail. Bolt's docs describe sync but not file structure.
- I found no single authoritative "production-ready repo" checklist from GitHub. The list above is assembled from per-tool docs.
- I did not research FastAPI's own deployment docs (Docker/`fastapi run`) or pyproject/uv lockfile conventions directly.

## What are the simplest free or cheap deploy targets per stack in 2026, and what does each require?

### Takeaway
- **Streamlit:** Streamlit Community Cloud. It is free and needs GitHub plus `requirements.txt`. Private repos work with extra authorization, so the repo does not have to be public.
- **Static React/Vite:** Netlify (300 credits a month), Vercel or Cloudflare Pages, connected to the GitHub repo.
- **FastAPI:** Vercel (zero-config, runs as a function), Render (free, sleeps after 15 minutes idle) or Cloud Run (`gcloud run deploy --source .`, no Dockerfile needed, free tier per billing account).
- **Railway:** $1 a month of free usage.
- **Fly.io:** no free tier any more, only a $1, 7-day trial.

### Cited Findings
**Streamlit Community Cloud**
- It needs a GitHub account; deploying from GitHub is the model. Public repos come by default. Private repos need an additional "Authorize streamlit" grant. The user needs admin rights on the repo, and org repos need the owner's approval. — [Streamlit: connect GitHub](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account)
- To deploy: share.streamlit.io, then "Create app", then pick the repo, branch and entrypoint file (or paste a GitHub URL). The default Python is 3.12, and another version can be picked under Advanced settings. Secrets are pasted into Advanced settings in TOML. A custom `*.streamlit.app` subdomain is optional. — [Streamlit: deploy](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- Limits (as of Feb 2024, "may change at any time"): CPU 0.078 to 2 cores, memory 690 MB to 2.7 GB, storage up to 50 GB. Apps sleep after 12 hours without traffic, and any viewer can wake them. — [Streamlit: manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
- Only Python versions still receiving security updates are supported; apps on an unsupported version are forcibly upgraded. GitHub updates are capped at 5 per minute. Apps are hosted in the US only. — [Streamlit: status](https://docs.streamlit.io/deploy/streamlit-community-cloud/status); [Streamlit: deploy](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)

**Vercel**
- FastAPI deploys as a single Vercel Function on Fluid compute. Deploy by connecting Git or with `vc deploy` (CLI 48.1.8 or later).
- `vercel deploy --temporary` deploys without an account and prints a claim URL.
- The bundle limit is 500 MB (Large Functions up to 5 GB, in beta). Shutdown cleanup gets at most 500 ms. `maxDuration` is set in `vercel.json`, and WebSockets follow function duration limits.
- Source: [Vercel: FastAPI](https://vercel.com/docs/frameworks/backend/fastapi)
- v0 deploys to Vercel: the production branch gets production deployments, and each working branch gets its own preview deployment. — [v0 docs: GitHub](https://v0.app/docs/github)

**Netlify**
- The Free plan has 300 credits a month with a hard limit, no recharge, and never charges.
- Credit rates: a production deploy costs 15 credits, 1 GB of bandwidth 20, 10k requests 2, and 1 GB-hour of functions compute 10. Deploy previews and branch deploys are not metered.
- It includes Git deploys, a CDN, custom domains with SSL and 1 concurrent build.
- Source: [Netlify: credit-based plans](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/)
- Inference from the rates (my arithmetic): about 20 production deploys a month uses the whole Free allowance, so frequent redeploys can pause a free site.

**Render**
- A Free web service spins down after 15 minutes without inbound traffic and takes about 1 minute to spin up. Each workspace gets 750 free instance hours a month, and services are suspended when they run out.
- Free Postgres expires 30 days after creation, with 14 days of grace before deletion. Each workspace gets one, with 1 GB.
- Source: [Render: free](https://render.com/docs/free)

**Google Cloud Run**
- `gcloud services enable run.googleapis.com cloudbuild.googleapis.com`, then `gcloud run deploy --source .`. "Cloud Run automatically builds a Dockerfile for you when you deploy from source code" (buildpacks). There is no charge while the service isn't in use, but Artifact Registry storage may cost money. — [Cloud Run Python quickstart](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service)
- The free tier is aggregated per billing account and resets monthly. Request-based billing gets 2M requests and 180,000 vCPU-seconds a month (Tier 1 regions). The pricing page lists 240,000 vCPU-seconds for instance-based billing. — [Cloud Run pricing](https://cloud.google.com/run/pricing) (via search snippets; full page did not render in fetch)

**Railway**
- Free plan: $0 a month with $1 of usage included and no card. Limits: 1 project, 3 services, 1 vCPU / 0.5 GB each. Services sleep after 5 to 10 minutes without outbound traffic.
- New accounts get a 30-day trial with $5 of credit.
- Hobby is $5 a month with $5 of usage included.
- Source: [Railway: free trial/pricing](https://docs.railway.com/reference/pricing/free-trial)

**Fly.io**
- "New organizations don't have a free tier or a monthly free usage allowance." The trial is $1 of credit for 7 days with no card. The smallest machine (shared-cpu-1x, 256 MB) costs $2.19 per 30 days. — [Fly.io pricing](https://docs.fly.io/about/pricing)

**Lovable's own list of external hosts**
- Netlify, Cloudflare Pages, Vercel, AWS Amplify, Azure Static Web Apps and Firebase Hosting, plus Docker on Cloud Run, ECS, Kubernetes or VMs. — [Lovable docs: external deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)

### Inferences
Suggested default deploy recommendation per stack, for H.E.X Mind's README "Deploy" section:

| Stack | First choice | Needs | Fallback |
|---|---|---|---|
| Streamlit | Community Cloud | GitHub repo (public, or private with extra auth), `requirements.txt`, entrypoint path, secrets pasted in the UI | Cloud Run/Render with the Streamlit Dockerfile |
| React/Vite SPA | Netlify, Vercel or Cloudflare Pages | GitHub repo, build `npm run build`, output `dist`, SPA rewrite file, `VITE_*` vars | Any static host |
| FastAPI | Render free or Vercel | `app` entrypoint, `requirements.txt`/`pyproject.toml`, start command binding `0.0.0.0:$PORT` | Cloud Run (`gcloud run deploy --source .`) |
| CLI | none (publish to PyPI or npm, or GitHub Releases) | n/a | n/a |

- Every Git-connected host deploys from GitHub, so a GitHub push is the gate for all of them. Cloud Run and Vercel are the exceptions: they can deploy from a local folder through their CLIs.

### Gaps
- I did not confirm whether Cloud Run's free tier requires a billing account to be linked. Sources only state that for Cloud Run functions (1st gen) (see [functions pricing](https://cloud.google.com/functions/pricing-1stgen)). It is commonly believed to be required; verify.
- I did not fetch the Vercel Hobby plan limits, Cloudflare Pages limits, the Render Docker/Blueprint (`render.yaml`) docs, or Hugging Face Spaces (another common free Streamlit host).
- The Streamlit resource limits are dated Feb 2024 and may be stale. I found no current count of private apps allowed.

## How do the app builders implement "push to GitHub", and what goes in the first commit?

### Takeaway
Lovable, Bolt and v0 all use a GitHub App installed on the user's account or org. Each creates a new private repo by default, pushes the current code, then syncs. Lovable and Bolt sync both ways on one active branch. v0 uses working branches and PRs that merge to the base branch on Publish. Replit relies on its Git pane, a personal access token kept in a Replit Secret, or the `gh` CLI. For a local desktop app like H.E.X Mind, the closest equivalent is `gh repo create --private --source=. --push`, using the user's own `gh` login. None of the docs I read describe the first commit's contents beyond "the project's current code."

### Cited Findings
**Lovable**
- It uses the Lovable GitHub App, connected at the workspace level, with one project linked to one repo.
- On first connect it creates a new repo (private by default) and starts two-way sync on the default branch. It can't link an existing repo, and reconnecting creates a new repo.
- Files over 100 MB are rejected by GitHub, and Lovable can't edit files over 10 MB.
- Source: [Lovable docs: GitHub](https://docs.lovable.dev/integrations/github)

**Bolt**
- It needs an individual GitHub account: GitHub login, then authorize, then install the GitHub App with access to all repos or selected repos. "Create repository" makes a private repo.
- Sync goes both ways. Bolt commits after each change that doesn't break the project and polls GitHub every 30 seconds. If GitHub is newer, it shows a "GitHub conflict" message.
- Merging happens through GitHub PRs. Only the owner can connect, and disconnecting is permanent.
- Source: [Bolt support: Git](https://support.bolt.new/integrations/git)

**v0**
- It uses the Vercel GitHub App. "v0 creates a private repository and pushes the project's current code to it." After that, the repo is the source of truth.
- v0 commits to a lazily created working branch, never directly to the base branch. Publish opens or reuses a PR, merges it and waits for the production deploy.
- Branch protection can block the merge. v0 offers "Fix CI" and "Fix Conflicts" actions.
- Source: [v0 docs: GitHub](https://v0.app/docs/github)

**Replit**
- It has a Git pane with one-click push and AI commit messages.
- The docs describe storing a GitHub personal access token in a Replit Secret (`GIT_URL`) and running `git push $GIT_URL`, and warn that collaborators can see it. They also describe `gh` CLI support and a Replit GitHub App, which orgs may need to allow-list.
- Source: [Replit docs: git interface](https://docs.replit.com/features/workspace-tools/git-interface); [Replit: GitHub auth errors](https://docs.replit.com/programming-ide/using-git-on-replit/github-auth-errors)
- Several of those Replit pages sit at older URL paths. A newer page says Replit pushes branches and opens PRs only when asked and permitted. — [Replit: manage repository access](https://docs.replit.com/build/code/manage-repository-access.md)

**`gh` CLI**
- `gh repo create [name] --private --source=. --remote=origin --push` creates the remote from a local repo and pushes. Non-interactive use requires one of `--public`, `--private` or `--internal`. The name defaults to the source directory. — [gh repo create manual](https://cli.github.com/manual/gh_repo_create)

**Streamlit Community Cloud**
- It uses a "Streamlit" OAuth app for public repos and a separate grant for private ones. — [Streamlit: connect GitHub](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account)

### Inferences
H.E.X Mind runs locally and already has git, so it doesn't need its own OAuth or GitHub App. The lowest-risk option is to detect `gh` and `gh auth status`. With the user's explicit click, it then runs `gh repo create <name> --private --source=<folder> --remote=origin --push`. If `gh` is missing, it shows the manual `git remote add` and `git push` steps.

Rules for that flow:
- Default to private, as Lovable, Bolt and v0 all do. Ask before making the repo public, which Streamlit Community Cloud's simplest path needs.
- Never handle the GitHub token in H.E.X Mind, which fits the CLAUDE.md key rules.

Before the first push:
1. Make sure `.gitignore` covers `.env`, `.streamlit/secrets.toml`, `node_modules/`, `.venv/`, `__pycache__/` and `dist/`.
2. Scan the staged files for secrets and large files (GitHub rejects files over 100 MB).
3. Make one clean commit, for example "Initial commit: <app name>", on `main`. Don't push the agents' worktree history unless the user wants it.

### Gaps
- None of the builders document what their first commit contains (message, files) or whether they add CI or a Dockerfile. I found no evidence that Lovable, Bolt or v0 generate GitHub Actions workflows by default.
- I did not verify GitHub push protection or secret scanning behavior for new private repos on free accounts.

## What minimal GitHub Actions CI is standard for each stack?

### Takeaway
GitHub's own tutorials give a one-job workflow on `ubuntu-latest`:
- Python: checkout, then setup-python with pip cache, `pip install -r requirements.txt`, `ruff check`, `pytest`.
- Node: checkout, then setup-node with npm cache, `npm ci`, `npm run build --if-present`, `npm test`.

Add `.github/dependabot.yml` for dependency and Actions updates.

### Cited Findings
- **Python workflow:** `on: [push]`, `actions/checkout@v6`, `actions/setup-python@v5` with `python-version: '3.x'` and `cache: 'pip'`, then `pip install -r requirements.txt`, `pipx install ruff && ruff check --output-format=github`, and `pip install pytest && pytest`. — [GitHub Docs: Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- **Node workflow:** `on: [push]`, `actions/checkout@v6`, `actions/setup-node` (the fetched page showed `@v7`; verify) with `node-version: '20.x'` and `cache: 'npm'`, then `npm ci`, `npm run build --if-present`, `npm test`. Save it as `.github/workflows/node.js.yml`. — [GitHub Docs: Node.js](https://docs.github.com/en/actions/tutorials/build-and-test-code/nodejs)
- **Dependabot:** `version: 2`, with ecosystems `pip`, `uv`, `npm`, `docker` and `github-actions` (directory `/`, weekly). — [GitHub Docs: Dependabot options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)
- **v0:** It treats required CI checks as a merge gate and offers "Fix CI". — [v0 docs: GitHub](https://v0.app/docs/github)

### Inferences
**Recommended CI templates for H.E.X Mind**
- Trigger on `push` and `pull_request` to `main`.
- Pin the Python version to the one the mission used (e.g. `3.12`, Streamlit Cloud's default) and Node to `22` (Lovable's recommendation), rather than `3.x` or `20.x`.
- Python/Streamlit/FastAPI: `ruff check` plus `pytest`.
- Streamlit: add a smoke import of the entrypoint, or `streamlit.testing.v1.AppTest` (not researched here).
- Node: `npm ci`, `npm run lint --if-present`, `npm run build --if-present`, `npm test --if-present`.
- If a Dockerfile exists, a `docker build .` step catches broken images.
- Reuse the commands in `.hex/project.json`, so the CI runs exactly what the sandbox ran.
- Only claim that CI passes after a real run on GitHub. Before that, the honest claim is "the same commands passed locally in the sandbox", per the "never fabricate" rule.

**Production and growth checklist** (synthesized from the sources above; each item traces to a finding in this file)
1. Configure secrets on the host, never in git: the Streamlit Advanced settings, Vercel, Netlify or Render env vars, and GitHub Actions secrets if CI needs them. Ship `.env.example`.
2. Pin dependencies with a lockfile (`package-lock.json`, `uv.lock` or pinned `requirements.txt`). Use `npm ci` in CI. Add Dependabot for the ecosystem and `github-actions`.
3. Keep tests in the repo and make CI required before merge, by branch protection, as v0 respects.
4. Add a linter (ruff for Python; ESLint is the common choice for Node, not cited here).
5. Bind to `0.0.0.0:$PORT`, add a health endpoint (Streamlit has `/_stcore/health`) and a Dockerfile only for container hosts.
6. Versioning (tags and CHANGELOG) and monitoring: host logs (Vercel Runtime Logs/Observability; Streamlit logs, visible only to repo writers). See [Vercel: FastAPI](https://vercel.com/docs/frameworks/backend/fastapi) and [Streamlit: deploy](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
7. Free-tier caveats belong in the README: Render sleeps after 15 minutes, Streamlit after 12 hours, Railway after 5 to 10 minutes; Render's free Postgres expires after 30 days; Fly has no free tier.

### Gaps
- I did not research semantic versioning, release-please or changesets, Sentry or uptime monitoring, CodeQL, or GitHub secret-scanning defaults. Versioning and monitoring advice above is thin and only partly sourced.
- The current major versions of `actions/setup-node` and `actions/setup-python` should be re-checked when the templates are written. The fetch summarizer reported `setup-node@v7` and `setup-python@v5`, which I could not confirm independently.
