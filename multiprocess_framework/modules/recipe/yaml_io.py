# -*- coding: utf-8 -*-
"""yaml_io.py — запись YAML с сохранением комментариев (ruamel round-trip).

Generic comment-preserving writer модуля `recipe` (C3, ADR-RCP-005). Раньше жил в
прототипе (`multiprocess_prototype/recipes/yaml_io.py`) — теперь консолидирован во
фреймворк как generic-часть модуля рецептов; прототип держит тонкий шим на этот путь.

Используется там, где файл редактирует и человек, и приложение:
  - рецепты (``recipes/*.yaml``) — заголовок-док + per-node комментарии;
  - главный конфиг ``app.yaml`` — persist активного pipeline без потери комментариев.

Запись атомарна (буфер -> ``service._atomic_write``: tmp + fsync + ``os.replace``),
права файла сохраняются — см. ``_dump_atomic``.

Контракт ``update_yaml_preserving``: обновляет ТОЛЬКО указанные top-level ключи
существующего файла, не трогая остальное (комментарии, порядок, заголовок).
Замена значения ключа сохраняет комментарий, привязанный к самому ключу; теряются
лишь комментарии ВНУТРИ заменяемого поддерева (например, при полной перезаписи
``blueprint`` — это неизбежно, т.к. топология изменилась).

``update_blueprint_metadata_preserving`` работает с формой v3-рецепта (вложенный
``blueprint.metadata``) — это формат рецепта, а не прикладной домен Inspector,
поэтому writer generic (никаких cameras/robot/…).

ruamel импортируется лениво (внутри функции): модуль грузится без падения даже
если зависимость ещё не установлена — ошибка возникает только при реальной записи,
с понятным сообщением «запусти uv sync».
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import Any

__all__ = ["update_yaml_preserving", "update_blueprint_metadata_preserving"]


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
    _dump_atomic(yaml, data, path)


def _dump_atomic(yaml, data: Any, path: Path) -> None:
    """Сериализовать в буфер и записать через ``service._atomic_write`` (tmp в том же
    каталоге + fsync + ``os.replace``; при сбое tmp убирается, старый файл цел).

    Сбой сериализации (ruamel не представил значение) случается ДО открытия файла —
    файл не тронут вовсе. Права файла сохраняются: ``mkstemp`` создаёт tmp с 0600,
    поэтому после замены mode исходного файла возвращается ``chmod``. Нового файла нет —
    сначала ``touch`` (mode по umask процесса, как прежний ``open("w")``), при сбое он
    удаляется.
    ponytail: chmod ПОСЛЕ ``os.replace`` — между заменой и chmod файл виден с 0600
    (читатель-другой пользователь получит EACCES на микросекунды); убрать окно —
    copymode на tmp внутри ``_atomic_write`` (service.py)."""
    from .service import _atomic_write

    # Прежний open("w") писал СКВОЗЬ симлинк и падал PermissionError на файле 0444 — сохраняем оба
    # свойства для всех вызывающих (ревью 1.2a it.2, F1). ponytail: жёсткая ссылка атомарной заменой
    # рвётся, каталог 0555 теперь не даёт записать (нужен tmp рядом) — ADR-RCP-008; таких файлов 0.
    path = Path(os.path.realpath(path))
    if path.exists() and not os.access(path, os.W_OK):
        raise PermissionError(f"файл только для чтения: {path}")

    buf = io.StringIO()
    yaml.dump(data, buf)
    raw = buf.getvalue().encode("utf-8")
    created = not path.exists()
    if created:
        path.touch()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        _atomic_write(path, raw)
        os.chmod(path, mode)
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def update_blueprint_metadata_preserving(path: str | Path, metadata_updates: dict[str, Any]) -> None:
    """Точечно обновить ``blueprint.metadata.<key>``, сохранив ВСЕ комментарии.

    В отличие от :func:`update_yaml_preserving`, НЕ перезаписывает весь ``blueprint``
    (что стёрло бы комментарии внутри него — per-node ``# --- ... ---`` и т.п.), а
    меняет только указанные ключи внутри ``blueprint.metadata`` на ruamel-документе.
    Применяется для авто-персиста layout (gui_positions / locked_nodes), который не
    должен портить рецепт при каждом перетаскивании ноды.

    No-op, если файла нет, он пуст или в нём нет вложенного ``blueprint`` (raw-topology
    без editor-обёртки — layout писать некуда).

    Args:
        path: путь к YAML-файлу рецепта.
        metadata_updates: ключи для записи в ``blueprint.metadata`` (значения заменяются
            целиком — напр. ``{"gui_positions": {...}, "locked_nodes": [...]}``).
    """
    from ruamel.yaml.comments import CommentedMap

    path = Path(path)
    if not path.exists():
        return
    yaml = _make_yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.load(f)
    if not isinstance(doc, dict):
        return
    bp = doc.get("blueprint")
    if not isinstance(bp, dict):
        # raw-topology без вложенного blueprint — layout некуда писать.
        return

    meta = bp.get("metadata")
    if not isinstance(meta, dict):
        meta = CommentedMap()
        bp["metadata"] = meta
    for key, value in metadata_updates.items():
        meta[key] = value

    _dump_atomic(yaml, doc, path)
