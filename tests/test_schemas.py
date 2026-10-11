import pytest
from pydantic import ValidationError

from src.schemas import FixProposal, IssueInfo, FixRequest


def test_fix_request_defaults():
    request = FixRequest(issue=IssueInfo(repo_full_name="org/repo", issue_number=1, title="t"))
    assert request.attempt == 1
    assert request.snippets == []


def test_fix_proposal_confidence_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        FixProposal(explanation="x", patch="diff", confidence=1.5)
