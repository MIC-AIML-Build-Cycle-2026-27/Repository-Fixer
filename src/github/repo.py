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
            # git prints UTF-8 (file names, patch content in errors). Windows would decode
            # as cp1252, and a byte it can't map makes subprocess drop the output silently.
            encoding="utf-8",
            errors="replace",
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
    # autocrlf=false keeps files byte-for-byte as committed. On Windows the default would
    # turn LF into CRLF, and then LLM patches (written with LF) would not apply.
    args = ["clone", "--config", "core.autocrlf=false"]
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


# Patches may not touch these. A pushed branch with a changed workflow could run it with
# the target repo's secrets, and the patch comes from an LLM reading an untrusted issue.
PROTECTED_PATHS = (".github/",)


def apply_patch(repo_path: Path, patch: str) -> None:
    """Apply a unified diff to the working tree. Raises GitError if it does not apply.

    `git apply` is all-or-nothing, so a failed patch leaves the tree unchanged.
    `--recount` ignores the line counts in hunk headers, which LLMs often get wrong.
    `--index` also stages the change, so the commit holds exactly what the patch touched,
    including files matched by .gitignore (which `git add -A` would skip).
    """
    if not patch.endswith("\n"):
        patch += "\n"
    # Written as bytes to a file outside the repo: piping text on Windows would turn
    # "\n" into "\r\n" and break the patch.
    fd, patch_file = tempfile.mkstemp(suffix=".patch")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(patch.encode())
        changed = _git(["apply", "--recount", "--numstat", patch_file], cwd=repo_path)
        for protected in PROTECTED_PATHS:
            if protected in changed:
                raise GitError(f"Patch changes {protected}, which is not allowed")
        _git(["apply", "--recount", "--index", patch_file], cwd=repo_path)
    finally:
        os.unlink(patch_file)


def reset_hard(repo_path: Path) -> None:
    """Throw away uncommitted changes and untracked files (used between fix attempts).

    Files a patch added are staged (apply_patch uses --index), so `reset --hard` removes
    them. `clean -x` is the backstop for anything else left behind, ignored files included.
    A fresh clone has no files of its own that this would delete.
    """
    _git(["reset", "--hard", "-q"], cwd=repo_path)
    _git(["clean", "-fdxq"], cwd=repo_path)


@contextmanager
def cloned_repo(repo_full_name: str, token: str = "", ref: str | None = None) -> Iterator[Path]:
    """Clone into a temp folder and delete it when the `with` block ends."""
    # ignore_cleanup_errors: on Windows, git can still hold a lock on files under .git.
    # A leftover temp folder is better than an error hiding the real result of the run.
    with tempfile.TemporaryDirectory(prefix="repofixer-", ignore_cleanup_errors=True) as tmp:
        yield clone_github_repo(repo_full_name, Path(tmp) / "repo", token=token, ref=ref)