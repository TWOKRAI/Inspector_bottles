# -*- coding: utf-8 -*-
"""Тесты InterfaceSection — кнопка «Обновить UI» через request_ui_restart callback (G.5.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.settings.interface.section import (
    InterfaceSection,
)


def test_rebuild_invokes_callback(qtbot) -> None:
    """Клик «Обновить UI» вызывает injected request_ui_restart callback."""
    cb = MagicMock()
    section = InterfaceSection(request_ui_restart=cb)
    qtbot.addWidget(section)

    section._btn_rebuild.click()

    cb.assert_called_once_with()


def test_rebuild_none_is_noop(qtbot) -> None:
    """request_ui_restart=None — клик не падает (graceful no-op)."""
    section = InterfaceSection(request_ui_restart=None)
    qtbot.addWidget(section)

    # Не должно бросить исключение
    section._btn_rebuild.click()


def test_section_protocol_identifiers(qtbot) -> None:
    """key/title секции соответствуют SectionProtocol."""
    section = InterfaceSection()
    qtbot.addWidget(section)

    assert section.key == "interface_settings"
    assert section.title == "Настройка интерфейса"
    assert section.widget() is section
    assert section.action_buttons() == []


def test_fullscreen_button_toggles_window(qtbot) -> None:
    """Клик «На весь экран» переключает полноэкранный режим окна и подпись кнопки."""
    section = InterfaceSection()
    qtbot.addWidget(section)
    section.show()
    qtbot.waitExposed(section)

    window = section.window()
    assert not window.isFullScreen()
    assert section._btn_fullscreen.text() == "На весь экран"

    section._btn_fullscreen.click()
    assert window.isFullScreen()
    assert section._btn_fullscreen.text() == "Свернуть из полноэкранного"

    section._btn_fullscreen.click()
    assert not window.isFullScreen()
    assert section._btn_fullscreen.text() == "На весь экран"
