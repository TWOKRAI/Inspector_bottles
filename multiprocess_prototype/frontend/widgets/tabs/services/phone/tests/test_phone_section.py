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


def test_presenter_no_bridge_is_noop():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.presenter import (
        PhoneServicePresenter,
    )

    presenter = PhoneServicePresenter(bridge=None)
    assert presenter.start_server() is False
    assert presenter.stop_server() is False


def test_widget_observation_only(qtbot):
    """Виджет наблюдения строится (QApplication) и НЕ содержит пульта сигналов."""
    from multiprocess_prototype.frontend.widgets.tabs.services.phone.widget import (
        PhoneServiceWidget,
    )

    w = PhoneServiceWidget()
    qtbot.addWidget(w)
    # Пульт убран: ни сигнала запроса, ни полей/методов эмита.
    assert not hasattr(w, "signal_requested")
    assert not hasattr(w, "_emit_coords")
    assert not hasattr(w, "_coord_x")


def test_build_phone_section_spec():
    from multiprocess_prototype.frontend.widgets.tabs.services.phone import (
        build_phone_section,
    )

    spec = build_phone_section(services=object(), runtime=object(), title="Телефон")
    assert spec.key == "__phone__"
    assert spec.title == "Телефон"
