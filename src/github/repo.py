"""Clone and branch helpers. Everything goes through the `git` command line."""

import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class GitError(RuntimeError):
    """A git command failed."""


def _git(args: list[str], cwd: Path | None = None, timeout: int = 300, secrets=()) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        for secret in secrets:
            if secret:
                message = message.replace(secret, "***")
        if not message:
            message = f"exit code {proc.returncode} with no output"
        raise GitError(f"git {args[0]} failed: {message}")
    return proc.stdout.strip()


def github_clone_url(repo_full_name: str, token: str = "") -> str:
    if not REPO_NAME_RE.match(repo_full_name):
        raise ValueError(f"Invalid repository name: {repo_full_name!r}")
    if token:
        return f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
    return f"https://github.com/{repo_full_name}.git"


def clone_repo(
    url: str, dest: Path, ref: str | None = None, depth: int | None = 1, secrets=()
) -> Path:
    """Clone any git URL (or local path) into `dest`."""
    args = ["clone"]
    if depth:
        args += ["--depth", str(depth)]
    if ref:
        args += ["--branch", ref]
    args += [url, str(dest)]
    _git(args, secrets=secrets)
    return Path(dest)


def clone_github_repo(
    repo_full_name: str, dest: Path, token: str = "", ref: str | None = None
) -> Path:
    """Clone a GitHub repo. The token is removed from the saved remote URL afterwards."""
    url = github_clone_url(repo_full_name, token)
    path = clone_repo(url, dest, ref=ref, secrets=(token,))
    if token:
        clean_url = github_clone_url(repo_full_name)
        _git(["remote", "set-url", "origin", clean_url], cwd=path)
    return path


def checkout_branch(repo_path: Path, branch: str, create: bool = True) -> None:
    if not BRANCH_RE.match(branch) or branch.startswith("-"):
        raise ValueError(f"Invalid branch name: {branch!r}")
    args = ["checkout", "-b", branch] if create else ["checkout", branch]
    _git(args, cwd=repo_path)


def current_branch(repo_path: Path) -> str:
    return _git(["branch", "--show-current"], cwd=repo_path)


@contextmanager
def cloned_repo(repo_full_name: str, token: str = "", ref: str | None = None) -> Iterator[Path]:
    """Clone into a temp folder and delete it when the `with` block ends."""
    with tempfile.TemporaryDirectory(prefix="repofixer-") as tmp:
        try:
            yield clone_github_repo(repo_full_name, Path(tmp) / "repo", token=token, ref=ref)
        finally:
            pass
    # Note: TemporaryDirectory cleanup failures (e.g. Windows file locks) raise here