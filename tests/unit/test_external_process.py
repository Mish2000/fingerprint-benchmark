"""Launching one external tool, six ways it can go wrong.

Each test here stands for a mistake this helper exists to make unrepeatable:
a shell that reinterprets a file name, a PATH lookup that defeats a pinned
runtime, a timeout that leaves the child alive, output that fills memory, an
inherited environment that makes a score depend on somebody's shell profile
(spec sections 36 to 42).

The "tool" is this interpreter running a one-line program, so the suite needs
nothing installed and behaves the same on every platform.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fpbench.adapters.support.process import (
    DETERMINISTIC_ENVIRONMENT,
    ExternalCommand,
    run_external_command,
)
from fpbench.core.errors import ConfigurationError

pytestmark = pytest.mark.adapter_contract

PYTHON = Path(sys.executable).resolve()


def python_command(program: str, tmp_path: Path, **overrides) -> ExternalCommand:
    settings: dict[str, object] = {
        "argv": (str(PYTHON), "-c", program),
        "working_directory": tmp_path,
        "timeout_seconds": 30.0,
    }
    settings.update(overrides)
    return ExternalCommand(**settings)  # type: ignore[arg-type]


# ----------------------------------------------------------------- the model


def test_an_empty_argv_is_not_a_command(tmp_path):
    with pytest.raises(ConfigurationError, match="needs an argv"):
        ExternalCommand(argv=(), working_directory=tmp_path, timeout_seconds=1.0)


def test_a_bare_command_name_is_refused(tmp_path):
    """A PATH lookup is exactly what a pinned runtime bundle exists to prevent."""
    with pytest.raises(ConfigurationError, match="absolute path"):
        ExternalCommand(
            argv=("mindtct", "in", "out"),
            working_directory=tmp_path,
            timeout_seconds=1.0,
        )


def test_a_single_command_string_cannot_be_expressed(tmp_path):
    """There is no string form, so there is nothing for a shell to reparse."""
    command = ExternalCommand(
        argv=(str(PYTHON), "-c", "print(1)"),
        working_directory=tmp_path,
        timeout_seconds=1.0,
    )
    assert isinstance(command.argv, tuple)
    assert "shell" not in ExternalCommand.__dataclass_fields__


@pytest.mark.parametrize("value", ["60", True, 0, -1, float("inf")])
def test_a_timeout_must_be_a_finite_positive_number(tmp_path, value):
    with pytest.raises(ConfigurationError, match="timeout_seconds"):
        python_command("pass", tmp_path, timeout_seconds=value)


@pytest.mark.parametrize("value", [1024.0, "1024", True, 0, -1])
def test_output_limits_must_be_exact_positive_integers(tmp_path, value):
    with pytest.raises(ConfigurationError, match="limit_bytes"):
        python_command("pass", tmp_path, stdout_limit_bytes=value)


def test_environment_values_must_be_strings(tmp_path):
    with pytest.raises(ConfigurationError, match="strings"):
        python_command("pass", tmp_path, environment={"THREADS": 4})


def test_the_working_directory_must_stay_inside_the_job(tmp_path):
    inside = tmp_path / "work" / "job"
    inside.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    python_command("pass", inside, containment_root=tmp_path / "work")
    with pytest.raises(ConfigurationError, match="inside the directory"):
        python_command("pass", elsewhere, containment_root=tmp_path / "work")


# ----------------------------------------------------------- the environment


def test_the_child_sees_a_named_environment_and_not_the_developers(tmp_path, monkeypatch):
    monkeypatch.setenv("FPBENCH_LEAKED_SETTING", "please-do-not-inherit-me")
    result = run_external_command(
        python_command(
            "import os,json;print(json.dumps(dict(os.environ)))", tmp_path
        )
    )
    assert result.succeeded, result.stderr
    child = __import__("json").loads(result.stdout)
    assert "FPBENCH_LEAKED_SETTING" not in child
    for name, value in DETERMINISTIC_ENVIRONMENT.items():
        assert child.get(name) == value


def test_an_adapter_may_declare_a_variable_it_actually_needs(tmp_path):
    result = run_external_command(
        python_command(
            "import os;print(os.environ.get('NBIS_STYLE_SETTING', 'absent'))",
            tmp_path,
            environment={"NBIS_STYLE_SETTING": "declared"},
        )
    )
    assert result.stdout.strip() == "declared"


# ---------------------------------------------------------------- behaviour


def test_a_successful_command_reports_its_output_and_exit_code(tmp_path):
    result = run_external_command(python_command("print('score 42')", tmp_path))
    assert result.succeeded
    assert result.exit_code == 0
    assert result.stdout.strip() == "score 42"
    assert not result.timed_out and not result.launch_failed


def test_a_finished_windows_process_survives_the_job_assignment_race(monkeypatch):
    """A tool may exit after CreateProcess but before it enters the Job Object."""
    import ctypes

    from fpbench.adapters.support import process as process_module

    class FailedAssignment:
        argtypes = None
        restype = None

        def __call__(self, _job, _process):
            return False

    class Kernel32:
        AssignProcessToJobObject = FailedAssignment()

    class FinishedProcess:
        _handle = 123

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def kill():
            raise AssertionError("a completed process must not be killed")

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: Kernel32(),
        raising=False,
    )
    process_module._assign_windows_job(1, FinishedProcess())


def test_a_non_zero_exit_is_a_result_and_not_an_exception(tmp_path):
    """Whether exit 3 means "no minutiae" is the adapter's business, not this one's."""
    result = run_external_command(
        python_command("import sys;sys.stderr.write('bad input');sys.exit(3)", tmp_path)
    )
    assert result.exit_code == 3
    assert not result.succeeded
    assert "bad input" in result.stderr


def test_a_crash_is_reported_rather_than_raised(tmp_path):
    result = run_external_command(
        python_command("import os;os._exit(134)", tmp_path)
    )
    assert result.exit_code not in (0, None)
    assert not result.launch_failed


def test_a_missing_executable_is_a_launch_failure_with_no_path_in_it(tmp_path):
    absent = (tmp_path / "not-installed-tool").resolve()
    result = run_external_command(
        ExternalCommand(
            argv=(str(absent),), working_directory=tmp_path, timeout_seconds=5.0
        )
    )
    assert result.launch_failed
    assert result.exit_code is None
    assert str(tmp_path) not in result.stderr
    assert "Traceback" not in result.stderr


def test_a_timeout_ends_the_process_and_says_so(tmp_path):
    result = run_external_command(
        python_command("import time;time.sleep(30)", tmp_path, timeout_seconds=1.0)
    )
    assert result.timed_out
    assert not result.succeeded


def test_a_timeout_leaves_no_child_holding_the_directory(tmp_path):
    """The result is returned only once the child is actually gone."""
    marker = tmp_path / "still-running.txt"
    program = (
        "import time,sys\n"
        f"open(r'{marker}', 'w').close()\n"
        "time.sleep(30)\n"
        f"open(r'{marker}', 'a').write('survived')\n"
    )
    result = run_external_command(
        python_command(program, tmp_path, timeout_seconds=1.5)
    )
    assert result.timed_out
    assert marker.is_file()
    assert "survived" not in marker.read_text(encoding="utf-8")


def test_a_timeout_ends_descendants_before_they_can_write(tmp_path):
    marker = tmp_path / "descendant-survived.txt"
    child_program = (
        "import time,pathlib;"
        "time.sleep(1.5);"
        f"pathlib.Path({str(marker)!r}).write_text('survived')"
    )
    parent_program = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable, '-c', {child_program!r}]);"
        "time.sleep(30)"
    )
    result = run_external_command(
        python_command(parent_program, tmp_path, timeout_seconds=0.5)
    )
    assert result.timed_out
    time.sleep(2.0)
    assert not marker.exists()


def test_large_stdout_is_truncated_rather_than_read_whole(tmp_path):
    result = run_external_command(
        python_command(
            "import sys;sys.stdout.write('x' * 200000)",
            tmp_path,
            stdout_limit_bytes=1024,
        )
    )
    assert result.stdout_truncated
    assert len(result.stdout) == 1024
    assert result.exit_code == 0


def test_large_stderr_is_truncated_too(tmp_path):
    result = run_external_command(
        python_command(
            "import sys;sys.stderr.write('e' * 200000)",
            tmp_path,
            stderr_limit_bytes=512,
        )
    )
    assert result.stderr_truncated
    assert len(result.stderr) == 512


def test_output_at_the_limit_is_not_marked_truncated(tmp_path):
    result = run_external_command(
        python_command(
            "import sys;sys.stdout.write('y' * 64)", tmp_path, stdout_limit_bytes=64
        )
    )
    assert not result.stdout_truncated
    assert result.stdout == "y" * 64


def test_undecodable_output_does_not_crash_the_harness(tmp_path):
    result = run_external_command(
        python_command(
            "import sys;sys.stdout.buffer.write(b'\\xff\\xfe raw bytes')", tmp_path
        )
    )
    assert result.exit_code == 0
    assert "raw bytes" in result.stdout


def test_the_child_runs_in_the_directory_it_was_given(tmp_path):
    workdir = tmp_path / "work" / "job"
    workdir.mkdir(parents=True)
    result = run_external_command(
        python_command("import os;print(os.getcwd())", workdir)
    )
    assert Path(result.stdout.strip()).resolve() == workdir.resolve()


def test_no_temporary_output_files_survive_the_call(tmp_path):
    before = {path for path in tmp_path.rglob("*") if path.is_file()}
    run_external_command(python_command("print('hello')", tmp_path))
    after = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_stdin_is_closed_so_a_tool_cannot_wait_for_input(tmp_path):
    result = run_external_command(
        python_command("import sys;print(len(sys.stdin.read()))", tmp_path)
    )
    assert result.stdout.strip() == "0"


def test_the_helper_never_uses_a_shell():
    """Structural, over the syntax tree rather than the text.

    A substring search would trip over the module's own docstring explaining why
    there is no shell, which is the sort of test that gets deleted rather than
    understood.
    """
    import ast

    tree = ast.parse(_process_source())
    shell_arguments = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "shell"
    ]
    assert shell_arguments, "the helper should pass shell explicitly"
    for value in shell_arguments:
        assert isinstance(value, ast.Constant) and value.value is False


def test_the_platform_floor_is_named_rather_than_inherited(tmp_path, monkeypatch):
    """Windows needs ``SystemRoot``; nothing else comes along with it."""
    monkeypatch.setenv("PATH", os.pathsep.join(["/nowhere"]))
    result = run_external_command(
        python_command("import os;print('PATH' in os.environ)", tmp_path)
    )
    assert result.stdout.strip() == "False"


def test_a_working_directory_must_be_absolute(tmp_path):
    with pytest.raises(ConfigurationError, match="absolute"):
        ExternalCommand(
            argv=(str(PYTHON), "-c", "pass"),
            working_directory=Path("relative"),
            timeout_seconds=1.0,
        )


def test_subprocess_is_the_only_process_api_used():
    """A regression guard: ``os.system`` would reintroduce the shell."""
    import ast

    tree = ast.parse(_process_source())
    called = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "os.system" not in called
    assert "os.popen" not in called
    assert "subprocess.Popen" in called


def _process_source() -> str:
    from fpbench.adapters.support import process as module

    return Path(module.__file__).read_text(encoding="utf-8")
