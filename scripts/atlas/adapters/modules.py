"""Адаптер `modules`: узлы module из modules.yaml дерева сборки (Task 1.3a).

Purpose: читает modules.yaml из ревизии (не с диска); нет файла — пустой выход; невалидный — ValueError ->
    AtlasError (exit 2) с текстом parse_modules.
Public API: ModulesAdapter, modules_for.
Stability: lite
"""

from __future__ import annotations

from scripts.atlas.modules import parse_modules
from scripts.atlas.schema import AdapterOutput, BuildContext, Node
from scripts.atlas.tree import AtlasError, Tree

__all__ = ["ModulesAdapter", "modules_for"]

_FILE = "modules.yaml"


def modules_for(tree: Tree) -> list[dict]:
    """Строки modules.yaml ревизии; нет файла -> []; невалидный -> AtlasError с текстом ValueError."""
    try:
        text = tree.read(_FILE).decode("utf-8")
    except FileNotFoundError:
        return []
    try:
        return parse_modules(text, _FILE)
    except ValueError as exc:
        raise AtlasError(str(exc)) from exc


class ModulesAdapter:
    name = "modules"
    version = 1

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        return AdapterOutput(nodes=[Node("module", row["id"], _FILE) for row in modules_for(ctx.tree)])
