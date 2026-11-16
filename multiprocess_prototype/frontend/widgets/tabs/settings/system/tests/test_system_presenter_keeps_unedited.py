# -*- coding: utf-8 -*-
"""Hazard Task 2.1 (ревью M1): ``save()`` не должен затирать поля, у которых нет редакторов.

Редакторы есть у пяти секций (system/camera/processing/display/storage). ``run_gate`` и
``shutdown.pre_stop`` их не имеют: если ``save()`` валидирует dict только из редакторов, эти поля берут
умолчания схемы и стираются в боевом system.yaml. Тест идёт настоящими load/save на tmp-файле.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from unittest.mock import patch

import yaml

from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.widgets.tabs.settings import yaml_io
from multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter import SystemSettingsPresenter
from multiprocess_prototype.frontend.widgets.tabs.settings.system.tests.test_system_presenter import MockSystemView

_MODULE = "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
_PRE_STOP = [{"target": "devices", "command": "robot_home", "args": {"device_id": "robot_main"}, "timeout_s": 3.0}]


def test_save_keeps_run_gate_and_pre_stop_not_covered_by_editors(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(
        yaml.safe_dump(
            {"run_gate": True, "system": {"stop_timeout": 5.0}, "shutdown": {"pre_stop": _PRE_STOP}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    view = MockSystemView()
    view.editor_values = {"system.stop_timeout": 7.5, "camera.fps": 30}  # редактор правит ТОЛЬКО свои поля

    with (
        patch(f"{_MODULE}.load_settings", partial(yaml_io.load_settings, path)),
        patch(f"{_MODULE}.save_settings", partial(_save_to, path)),
    ):
        presenter = SystemSettingsPresenter(view=view, rm=None, ui=None, services=make_test_app_services())
        assert presenter._cfg.run_gate is True  # предусловие: конфиг загружен с гейтом
        assert presenter.save() is True

    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert after["run_gate"] is True
    assert after["shutdown"]["pre_stop"] == _PRE_STOP
    # правка редактора при этом дошла до файла
    assert after["system"]["stop_timeout"] == 7.5
    assert after["camera"]["fps"] == 30


def _save_to(path: Path, cfg) -> None:
    yaml_io.save_settings(cfg, path)
