# -*- coding: utf-8 -*-
"""_node_read.py — чтение пути УЗЛА из telemetry read-model driver'а (P3r).

После П3 ``TelemetryReadModel`` хранит ЛИСТЬЯ: dict-дельта по узлу раскладывается на
листья, ``snapshot("a.n")`` даёт плоские ``{"a.n.x": 3}``, а ``get("a.n")`` — None.
Потребитель, спросивший путь узла и проверивший ``path in snapshot(path)``, видит
«пути нет». :func:`read_node` собирает узел обратно из листьев.

Алгоритм сборки живёт в ``telemetry_readmodel_module.node_read`` (одна копия); здесь
остаётся только взятие снимка под ``_telemetry_lock``.

Модуль приватный (``_``-имя): общий нейтральный импорт для ``conditions.py`` и
``recorder.py`` (``recorder`` не тянет ``conditions``), не публичный контракт.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.telemetry_readmodel_module import assemble_leaves as _assemble  # noqa: F401 — для driver.py:91
from multiprocess_framework.modules.telemetry_readmodel_module import node_from_snapshot


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
    return node_from_snapshot(snap, path)
