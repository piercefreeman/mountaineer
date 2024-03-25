from create_mountaineer_app.cli import get_current_version_number


def test_get_current_version_number():
    # Before we release our package and bump the version in pyproject.toml, our version
    # will be static during local development
    assert get_current_version_number() == "0.1.0"
