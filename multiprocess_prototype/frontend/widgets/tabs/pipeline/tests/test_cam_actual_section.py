# -*- coding: utf-8 -*-
"""Тесты CamActualSection — блок actual-телеметрии камеры (F.6).

Покрытие:
- show_for биндит 6 путей state store и показывает блок;
- hide_and_unbind / dispose снимают все подписки (баланс bind/unbind = 0);
- смена процесса перепривязывает без утечки (баланс сохраняется);
- разрешение собирается из раздельных width/height через общий _cam_res;
- без bindings блок не показывается и не падает.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.cam_actual_section import (
    CamActualSection,
)


class _FakeBindings:
    """Двойник GuiStateBindings: считает bind/unbind, хранит formatter'ы по пути."""

    def __init__(self) -> None:
        self.bind_count = 0
        self.unbind_count = 0
        self.live = 0
        self.formatters: dict[str, Any] = {}

    def bind(self, path: str, widget: Any, prop: str = "value", *, formatter: Any = None) -> tuple:
        self.bind_count += 1
        self.live += 1
        self.formatters[path] = formatter
        return ("handle", path, self.bind_count)

    def unbind(self, handle: Any) -> None:
        self.unbind_count += 1
        self.live -= 1


def test_show_for_binds_six_paths(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)

    section.show_for("camera_0")

    assert b.bind_count == 6
    base = "processes.camera_0.state.cam.actual"
    for suffix in ("fps", "exposure", "gain", "fourcc", "width", "height"):
        assert f"{base}.{suffix}" in b.formatters
    assert not section.isHidden()


def test_hide_and_unbind_balances(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    section.hide_and_unbind()

    assert b.unbind_count == b.bind_count
    assert b.live == 0
    assert section._handles == []
    assert section.isHidden()


def test_dispose_balances_and_idempotent(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    section.dispose()
    assert b.live == 0
    unbound_after_first = b.unbind_count

    section.dispose()  # идемпотентно — лишних unbind нет
    assert b.unbind_count == unbound_after_first


def test_reshow_does_not_leak(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)

    section.show_for("camera_0")
    section.show_for("camera_1")  # смена процесса: старые сняты, новые навешены

    assert b.live == 6  # только текущие живы
    assert b.unbind_count == 6  # предыдущие 6 сняты


def test_resolution_combines_width_and_height(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    base = "processes.camera_0.state.cam.actual"
    width_fmt = b.formatters[f"{base}.width"]
    height_fmt = b.formatters[f"{base}.height"]
    width_fmt(1920)
    result = height_fmt(1080)
    assert result == "1920×1080"


def test_no_bindings_is_noop(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    # Без set_bindings — show_for не показывает блок и не падает.
    section.show_for("camera_0")
    assert section.isHidden()
    assert section._handles == []
    section.dispose()  # тоже не падает
