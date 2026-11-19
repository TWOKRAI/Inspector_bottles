"""yaml_io.py — I/O утилиты для Settings таба.

Загружает config/system.yaml → SystemConfig, сохраняет атомарно,
разворачивает SystemConfig в список FieldInfo для RegisterView.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from multiprocess_framework.modules.process_manager_module.process.run_config import RUN_CONFIG_KEYS
from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo, extract_fields

# backend/config/system.yaml относительно multiprocess_prototype/
# parents[4] от tabs/settings/yaml_io.py:
#   [0]=settings/, [1]=tabs/, [2]=widgets/, [3]=frontend/, [4]=multiprocess_prototype/
SETTINGS_PATH: Path = Path(__file__).resolve().parents[4] / "backend" / "config" / "system.yaml"

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


def _keep_run_keys_as_on_disk(data: dict, target: Path) -> None:
    """Плоские ключи ``RunConfig`` в ``data`` — как в исходном файле ``target``; нет в файле — не пишем.

    У ключей нет редакторов, поэтому значение в ``cfg`` отличается от файла только умолчанием схемы или
    ``user_overrides.yaml`` — ни то ни другое в ``system.yaml`` попадать не должно. Файла нет или он не
    словарь -> исходных ключей нет. Нет файла на диске — плоские ключи ``run_*`` не пишутся (Save идёт в
    существующий ``system.yaml``). Ошибка разбора yaml не глотается.
    """
    on_disk: dict = {}
    if target.exists():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            on_disk = loaded
    for key in RUN_CONFIG_KEYS:
        if key in on_disk:
            data[key] = on_disk[key]
        else:
            data.pop(key, None)


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

    data = cfg.model_dump()
    _keep_run_keys_as_on_disk(data, target)

    tmp_path = target.with_suffix(".yaml.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
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
