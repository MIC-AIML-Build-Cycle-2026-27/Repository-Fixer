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
    assert f"{tmp_path}:/src:ro" in command  # the clone on the host is never written to


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


def _result(passed, output):
    return runner.TestResult(passed=passed, output=output)


SUMMARY_FAIL = (
    "FAILED tests/test_a.py::test_x - AssertionError: boom\n"
    "ERROR tests/test_b.py - ImportError\n"
    "1 failed, 1 error in 0.20s"
)


def test_failed_tests_reads_the_short_summary():
    assert runner.failed_tests(SUMMARY_FAIL) == {"tests/test_a.py::test_x", "tests/test_b.py"}


def test_new_failures_ignores_tests_that_already_failed():
    baseline = _result(False, SUMMARY_FAIL)
    after = _result(False, SUMMARY_FAIL + "\nFAILED tests/test_c.py::test_new - x\n")
    assert runner.new_failures(baseline, after) == ["tests/test_c.py::test_new"]
    assert runner.new_failures(baseline, _result(False, SUMMARY_FAIL)) == []


def test_new_failures_when_everything_passes():
    assert runner.new_failures(_result(False, SUMMARY_FAIL), _result(True, "3 passed")) == []


def test_new_failures_without_a_pytest_summary_is_none():
    timed_out = _result(False, "Tests timed out after 300s")
    assert runner.new_failures(_result(True, "3 passed"), timed_out) is None


def test_summary_line():
    output = "x\n===== 3 passed in 0.1s =====\nWARNING: pip says something\n"
    assert runner.summary_line(output) == "3 passed in 0.1s"
    assert runner.summary_line("Tests timed out after 300s") == "(no pytest summary)"


def test_output_is_one_utf8_stream(monkeypatch, tmp_path):
    seen = {}

    def fake(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "1 passed", None)

    monkeypatch.setattr(runner.subprocess, "run", fake)
    runner.run_tests_in_docker(tmp_path)

    # stderr merged into stdout keeps pip warnings in order; utf-8 keeps Windows from
    # decoding as cp1252 and dropping the output.
    assert seen["stderr"] == subprocess.STDOUT
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"


def test_script_stops_if_copying_the_repo_fails():
    copy_step = runner.TEST_SCRIPT.split(";")[0]
    assert copy_step.startswith("cp -a /src/. /workspace ||")
    assert "exit 125" in runner.TEST_SCRIPT.split("pip install")[0]


def test_pytest_ran():
    assert runner.pytest_ran(_result(True, ""))
    assert runner.pytest_ran(_result(False, SUMMARY_FAIL))
    assert not runner.pytest_ran(_result(False, "Tests timed out after 300s"))
