# -*- coding: utf-8 -*-
"""Авторский hazard-тест доставки readback ДО секции (Task 4.2) — сшивка,
которую независимая приёмка (test_telemetry_controls_readback_catalogue.py)
проверить не могла: она конструирует секцию напрямую с dict-параметром
``readback`` и не видит ``_panels.py`` вовсе.

Держит ровно то, что называет резидуал в ``_telemetry_controls.py:11-15`` до
правки: путь readback от read-model (``TelemetryViewModel``) до секции —
``SingleProcessPanel._apply_telemetry_items`` замечает путь
``processes.<P>.telemetry.gated_metrics`` и зовёт ``apply_readback``. Без этого
теста правка `_telemetry_controls.py` могла бы быть верна изолированно и всё
равно не работать на живой панели — сшивку из отдельного юнит-теста секции не
увидеть.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter

from ._helpers import make_processes_services


def _presenter() -> ProcessesPresenter:
    return ProcessesPresenter(make_processes_services())


def _delta(path: str, value: object) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": False}


class TestPollerDeliveryReachesTheSection:
    def test_gated_metrics_delta_after_panel_is_open_adds_a_row(self, qtbot) -> None:
        """Живой случай: карточка процесса уже открыта (импортный фолбэк уже
        нарисован), а readback приходит ПОЗЖЕ — точно так, как TelemetryPoller
        вливает ``processes.<P>.telemetry.gated_metrics`` в VM ПОСЛЕ первого
        успешного ответа ``introspect.telemetry``."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), bindings=None, process_name="camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        from PySide6.QtWidgets import QLabel

        before = {lbl.text() for lbl in panel._telemetry_controls.findChildren(QLabel)}
        assert "backend_only_metric" not in before  # резидуал воспроизведён: строки ещё нет

        vm.on_state_delta(_delta("processes.camera_0.telemetry.gated_metrics", ["fps", "backend_only_metric"]))
        qtbot.wait(10)  # коалесинг-таймер VM (0 мс, singleShot) — дать циклу событий сработать

        after = {lbl.text() for lbl in panel._telemetry_controls.findChildren(QLabel)}
        assert "backend_only_metric" in after, "readback долетел до VM, но строка в панели не появилась"

    def test_gated_metrics_delta_for_a_different_process_is_ignored(self, qtbot) -> None:
        """Путь читается ТОЧНО по имени своего процесса — чужой readback
        (другая карточка того же VM) не должен утекать в эту секцию."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), bindings=None, process_name="camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        from PySide6.QtWidgets import QLabel

        vm.on_state_delta(_delta("processes.OTHER_PROCESS.telemetry.gated_metrics", ["alien_metric"]))
        qtbot.wait(10)

        texts = {lbl.text() for lbl in panel._telemetry_controls.findChildren(QLabel)}
        assert "alien_metric" not in texts

    def test_malformed_gated_metrics_value_does_not_break_the_rest_of_the_batch(self, qtbot) -> None:
        """Мусорное значение по правильному пути (не dict-совместимая форма,
        которую ждёт ``apply_readback`` через обёртку ``{"gated_metrics": value}``)
        не должно ронять обработку остальной пачки — соседний сеттер (fps)
        обязан отработать как обычно."""
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), bindings=None, process_name="camera_0", telemetry=vm)
        qtbot.addWidget(panel)

        vm.on_state_delta(_delta("processes.camera_0.telemetry.gated_metrics", "not-a-list"))
        vm.on_state_delta(_delta("processes.camera_0.state.fps", 42.0))
        qtbot.wait(10)

        # Секция жива, читаемый статус fps применился (панель не упала на мусоре).
        assert panel._telemetry_controls._rows["fps"].readout.text() == "42.0"
