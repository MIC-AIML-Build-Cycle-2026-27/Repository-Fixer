import json

import httpx
import pytest

from src.github.client import GitHubClient, GitHubError

TOKEN = "ghp_secret_token"


def _client(handler) -> GitHubClient:
    return GitHubClient(TOKEN, transport=httpx.MockTransport(handler))


def test_get_issue_returns_issue_info():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"title": "Crash on start", "body": "It fails"})

    issue = _client(handler).get_issue("org/repo", 7)

    assert seen["url"] == "https://api.github.com/repos/org/repo/issues/7"
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert issue.title == "Crash on start"
    assert issue.body == "It fails"
    assert issue.issue_number == 7
    assert issue.repo_full_name == "org/repo"


def test_issue_with_empty_body_becomes_empty_string():
    client = _client(lambda r: httpx.Response(200, json={"title": "t", "body": None}))
    assert client.get_issue("org/repo", 1).body == ""


def test_get_default_branch():
    client = _client(lambda r: httpx.Response(200, json={"default_branch": "main"}))
    assert client.get_default_branch("org/repo") == "main"


def test_create_pull_request_sends_the_right_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.content)
        return httpx.Response(201, json={"html_url": "https://github.com/org/repo/pull/3"})

    url = _client(handler).create_pull_request(
        "org/repo", head="fix/issue-7", base="main", title="Fix #7", body="Closes #7"
    )

    assert url == "https://github.com/org/repo/pull/3"
    assert seen["method"] == "POST"
    assert seen["path"] == "/repos/org/repo/pulls"
    assert seen["json"] == {
        "title": "Fix #7",
        "head": "fix/issue-7",
        "base": "main",
        "body": "Closes #7",
        "draft": False,
    }


def test_comment_on_issue():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 1})

    _client(handler).comment_on_issue("org/repo", 7, "On it!")

    assert seen["path"] == "/repos/org/repo/issues/7/comments"
    assert seen["json"] == {"body": "On it!"}


@pytest.mark.parametrize("status", [401, 404, 422])
def test_http_errors_become_github_error(status):
    client = _client(lambda r: httpx.Response(status, json={"message": "Nope"}))
    with pytest.raises(GitHubError) as info:
        client.get_issue("org/repo", 1)
    assert info.value.status_code == status
    assert "Nope" in str(info.value)


def test_token_is_never_included_in_error_messages():
    client = _client(lambda r: httpx.Response(401, json={"message": f"Bad token {TOKEN}"}))
    with pytest.raises(GitHubError) as info:
        client.get_issue("org/repo", 1)
    assert TOKEN not in str(info.value)


def test_network_failure_becomes_github_error():
    def handler(request):
        raise httpx.ConnectError("no internet")

    with pytest.raises(GitHubError):
        _client(handler).get_issue("org/repo", 1)


def test_invalid_repo_name_is_rejected():
    client = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.get_issue("not a repo", 1)
