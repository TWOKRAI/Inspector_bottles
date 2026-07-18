"""Тесты IoDebugSection — панель I/O-отладки плагина (Этап 5 фронтенд).

Покрытие:
- set_bindings вешает один fan-out на io_peek (идемпотентно);
- рендерит снимок ТОЛЬКО активного пути (фильтр чужих плагинов);
- «Заморозить» останавливает обновление, «Возобновить» — продолжает;
- сворачивание тела по кнопке-заголовку;
- clear_target усыпляет секцию.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.io_debug_section import (
    IoDebugSection,
)


class _FakeReadModel:
    """Двойник read-model: get(path) из кэша (io_debug replay читает его)."""

    def __init__(self, cache: dict):
        self._cache = cache

    def get(self, path, default=None):
        return self._cache.get(path, default)


class _FakeBindings:
    """Двойник GuiStateBindings: хранит fan-out callbacks, умеет их дёргать."""

    def __init__(self):
        self.fanouts: list = []
        self._cache: dict = {}
        # io_debug реплеит через bindings.read_model.get(path).
        self.read_model = _FakeReadModel(self._cache)

    def bind_fanout(self, pattern, callback, owner=None):
        self.fanouts.append((pattern, callback))

    def emit(self, path, value):
        for _pattern, cb in self.fanouts:
            cb(path, value)


def _peek(method="process", ts=1.0, in_count=1):
    return {
        "method": method,
        "ts": ts,
        "input": {"count": in_count, "items": [{"detections": {"_type": "list", "len": 2}}]},
        "output": {"count": 1, "items": [{"overlay": {"vlines": 1}}]},
    }


def test_set_bindings_subscribes_once(qtbot):
    b = _FakeBindings()
    section = IoDebugSection()
    qtbot.addWidget(section)
    section.set_bindings(b)
    section.set_bindings(b)  # повторно — без дубля подписки
    assert len(b.fanouts) == 1
    assert b.fanouts[0][0] == "processes.*.plugins.*.io_peek"


def test_renders_only_active_path(qtbot):
    b = _FakeBindings()
    section = IoDebugSection(b)
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")

    # Чужой плагин — игнор.
    b.emit("processes.line.plugins.line_filter.io_peek", _peek(method="other"))
    assert "other" not in section._status.text()

    # Активный плагин — рендерится в два отдельных окна; статус читаемый (process→обработка).
    b.emit("processes.draw.plugins.overlay_draw.io_peek", _peek(method="process"))
    assert "обработка" in section._status.text()
    assert "detections" in section._input_text.text()  # вход
    assert "overlay" in section._output_text.text()  # выход


def test_freeze_stops_updates(qtbot):
    b = _FakeBindings()
    section = IoDebugSection(b)
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")
    path = "processes.draw.plugins.overlay_draw.io_peek"

    # Различаем обновления по счётчику входа (в статусе «вход: N»).
    b.emit(path, _peek(in_count=1))
    assert "вход: 1" in section._status.text()

    # Заморозить → следующая дельта не обновляет отображение.
    section._freeze_btn.setChecked(True)
    section._on_freeze(True)
    b.emit(path, _peek(in_count=5))
    assert "вход: 1" in section._status.text()  # осталось замороженным

    # Возобновить → снова обновляется.
    section._freeze_btn.setChecked(False)
    section._on_freeze(False)
    b.emit(path, _peek(in_count=9))
    assert "вход: 9" in section._status.text()


def test_source_input_placeholder(qtbot):
    """У источника (produce, input.items=None) — плейсхолдер вместо сырого null."""
    b = _FakeBindings()
    section = IoDebugSection(b)
    qtbot.addWidget(section)
    section.set_target("camera_0", "capture")
    peek = {
        "method": "produce",
        "ts": 1.0,
        "input": {"count": 0, "items": None},
        "output": {"count": 1, "items": [{"frame": {"_type": "ndarray"}}]},
    }
    b.emit("processes.camera_0.plugins.capture.io_peek", peek)
    assert "источник" in section._input_text.text()
    assert "вход" not in section._status.text()  # счётчик входа скрыт у источника
    assert "генерация" in section._status.text()


def test_toggle_shows_body(qtbot):
    section = IoDebugSection()
    qtbot.addWidget(section)
    # isVisibleTo(parent): намерение видимости без показа всей цепочки родителей.
    assert not section._body.isVisibleTo(section)
    section._toggle_btn.setChecked(True)
    section._on_toggle(True)
    assert section._body.isVisibleTo(section)


def test_clear_target_sleeps(qtbot):
    b = _FakeBindings()
    section = IoDebugSection(b)
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")
    section.clear_target()
    # После очистки активного пути дельты игнорируются.
    b.emit("processes.draw.plugins.overlay_draw.io_peek", _peek(method="process"))
    assert section._status.text() == "нет данных"


def test_replay_cached_on_set_target(qtbot):
    b = _FakeBindings()
    b._cache["processes.draw.plugins.overlay_draw.io_peek"] = _peek(method="cached")
    section = IoDebugSection(b)
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")
    # Кэш проигрывается сразу при привязке (нода открыта после дельты).
    assert "cached" in section._status.text()
