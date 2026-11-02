# -*- coding: utf-8 -*-
"""Проводка Task 1.10 (C-30): настоящая ``_CameraSection`` берёт ``commands`` из services, ``save_active`` из runtime.

Без ``getattr(services, "commands", None)`` и ``getattr(runtime, "save_active_topology", None)`` в ``section.py``
кнопка «Сохранить» камеры не доходит ни до редактора, ни до ``_save_active_topology`` (ACC 12). Секция, виджет,
презентер, диспетчер, стор и файл рецепта — настоящие (обвязка из ``test_camera_save_blind``); подменён только
метод ``widget.set_status``: он записывает показанные тексты
(``_status`` приватный, ``set_status("")`` текст не стирает).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from multiprocess_prototype.frontend.widgets.tabs.services.camera.tests.test_camera_save_blind import (
    CONFLICT_TEXT,
    CountingCall,
    Rig,
    make_rig,
)

_SAVED = "Сохранено в активный рецепт."
_NOT_SAVED = "Не удалось сохранить (нет активного рецепта или изменений)."


def _conflict() -> bool:
    raise RuntimeError(CONFLICT_TEXT)


def _press_save(qtbot: Any, rig: Rig, runtime_kwargs: dict[str, Any]) -> list[str]:
    """Секция на настоящем RuntimeDeps; param_changed("brightness", 50) + save_clicked; вернуть показанные статусы."""
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
    from multiprocess_prototype.frontend.widgets.tabs.services.camera.section import _CameraSection

    services = SimpleNamespace(recipes=rig.store, topology=rig.repo, commands=rig.commands)
    section = _CameraSection(services, RuntimeDeps(**runtime_kwargs))
    widget = section.widget()
    qtbot.addWidget(widget)
    statuses: list[str] = []
    widget.set_status = statuses.append  # type: ignore[method-assign]

    widget.param_changed.emit("brightness", 50)
    widget.save_clicked.emit()
    return statuses


def test_acc12_save_clicked_reports_saved(qtbot, tmp_path: Path) -> None:
    """ACC 12: save_active_topology в RuntimeDeps -> вызван 1 раз, статус «Сохранено в активный рецепт.»."""
    rig = make_rig(tmp_path)

    statuses = _press_save(qtbot, rig, {"save_active_topology": rig.save_active})

    assert rig.save_active.calls == 1
    assert statuses[-1] == _SAVED
    assert rig.commands.set_plugin_configs() == [("camera_0", 0, "params")]  # путь секция -> редактор достигнут
    assert b"brightness: 50" in rig.path.read_bytes()  # и запись дошла до файла


def test_acc12_save_clicked_conflict_text_in_status(qtbot, tmp_path: Path) -> None:
    """ACC 12: save_active бросает RuntimeError(конфликт) -> статус = текст исключения."""
    rig = make_rig(tmp_path)
    failing = CountingCall(_conflict)

    statuses = _press_save(qtbot, rig, {"save_active_topology": failing})

    assert failing.calls == 1  # save_active достигнут: статус ниже — от него, а не от раннего выхода
    assert statuses[-1] == CONFLICT_TEXT


def test_acc12_save_clicked_without_save_active_reports_not_saved(qtbot, tmp_path: Path) -> None:
    """ACC 12: в RuntimeDeps нет save_active_topology -> ничего не записано, статус «Не удалось сохранить ...»."""
    rig = make_rig(tmp_path)

    statuses = _press_save(qtbot, rig, {})

    assert rig.save_active.calls == 0  # в секцию он не передан; парная проверка достижимости — в тестах выше
    assert statuses[-1] == _NOT_SAVED
    assert rig.path.read_bytes() == rig.src


def test_acc12_runtime_deps_default_is_none() -> None:
    """ACC 12: поле RuntimeDeps.save_active_topology есть и по умолчанию None."""
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps

    assert RuntimeDeps().save_active_topology is None
