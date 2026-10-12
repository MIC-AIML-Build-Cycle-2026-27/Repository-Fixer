"""Commit and push helpers. Pushing is done with git; opening the PR is done by GitHubClient."""

import re
from pathlib import Path

from src.github.repo import BRANCH_RE, GitError, _git, github_clone_url

BOT_NAME = "Repository Fixer"
BOT_EMAIL = "repository-fixer@users.noreply.github.com"


def commit_all(repo_path: Path, message: str) -> bool:
    """Stage and commit every change. Returns False if there was nothing to commit."""
    _git(["add", "-A"], cwd=repo_path)
    if not _git(["status", "--porcelain"], cwd=repo_path):
        return False
    _git(
        ["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "-m", message],
        cwd=repo_path,
    )
    return True


def push_to_url(repo_path: Path, url: str, branch: str, secrets=()) -> None:
    """Push `branch` to `url`. Works with any git URL or path (handy for tests)."""
    if not BRANCH_RE.match(branch) or branch.startswith("-"):
        raise ValueError(f"Invalid branch name: {branch!r}")
    _git(["push", url, f"{branch}:{branch}"], cwd=repo_path, secrets=secrets)


def push_branch(repo_path: Path, repo_full_name: str, branch: str, token: str) -> None:
    """Push to GitHub. The token is used for this one command and is not saved in .git/config."""
    if not token:
        raise GitError("A GitHub token is required to push")
    url = github_clone_url(repo_full_name, token)
    push_to_url(repo_path, url, branch, secrets=(token,))


def is_safe_branch_part(text: str) -> str:
    """Turn free text into something usable inside a branch name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "fix"
