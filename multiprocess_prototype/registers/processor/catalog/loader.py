"""Загрузка и сохранение каталога операций обработки из/в YAML."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .schemas import ProcessingOperationDef

logger = logging.getLogger(__name__)


def load_catalog(path: str | Path) -> dict[str, ProcessingOperationDef]:
    """Загрузить каталог операций из YAML-файла.

    Возвращает словарь: type_key → ProcessingOperationDef.
    Если файл не существует — возвращает пустой dict и пишет предупреждение.
    """
    catalog_path = Path(path)

    if not catalog_path.exists():
        logger.warning("Файл каталога не найден: %s — возвращается пустой каталог", catalog_path)
        return {}

    with catalog_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or "operations" not in raw:
        logger.warning("Каталог пуст или не содержит ключа 'operations': %s", catalog_path)
        return {}

    result: dict[str, ProcessingOperationDef] = {}
    for item in raw["operations"]:
        op_def = ProcessingOperationDef.model_validate(item)
        result[op_def.type_key] = op_def

    return result


def save_catalog(path: str | Path, catalog: dict[str, ProcessingOperationDef]) -> None:
    """Сохранить каталог операций в YAML-файл.

    Принимает словарь: type_key → ProcessingOperationDef.
    """
    catalog_path = Path(path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    operations = [op_def.model_dump() for op_def in catalog.values()]
    data = {"operations": operations}

    with catalog_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


__all__ = ["load_catalog", "save_catalog"]
