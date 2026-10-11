import shutil
import subprocess

import pytest

from src.github.repo import (
    GitError,
    checkout_branch,
    clone_repo,
    current_branch,
    github_clone_url,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def source_repo(tmp_path):
    """A tiny local git repo that stands in for GitHub."""
    src = tmp_path / "source"
    src.mkdir()
    _run("init", cwd=src)
    (src / "hello.txt").write_text("hi")
    _run("add", ".", cwd=src)
    _run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init", cwd=src)
    return src


def test_clone_repo_copies_files(source_repo, tmp_path):
    dest = tmp_path / "clone"
    clone_repo(str(source_repo), dest, depth=None)
    assert (dest / "hello.txt").read_text() == "hi"


def test_checkout_creates_new_branch(source_repo, tmp_path):
    dest = tmp_path / "clone"
    clone_repo(str(source_repo), dest, depth=None)

    checkout_branch(dest, "fix/issue-7")

    assert current_branch(dest) == "fix/issue-7"


def test_invalid_branch_name_is_rejected(source_repo, tmp_path):
    dest = tmp_path / "clone"
    clone_repo(str(source_repo), dest, depth=None)
    with pytest.raises(ValueError):
        checkout_branch(dest, "--upload-pack=evil")


def test_clone_of_missing_repo_raises_git_error(tmp_path):
    with pytest.raises(GitError):
        clone_repo(str(tmp_path / "does-not-exist"), tmp_path / "clone", depth=None)


def test_github_clone_url_validates_and_adds_token():
    assert github_clone_url("org/repo") == "https://github.com/org/repo.git"
    assert "x-access-token:abc@" in github_clone_url("org/repo", token="abc")
    with pytest.raises(ValueError):
        github_clone_url("not a repo name")
