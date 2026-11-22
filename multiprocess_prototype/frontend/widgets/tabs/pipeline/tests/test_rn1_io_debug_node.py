"""RN1 — слепой RED-тест: ``IoDebugSection._replay_cached`` на НАСТОЯЩЕЙ ``TelemetryViewModel``.

Контракт по брифу ``plans/2026-10-27_system-run-state/tasks/RN1.md`` (О2, DESIGN 4, ЛИТЕРАЛЫ io_debug):
узел ``…io_peek`` в настоящей модели — листья, ``get(path)`` -> ``None`` (регресс П3);
секция обязана читать узел через ``get_node`` и отрисовать «обработка».
Фейк read-model с ``get`` (``test_io_debug_section.py``) этот регресс скрывает, поэтому здесь — настоящая VM.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import (  # noqa: E402
    TelemetryViewModel,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.io_debug_section import (  # noqa: E402
    IoDebugSection,
)

_PATH = "processes.draw.plugins.overlay_draw.io_peek"


class _Bindings:
    """Минимальные bindings: fan-out подписки + настоящая VM как ``read_model``."""

    def __init__(self, read_model: TelemetryViewModel) -> None:
        self.read_model = read_model
        self.fanouts: list = []

    def bind_fanout(self, pattern, callback, owner=None):
        self.fanouts.append((pattern, callback))


def _peek(method: str = "process", ts: float = 1.0, in_count: int = 1) -> dict:
    return {
        "method": method,
        "ts": ts,
        "input": {"count": in_count, "items": [{"detections": {"_type": "list", "len": 2}}]},
        "output": {"count": 1, "items": [{"overlay": {"vlines": 1}}]},
    }


def test_replay_cached_renders_node_from_leaves_on_real_view_model(qtbot) -> None:
    """Свойство: узел ``io_peek``, пришедший ДО открытия ноды, проигрывается при ``set_target``
    с настоящей VM (хранит листья): в ``section._status.text()`` есть «обработка».

    Убивает мутантов: (а) ``get_node`` -> ``return self._model.get(...)`` (VM отдаёт ``None``);
    (б) ``_replay_cached`` возвращён на ``read_model.get(path)`` (виджет остаётся «нет данных»).
    """
    vm = TelemetryViewModel()
    vm.on_state_delta({"data_type": "state_delta", "path": _PATH, "value": _peek(method="process"), "deleted": False})
    assert vm.get(_PATH) is None  # предпосылка: настоящая VM хранит листья, узел как значение не отдаёт

    section = IoDebugSection(_Bindings(vm))
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")

    assert "обработка" in section._status.text()


def test_replay_cached_renders_input_and_output_from_node_leaves(qtbot) -> None:
    """Свойство: из собранного узла отрисованы ОБА окна — вход и выход (не только статус).

    Убивает мутанта: ``_replay_cached`` отдаёт в ``_render`` частичный узел (только верхние листья).
    Ожидания «detections»/«overlay» — те же подстроки, что в ``test_renders_only_active_path``.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta({"data_type": "state_delta", "path": _PATH, "value": _peek(method="process"), "deleted": False})

    section = IoDebugSection(_Bindings(vm))
    qtbot.addWidget(section)
    section.set_target("draw", "overlay_draw")

    assert "detections" in section._input_text.text()
    assert "overlay" in section._output_text.text()
