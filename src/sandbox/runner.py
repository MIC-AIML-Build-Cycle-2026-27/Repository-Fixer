"""Run a cloned repo's tests inside a throwaway Docker container.

Safety notes:
- Never run untrusted repo code directly on your own machine. Always go through here.
- No secrets (tokens, .env) are passed into the container.
- The network stays ON so `pip install` works. Later, build an image with the
  dependencies baked in and pass network="none".
- The repo is mounted read-only at /src and copied to /workspace inside the container.
  Whatever the install or the tests write (*.egg-info, caches) stays in the container,
  so it can never end up in the fix commit, and no root-owned files are left on the host.
- Compare a run with the baseline using `new_failures()`, not `TestResult.passed`.
  A repo with no tests (pytest exit code 5) has no new failures, so any patch that
  applies counts as a fix. The PR body shows the pytest summary line so reviewers can see that.

Manual check:  python -m src.sandbox.runner path/to/cloned/repo
"""

import logging
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.schemas import TestResult

log = logging.getLogger(__name__)

DEFAULT_IMAGE = "repofixer-sandbox:latest"
MAX_OUTPUT_CHARS = 20_000

# Phrases that suggest Docker itself had a problem (not the tests).
DOCKER_INFRA_PATTERNS = (
    "cannot connect to the docker daemon",
    "docker daemon",
    "daemon not running",
    "no such image",
    "permission denied",
    "is the docker daemon running",
)

# If pytest printed a summary line, pytest really ran, so any "infra" phrase in the output
# came from the repo's own tests and must not be treated as a Docker failure.
PYTEST_SUMMARY_RE = re.compile(
    r"\b\d+ (passed|failed|errors?|skipped|deselected|xfailed|xpassed)\b|no tests ran"
)

# pytest's short summary lines (printed because of -rfE), e.g.
#   FAILED tests/test_x.py::test_y - AssertionError: ...
#   ERROR tests/test_z.py - ImportError: ...
FAILED_LINE_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)

# If the copy fails, stop with 125 (reported as SandboxError). Carrying on would run
# pytest on an empty folder: "no tests ran" means no new failures, so any patch would pass.
TEST_SCRIPT = (
    "cp -a /src/. /workspace || { echo 'sandbox: could not copy the repo'; exit 125; }; "
    "if [ -f requirements.txt ]; then pip install -q -r requirements.txt; fi; "
    "if [ -f pyproject.toml ] || [ -f setup.py ]; then "
    "pip install -q -e '.[test]' || pip install -q -e '.[dev]' || pip install -q -e .; fi; "
    "pip install -q pytest; "
    "python -m pytest -q -rfE --tb=short -p no:cacheprovider"
)


class SandboxError(RuntimeError):
    """Docker itself is missing or failed (not the same as 'the tests failed')."""


def _to_text(value) -> str:
    """subprocess can hand back bytes (e.g. on timeout) even when text=True was used."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def build_docker_command(
    repo_path: Path,
    container_name: str,
    image: str = DEFAULT_IMAGE,
    memory: str = "1g",
    cpus: str = "1",
    network: str = "bridge",
) -> list[str]:
    return [
        "docker", "run", "--rm",
        "--name", container_name,
        "--memory", memory,
        "--cpus", cpus,
        "--pids-limit", "256",
        "--network", network,
        "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "-e", "PIP_ROOT_USER_ACTION=ignore",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{repo_path}:/src:ro",
        "-w", "/workspace",
        image,
        "sh", "-c", TEST_SCRIPT,
    ]  # fmt: skip


def run_tests_in_docker(
    repo_path: str | Path,
    image: str = DEFAULT_IMAGE,
    timeout: int = 300,
    memory: str = "1g",
    cpus: str = "1",
    network: str = "bridge",
) -> TestResult:
    path = Path(repo_path).resolve()
    if not path.is_dir():
        raise SandboxError(f"Not a directory: {path}")

    name = f"repofixer-{uuid.uuid4().hex[:12]}"
    command = build_docker_command(path, name, image, memory, cpus, network)
    started = time.monotonic()

    try:
        # One stream, in the order it was printed. Separate pipes would put pip's stderr
        # warnings after pytest's summary, at the end of the output the LLM gets back.
        # UTF-8 explicitly: Windows would decode as cp1252, and a byte it can't map makes
        # subprocess drop the whole output silently.
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise SandboxError("Docker is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        partial = (_to_text(exc.stdout) + _to_text(exc.stderr)).strip()
        # Killing the `docker` client does not stop the container, so kill it by name.
        # With a timeout of its own, so a hung Docker can't hang the worker forever.
        kill = subprocess.run(
            ["docker", "kill", name], capture_output=True, text=True, errors="replace", timeout=60
        )
        if kill.returncode != 0:
            log.warning(
                "docker kill %s failed: %s", name, (kill.stderr or kill.stdout).strip()
            )
        output = f"Tests timed out after {timeout}s"
        if partial:
            output += f"\nPartial output:\n{partial[-MAX_OUTPUT_CHARS:]}"
        return TestResult(
            passed=False,
            output=output,
            duration_seconds=time.monotonic() - started,
        )

    full_output = (proc.stdout or "") + (proc.stderr or "")
    truncated = len(full_output) > MAX_OUTPUT_CHARS
    output = full_output[-MAX_OUTPUT_CHARS:]
    if truncated:
        output = "...[truncated]...\n" + output

    # Exit code 125 means `docker run` itself failed (e.g. the daemon is not running).
    # Other infra problems are detected from the message, but only when pytest never ran.
    lowered = output.lower()
    looks_like_infra = (
        proc.returncode != 0
        and not PYTEST_SUMMARY_RE.search(output)
        and any(p in lowered for p in DOCKER_INFRA_PATTERNS)
    )
    if proc.returncode == 125 or looks_like_infra:
        raise SandboxError(output.strip() or "Cannot run Docker. Is the daemon running?")

    return TestResult(
        passed=proc.returncode == 0,
        output=output,
        duration_seconds=time.monotonic() - started,
    )


def failed_tests(output: str) -> set[str]:
    """IDs of the tests (or test files) pytest reported as FAILED or ERROR."""
    return set(FAILED_LINE_RE.findall(output))


def pytest_ran(result: TestResult) -> bool:
    """False when pytest never reported a result (timeout, crash), so nothing can be compared."""
    return result.passed or bool(PYTEST_SUMMARY_RE.search(result.output))


def new_failures(baseline: TestResult, after: TestResult) -> list[str] | None:
    """Tests that fail after the patch but did not fail in the baseline.

    Returns [] when the patch broke nothing. Returns None when pytest did not run to the
    end after the patch (see pytest_ran): treat that as a failure.
    """
    if after.passed:
        return []
    if not pytest_ran(after):
        return None
    return sorted(failed_tests(after.output) - failed_tests(baseline.output))


def summary_line(output: str) -> str:
    """pytest's final count line, e.g. '1 failed, 3 passed in 2.01s'."""
    for line in reversed(output.splitlines()):
        if PYTEST_SUMMARY_RE.search(line):
            return line.strip("= ")
    return "(no pytest summary)"


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    result = run_tests_in_docker(target)
    print(result.output)
    print("PASSED" if result.passed else "FAILED", f"({result.duration_seconds:.1f}s)")
    sys.exit(0 if result.passed else 1)