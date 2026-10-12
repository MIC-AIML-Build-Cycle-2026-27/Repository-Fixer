import shutil
import subprocess

import pytest

from src.github.publish import commit_all, is_safe_branch_part, push_to_url
from src.github.repo import GitError, checkout_branch

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _run(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    _run("init", cwd=path)
    (path / "a.txt").write_text("one")
    return path


def test_commit_all_commits_changes_once(repo):
    assert commit_all(repo, "Add a.txt") is True
    assert _run("log", "-1", "--format=%s", cwd=repo) == "Add a.txt"
    assert _run("log", "-1", "--format=%an", cwd=repo) == "Repository Fixer"
    assert commit_all(repo, "Nothing new") is False


def test_push_to_url_creates_the_branch_on_the_remote(repo, tmp_path):
    commit_all(repo, "init")
    remote = tmp_path / "remote.git"
    _run("init", "--bare", str(remote), cwd=tmp_path)
    checkout_branch(repo, "fix/issue-1")

    push_to_url(repo, str(remote), "fix/issue-1")

    assert "fix/issue-1" in _run("branch", "--list", cwd=remote)


def test_push_to_url_rejects_bad_branch_names(repo):
    with pytest.raises(ValueError):
        push_to_url(repo, "ignored", "--force")


def test_push_failure_raises_git_error(repo, tmp_path):
    commit_all(repo, "init")
    checkout_branch(repo, "fix/x")
    with pytest.raises(GitError):
        push_to_url(repo, str(tmp_path / "missing.git"), "fix/x")


def test_is_safe_branch_part():
    assert is_safe_branch_part("Fix: crash on start!") == "Fix-crash-on-start"
    assert is_safe_branch_part("!!!") == "fix"
