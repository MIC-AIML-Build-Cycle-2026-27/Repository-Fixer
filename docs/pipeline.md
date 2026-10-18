# Pipeline Team Guide

This document covers the **pipeline** part of Repository Fixer: what it does, what is already built, and how to set up your machine and start working. The pipeline is the backbone that connects GitHub, the LLM team's code and the frontend team's dashboard.

> **Team:** Pipeline (2 members). Branch: `pipeline`.

---

## 1. What the pipeline does

```
GitHub issue
   -> POST /webhook/github (FastAPI)
   -> verify signature, save a Run in PostgreSQL, push its ID onto a Valkey queue
   -> [worker] read the issue -> clone repo -> create branch fix/issue-<n>-run-<id>
   -> baseline tests in Docker (records the tests that already fail)
   -> ask the LLM for a patch -> git apply -> tests in Docker again
      -> no new failures? continue. Otherwise retry with the failure as feedback (max 3)
   -> commit, push the branch, open a draft Pull Request, comment on the issue
Frontend  -> GET /runs, GET /runs/{id}  (reads the same database)
```

Not built yet: the real LLM client (`FakeLLMClient` stands in). The LLM team owns both finding the relevant code (RAG) and writing the patch. For now the LLM gets the issue only, because how its client reaches the cloned repo isn't agreed yet (see "Team contracts" below).

**When is a fix accepted?** Only if, after the patch, no test fails that did not already fail in the baseline. Tests that were already broken before the patch don't count against it. A repo with no tests has nothing to compare, so any patch that applies is accepted. The PR body shows the pytest summary line so reviewers can see this.

**Why a queue?** GitHub expects a webhook reply within seconds, but fixing an issue takes minutes. The web server only records the job and replies at once. A separate worker does the slow work.

## 2. Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| Database | PostgreSQL 16 (SQLAlchemy) |
| Queue | Valkey 8 (Redis-compatible) |
| Git work | `git` command line |
| Sandbox | Docker |
| Testing / lint | pytest, ruff |
| GitHub API | REST via `httpx` (`src/github/client.py`) |
| LLM + code retrieval (RAG) | Provided by the LLM team; `FakeLLMClient` stands in until then |

## 3. Current status

**Done (Week 1)**

- [x] Project skeleton, config, Docker Compose (Postgres + Valkey)
- [x] Shared data contracts in `src/schemas.py`
- [x] Health endpoints: `/health`, `/health/deps`
- [x] GitHub webhook with HMAC signature verification
- [x] Webhook creates a `Run` row and queues it
- [x] `GET /runs` and `GET /runs/{id}`
- [x] Clone and branch helpers (`src/github/repo.py`)
- [x] Docker sandbox that runs a repo's tests (`src/sandbox/runner.py`), checked against the Click repository
- [x] Unit tests that run without Postgres, Valkey, Docker or GitHub

**Done (Week 2)**

- [x] GitHub REST client: read issue, default branch, open PR, comment (`src/github/client.py`)
- [x] Commit and push helpers (`src/github/publish.py`)
- [x] Worker skeleton (`src/worker/worker.py`): consumes the queue, reads the real issue, calls the LLM interface, updates the run status, marks failures
- [x] LLM interface plus `FakeLLMClient` (`src/worker/llm.py`)

**Done (Phase A: issue to PR, end to end)**

- [x] Worker clones the repo and creates the fix branch `fix/issue-<n>-run-<id>`
- [x] Baseline test run, then comparing failing-test IDs before and after the patch (`new_failures` in `src/sandbox/runner.py`)
- [x] Failing-test IDs parsed from pytest's short summary (`-rfE`)
- [x] Applying the LLM's patch (`apply_patch` in `src/github/repo.py`). Patches that touch `.github/` are rejected
- [x] Retry loop, up to 3 attempts, using `FixRequest.attempt` and `failing_test_output`
- [x] Commit, push, open a draft PR, save `pr_url`, comment on the issue (start, failure, PR link)
- [x] Sandbox mounts the repo read-only and copies it inside the container, so test leftovers never end up in the fix commit
- [x] End-to-end worker tests against a local bare repo (no GitHub, no Docker)
- [x] Checked with real Docker: the whole loop on a small demo repo (bad patch rejected, retry, push, PR), and the sandbox on the Click repository

**Not done yet**

Backend:

- [ ] Recover runs left stuck in progress when the worker crashes or is stopped
- [ ] Prevent duplicate runs for the same issue (trigger on one label only)
- [ ] Failure reason, branch and `updated_at` on `Run` (contract change: tell the frontend team)
- [ ] CORS for the frontend, `limit` validation on `GET /runs`, 503 from `/health/deps` when a dependency is down
- [ ] Worker service and table creation in `docker-compose.yml`

Sandbox:

- [ ] Reuse one container per run, so dependencies are installed once, not on every test run
- [ ] No network after dependencies are installed

Team contracts:

- [ ] LLM team: real client, which also does retrieval (RAG)
- [ ] LLM team: how their client gets the cloned repo to search (e.g. a `repo_path` field on `FixRequest`). The pipeline then stops sending `snippets`
- [ ] LLM team: patch format, unified diff or search/replace edits. Unified diffs are fragile: a hunk with no context after the change only applies at the end of the file, which the real-Docker check ran into

