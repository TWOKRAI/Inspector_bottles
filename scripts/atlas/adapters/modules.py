"""Адаптер `modules`: узлы module из modules.yaml дерева сборки (Task 1.3a).

Purpose: читает modules.yaml из ревизии (не с диска); нет файла — пустой выход; невалидный (в т.ч. пустой,
    не строковый или повторяющийся id, битый `__init__.py` юнита) — AtlasError (exit 2) без значений в тексте.
    Юниты из `roots` идут перед записями `modules:`; их `__init__.py` читаются одним `git cat-file --batch`.
Public API: ModulesAdapter, modules_for.
Stability: lite
"""

from __future__ import annotations

import yaml

from scripts.atlas.modules import expand_roots, parse_modules
from scripts.atlas.schema import AdapterOutput, BuildContext, Node
from scripts.atlas.tree import AtlasError, Tree, run_git

__all__ = ["ModulesAdapter", "modules_for"]

_FILE = "modules.yaml"
_UNPARSEABLE = "modules.yaml: файл не разобран как YAML в UTF-8"


def _read_many(tree: Tree, paths: list[str]) -> dict[str, bytes | None]:
    """Содержимое файлов ревизии одним `git cat-file --batch`; нет файла или не blob -> None."""
    if not paths:
        return {}
    proc = run_git(tree.root, "cat-file", "--batch", input="".join(f"{tree.ref}:{p}\n" for p in paths).encode("utf-8"))
    out: dict[str, bytes | None] = {}
    pos = 0
    try:
        if proc.returncode != 0:
            raise ValueError
        for path in paths:
            end = proc.stdout.index(b"\n", pos)
            header, pos = proc.stdout[pos:end], end + 1
            out[path] = None
            if not header.endswith(b" missing"):  # путь с пробелом даёт заголовок из 3+ частей
                _, kind, size = header.split(b" ")
                out[path] = proc.stdout[pos : pos + int(size)] if kind == b"blob" else None
                pos += int(size) + 1
    except ValueError:
        raise AtlasError("atlas: git cat-file failed") from None
    return out


def modules_for(tree: Tree) -> list[dict]:
    """Строки ревизии: юниты из `roots`, затем записи modules.yaml; нет файла -> []; невалидный -> AtlasError."""
    try:
        raw = tree.read(_FILE)
    except FileNotFoundError:
        return []
    try:
        text = raw.decode("utf-8")
        rows = parse_modules(text, _FILE)
        units = expand_roots(text, _FILE, tree.files(), lambda paths: _read_many(tree, paths))
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
    return [*units, *rows]


class ModulesAdapter:
    name = "modules"
    version = 1

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        return AdapterOutput(nodes=[Node("module", row["id"], _FILE) for row in modules_for(ctx.tree)])
