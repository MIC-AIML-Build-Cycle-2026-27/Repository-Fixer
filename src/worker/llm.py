"""LLM client interface used by the worker.

Note for the LLM team: read docs/llm-integration.md before starting. In short:
- Implement one method, `propose_fix(request: FixRequest) -> FixProposal` (see LLMClient),
  and return your client from `get_llm_client()` below. That is all the wiring needed.
- Retrieval (RAG) is yours too. For now the request carries the issue only.
- Read the API key with `get_settings().llm_api_key` (LLM_API_KEY in .env).
- Retry rate limits and timeouts inside your client: an exception fails the whole run.
- Tests must not call the real API (CI has no key). Use FakeLLMClient or your own fake.
"""

from typing import Protocol

from src.schemas import FixProposal, FixRequest

# Placeholder patch. `git apply` will only succeed if the target repo has a matching README.md.
FAKE_PATCH = """\
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 # Demo
+Fixed by Repository Fixer (fake LLM)
"""


class LLMClient(Protocol):
    def propose_fix(self, request: FixRequest) -> FixProposal:
        ...


class FakeLLMClient:
    """Returns a canned answer so the pipeline can be built and tested without a real LLM."""

    def __init__(self, patch: str = FAKE_PATCH, confidence: float = 0.5) -> None:
        self.patch = patch
        self.confidence = confidence
        self.requests: list[FixRequest] = []  # every request received, handy in tests

    def propose_fix(self, request: FixRequest) -> FixProposal:
        self.requests.append(request)
        return FixProposal(
            explanation=f"Fake fix for issue #{request.issue.issue_number}",
            patch=self.patch,
            confidence=self.confidence,
        )


def get_llm_client() -> LLMClient:
    # TODO (LLM team): return your real client here. Keep FakeLLMClient for tests.
    return FakeLLMClient()
