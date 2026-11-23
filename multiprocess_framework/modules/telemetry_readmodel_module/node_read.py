"""node_read.py — сборка узла из листьев снимка read-model (чистые функции, только stdlib).

После П3 ``TelemetryReadModel`` хранит ЛИСТЬЯ: dict-дельта по узлу раскладывается на
листья, ``snapshot("a.n")`` даёт плоские ``{"a.n.x": 3}``, а ``get("a.n")`` — None.
Потребитель, спросивший путь узла, собирает его обратно через :func:`node_from_snapshot`.

Модуль импортирует только stdlib: его берут и ядро (``TelemetryReadModel.read_node``),
и headless-драйвер диагностики (``backend_ctl``) — одна копия алгоритма, без циклов.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assemble_leaves(leaves: dict[tuple[str, ...], Any]) -> dict[str, Any]:
    """Вложенный dict из листьев ``{части_пути: значение}``; лист-предок побеждает.

    Результат не зависит от порядка листьев: сначала отбрасываются листья, у которых
    какой-либо собственный префикс сам является листом, потом строится дерево.
    """
    tree: dict[str, Any] = {}
    for parts, value in leaves.items():
        if any(parts[:i] in leaves for i in range(1, len(parts))):
            continue
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return tree


def node_from_snapshot(snap: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """(есть ли путь, значение) из снимка ``snap``; узел собирается из листьев.

    Правила по порядку:

      1. Пустой ``path`` — всегда ``(False, None)``.
      2. ``path`` — лист → ``(True, значение)`` (значение может быть None: «узел со
         значением None» и «нет узла» — разные состояния). Лист-предок побеждает
         потомков.
      3. Есть ключи с префиксом ``path + "."`` → ``(True, вложенный dict)`` относительно
         ``path``; при конфликте «лист и потомок» внутри поддерева лист-предок побеждает.
      4. Иначе ``(False, None)``.

    Известное расхождение с живым ``state.get`` (потеря лежит в read-model): пустой
    dict-узел исчезает, пустой вложенный dict теряется, ключ с точкой в имени
    собирается как вложенный.
    """
    if not path:
        return False, None
    if path in snap:
        return True, snap[path]
    prefix = path + "."
    leaves = {tuple(key[len(prefix) :].split(".")): value for key, value in snap.items() if key.startswith(prefix)}
    if not leaves:
        return False, None
    return True, assemble_leaves(leaves)


__all__ = ["assemble_leaves", "node_from_snapshot"]
