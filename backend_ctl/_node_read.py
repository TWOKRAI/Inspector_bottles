# -*- coding: utf-8 -*-
"""_node_read.py — чтение пути УЗЛА из telemetry read-model driver'а (P3r).

После П3 ``TelemetryReadModel`` хранит ЛИСТЬЯ: dict-дельта по узлу раскладывается на
листья, ``snapshot("a.n")`` даёт плоские ``{"a.n.x": 3}``, а ``get("a.n")`` — None.
Потребитель, спросивший путь узла и проверивший ``path in snapshot(path)``, видит
«пути нет». :func:`read_node` собирает узел обратно из листьев.

Модуль приватный (``_``-имя): общий нейтральный импорт для ``conditions.py`` и
``recorder.py`` (``recorder`` не тянет ``conditions``), не публичный контракт.
"""

from __future__ import annotations

from typing import Any


def read_node(drv: Any, path: str) -> tuple[bool, Any]:
    """(есть ли путь, значение) из read-model driver'а; узел собирается из листьев.

    Сам берёт ``drv._telemetry_lock`` и делает РОВНО ОДИН вызов
    ``drv._telemetry_model.snapshot(path)`` (никаких ``get`` и второго прохода).
    ВНИМАНИЕ: ``_telemetry_lock`` — обычный ``threading.Lock``; звать ``read_node``
    под уже взятым локом нельзя (повторный захват вешает поток).

    Правила по порядку:

      1. ``path`` — лист → ``(True, значение)`` (значение может быть None: «узел со
         значением None» и «нет узла» — разные состояния). Лист-предок побеждает
         потомков (как ``_assemble`` в ``leaf_copy.py``).
      2. Есть ключи с префиксом ``path + "."`` → ``(True, вложенный dict)`` относительно
         ``path``; при конфликте «лист и потомок» внутри поддерева лист-предок побеждает.
      3. Иначе ``(False, None)``. Пустой ``path`` — всегда ``(False, None)``.

    Известное расхождение с живым ``state.get`` (потеря лежит в read-model): пустой
    dict-узел исчезает, пустой вложенный dict теряется, ключ с точкой в имени
    собирается как вложенный.
    """
    if not path:
        return False, None
    with drv._telemetry_lock:
        snap = drv._telemetry_model.snapshot(path)
    if path in snap:
        return True, snap[path]
    prefix = path + "."
    leaves = {tuple(key[len(prefix) :].split(".")): value for key, value in snap.items() if key.startswith(prefix)}
    if not leaves:
        return False, None
    return True, _assemble(leaves)


def _assemble(leaves: dict[tuple[str, ...], Any]) -> dict[str, Any]:
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