## 4. Repository layout

```
.
├── src/
│   ├── api/            # FastAPI app: main.py, health.py, webhook.py, runs.py
│   ├── db/             # models.py, session.py, init_db.py
│   ├── github/         # repo.py (clone, branch), client.py (REST API), publish.py (commit, push), manual_check.py
│   ├── sandbox/        # runner.py (tests in Docker)
│   ├── worker/         # worker.py (queue consumer, the whole fix loop), llm.py (LLM interface + fake)
│   ├── analysis/       # (empty) not needed: the LLM team does code retrieval; can be deleted
│   ├── config.py       # settings from .env
│   ├── jobs.py         # Valkey queue helpers
│   └── schemas.py      # shared contracts between teams
├── tests/
├── Dockerfile          # API image
├── Dockerfile.sandbox  # image used to run tests of target repos
├── docker-compose.yml  # Postgres + Valkey (+ API)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

## 5. First-time setup (Windows, PowerShell)

### Prerequisites

- Git
- Python 3.12
- Docker Desktop (must be **running**)
- Access to the repository (write access as a team member)

### Steps

```powershell
# 1. Get the code and switch to the team branch
git clone https://github.com/MIC-AIML-Build-Cycle-2026-27/Repository-Fixer.git
cd Repository-Fixer
git fetch --all
git switch pipeline

# 2. Python environment
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt

# 3. Local configuration
copy .env.example .env
# open .env and fill in values (see section 6)

# 4. Start PostgreSQL and Valkey
docker compose up -d db valkey

# 5. Create the database tables
python -m src.db.init_db

# 6. Build the sandbox image (once)
docker build -f Dockerfile.sandbox -t repofixer-sandbox:latest .

# 7. Check that everything works
pytest
ruff check .
```

If `venv\Scripts\activate` is blocked by PowerShell, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Run the API

```powershell
uvicorn src.api.main:app --reload
```

Open <http://localhost:8000/docs>.

- `GET /health` should return `{"status": "ok"}`
- `GET /health/deps` should show `postgres: ok` and `valkey: ok`

## 6. Environment variables

Copy `.env.example` to `.env`. **Never commit `.env`** (it is git-ignored).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (default matches `docker-compose.yml`) |
| `VALKEY_URL` | Valkey connection |
| `GITHUB_TOKEN` | Personal access token, used for cloning and the GitHub API |
| `GITHUB_WEBHOOK_SECRET` | Shared secret used to verify incoming webhooks |
| `LLM_API_KEY` | LLM provider key, for the LLM team's client (not used yet) |

The two team members can use different tokens. The webhook secret only needs to match between your `.env` and the webhook settings on GitHub.

## 7. Trying the main pieces by hand

### Clone a repo and run its tests in the sandbox

```powershell
git clone --depth 1 https://github.com/pallets/click.git C:/temp/click
python -m src.sandbox.runner C:/temp/click
```

The runner prints the test output and then `PASSED` or `FAILED`. Big projects like Click can have a few environment-related failures, which is expected. A `SandboxError` means Docker itself is not working (is Docker Desktop running?).

### Test the webhook locally

GitHub cannot reach `localhost`, so use a forwarder:

1. Go to <https://smee.io> and click **Start a new channel**. Copy the URL.
2. Forward events to your machine (needs Node.js):
   ```powershell
   npx smee-client --url https://smee.io/YOUR-CHANNEL --target http://localhost:8000/webhook/github
   ```
3. In a **test repository you own**, go to Settings -> Webhooks -> Add webhook:
   - Payload URL: your smee URL
   - Content type: `application/json`
   - Secret: the same value as `GITHUB_WEBHOOK_SECRET`
   - Events: **Issues**
4. Open an issue in that repo, then check <http://localhost:8000/runs>. A new run with status `queued` should appear.

### Try the whole loop (issue to draft PR)

With the fake LLM, the "fix" only adds a line to `README.md`, so the test repo must have a `README.md` whose first line is exactly `# Demo`.

1. Create a **test repository you own** with that `README.md`. Set up the webhook as above.
2. Put a real `GITHUB_TOKEN` in `.env` with permission to read issues, push branches and open pull requests on that repo (fine-grained token: Contents, Issues and Pull requests, all read and write).
3. Start Docker Desktop, build the sandbox image (section 5), and start the API and the smee forwarder.
4. Start the worker in a second terminal:
   ```powershell
   python -m src.worker.worker
   ```
5. Open an issue. The worker logs each step. You should get a comment on the issue, then a draft PR from `fix/issue-<n>-run-<id>`, and the run in `/runs` should end as `pr_opened` with its `pr_url`.

Private repositories on the free GitHub plan can't have draft PRs, so use a public test repo.

## 8. Daily workflow

The template's [CONTRIBUTING.md](../CONTRIBUTING.md) is the source of truth. In short:

