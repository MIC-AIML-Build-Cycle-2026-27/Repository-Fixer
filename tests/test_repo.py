import shutil
import subprocess

import pytest

from src.github.repo import (
    GitError,
    _git,
    apply_patch,
    checkout_branch,
    clone_repo,
    current_branch,
    github_clone_url,
    reset_hard,
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


NEW_FILE_PATCH = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"


def test_apply_patch_and_reset_hard(source_repo, tmp_path):
    dest = clone_repo(str(source_repo), tmp_path / "clone", depth=None)

    apply_patch(dest, NEW_FILE_PATCH)
    assert (dest / "new.txt").read_text() == "hello\n"

    reset_hard(dest)
    assert not (dest / "new.txt").exists()


def test_patch_that_does_not_apply_raises_and_changes_nothing(source_repo, tmp_path):
    dest = clone_repo(str(source_repo), tmp_path / "clone", depth=None)
    bad = "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-not the content\n+x\n"
    with pytest.raises(GitError):
        apply_patch(dest, bad)
    assert (dest / "hello.txt").read_text() == "hi"


def test_patch_touching_github_folder_is_rejected(source_repo, tmp_path):
    dest = clone_repo(str(source_repo), tmp_path / "clone", depth=None)
    patch = NEW_FILE_PATCH.replace("b/new.txt", "b/.github/workflows/evil.yml")
    with pytest.raises(GitError, match=".github"):
        apply_patch(dest, patch)
    assert not (dest / ".github").exists()


def _out(*args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout


def test_patch_creating_an_ignored_file_is_staged_and_reset_removes_it(source_repo, tmp_path):
    (source_repo / ".gitignore").write_text("*.log\n")
    _run("add", ".", cwd=source_repo)
    _run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "ignore", cwd=source_repo)
    dest = clone_repo(str(source_repo), tmp_path / "clone", depth=None)

    apply_patch(dest, NEW_FILE_PATCH.replace("new.txt", "debug.log"))
    # Staged even though .gitignore matches it, so the fix commit is complete.
    assert _out("diff", "--cached", "--name-only", cwd=dest).split() == ["debug.log"]

    reset_hard(dest)
    assert not (dest / "debug.log").exists()


def test_git_output_is_decoded_as_utf8(source_repo):
    # On Windows the default decoding is cp1252: "Ё" contains a byte it can't map, and
    # subprocess would then drop the whole output.
    (source_repo / "u.txt").write_bytes("Ё ✓\n".encode())
    _run("add", ".", cwd=source_repo)
    _run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "utf8", cwd=source_repo)
    assert _git(["show", "HEAD:u.txt"], cwd=source_repo) == "Ё ✓"


def test_reset_hard_also_removes_untracked_ignored_files(source_repo, tmp_path):
    (source_repo / ".gitignore").write_text("*.log\n")
    _run("add", ".", cwd=source_repo)
    _run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "ignore", cwd=source_repo)
    dest = clone_repo(str(source_repo), tmp_path / "clone", depth=None)
    (dest / "left-behind.log").write_text("x")

    reset_hard(dest)

    assert not (dest / "left-behind.log").exists()
