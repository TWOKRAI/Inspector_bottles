"""yaml_io.py — I/O утилиты для Settings таба.

Загружает config/system.yaml → SystemConfig, сохраняет атомарно,
разворачивает SystemConfig в список FieldInfo для RegisterView.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from multiprocess_prototype.config.schemas import SystemConfig, load_system_config
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo, extract_fields

# config/system.yaml относительно multiprocess_prototype/
# parents[4] от tabs/settings/yaml_io.py:
#   [0]=settings/, [1]=tabs/, [2]=widgets/, [3]=frontend/, [4]=multiprocess_prototype/
SETTINGS_PATH: Path = Path(__file__).resolve().parents[4] / "config" / "system.yaml"

# Секции SystemConfig в порядке отображения
_SECTIONS = ["system", "camera", "processing", "display", "storage"]


def load_settings(path: Path | None = None) -> SystemConfig:
    """Загрузить SystemConfig из YAML.

    При отсутствии файла возвращает SystemConfig() с defaults.

    Args:
        path: путь к YAML-файлу (None = SETTINGS_PATH)

    Returns:
        Валидированный SystemConfig
    """
    return load_system_config(path or SETTINGS_PATH)


def save_settings(cfg: SystemConfig, path: Path | None = None) -> None:
    """Атомарно сохранить SystemConfig в YAML.

    Использует .tmp + os.replace для атомарности.
    allow_unicode=True чтобы кириллица не эскейпилась.
    sort_keys=False чтобы сохранить порядок секций.

    Args:
        cfg: валидированный SystemConfig для записи
        path: путь к YAML-файлу (None = SETTINGS_PATH)
    """
    target = path or SETTINGS_PATH
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target.with_suffix(".yaml.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                cfg.model_dump(),
                f,
                allow_unicode=True,
                sort_keys=False,
            )
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def schema_to_field_infos(cfg: SystemConfig) -> list[FieldInfo]:
    """Развернуть SystemConfig в плоский список FieldInfo.

    Для каждой секции (system/camera/processing/display/storage) вызывает
    extract_fields(section_name, type(section), category=section_name).

    Ключ редактора в RegisterView будет 'section_name.field_name'
    (т.к. FieldInfo.plugin_name=section_name, FieldInfo.field_name=field_name).

    Args:
        cfg: загруженный SystemConfig

    Returns:
        Плоский список FieldInfo всех секций в порядке _SECTIONS
    """
    result: list[FieldInfo] = []
    for section_name in _SECTIONS:
        section_obj = getattr(cfg, section_name, None)
        if section_obj is None:
            continue
        section_cls = type(section_obj)
        fields = extract_fields(
            plugin_name=section_name,
            register_cls=section_cls,
            category=section_name,
        )
        result.extend(fields)
    return result
