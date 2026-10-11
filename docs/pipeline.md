# Pipeline Team Guide

This document covers the **pipeline** part of Repository Fixer: what it does, what is already built, and how to set up your machine and start working. The pipeline is the backbone that connects GitHub, the LLM team's code and the frontend team's dashboard.

> **Team:** Pipeline (2 members). Branch: `pipeline`.

---

## 1. What the pipeline does

```
GitHub issue
   -> POST /webhook/github (FastAPI)
   -> verify signature, save a Run in PostgreSQL, push its ID onto a Valkey queue
   -> [worker, Week 2] clone repo -> find relevant code -> ask the LLM for a patch
   -> apply patch -> run tests in Docker -> retry on failure
   -> push a branch and open a Pull Request through the GitHub API
Frontend  -> GET /runs, GET /runs/{id}  (reads the same database)
```

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
| Planned | Tree-sitter, Semgrep, GitHub REST API, LLM API |

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

**Not done yet (Week 2 onward)**

- [ ] Worker that consumes the queue and runs the whole loop
- [ ] GitHub REST client (read issue, create branch, open PR, comment)
- [ ] Code analysis with Tree-sitter and Semgrep
- [ ] Baseline test run, and comparing results before and after a patch
- [ ] Applying the LLM's patch with `git apply`
- [ ] Parsing pytest output into a short summary
- [ ] Sandbox hardening (no network after dependencies are installed)

## 4. Repository layout

```
.
├── src/
│   ├── api/            # FastAPI app: main.py, health.py, webhook.py, runs.py
│   ├── db/             # models.py, session.py, init_db.py
│   ├── github/         # repo.py (clone, branch)  <- GitHub REST client goes here
│   ├── sandbox/        # runner.py (tests in Docker)
│   ├── worker/         # (empty) queue consumer, Week 2
│   ├── analysis/       # (empty) Tree-sitter / Semgrep, Week 2
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
| `LLM_API_KEY` | LLM provider key (used from Week 2) |

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
| Owns | `src/api/`, `src/db/`, `src/jobs.py`, `src/github/` (REST client) | `src/github/repo.py`, `src/analysis/`, `src/sandbox/` |
| Next tasks | GitHub REST client (read issue, create branch, open PR, comment), worker skeleton that consumes the queue, status updates on `Run` | Parse pytest output into a summary, baseline vs after-patch comparison, `git apply` for patches, Tree-sitter / Semgrep context |

Write the worker (`src/worker/`) **together**, because it is where both parts connect.

## 10. Team agreements and shared contracts

`src/schemas.py` defines the data passed between teams:

- `FixRequest` (pipeline -> LLM team): issue, code snippets, failing test output, attempt number
- `FixProposal` (LLM team -> pipeline): explanation, unified-diff patch, confidence 0 to 1
- `RunSummary` (pipeline -> frontend): id, repo, issue number, status, attempts, PR link
- `RunStatus`: `queued`, `analyzing`, `fixing`, `testing`, `pr_opened`, `failed`

**Do not change these without telling the LLM and frontend teams.**

Important design decision for the worker: always run the tests **before** applying a patch to record a **baseline** of already-failing tests. After the patch, count a fix as successful only if there are no new failures compared with the baseline.

## 11. Known limitations

- The sandbox only handles Python repositories.
- The sandbox keeps the network on so `pip install` works. Later, build images with dependencies installed and run with `network="none"`.
- The sandbox runs the repo's whole test suite. Large repos can be slow (the default timeout is 300 seconds).
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
