# -*- coding: utf-8 -*-
"""Совместимость секций SettingsTab с SectionProtocol фреймворка.

Перенесено из ``frontend_module/tests/test_section_spec.py`` (frontend-constructor
Ф1, T1.4): frontend_module/tests не должен зависеть от multiprocess_prototype
(инверсия слоёв) — модуль фреймворка не может знать о прикладном коде.
"""

from __future__ import annotations

import pytest


def test_existing_settings_sections_satisfy_section_protocol() -> None:
    """SystemSection / AppearanceSection / HistorySection остаются валидными.

    Это критично: расширение `SectionProtocol` опциональным mixin'ом
    (`SectionWithEvents`) во frontend_module не должно ломать существующие
    реализации секций прототипа.
    """
    # Эти импорты требуют PySide6 (секции — QWidget'ы), но Protocol-проверка
    # выполняется без инстанцирования виджетов.
    pytest.importorskip("PySide6")

    from multiprocess_prototype.frontend.widgets.tabs.settings.system import (
        SystemSection,
    )
    from multiprocess_prototype.frontend.widgets.tabs.settings.appearance import (
        AppearanceSection,
    )
    from multiprocess_prototype.frontend.widgets.tabs.settings.history import (
        HistorySection,
    )

    # У классов должны быть обязательные методы SectionProtocol
    for cls in (SystemSection, AppearanceSection, HistorySection):
        assert hasattr(cls, "key")
        assert hasattr(cls, "title")
        assert hasattr(cls, "widget")
        assert hasattr(cls, "action_buttons")
        assert hasattr(cls, "on_activated")
        assert hasattr(cls, "on_deactivated")