```powershell
git switch pipeline
git pull
git switch -c feature/short-description     # one branch per issue

# ... make changes ...
pytest
ruff check .

git add .
git commit -m "Add GitHub client for creating pull requests"
git push -u origin feature/short-description
```

Then open a Pull Request on GitHub **into `pipeline`**. CI runs ruff and pytest and must pass. Do not commit directly to `main` or `pipeline`.

Conventions:

- Branch prefixes: `feature/`, `fix/`, `docs/`, `research/`, `experiment/`
- Write commit messages in the imperative: "Add ...", "Fix ..."
- Create or pick up a GitHub issue for each piece of work and assign yourself
- Add a test with every new feature. Tests must not need Docker, Postgres, Valkey or the internet (use the fixtures in `tests/conftest.py`)
- Never commit tokens, `.env`, or cloned repositories

## 9. Who works on what

| | Person A: API & integration | Person B: Analysis & sandbox |
|---|---|---|
| Owns | `src/api/`, `src/db/`, `src/jobs.py`, `src/github/` (REST client) | `src/github/repo.py`, `src/sandbox/` |
| Done | GitHub REST client, worker skeleton, status updates on `Run` | Clone/branch helpers, Docker sandbox |
| Done together (Phase A) | Whole fix loop in the worker: clone, baseline, patch, retest, retry, push, draft PR, comments | |
| Next tasks | Stuck-run recovery, duplicate-run guard, new `Run` fields, CORS, `limit` and health fixes, compose worker service | One container per run (install once), no network after install |

Write the worker (`src/worker/`) **together**, because it is where both parts connect.

## 10. Team agreements and shared contracts

`src/schemas.py` defines the data passed between teams:

- `FixRequest` (pipeline -> LLM team): issue, code snippets (always empty: the LLM team does retrieval), failing test output, attempt number
- `FixProposal` (LLM team -> pipeline): explanation, unified-diff patch, confidence 0 to 1

What these fields mean in practice, the patch rules and how errors are handled are written up for the LLM team in [`llm-integration.md`](llm-integration.md). Keep it up to date when the worker changes.
- `RunSummary` (pipeline -> frontend): id, repo, issue number, status, attempts, PR link
- `RunStatus`: `queued`, `analyzing`, `fixing`, `testing`, `pr_opened`, `failed`

**Do not change these without telling the LLM and frontend teams.**

Important design decision for the worker: always run the tests **before** applying a patch to record a **baseline** of already-failing tests. After the patch, count a fix as successful only if there are no new failures compared with the baseline.

## 11. Known limitations

- The sandbox only handles Python repositories.
- The sandbox keeps the network on so `pip install` works. Later, build images with dependencies installed and run with `network="none"`.
- The sandbox runs the repo's whole test suite. Large repos can be slow (the default timeout is 300 seconds).
- Each run tests the code at least twice (baseline, plus once per attempt), and every test run starts a fresh container and reinstalls dependencies. A run can take several times the suite's own duration.
- The worker can only open PRs on repos the token can push to. Repos you don't own would need a fork-based flow or a GitHub App.
- The LLM receives the issue text only. The LLM team's client will find the relevant code itself once it can reach the cloned repo.
- If the worker crashes or is stopped in the middle of a run, that run stays in `analyzing`/`fixing`/`testing` for good (fix planned).
- Tables are created with `create_all`. Move to Alembic migrations once the schema starts changing often.

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `/health/deps` shows an error for Postgres or Valkey | Run `docker compose up -d db valkey` and check Docker Desktop is running |
| `SandboxError: Docker is not installed...` or daemon errors | Start Docker Desktop and wait until it says "running" |
| `Unable to find image 'repofixer-sandbox:latest'` | Run the `docker build -f Dockerfile.sandbox ...` command from section 5 |
| `ModuleNotFoundError: No module named 'src'` | Run commands from the project root, with the venv activated |
| Webhook returns 401 | `GITHUB_WEBHOOK_SECRET` in `.env` does not match the secret on GitHub. Restart uvicorn after editing `.env` |
| Port 5432 or 6379 already in use | Another Postgres/Redis is running locally. Stop it, or change the port mapping in `docker-compose.yml` |
| Git cannot see the `pipeline` branch | Run `git fetch --all`, then `git switch pipeline` |
| Run ends `failed` with "The patch did not apply" in the worker log | With the fake LLM, the test repo's `README.md` must start with the line `# Demo` (section 7) |
| Run ends `failed` with "GITHUB_TOKEN is not set" | The fix was found, but there is no token to push and open the PR. Set `GITHUB_TOKEN` and restart the worker |
| Push fails with 403 | The token can't write to that repo. Give it Contents: read and write |
| PR creation fails with 422 "Draft pull requests are not supported" | The test repo is private on the free plan. Use a public repo |
| CI fails on `ruff` | Run `ruff check .` locally and fix the reported lines |

## 13. Useful commands

```powershell
docker compose ps                      # what is running
docker compose logs -f db              # database logs
docker compose down                    # stop everything (data is kept)
docker compose down -v                 # stop and delete the database data
pytest -k webhook                      # run only webhook tests
pytest -x                              # stop at first failure
ruff check . --fix                     # auto-fix simple lint problems
```