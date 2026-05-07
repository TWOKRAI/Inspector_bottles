"""glob_walker.py — обход вложенного dict-дерева по glob-паттерну.

Публичная утилита `iter_matches` — генератор, выдающий пары
``(полный_точечный_путь, значение)`` для всех узлов, чьи пути
совпадают с паттерном (`*` — один сегмент, `**` — ноль и более).

Используется selectors (для сбора зависимостей). Здесь сосредоточена
вся логика обхода tree×pattern, чтобы не дублировать её в нескольких
местах модуля. Сравнение одного пути с паттерном — отдельная операция,
живёт в `subscription_manager._match_pattern` (см. `core.match_pattern`).
"""

from __future__ import annotations

from typing import Any, Iterator

from .subscription_manager import split_pattern


def iter_matches(root: dict, pattern: str) -> Iterator[tuple[str, Any]]:
    """Итерация по всем узлам дерева, чьи пути совпадают с pattern.

    Args:
        root: корневой dict дерева состояний.
        pattern: glob-паттерн, например ``cameras.*.state.actual_fps``.

    Yields:
        Кортежи ``(точечный_путь, значение)``. Значение возвращается
        как есть (без deep-copy) — клиент сам решает, копировать ли.
    """
    if not isinstance(root, dict):
        return
    pattern_segs = split_pattern(pattern)
    yield from _walk(root, pattern_segs, 0, [])


def _walk(
    node: Any,
    segs: tuple[str, ...],
    depth: int,
    current_path: list[str],
) -> Iterator[tuple[str, Any]]:
    """Рекурсивный обход с матчингом паттерна. Yields (path, value)."""
    # Паттерн исчерпан → текущий узел — результат
    if depth >= len(segs):
        yield ".".join(current_path), node
        return

    seg = segs[depth]

    if seg == "**":
        # '**' может поглотить 0 сегментов: пропускаем '**' и идём дальше.
        # Делаем это ДО проверки isinstance(node, dict), потому что '**'
        # должен совпадать и на листьях (path = "cameras.0.fps" под pattern
        # "cameras.**" — лист валидное завершение).
        yield from _walk(node, segs, depth + 1, current_path)

        # '**' может поглотить 1+ сегментов: съедаем один уровень, остаёмся на '**'.
        # Это требует dict — дальше идти можно только по нему.
        if isinstance(node, dict):
            for key, child in node.items():
                yield from _walk(child, segs, depth, current_path + [key])
        return

    # Для конкретных ключей и '*' нужен dict
    if not isinstance(node, dict):
        return

    if seg == "*":
        # '*' — ровно один сегмент (любой ключ)
        for key, child in node.items():
            yield from _walk(child, segs, depth + 1, current_path + [key])
    else:
        # Конкретный ключ
        if seg in node:
            yield from _walk(node[seg], segs, depth + 1, current_path + [seg])
