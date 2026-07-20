"""Structural guardrails for the hexagonal layout: domain/ packages must stay
pure (no DB, no HTTP), so they're testable without any infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "metrics"

# Modules a domain/ file must never import — these are I/O adapters' business.
FORBIDDEN_IN_DOMAIN = {"duckdb", "httpx", "yaml"}


def _domain_files() -> list[Path]:
    return sorted(SRC.glob("*/domain/*.py"))


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_domain_packages_exist():
    # Guards against a silently-empty glob (e.g. a rename breaking the pattern).
    assert len(_domain_files()) >= 5


def test_domain_files_do_not_import_infrastructure():
    violations = {}
    for path in _domain_files():
        hit = _imported_top_level_modules(path) & FORBIDDEN_IN_DOMAIN
        if hit:
            violations[str(path.relative_to(SRC.parent.parent))] = hit
    assert not violations, (
        f"domain/ files must stay pure (no DB/HTTP/YAML imports): {violations}"
    )
