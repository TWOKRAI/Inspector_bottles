"""Адаптер `modules`: узлы module из modules.yaml дерева сборки (Task 1.3a).

Purpose: читает modules.yaml из ревизии (не с диска); нет файла — пустой выход; невалидный — ValueError ->
    AtlasError (exit 2) с текстом parse_modules.
Public API: ModulesAdapter, modules_for.
Stability: lite
"""

from __future__ import annotations

import yaml

from scripts.atlas.modules import parse_modules
from scripts.atlas.schema import AdapterOutput, BuildContext, Node
from scripts.atlas.tree import AtlasError, Tree

__all__ = ["ModulesAdapter", "modules_for"]

_FILE = "modules.yaml"
_UNPARSEABLE = "modules.yaml: файл не разобран как YAML в UTF-8"


def modules_for(tree: Tree) -> list[dict]:
    """Строки modules.yaml ревизии; нет файла -> []; невалидный -> AtlasError с текстом ValueError."""
    try:
        raw = tree.read(_FILE)
    except FileNotFoundError:
        return []
    try:
        return parse_modules(raw.decode("utf-8"), _FILE)
    except (yaml.YAMLError, UnicodeDecodeError):
        # Текст ошибки парсера несёт фрагмент файла — отдаём одну константу, без значений.
        raise AtlasError(_UNPARSEABLE) from None
    except ValueError as exc:
        raise AtlasError(str(exc)) from exc


class ModulesAdapter:
    name = "modules"
    version = 1

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        return AdapterOutput(nodes=[Node("module", row["id"], _FILE) for row in modules_for(ctx.tree)])
