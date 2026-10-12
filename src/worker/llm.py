"""LLM client interface used by the worker.

The real client will come from the LLM team. It only has to provide one method with this
signature, so swapping it in later is a one-line change in `get_llm_client()`.
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
    # TODO: return the LLM team's real client here once it exists.
    return FakeLLMClient()
