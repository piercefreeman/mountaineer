from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.ssr import render_ssr
from mountaineer.static import get_static_path


def _write_package_json(
    base_path: Path, *, dependency_name: str, dependency_version: str
) -> None:
    package_json = {
        "name": "mountaineer-react-ssr-test",
        "version": "1.0.0",
        "private": True,
        "type": "module",
        "dependencies": {
            "react": "^19.2.0",
            "react-dom": "^19.2.0",
            dependency_name: dependency_version,
        },
    }
    (base_path / "package.json").write_text(json.dumps(package_json, indent=2))


def _npm_install(package_root: Path) -> None:
    try:
        subprocess.run(
            ["npm", "install"],
            cwd=package_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"npm install failed: {exc.stdout}\n{exc.stderr}"
        ) from exc


@pytest.mark.parametrize(
    ("package_name", "package_version", "react_snippet"),
    [
        (
            "streamdown",
            "^1.4.0",
            """\
import React from 'react';
import StreamDown from 'streamdown';

const markdown = `# Hello World!\\n\\nThis is a streamdown test.`;

export default function Page() {
    return <StreamDown>{markdown}</StreamDown>;
}
""",
        ),
    ],
)
def test_react_packages_render_via_ssr(
    package_name: str,
    package_version: str,
    react_snippet: str,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "react_package"
    package_root.mkdir()

    _write_package_json(
        package_root,
        dependency_name=package_name,
        dependency_version=package_version,
    )
    _npm_install(package_root)

    component_path = package_root / "component.jsx"
    component_path.write_text(react_snippet)

    script_payloads, sourcemap_payloads = mountaineer_rs.compile_independent_bundles(
        [[str(component_path.resolve())]],
        str((package_root / "node_modules").resolve()),
        "development",
        0,
        str(get_static_path("live_reload.ts").resolve()),
        True,
        None,
    )

    ssr_script = script_payloads[0]
    sourcemap = sourcemap_payloads[0] or None

    rendered_html = render_ssr(
        script=ssr_script,
        render_data={},
        hard_timeout=5,
        sourcemap=sourcemap,
    )

    assert "Hello World" in rendered_html
