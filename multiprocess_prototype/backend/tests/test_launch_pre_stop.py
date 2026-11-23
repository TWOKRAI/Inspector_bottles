# -*- coding: utf-8 -*-
"""Слепой набор Task 1.4m (gui-graceful-close): лончер кладёт ``pre_stop`` в ``orchestrator_config``.

Дёргается НАСТОЯЩИЙ ``SystemBuilder(...).build()`` — без запуска процессов (он лишь собирает
``SystemLauncher``): проверяемое место живёт именно в ``build()``. Образец формы — прямой
конструктор из ``test_boot_companion_base.py``. ``build()`` пишет в ``os.environ`` — фикстура
``_restore_environ`` возвращает окружение как было.

Три ячейки одного контракта:
  (а) шаги из ``system.yaml`` доезжают до ``orchestrator_config["pre_stop"]``;
  (б) доехавший список — ГЛУБОКАЯ копия: правка вложенного ``args`` не трогает конфиг;
  (в) пустой список доезжает как ``[]``, ключ не пропадает.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config
from multiprocess_prototype.backend.launch import SystemBuilder

#: Минимальный blueprint: один процесс, ни плагинов, ни проводов.
_BLUEPRINT: Dict[str, Any] = {
    "name": "pre_stop_probe",
    "processes": [{"process_name": "seg", "process_class": "some.module.SegApp", "plugins": []}],
    "wires": [],
}


@pytest.fixture(autouse=True)
def _restore_environ():
    """``build()`` пишет в ``os.environ`` — вернуть окружение ровно как было."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _orchestrator_config(sys_config: SystemConfig, topology_path: Path) -> Dict[str, Any]:
    """``orchestrator_config`` лончера, собранного настоящим ``build()`` (процессы не стартуют)."""
    launcher = SystemBuilder(
        sys_config=sys_config,
        blueprint=copy.deepcopy(_BLUEPRINT),
        topology_path=topology_path,
    ).build()
    return launcher._orchestrator_config


@pytest.fixture()
def topology_path(tmp_path: Path) -> Path:
    path = tmp_path / "pre_stop_probe.yaml"
    path.write_text("name: pre_stop_probe\n", encoding="utf-8")
    return path


def test_reds4a_real_pre_stop_reaches_orchestrator_config(topology_path: Path) -> None:
    """Список П2 из настоящего system.yaml лежит в ``orchestrator_config["pre_stop"]`` буквально."""
    cfg = load_system_config()
    list_p2 = [{"process": "devices", "command": "robot_park_all", "args": {}, "timeout_s": 35}]
    # Предусловие: сам конфиг отдаёт ожидаемый список (иначе сверка ниже о другом).
    assert cfg.shutdown.pre_stop == list_p2

    orchestrator_config = _orchestrator_config(cfg, topology_path)

    assert orchestrator_config["pre_stop"] == list_p2


def test_reds4b_orchestrator_pre_stop_is_a_deep_copy(topology_path: Path) -> None:
    """Правка ВЛОЖЕННОГО ``args`` в ``orchestrator_config`` не меняет ``cfg.shutdown.pre_stop``."""
    cfg = load_system_config()
    assert cfg.shutdown.pre_stop[0]["args"] == {}  # предусловие: исходник чист

    orchestrator_config = _orchestrator_config(cfg, topology_path)
    orchestrator_config["pre_stop"][0]["args"]["x"] = 1

    assert cfg.shutdown.pre_stop[0]["args"] == {}, "копия мелкая: args общий с конфигом"


def test_reds4c_empty_pre_stop_keeps_the_key_as_empty_list(topology_path: Path) -> None:
    """Пустой ``shutdown.pre_stop`` -> ключ ``pre_stop`` ЕСТЬ и равен ``[]`` (не отсутствует, не None)."""
    cfg = SystemConfig.model_validate({"discovery": {"auto_discover": False}, "shutdown": {"pre_stop": []}})

    orchestrator_config = _orchestrator_config(cfg, topology_path)

    assert "pre_stop" in orchestrator_config
    assert orchestrator_config["pre_stop"] == []
