"""Discover third-party imports referenced by a Python package.

Invocation::

    python -c "$SCRIPT" /absolute/package/root dotted.package.name

The first positional argument is the package directory to scan recursively for
``*.py`` files. The second is the package's import name; its first dotted
segment is excluded so local imports are not treated as dependencies.

The script reads no stdin. It writes a sorted JSON array of absolute import
names to stdout, excluding standard-library modules, the package itself, and
files beneath ``.git``, ``.venv``, ``__pycache__``, or ``node_modules``.
Syntax or filesystem errors are intentionally fatal and reported by Python on
stderr for the Rust coordinator to surface.
"""

import ast
import json
import sys
from pathlib import Path

package_root = Path(sys.argv[1])
package_name = sys.argv[2].split(".", 1)[0]
ignored_directories = {".git", ".venv", "__pycache__", "node_modules"}
imports: set[str] = set()

for path in package_root.rglob("*.py"):
    if ignored_directories.intersection(path.parts):
        continue
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)

third_party = sorted(
    module
    for module in imports
    if module.split(".", 1)[0] != package_name
    and module.split(".", 1)[0] not in sys.stdlib_module_names
)
sys.stdout.write(json.dumps(third_party))
