"""Run a cloned repo's tests inside a throwaway Docker container.

Safety notes:
- Never run untrusted repo code directly on your own machine. Always go through here.
- No secrets (tokens, .env) are passed into the container.
- Week-1 draft: the network stays ON so `pip install` works. Later, build an image with the
  dependencies baked in and pass network="none".

Manual check:  python -m src.sandbox.runner path/to/cloned/repo
"""
import src.jobs  # noqa: F401

import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.schemas import TestResult

DEFAULT_IMAGE = "repofixer-sandbox:latest"
MAX_OUTPUT_CHARS = 20_000

TEST_SCRIPT = (
    "if [ -f requirements.txt ]; then pip install -q -r requirements.txt; fi; "
    "if [ -f pyproject.toml ] || [ -f setup.py ]; then "
    "pip install -q -e '.[test]' || pip install -q -e '.[dev]' || pip install -q -e .; fi; "
    "pip install -q pytest; "
    "python -m pytest -q --tb=short -p no:cacheprovider"
)


class SandboxError(RuntimeError):
    """Docker itself is missing or failed (not the same as 'the tests failed')."""


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
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{repo_path}:/workspace",
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
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SandboxError("Docker is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return TestResult(
            passed=False,
            output=f"Tests timed out after {timeout}s",
            duration_seconds=time.monotonic() - started,
        )

    output = (proc.stdout + proc.stderr)[-MAX_OUTPUT_CHARS:]

    # Exit code 125 means `docker run` itself failed (e.g. the daemon is not running).
    if proc.returncode == 125:
        raise SandboxError(output.strip() or "docker run failed")

    return TestResult(
        passed=proc.returncode == 0,
        output=output,
        duration_seconds=time.monotonic() - started,
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    result = run_tests_in_docker(target)
    print(result.output)
    print("PASSED" if result.passed else "FAILED", f"({result.duration_seconds:.1f}s)")
    sys.exit(0 if result.passed else 1)
