"""A small GitHub REST API client with only the calls the pipeline needs."""

import logging

import httpx

from src.config import get_settings
from src.github.repo import REPO_NAME_RE
from src.schemas import IssueInfo

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"


class GitHubError(RuntimeError):
    """The GitHub API returned an error (or could not be reached)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API error {status_code}: {message}")
        self.status_code = status_code


class GitHubClient:
    def __init__(
        self,
        token: str,
        base_url: str = API_URL,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "repository-fixer",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---- internals -------------------------------------------------------------------

    @staticmethod
    def _check_repo(repo_full_name: str) -> None:
        if not REPO_NAME_RE.match(repo_full_name):
            raise ValueError(f"Invalid repository name: {repo_full_name!r}")

    def _error_message(self, response: httpx.Response) -> str:
        try:
            data = response.json()
            message = str(data.get("message", ""))
            if data.get("errors"):
                message += f" {str(data['errors'])[:300]}"
        except ValueError:
            message = response.text[:200]
        return message.replace(self._token, "***").strip()

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            response = self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise GitHubError(0, f"request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise GitHubError(response.status_code, self._error_message(response))
        return response.json()

    # ---- API calls -------------------------------------------------------------------

    def get_issue(self, repo_full_name: str, number: int) -> IssueInfo:
        self._check_repo(repo_full_name)
        data = self._request("GET", f"/repos/{repo_full_name}/issues/{number}")
        return IssueInfo(
            repo_full_name=repo_full_name,
            issue_number=number,
            title=data["title"],
            body=data.get("body") or "",
        )

    def get_default_branch(self, repo_full_name: str) -> str:
        self._check_repo(repo_full_name)
        data = self._request("GET", f"/repos/{repo_full_name}")
        return data["default_branch"]

    def create_pull_request(
        self,
        repo_full_name: str,
        head: str,
        base: str,
        title: str,
        body: str = "",
        draft: bool = False,
    ) -> str:
        """Open a pull request and return its web URL. `head` is the branch with the fix."""
        self._check_repo(repo_full_name)
        data = self._request(
            "POST",
            f"/repos/{repo_full_name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        return data["html_url"]

    def comment_on_issue(self, repo_full_name: str, number: int, body: str) -> None:
        self._check_repo(repo_full_name)
        path = f"/repos/{repo_full_name}/issues/{number}/comments"
        self._request("POST", path, json={"body": body})


def get_github_client() -> GitHubClient | None:
    """Returns a client, or None when no real token is configured."""
    token = get_settings().github_token
    if not token or token == "replace-me":
        return None
    return GitHubClient(token)
