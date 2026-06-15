"""Тесты секции «Телефон» — presenter (toggle через bridge) + SectionSpec."""

from __future__ import annotations


class _FakeBridge:
    """Записывает вызовы on_action_command."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def on_action_command(self, plugin: str, command: str, args: dict) -> bool:
        self.calls.append((plugin, command, args))
        return True


def test_presenter_start_stop_route_to_phone_camera():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.presenter import (
        PhoneServicePresenter,
    )

    bridge = _FakeBridge()
    presenter = PhoneServicePresenter(bridge=bridge)

    assert presenter.start_server() is True
    assert presenter.stop_server() is True
    assert bridge.calls == [
        ("phone_camera", "start_server", {}),
        ("phone_camera", "stop_server", {}),
    ]


def test_presenter_emit_signal_routes_payload():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.presenter import (
        PhoneServicePresenter,
    )

    bridge = _FakeBridge()
    presenter = PhoneServicePresenter(bridge=bridge)
    assert presenter.emit_signal("signal_1", {"x_mm": 1.0, "y_mm": 2.0}) is True
    assert bridge.calls == [
        ("phone_camera", "emit_signal", {"port": "signal_1", "value": {"x_mm": 1.0, "y_mm": 2.0}}),
    ]


def test_presenter_no_bridge_is_noop():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.presenter import (
        PhoneServicePresenter,
    )

    presenter = PhoneServicePresenter(bridge=None)
    assert presenter.start_server() is False
    assert presenter.stop_server() is False


def test_widget_pult_emits_coords(qtbot):
    """Виджет строится (QApplication) и кнопка координат эмитит signal_requested."""
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.widget import (
        PhoneServiceWidget,
    )

    w = PhoneServiceWidget()
    qtbot.addWidget(w)
    w._coord_x.setText("12.5")
    w._coord_y.setText("34")
    captured: list[tuple[str, object]] = []
    w.signal_requested.connect(lambda port, val: captured.append((port, val)))
    w._emit_coords()
    assert captured == [("signal_1", {"x_mm": 12.5, "y_mm": 34.0})]


def test_widget_pult_emits_text(qtbot):
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.widget import (
        PhoneServiceWidget,
    )

    w = PhoneServiceWidget()
    qtbot.addWidget(w)
    w._signal_text.setText("ГАЙКА")
    captured: list[tuple[str, object]] = []
    w.signal_requested.connect(lambda port, val: captured.append((port, val)))
    w._emit_text()
    assert captured == [("signal_2", "ГАЙКА")]


def test_build_phone_section_spec():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone import (
        build_phone_section,
    )

    spec = build_phone_section(services=object(), runtime=object(), title="Телефон")
    assert spec.key == "__phone__"
    assert spec.title == "Телефон"
