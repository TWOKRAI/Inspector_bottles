"""Адаптер `modules`: узлы module из modules.yaml дерева сборки (Task 1.3a).

Purpose: читает modules.yaml из ревизии (не с диска); нет файла — пустой выход; невалидный (в т.ч. пустой,
    не строковый или повторяющийся id) — AtlasError (exit 2) без значений в тексте.
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
        rows = parse_modules(raw.decode("utf-8"), _FILE)
    except (yaml.YAMLError, UnicodeDecodeError):
        # Текст ошибки парсера несёт фрагмент файла — отдаём одну константу, без значений.
        raise AtlasError(_UNPARSEABLE) from None
    except ValueError as exc:
        if not str(exc).startswith(f"{_FILE}:"):  # ValueError самого YAML-конструктора (дата 2026-13-45)
            raise AtlasError(_UNPARSEABLE) from None
        raise AtlasError(str(exc)) from exc
    seen: set[str] = set()
    for index, row in enumerate(rows):
        row_id = row["id"]
        if not isinstance(row_id, str) or row_id == "" or row_id in seen:
            raise AtlasError(f"{_FILE}: в строке {index} ключ 'id' пустой, не строка или повторяется")
        seen.add(row_id)
    return rows


class ModulesAdapter:
    name = "modules"
    version = 1

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        return AdapterOutput(nodes=[Node("module", row["id"], _FILE) for row in modules_for(ctx.tree)])
