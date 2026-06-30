from pathlib import Path
from subprocess import CompletedProcess

from mountaineer.cli import _extract_lint_diagnostics, handle_lint


def test_handle_lint_fast_runs_only_ruff(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text, check):
        _ = (cwd, capture_output, text, check)
        commands.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mountaineer.cli.subprocess.run", fake_run)

    return_code = handle_lint(paths=["mountaineer"], fast=True)

    assert return_code == 0
    assert commands == [["ruff", "check", "mountaineer"]]


def test_handle_lint_fix_runs_fix_then_full_pipeline(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text, check):
        _ = (cwd, capture_output, text, check)
        commands.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mountaineer.cli.subprocess.run", fake_run)

    return_code = handle_lint(paths=["mountaineer"], fix=True)

    assert return_code == 0
    assert commands == [
        ["ruff", "check", "--fix", "mountaineer"],
        ["ruff", "check", "mountaineer"],
        ["pyright", "mountaineer"],
        ["mypy", "mountaineer"],
    ]


def test_handle_lint_returns_failure_when_checker_fails(monkeypatch):
    def fake_run(command, cwd, capture_output, text, check):
        _ = (cwd, capture_output, text, check)
        if command[0] == "mypy":
            return CompletedProcess(
                command,
                1,
                stdout="mountaineer/foo.py:10: error: Incompatible types in assignment [assignment]\n",
                stderr="",
            )
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mountaineer.cli.subprocess.run", fake_run)

    return_code = handle_lint(paths=["mountaineer"])

    assert return_code == 1


def test_handle_lint_missing_tool_is_reported_as_failure(monkeypatch):
    def fake_run(command, cwd, capture_output, text, check):
        _ = (cwd, capture_output, text, check)
        if command[0] == "pyright":
            raise FileNotFoundError("pyright")
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mountaineer.cli.subprocess.run", fake_run)

    return_code = handle_lint(paths=[str(Path("mountaineer"))])

    assert return_code == 1


def test_handle_lint_default_targets_package_dirs(tmp_path: Path, monkeypatch):
    package_dir = tmp_path / "example_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")

    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "__init__.py").write_text("")

    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text, check):
        _ = (cwd, capture_output, text, check)
        commands.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mountaineer.cli.subprocess.run", fake_run)

    return_code = handle_lint(fast=True, cwd=tmp_path)

    assert return_code == 0
    assert commands == [["ruff", "check", "example_pkg"]]


def test_extract_lint_diagnostics_pyright_deduplicates_supporting_lines():
    output = "\n".join(
        [
            "/tmp/example.py",
            "/tmp/example.py:3:14 - error: Type \"Literal['bad']\" is not assignable to declared type \"int\"",
            "  \"Literal['bad']\" is not assignable to \"int\" (reportAssignmentType)",
            "1 error, 0 warnings, 0 informations",
        ]
    )

    diagnostics = _extract_lint_diagnostics("pyright", output)

    assert diagnostics == [
        "/tmp/example.py:3:14 - error: Type \"Literal['bad']\" is not assignable to declared type \"int\""
    ]
