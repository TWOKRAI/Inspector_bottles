# -*- coding: utf-8 -*-
"""yaml_io.py — запись YAML с сохранением комментариев (ruamel round-trip).

Используется там, где файл редактирует и человек, и приложение:
  - рецепты (``recipes/*.yaml``) — заголовок-док + per-node комментарии;
  - главный конфиг ``app.yaml`` — persist активного pipeline без потери комментариев.

Контракт ``update_yaml_preserving``: обновляет ТОЛЬКО указанные top-level ключи
существующего файла, не трогая остальное (комментарии, порядок, заголовок).
Замена значения ключа сохраняет комментарий, привязанный к самому ключу; теряются
лишь комментарии ВНУТРИ заменяемого поддерева (например, при полной перезаписи
``blueprint`` — это неизбежно, т.к. топология изменилась).

ruamel импортируется лениво (внутри функции): модуль грузится без падения даже
если зависимость ещё не установлена — ошибка возникает только при реальной записи,
с понятным сообщением «запусти uv sync».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["update_yaml_preserving"]


def _make_yaml():
    """Сконфигурированный ruamel YAML (round-trip). Лениво — см. docstring модуля."""
    try:
        from ruamel.yaml import YAML
    except ModuleNotFoundError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "ruamel.yaml не установлен — нужен для записи YAML с сохранением "
            "комментариев. Установи зависимости: `uv sync` (ruamel.yaml уже в pyproject)."
        ) from exc
    yaml = YAML()  # round-trip по умолчанию
    yaml.preserve_quotes = True
    yaml.width = 4096  # не переносить длинные строки
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def update_yaml_preserving(path: str | Path, updates: dict[str, Any]) -> None:
    """Обновить top-level ключи YAML-файла, сохранив комментарии/структуру.

    Существующий файл — round-trip load + перезапись значений только ключей из
    ``updates`` (остальное, включая заголовок-комментарий, не тронуто). Новый файл —
    создаётся из ``updates``.

    Args:
        path: путь к YAML-файлу.
        updates: top-level ключи для записи (значения заменяются целиком).
    """
    path = Path(path)
    yaml = _make_yaml()

    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f)
        if data is None:
            from ruamel.yaml.comments import CommentedMap

            data = CommentedMap()
    else:
        from ruamel.yaml.comments import CommentedMap

        data = CommentedMap()

    for key, value in updates.items():
        data[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)
