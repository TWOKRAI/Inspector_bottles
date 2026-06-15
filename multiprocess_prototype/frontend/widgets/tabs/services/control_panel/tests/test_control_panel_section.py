"""Тесты секции «Пульт» — presenter (operate/add/remove) + виджет + SectionSpec."""

from __future__ import annotations


class _FakeBridge:
    """Записывает on_action_command."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def on_action_command(self, plugin: str, command: str, args: dict) -> bool:
        self.calls.append((plugin, command, args))
        return True


class _FakeCommands:
    def __init__(self) -> None:
        self.dispatched: list = []

    def dispatch(self, cmd, **kwargs) -> None:
        self.dispatched.append(cmd)


class _FakeServices:
    def __init__(self) -> None:
        self.commands = _FakeCommands()


def test_operate_routes_to_set_control():
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
        ControlPanelPresenter,
    )

    bridge = _FakeBridge()
    p = ControlPanelPresenter(bridge=bridge, services=None)
    assert p.operate("spd", 42.0) is True
    assert bridge.calls == [("control_panel", "set_control", {"id": "spd", "value": 42.0})]


def test_add_routes_command_and_persists():
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
        ControlPanelPresenter,
    )
    from multiprocess_prototype.domain.commands import SetPluginConfig

    bridge = _FakeBridge()
    services = _FakeServices()
    p = ControlPanelPresenter(bridge=bridge, services=services)
    spec = {"id": "go", "type": "button", "port": "out_1"}
    new_controls = [spec]
    assert p.add(spec, "pult", 0, new_controls) is True
    # live-команда
    assert bridge.calls == [("control_panel", "add_control", {"spec": spec})]
    # персист в рецепт через SetPluginConfig(field="controls")
    assert len(services.commands.dispatched) == 1
    cmd = services.commands.dispatched[0]
    assert isinstance(cmd, SetPluginConfig)
    assert cmd.process_name == "pult"
    assert cmd.field == "controls"
    assert cmd.value == new_controls


def test_remove_routes_command_and_persists():
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
        ControlPanelPresenter,
    )

    bridge = _FakeBridge()
    services = _FakeServices()
    p = ControlPanelPresenter(bridge=bridge, services=services)
    assert p.remove("go", "pult", 0, []) is True
    assert bridge.calls == [("control_panel", "remove_control", {"id": "go"})]
    assert services.commands.dispatched[0].value == []


def test_no_bridge_and_no_services_is_safe():
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
        ControlPanelPresenter,
    )

    p = ControlPanelPresenter(bridge=None, services=None)
    assert p.operate("x", 1) is False
    # add без services не падает (персист пропущен), команда без bridge → False
    assert p.add({"id": "a"}, "", 0, []) is False


def test_widget_renders_controls_and_emits_add(qtbot):
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.widget import (
        ControlPanelWidget,
    )

    w = ControlPanelWidget()
    qtbot.addWidget(w)
    w.set_controls(
        [
            {"id": "go", "type": "button", "label": "Старт", "port": "out_1"},
            {"id": "spd", "type": "slider", "label": "Скорость", "port": "out_2", "min": 0, "max": 10, "value": 3},
        ]
    )
    assert {c["id"] for c in w.current_controls()} == {"go", "spd"}

    captured: list[dict] = []
    w.control_add_requested.connect(lambda spec: captured.append(spec))
    w._add_type.setCurrentText("Тумблер")
    w._add_label.setText("Свет")
    w._add_port.setCurrentText("out_3")
    w._on_add_clicked()
    assert len(captured) == 1
    assert captured[0]["type"] == "toggle"
    assert captured[0]["label"] == "Свет"
    assert captured[0]["port"] == "out_3"
    assert captured[0]["id"]  # сгенерирован


def test_widget_button_operate_emits(qtbot):
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.widget import (
        ControlPanelWidget,
    )

    w = ControlPanelWidget()
    qtbot.addWidget(w)
    captured: list[tuple[str, object]] = []
    w.control_operated.connect(lambda cid, val: captured.append((cid, val)))
    w.set_controls([{"id": "go", "type": "button", "label": "Старт", "port": "out_1"}])
    # найти кнопку «Нажать» в ряду и кликнуть
    from PySide6.QtWidgets import QPushButton

    buttons = [b for b in w.findChildren(QPushButton) if b.text() == "Нажать"]
    assert buttons
    buttons[0].click()
    assert captured == [("go", True)]


def test_build_section_spec():
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel import (
        build_control_panel_section,
    )

    spec = build_control_panel_section(services=object(), runtime=object(), title="Пульт")
    assert spec.key == "__control_panel__"
    assert spec.title == "Пульт"


def test_section_implements_protocol_surface(qtbot):
    """Регрессия: секция реализует всю поверхность, что зовёт base_tree_nav_tab.

    _attach_section() при сборке Services-таба вызывает action_buttons() — без него
    весь таб падал «Ошибка загрузки» (поймано qt-mcp smoke, не unit-тестами спеки).
    """
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel import (
        build_control_panel_section,
    )

    spec = build_control_panel_section(services=object(), runtime=object(), title="Пульт")
    section = spec.factory(None)
    # Обязательная поверхность SectionProtocol.
    assert section.key == "__control_panel__"
    assert section.title == "Пульт"
    assert section.action_buttons() == []  # пульт без кнопок action-колонки
    w = section.widget()  # строит виджет (bindings=None при runtime=object())
    qtbot.addWidget(w)
    section.on_activated()
    section.on_deactivated()
