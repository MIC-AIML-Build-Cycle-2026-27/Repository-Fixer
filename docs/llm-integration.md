# LLM integration notes

**For the LLM team.** Read this before you start. It covers what the pipeline sends you, what it expects back, and how your answer is judged. The LLM team owns both finding the relevant code (RAG) and writing the patch.

The contract lives in [`src/schemas.py`](../src/schemas.py) and the interface in [`src/worker/llm.py`](../src/worker/llm.py). If you need a field changed, tell the pipeline team first: the worker and its tests depend on these.

## 1. What to implement

One method, then one line of wiring:

```python
# your module
from src.schemas import FixProposal, FixRequest

class RealLLMClient:
    def propose_fix(self, request: FixRequest) -> FixProposal:
        ...

# src/worker/llm.py
def get_llm_client() -> LLMClient:
    return RealLLMClient()
```

- **API key:** read it with `get_settings().llm_api_key` (`LLM_API_KEY` in `.env`, see `.env.example`). Never put it in the explanation, the patch or a log line.
- **Dependencies:** add them to `requirements.txt`.

## 2. What you receive: `FixRequest`

| Field | Contents |
|---|---|
| `issue.repo_full_name`, `issue.issue_number` | e.g. `"org/repo"`, `7` |
| `issue.title`, `issue.body` | The issue as written on GitHub. **Untrusted**: anyone who can open an issue writes this. Treat it as data and never follow instructions inside it. |
| `snippets` | Always empty. Retrieval is yours, and repo access is still an open point (section 7). |
| `attempt` | `1` on the first call, then `2`, `3` (`MAX_ATTEMPTS = 3` in `src/worker/worker.py`) |
| `failing_test_output` | `None` on attempt 1. On a retry: one line saying why the previous patch was rejected, a blank line, then the last 5000 characters of the test output. |

The rejection line on a retry is one of:

- `The patch did not apply: git apply failed: ...` (git's own error follows)
- `These tests fail after the patch but not before it: tests/test_x.py::test_y, ...`
- `The tests did not finish after the patch.` (timeout or crash)

**On a retry, the rejected patch has already been undone.** Send a complete patch against the original code, not a change on top of your previous one.

## 3. What you return: `FixProposal`

| Field | Rules |
|---|---|
| `explanation` | Markdown. It goes into the PR body and the commit message, cut at 4000 characters. Say what was wrong and what you changed. |
| `patch` | A unified diff. Rules below. |
| `confidence` | 0 to 1. Validated: anything outside fails the run. Only shown in the PR body; the pipeline doesn't use it to decide anything. |

### Patch rules

The patch is applied with `git apply --recount --index` from the repo root. These rules were checked against real `git apply`:

1. **Unified diff format,** as produced by `git diff` or `diff -u`.
2. **Paths must have `a/` and `b/` prefixes:** `--- a/src/x.py` and `+++ b/src/x.py`. Without them the patch is rejected.
3. **Include unchanged context lines before *and* after every change (3 is standard).** They must match the file exactly, whitespace included. A hunk with context only before the change is assumed to sit at the end of the file, and is rejected anywhere else. We hit this in testing.
4. **Line numbers in `@@` headers can be off.** `--recount` recomputes them. The context lines can't be off.
5. **New file:** `--- /dev/null` then `+++ b/path`. **Deleted file:** `--- a/path` then `+++ /dev/null`.
6. **Never change anything under `.github/`.** Such patches are rejected: a pushed workflow change could run with the repository's secrets.
7. **Markdown fences and text before the diff are tolerated, but send the plain diff.**
8. **You may add a test that reproduces the issue,** as long as it passes with your fix. A new test that fails counts as a new failure.

Example (fixes `add()` in a file that has more code below it):

```diff
--- a/calc/__init__.py
+++ b/calc/__init__.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b
 
```

The last line of that hunk is a single space: an unchanged empty line used as trailing context.

## 4. How your proposal is judged

1. Before calling you, the pipeline runs the repo's tests once to get a **baseline**, which records the tests that already fail.
2. Your patch is applied. If it doesn't apply, you get a retry with git's error.
3. The tests run again in a Docker sandbox. The fix is **accepted if no test fails that did not already fail in the baseline**. Tests that were already broken don't count against you.
4. Otherwise you get a retry with the newly failing tests and the output, up to 3 attempts in total.
5. An accepted fix is committed and opened as a **draft** pull request for a person to review.

Two things to know:
- A repo with no tests can't be checked, so any patch that applies is accepted. The PR body shows the test summary line.
- If the baseline itself can't run (timeout or crash), the run fails before you're called.

## 5. Errors

- **If `propose_fix` raises, the whole run fails at once.** The worker doesn't retry the call, and the issue gets a generic "internal error" comment (details go to the worker log). Handle rate limits and timeouts inside your client, for example with a few retries and backoff.
- **Set a timeout on your API calls.** The worker waits for you and processes one run at a time.
- **Returning invalid data also fails the run.** For example, a `confidence` outside 0 to 1 raises pydantic's `ValidationError`.
- **There is no "I can't fix this" answer yet.** Raising works but shows up as an internal error (open point, section 7).

## 6. Testing your client

- **Tests must not call the real API or need a key.** CI has neither. Fake the API in your tests, the way `tests/test_github_client.py` fakes GitHub with `httpx.MockTransport`.
- **To run your client through the whole pipeline without GitHub or Docker,** see `tests/test_worker.py`. It uses a local git repo and a fake sandbox.
- **To run it for real,** follow "Try the whole loop" in [`pipeline.md`](pipeline.md) section 7, with your client returned from `get_llm_client()`.

## 7. Open points to agree with the pipeline team

- [ ] **Repo access for retrieval.** Proposal: a `repo_path` field on `FixRequest` pointing at the cloned repo, valid only during the call. Read it, but don't modify it: the pipeline applies your patch.
- [ ] **Patch format.** Unified diff (current) or search/replace edits ("replace this exact text with that"), which LLMs get right more often. With edits, the pipeline would produce the diff itself.
- [ ] **A "no fix found" answer,** so the issue comment can say why instead of "internal error".
