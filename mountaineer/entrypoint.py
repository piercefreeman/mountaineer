from click import group, option

from mountaineer.cli import handle_lint


@group()
def main():
    """
    Mountaineer framework command group.

    """


@main.command()
@option(
    "--path",
    "paths",
    multiple=True,
    help="Optional path(s) to lint. Can be passed multiple times.",
)
@option(
    "--fix",
    is_flag=True,
    default=False,
    help="Apply Ruff autofixes before running checks.",
)
@option(
    "--fast",
    is_flag=True,
    default=False,
    help="Run only Ruff checks.",
)
def lint(paths: tuple[str, ...], fix: bool, fast: bool):
    exit_code = handle_lint(paths=list(paths), fix=fix, fast=fast)
    if exit_code != 0:
        raise SystemExit(exit_code)
