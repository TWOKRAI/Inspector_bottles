# -*- coding: utf-8 -*-
"""
Спутник рецепта — machine-owned файл слоя L2 (Task 5.12, шаг 7).

``recipes/foo.yaml`` (пишет человек) ↔ ``recipes/foo.observability.yaml``
(пишет машина). Граница проходит по ФАЙЛАМ, а не по дисциплине «аккуратно
патчить чужой YAML»: аккуратность уже подводила — GUI-save round-трипнул
``system.yaml`` через ``safe_dump(model_dump)`` и стёр все комментарии
(зафиксировано отдельным уроком проекта). Разделив файлы, мы делаем этот класс
ошибки невозможным, а не маловероятным.

Форма спутника — та же секция ``observability``, что в рецепте
(``defaults`` + ``processes[<имя>]``), поэтому загрузка не требует отдельной
ветки: он читается тем же ``resolve_recipe_section``.

Запись атомарная (tmp рядом + ``os.replace``) и идемпотентная: одинаковое
содержимое файл не трогает вовсе. Идемпотентность здесь не оптимизация — за
файлом следит watcher, и запись, меняющая mtime без изменения содержимого,
дала бы петлю «применили → записали → увидели → применили».
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: Суффикс спутника. Именно ``.observability.yaml``, а не ``.obs.yml``:
#: имя файла — единственная подсказка человеку, кто его хозяин.
COMPANION_SUFFIX = ".observability.yaml"

#: Шапка файла. Спутник machine-owned, и это должно быть написано В НЁМ —
#: не только в документации, которую при отладке никто не открывает.
COMPANION_HEADER = (
    "# Спутник рецепта: слой L2 наблюдаемости (Task 5.12).\n"
    "# ФАЙЛ MACHINE-OWNED — его перезаписывает команда observability.persist.\n"
    "# Правки руками переживут ровно до следующего сохранения из пульта.\n"
    "# Человеческие настройки конвейера — в самом рецепте, рядом.\n"
)


def companion_path(recipe_path: str | os.PathLike[str]) -> Path:
    """``recipes/foo.yaml`` → ``recipes/foo.observability.yaml``."""
    p = Path(recipe_path)
    return p.with_name(p.stem + COMPANION_SUFFIX)


def load_companion(recipe_path: str | os.PathLike[str]) -> Dict[str, Any]:
    """Прочитать секцию спутника. Нет файла / нечитаем → ``{}``.

    Отсутствие спутника — штатное состояние (его создаёт первое «сохранить»),
    поэтому это не ошибка. А вот битый YAML — ошибка, и она пробрасывается
    наверх: молча стартовать без сохранённых настроек хуже, чем отказать.
    """
    path = companion_path(recipe_path)
    if not path.exists():
        return {}
    from ...data_schema_module.serialization.converter import DataConverter

    loaded = DataConverter.load_from_file(path)
    if not isinstance(loaded, dict):
        return {}
    section = loaded.get("observability")
    return section if isinstance(section, dict) else {}


def build_companion_section(
    current: Dict[str, Any],
    process_name: str,
    delta: Dict[str, Any],
) -> Dict[str, Any]:
    """Вложить дельту процесса в секцию спутника (per-process, поверх текущей).

    Правка ОДНОГО процесса не имеет права переписать соседей — поэтому дельта
    кладётся в ``processes[<имя>]``, а не в ``defaults``: ``defaults`` — то, что
    человек решил про весь конвейер, и машине там не место.
    """
    from ...data_schema_module import deep_merge

    section = dict(current or {})
    processes = dict(section.get("processes") or {})
    processes[process_name] = deep_merge(processes.get(process_name) or {}, delta)
    section["processes"] = processes
    return section


def write_companion(
    recipe_path: str | os.PathLike[str],
    section: Dict[str, Any],
) -> Tuple[Path, bool]:
    """Записать секцию в спутник атомарно и идемпотентно.

    Returns:
        ``(путь, была_ли_запись)``. ``False`` — содержимое уже совпадало, файл
        не тронут (и watcher не разбужен).

    Note:
        ``os.replace`` на Windows уже давал ``WinError 5`` в этом проекте, когда
        целевой файл держит другой процесс. Здесь цель — machine-owned спутник,
        которого никто не держит открытым, а tmp кладётся В ТОТ ЖЕ каталог
        (замена между томами не атомарна). Отказ не глушится: вызывающий обязан
        узнать, что «сохранить» не сохранило.
    """
    import yaml

    path = companion_path(recipe_path)
    body = yaml.safe_dump(
        {"observability": section},
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    )
    payload = COMPANION_HEADER + body

    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == payload:
                return path, False
        except OSError:
            pass  # нечитаем — перезапишем

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return path, True


def persist_session_to_companion(
    recipe_path: Optional[str],
    process_name: str,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    """Перенести слой сессии процесса в спутник рецепта.

    Returns:
        Отчёт: ``{"success", "path", "written", "keys"}`` либо
        ``{"success": False, "reason": ...}``.
    """
    from .observability_layers import flatten_section

    if not recipe_path:
        return {"success": False, "reason": "путь к рецепту неизвестен — некуда сохранять"}
    if not session:
        return {"success": False, "reason": "слой сессии пуст — сохранять нечего"}

    section = build_companion_section(load_companion(recipe_path), process_name, session)
    path, written = write_companion(recipe_path, section)
    return {
        "success": True,
        "path": str(path),
        "written": written,
        "keys": sorted(flatten_section(session).keys()),
    }
