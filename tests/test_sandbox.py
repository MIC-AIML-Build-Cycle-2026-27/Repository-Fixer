import subprocess

import pytest

from src.sandbox import runner


def _fake_run(returncode=0, stdout="", stderr="", calls=None):
    def fake(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    return fake


def test_command_has_safety_limits(tmp_path):
    command = runner.build_docker_command(tmp_path, "test-container")
    assert command[:3] == ["docker", "run", "--rm"]
    for flag in ("--memory", "--cpus", "--pids-limit", "--network"):
        assert flag in command


def test_passing_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.subprocess, "run", _fake_run(0, stdout="2 passed"))
    result = runner.run_tests_in_docker(tmp_path)
    assert result.passed is True
    assert "2 passed" in result.output


def test_failing_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.subprocess, "run", _fake_run(1, stdout="1 failed"))
    result = runner.run_tests_in_docker(tmp_path)
    assert result.passed is False


def test_docker_failure_raises_sandbox_error(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.subprocess, "run", _fake_run(125, stderr="daemon not running"))
    with pytest.raises(runner.SandboxError):
        runner.run_tests_in_docker(tmp_path)


def test_docker_not_installed(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runner.subprocess, "run", missing)
    with pytest.raises(runner.SandboxError):
        runner.run_tests_in_docker(tmp_path)


def test_timeout_kills_container(monkeypatch, tmp_path):
    calls = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake)

    result = runner.run_tests_in_docker(tmp_path, timeout=1)

    assert result.passed is False
    assert "timed out" in result.output
    assert calls[-1][:2] == ["docker", "kill"]
