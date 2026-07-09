# Deploying to Cloud Run via GitHub Actions

Two Cloud Run services, deployed from one workflow on every push to `main`:

- **`money-minting-machine-backend`** — FastAPI + the 15-agent committee + SQLite, built from [`backend/Dockerfile`](../backend/Dockerfile)
- **`money-minting-machine-frontend`** — Streamlit, built from [`frontend/Dockerfile`](../frontend/Dockerfile), talks to the backend over `BACKEND_URL` (set automatically to the backend's live Cloud Run URL each deploy)

Project: `money-minting-machine` · Region: `asia-south1` (Mumbai — closest to NSE; change `REGION` in the workflow/setup script if you'd rather use somewhere else).

## One-time setup (you run this, not Claude)

IAM/security-account creation is something you should review and run yourself rather than have an agent do on your behalf.

```bash
bash deploy/setup-gcp.sh
```

This enables the required APIs, creates an Artifact Registry repo, prompts you (hidden input) for `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `NEWSAPI_KEY` and stores them in Secret Manager, creates a `github-deployer` service account scoped to just Cloud Run + Artifact Registry + Secret Manager access, and sets up Workload Identity Federation so GitHub Actions can authenticate **without any long-lived key** — only runs from the `GITHUB_REPO` set at the top of the script can impersonate it.

> If you're also renaming the GitHub repository itself (Settings → General → Repository name), do that first and update `GITHUB_REPO` in `setup-gcp.sh` to match before running it — the OIDC token's `repository` claim has to match exactly. I can't rename the GitHub repo myself (no GitHub write access from here); that one's on you via GitHub's UI. After a rename, also run `git remote set-url origin <new-url>` locally.

At the end it prints two values — add them as **GitHub repo secrets** (Settings → Secrets and variables → Actions):

| Secret name | Value |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | printed by the script |
| `GCP_SERVICE_ACCOUNT` | `github-deployer@money-minting-machine.iam.gserviceaccount.com` |

## Then: push to `main`, or run it manually

The workflow ([`.github/workflows/deploy-cloud-run.yml`](../.github/workflows/deploy-cloud-run.yml)) triggers on pushes touching `backend/`, `frontend/`, or `run_backend.py`, or manually via the Actions tab → "Deploy to Cloud Run" → **Run workflow**.

## Things worth knowing about this setup

- **`DATA_MODE=replay` by default.** The backend is pinned to `min-instances=1, max-instances=1` (SQLite + the in-process APScheduler ticker only work correctly as a single instance — see the earlier conversation about why). Combined with `live` mode's continuous real-time ticking + LLM calls, an always-on instance would run up real cost with nobody watching. `replay` demos convincingly at any time with bounded, predictable cost. Flip it to `live` by editing `DATA_MODE` in the workflow's `env_vars` block once you're ready to watch it trade for real — just know that instance now runs (and calls the LLM) continuously, 24/7, for as long as it's deployed.
- **SQLite is not persistent across deploys.** Cloud Run's filesystem is ephemeral — a new revision (i.e. your next push) starts from an empty database. Trade history within one deployed revision's lifetime persists fine (same instance, same disk), but redeploying resets it. Fine for a demo; if you want durable history across deploys, the follow-up is migrating `DATABASE_URL` to Cloud SQL (Postgres) — a real but separate piece of work, not done here.
- **Both services are public (`--allow-unauthenticated`).** Anyone with the URL can view the dashboard and trigger a tick. Reasonable for a hackathon demo; if you want it locked down, the backend can be made private with the frontend's own service identity granted `roles/run.invoker`, but that needs a small code change (frontend would have to attach a Google-signed ID token to its requests) — I didn't build that since it adds real complexity for what's currently a public demo app.
- Watchlist, tick interval, risk tolerance, etc. are hardcoded into the workflow's `env_vars` right now (mirroring your local `.env`) — edit them there if you want the deployed instance to run different settings than local dev.
