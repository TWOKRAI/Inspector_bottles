# -*- coding: utf-8 -*-
"""Тесты распространения флага protected через схемы до proc_dict.

Регрессия Этап 1 pipeline-live-control: ProcessConfig/GenericProcessConfig не
несли protected → флаг из base.yaml (gui: protected: true) терялся при
SystemBlueprint.model_validate → PM._get_protected_names не видел gui →
replace_blueprint рестартил GUI.

Контракт: build() кладёт protected на ВЕРХНИЙ уровень proc_dict
(PM._get_protected_names читает cfg.get("protected"), не cfg["config"]).
"""

from __future__ import annotations

from ..configs.process_launch_config import ProcessLaunchConfig
from ..generic.blueprint import ProcessConfig, SystemBlueprint


def test_process_launch_config_protected_in_proc_dict() -> None:
    cfg = ProcessLaunchConfig(process_name="gui", process_class="m.Gui", protected=True)
    _name, proc_dict = cfg.build()
    assert proc_dict["protected"] is True
    # protected на верхнем уровне, не в config
    assert "protected" not in proc_dict["config"]


def test_protected_defaults_false() -> None:
    cfg = ProcessLaunchConfig(process_name="worker", process_class="m.W")
    _name, proc_dict = cfg.build()
    assert proc_dict["protected"] is False


def test_blueprint_protected_survives_model_validate() -> None:
    """gui: protected: true из base.yaml не теряется при model_validate → build."""
    bp = {
        "name": "base",
        "processes": [
            {"process_name": "gui", "protected": True, "process_class": "m.Gui", "plugins": []},
            {"process_name": "worker", "process_class": "m.W", "plugins": []},
        ],
    }
    sb = SystemBlueprint.model_validate(bp)
    by_name = {}
    for cfg in sb.build_configs():
        name, proc_dict = cfg.build()
        by_name[name] = proc_dict["protected"]
    assert by_name == {"gui": True, "worker": False}


def test_process_config_as_generic_passes_protected() -> None:
    pc = ProcessConfig(process_name="gui", protected=True, process_class="m.Gui")
    generic = pc.as_generic_config()
    assert generic.protected is True
