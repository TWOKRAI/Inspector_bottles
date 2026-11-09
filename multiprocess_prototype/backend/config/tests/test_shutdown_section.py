# -*- coding: utf-8 -*-
"""Слепой набор Task 1.4m (gui-graceful-close): секция ``shutdown`` в ``system.yaml``.

Контракт: у ``SystemConfig`` есть поле ``shutdown`` с ``pre_stop`` (список шагов остановки,
по умолчанию пустой); настоящий ``system.yaml`` задаёт один шаг «devices.robot_park_all»;
шаг проходит схему ProcessManager (``parse_pre_stop``); слой ``user_overrides.yaml``
ЗАМЕНЯЕТ список целиком, а ``None`` в нём не роняет загрузку.

Тесты написаны по критериям приёмки, до реализации: ожидаемые значения — литералы.
Настоящий каталог ``backend/config/`` не трогаем: копии ``system.yaml`` — во временном.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from multiprocess_framework.modules.process_manager_module.process.pre_stop import parse_pre_stop
from multiprocess_prototype.backend.config import schemas
from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config

#: Настоящий system.yaml прототипа (только чтение — копируем, не правим).
_REAL_SYSTEM_YAML = Path(schemas.__file__).parent / "system.yaml"

#: Ожидаемый единственный шаг «списка П2» — литерал, не производный от кода.
_STEP_P2 = {"process": "devices", "command": "robot_park_all", "args": {}, "timeout_s": 35}


def _copy_system_yaml(tmp_path: Path) -> Path:
    """Копия настоящего system.yaml во временный каталог; рядом можно класть user_overrides."""
    dst = tmp_path / "system.yaml"
    shutil.copyfile(_REAL_SYSTEM_YAML, dst)
    return dst


def test_reds1_default_pre_stop_is_empty_list() -> None:
    """Схемный дефолт: без секции в yaml шагов остановки нет."""
    assert SystemConfig().shutdown.pre_stop == []


def test_reds2_real_system_yaml_has_the_single_robot_park_step() -> None:
    """Настоящий system.yaml: ровно один шаг — парковка робота процессом devices, 35 с."""
    assert load_system_config().shutdown.pre_stop == [_STEP_P2]


def test_reds3_real_pre_stop_passes_the_pm_schema() -> None:
    """Список из загруженного конфига принимает схема PM: один шаг, без ошибок, 35,0 с."""
    raw = load_system_config().shutdown.pre_stop  # вход — из конфига, не литерал

    steps, errors = parse_pre_stop(raw)

    assert errors == [], f"схема PM отвергла шаг из system.yaml: {errors}"
    assert len(steps) == 1, f"ожидался ровно 1 шаг, принято {len(steps)}"
    assert steps[0].label == "devices.robot_park_all"
    assert steps[0].timeout_s == 35.0


def test_reds5_user_overrides_empty_list_replaces_not_merges(tmp_path: Path) -> None:
    """Оверрайд ``pre_stop: []`` ЗАМЕНЯЕТ список базы (не склеивается с ним)."""
    system_yaml = _copy_system_yaml(tmp_path)
    (tmp_path / "user_overrides.yaml").write_text("shutdown:\n  pre_stop: []\n", encoding="utf-8")

    assert load_system_config(system_yaml).shutdown.pre_stop == []


def test_reds6_user_overrides_none_pre_stop_gives_empty_list(tmp_path: Path) -> None:
    """Оверрайд ``pre_stop:`` (значение None) не роняет загрузку и даёт ``[]``.

    База — настоящая, с непустым списком: иначе ячейка зелёная и при игнорировании None.
    """
    system_yaml = _copy_system_yaml(tmp_path)
    # Предусловие: без оверрайда база непустая, иначе проверка ничего не различает.
    assert load_system_config(system_yaml).shutdown.pre_stop == [_STEP_P2]
    (tmp_path / "user_overrides.yaml").write_text("shutdown:\n  pre_stop:\n", encoding="utf-8")

    cfg = load_system_config(system_yaml)

    assert cfg.shutdown.pre_stop == []
