from click.testing import CliRunner

from mountaineer.entrypoint import main


def test_lint_command_invokes_handle_lint(monkeypatch):
    captured: dict[str, object] = {}

    def fake_handle_lint(*, paths, fix, fast):
        captured["paths"] = paths
        captured["fix"] = fix
        captured["fast"] = fast
        return 0

    monkeypatch.setattr("mountaineer.entrypoint.handle_lint", fake_handle_lint)

    result = CliRunner().invoke(
        main,
        ["lint", "--path", "mountaineer", "--path", "create_mountaineer_app", "--fix", "--fast"],
    )

    assert result.exit_code == 0
    assert captured == {
        "paths": ["mountaineer", "create_mountaineer_app"],
        "fix": True,
        "fast": True,
    }


def test_lint_command_propagates_nonzero_exit(monkeypatch):
    def fake_handle_lint(*, paths, fix, fast):
        _ = (paths, fix, fast)
        return 2

    monkeypatch.setattr("mountaineer.entrypoint.handle_lint", fake_handle_lint)

    result = CliRunner().invoke(main, ["lint"])

    assert result.exit_code == 2
