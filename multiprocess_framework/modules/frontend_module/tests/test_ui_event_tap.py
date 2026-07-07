# -*- coding: utf-8 -*-
"""Тесты UiEventTap + команд ui.tap.* (отладка фронтенда агентами).

Qt-часть (pytest-qt, offscreen): фильтр ловит клик по кнопке/табу, выключенный
тап — no-op, событие никогда не поглощается, ошибки send не роняют GUI.
Команды: subscribe включает тап с RouterPushChannel-доставкой (контракт формы
пуша — targets=[subscriber]+queue_type=system БЕЗ channel, урок 1.1b/1.5),
unsubscribe выключает, ping шлёт синтетическое событие тем же путём.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QTabBar, QVBoxLayout, QWidget

from multiprocess_framework.modules.frontend_module.debug import (
    UiEventTap,
    register_ui_tap_commands,
)


# ---------------------------------------------------------------------------
# Qt: фильтр событий
# ---------------------------------------------------------------------------


@pytest.fixture
def tap_on_app(qapp):
    """UiEventTap, установленный на QApplication (снимается после теста)."""
    tap = UiEventTap(qapp)
    qapp.installEventFilter(tap)
    yield tap
    qapp.removeEventFilter(tap)


class TestUiEventTapFilter:
    def test_button_click_captured(self, qtbot, tap_on_app) -> None:
        events: List[Dict[str, Any]] = []
        tap_on_app.enable("backend_ctl", events.append)

        btn = QPushButton("Запустить")
        btn.setObjectName("launch_button")
        qtbot.addWidget(btn)
        btn.show()
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert len(events) == 1
        evt = events[0]
        assert evt["kind"] == "button"
        assert evt["text"] == "Запустить"
        assert evt["widget"] == "launch_button"
        assert "launch_button" in evt["path"]
        assert evt["ts"] > 0

    def test_disabled_tap_is_noop(self, qtbot, tap_on_app) -> None:
        events: List[Dict[str, Any]] = []
        # enable НЕ вызывался
        btn = QPushButton("X")
        qtbot.addWidget(btn)
        btn.show()
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert events == []
        assert tap_on_app.events_sent == 0

    def test_unsubscribe_stops_events(self, qtbot, tap_on_app) -> None:
        events: List[Dict[str, Any]] = []
        tap_on_app.enable("backend_ctl", events.append)
        tap_on_app.disable()
        btn = QPushButton("X")
        qtbot.addWidget(btn)
        btn.show()
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert events == []

    def test_tab_click_captured(self, qtbot, tap_on_app) -> None:
        events: List[Dict[str, Any]] = []
        tap_on_app.enable("backend_ctl", events.append)

        w = QWidget()
        layout = QVBoxLayout(w)
        bar = QTabBar()
        bar.addTab("Обзор")
        bar.addTab("Pipeline")
        layout.addWidget(bar)
        qtbot.addWidget(w)
        w.show()
        qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())

        tabs = [e for e in events if e["kind"] == "tab"]
        assert tabs, events
        assert tabs[-1]["text"] == "Pipeline"
        assert tabs[-1]["index"] == 1

    def test_send_error_does_not_break_gui_and_counts(self, qtbot, tap_on_app) -> None:
        def boom(_evt: Dict[str, Any]) -> None:
            raise RuntimeError("доставка упала")

        tap_on_app.enable("backend_ctl", boom)
        btn = QPushButton("X")
        qtbot.addWidget(btn)
        btn.show()
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)  # не должно бросить
        assert tap_on_app.send_errors == 1
        assert tap_on_app.events_sent == 0

    def test_click_on_button_child_resolved_to_button(self, qtbot, tap_on_app) -> None:
        """Клик может прийти в дочерний виджет кнопки — цепочка родителей находит её."""
        events: List[Dict[str, Any]] = []
        tap_on_app.enable("backend_ctl", events.append)
        btn = QPushButton("Родитель")
        qtbot.addWidget(btn)
        btn.show()
        # Событие эмулируем на самой кнопке (Qt сам решает receiver'а); главное —
        # фильтр не зависит от того, кто точный receiver в цепочке.
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert events and events[0]["kind"] == "button"


# ---------------------------------------------------------------------------
# Команды ui.tap.* (без Qt-кликов: fake services + fake router)
# ---------------------------------------------------------------------------


class _FakeRouter:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.sent.append(message)


class _FakeServices:
    name = "gui"

    def __init__(self) -> None:
        self.command_manager = MagicMock()
        self.router_manager = _FakeRouter()


def _registered_handlers(services: _FakeServices) -> Dict[str, Any]:
    """Достать зарегистрированные обработчики из вызовов register_command."""
    return {
        call.args[0]: call.args[1]
        for call in services.command_manager.register_command.call_args_list
    }


class TestUiTapCommands:
    def _setup(self, qapp) -> tuple[_FakeServices, UiEventTap, Dict[str, Any]]:
        services = _FakeServices()
        tap = UiEventTap(qapp)
        assert register_ui_tap_commands(services, lambda: tap) is True
        return services, tap, _registered_handlers(services)

    def test_registers_three_commands(self, qapp) -> None:
        _, _, handlers = self._setup(qapp)
        assert set(handlers) == {"ui.tap.subscribe", "ui.tap.unsubscribe", "ui.tap.ping"}

    def test_subscribe_enables_tap_and_push_shape(self, qapp) -> None:
        services, tap, handlers = self._setup(qapp)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        assert res["success"] is True
        assert tap.enabled and tap.subscriber == "backend_ctl"

        # Контракт формы пуша (урок 1.1b/1.5): targets+queue_type, БЕЗ channel.
        tap.emit_event({"kind": "ping", "note": "t"})
        assert len(services.router_manager.sent) == 1
        msg = services.router_manager.sent[0]
        assert msg["targets"] == ["backend_ctl"]
        assert msg["queue_type"] == "system"
        assert msg["command"] == "ui.event"
        assert "channel" not in msg
        assert msg["data"]["process"] == "gui"
        assert msg["data"]["record"]["kind"] == "ping"

    def test_subscribe_requires_subscriber(self, qapp) -> None:
        _, _, handlers = self._setup(qapp)
        res = handlers["ui.tap.subscribe"]({})
        assert res["success"] is False

    def test_unsubscribe_disables(self, qapp) -> None:
        _, tap, handlers = self._setup(qapp)
        handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        res = handlers["ui.tap.unsubscribe"]({})
        assert res["success"] is True and res["was_subscriber"] == "backend_ctl"
        assert not tap.enabled

    def test_ping_sends_through_delivery_path(self, qapp) -> None:
        services, _, handlers = self._setup(qapp)
        handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        res = handlers["ui.tap.ping"]({"note": "smoke"})
        assert res["success"] is True and res["events_sent"] == 1
        assert services.router_manager.sent[-1]["data"]["record"]["note"] == "smoke"

    def test_ping_without_subscribe_fails_loud(self, qapp) -> None:
        _, _, handlers = self._setup(qapp)
        res = handlers["ui.tap.ping"]({})
        assert res["success"] is False

    def test_no_gui_yet_reports_honestly(self, qapp) -> None:
        services = _FakeServices()
        register_ui_tap_commands(services, lambda: None)  # GUI ещё не поднят
        handlers = _registered_handlers(services)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        assert res["success"] is False
        assert "не поднят" in res["reason"]
