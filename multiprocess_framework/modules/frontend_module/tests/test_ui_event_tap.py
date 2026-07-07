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


# ---------------------------------------------------------------------------
# Debug-plane v1: уровень «намерение» (CommandSenderTap) + sources в подписке
# ---------------------------------------------------------------------------


class _FakeCommandSender:
    """Дверь GUI→бэкенд: записывает реальные отправки (проверка прозрачности тапа)."""

    def __init__(self) -> None:
        self.sent: List[tuple] = []

    def send_command(self, target_process, command, args=None):
        self.sent.append(("cmd", target_process, command, args))

    def send_system_command(self, command):
        self.sent.append(("sys", command))


class TestCommandSenderTap:
    def test_wraps_and_emits_then_delegates(self) -> None:
        from multiprocess_framework.modules.frontend_module.debug import CommandSenderTap

        sender = _FakeCommandSender()
        events: List[Dict[str, Any]] = []
        tap = CommandSenderTap(sender, events.append)
        tap.install()

        sender.send_command("preprocessor", "register_update", {"register": "resize", "field": "target_width", "value": 512})
        sender.send_system_command({"cmd": "process.start", "process_name": "camera"})

        # события эмитятся
        assert [e["kind"] for e in events] == ["command", "system_command"]
        assert events[0]["target"] == "preprocessor"
        assert events[0]["command"] == "register_update"
        assert events[0]["args"]["value"] == 512
        # прод-путь прозрачен: команды реально ушли
        assert sender.sent[0][:3] == ("cmd", "preprocessor", "register_update")
        assert sender.sent[1] == ("sys", {"cmd": "process.start", "process_name": "camera"})

    def test_remove_restores_originals(self) -> None:
        from multiprocess_framework.modules.frontend_module.debug import CommandSenderTap

        sender = _FakeCommandSender()
        events: List[Dict[str, Any]] = []
        tap = CommandSenderTap(sender, events.append)
        tap.install()
        tap.remove()
        sender.send_command("x", "y")
        assert events == []  # перехват снят
        assert sender.sent  # команда ушла

    def test_emit_error_does_not_block_command(self) -> None:
        from multiprocess_framework.modules.frontend_module.debug import CommandSenderTap

        sender = _FakeCommandSender()

        def boom(_e):
            raise RuntimeError("доставка упала")

        CommandSenderTap(sender, boom).install()
        sender.send_command("x", "y")  # не должно бросить
        assert sender.sent  # прод-путь важнее отладки

    def test_install_idempotent(self) -> None:
        from multiprocess_framework.modules.frontend_module.debug import CommandSenderTap

        sender = _FakeCommandSender()
        events: List[Dict[str, Any]] = []
        tap = CommandSenderTap(sender, events.append)
        tap.install()
        tap.install()  # повторный — no-op, не двойная обёртка
        sender.send_command("x", "y")
        assert len(events) == 1

    def test_long_args_truncated(self) -> None:
        from multiprocess_framework.modules.frontend_module.debug import CommandSenderTap

        sender = _FakeCommandSender()
        events: List[Dict[str, Any]] = []
        CommandSenderTap(sender, events.append).install()
        sender.send_command("x", "y", {"blob": "A" * 1000})
        assert len(events[0]["args"]["blob"]) < 250  # обрезано, поток не раздувается


class TestSubscribeSources:
    def _setup(self, qapp, with_sender: bool = True):
        services = _FakeServices()
        tap = UiEventTap(qapp)
        sender = _FakeCommandSender() if with_sender else None
        assert register_ui_tap_commands(services, lambda: tap, lambda: sender) is True
        return services, tap, sender, _registered_handlers(services)

    def test_default_sources_include_command_gate(self, qapp) -> None:
        services, tap, sender, handlers = self._setup(qapp)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        assert set(res["sources"]) == {"gesture", "command"}
        # дверь перехвачена: send_command порождает ui.event kind=command с seq
        sender.send_command("preprocessor", "introspect.status")
        msg = services.router_manager.sent[-1]
        assert msg["command"] == "ui.event"
        assert msg["data"]["record"]["kind"] == "command"
        assert msg["data"]["record"]["seq"] >= 1

    def test_unsubscribe_removes_command_gate(self, qapp) -> None:
        services, tap, sender, handlers = self._setup(qapp)
        handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        handlers["ui.tap.unsubscribe"]({})
        n = len(services.router_manager.sent)
        sender.send_command("x", "y")
        assert len(services.router_manager.sent) == n  # перехват снят

    def test_gesture_only_when_requested(self, qapp) -> None:
        services, tap, sender, handlers = self._setup(qapp)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl", "sources": ["gesture"]})
        assert res["sources"] == ["gesture"]
        sender.send_command("x", "y")
        assert services.router_manager.sent == []  # дверь не перехвачена

    def test_no_sender_degrades_to_gesture(self, qapp) -> None:
        _, _, _, handlers = self._setup(qapp, with_sender=False)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl"})
        assert res["sources"] == ["gesture"]  # честно: намерение недоступно

    def test_unknown_source_fails_loud(self, qapp) -> None:
        _, _, _, handlers = self._setup(qapp)
        res = handlers["ui.tap.subscribe"]({"subscriber": "backend_ctl", "sources": ["telepathy"]})
        assert res["success"] is False
