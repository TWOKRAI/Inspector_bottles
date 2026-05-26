# -*- coding: utf-8 -*-
"""Интеграционные тесты кнопки «Тест» + sandbox-виджета в PluginsTab.

Покрывает:
- test_test_button_disabled_for_source     — capture (source) → кнопка disabled, tooltip непустой
- test_test_button_enabled_for_grayscale   — grayscale (processing) → кнопка enabled
- test_test_button_disabled_for_stitcher   — stitcher → кнопка disabled (multi-input)
- test_open_sandbox_switches_content       — клик «Тест» для grayscale → content_stack показывает PluginSandboxWidget
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import (
    _PluginSection,
)
from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
from multiprocess_prototype.frontend.widgets.tabs.plugins.tab import PluginsTab


# ---------------------------------------------------------------------------
# Вспомогательные моки (аналог test_plugins_tab.py)
# ---------------------------------------------------------------------------


class _MockEntry:
    """Mock для PluginEntry."""

    def __init__(
        self,
        name: str,
        category: str,
        description: str = "",
        register_classes: list | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.description = description
        self.register_classes = register_classes or []
        self.inputs = inputs or []
        self.outputs = outputs or []


class _MockRegistry:
    """Mock для PluginRegistry."""

    def __init__(self, entries: list[_MockEntry]) -> None:
        self._entries = entries

    def list(self) -> list[_MockEntry]:
        return self._entries

    def get(self, name: str) -> _MockEntry | None:
        return next((e for e in self._entries if e.name == name), None)

    def filter(self, category: str | None = None) -> list[_MockEntry]:
        if category:
            return [e for e in self._entries if e.category == category]
        return self._entries


def _make_mock_ctx(entries: list[_MockEntry] | None = None) -> MagicMock:
    """Собрать минимальный mock AppContext с нужными плагинами."""
    if entries is None:
        entries = [
            _MockEntry("grayscale", "processing", "Чёрно-белое"),
            _MockEntry("capture", "source", "Захват камеры"),
            _MockEntry("stitcher", "processing", "Сшивка кадров"),
        ]

    registry = _MockRegistry(entries)

    ctx = MagicMock()
    ctx.plugin_registry.return_value = registry
    ctx.registers_manager.return_value = None
    ctx.config = {}
    ctx.extras = {}
    ctx.bindings.return_value = None
    ctx.action_bus.return_value = None
    ctx.form_context.return_value = None
    # service_registry = None → кнопка webcam disabled, не падает
    ctx.service_registry.return_value = None
    return ctx


# ---------------------------------------------------------------------------
# Вспомогательная функция: получить action-кнопки из секции
# ---------------------------------------------------------------------------


def _get_test_button(ctx: MagicMock, plugin_name: str, open_sandbox_cb=None):
    """Создать _PluginSection и вернуть первую кнопку из action_buttons()."""
    section = _PluginSection(ctx, plugin_name, plugin_name, open_sandbox_cb=open_sandbox_cb)
    buttons = section.action_buttons()
    assert len(buttons) == 1, f"Ожидали 1 кнопку, получили {len(buttons)}"
    return buttons[0]


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestSandboxIntegration:
    def test_test_button_disabled_for_source(self, qtbot: pytest.fixture) -> None:
        """capture (source) → кнопка «Тест» disabled, tooltip непустой."""
        ctx = _make_mock_ctx()
        dummy_cb = MagicMock()

        btn = _get_test_button(ctx, "capture", open_sandbox_cb=dummy_cb)
        qtbot.addWidget(btn)

        assert not btn.isEnabled(), "кнопка должна быть disabled для source-плагина"
        assert btn.toolTip(), "tooltip должен быть непустым для source-плагина"

    def test_test_button_enabled_for_grayscale(self, qtbot: pytest.fixture) -> None:
        """grayscale (processing, single-input) → кнопка «Тест» enabled."""
        ctx = _make_mock_ctx()
        dummy_cb = MagicMock()

        btn = _get_test_button(ctx, "grayscale", open_sandbox_cb=dummy_cb)
        qtbot.addWidget(btn)

        assert btn.isEnabled(), "кнопка должна быть enabled для grayscale (processing)"
        # tooltip не обязателен когда enabled — просто не должен быть «причиной отказа»
        assert btn.toolTip() == "" or "недоступен" not in btn.toolTip()

    def test_test_button_disabled_for_stitcher(self, qtbot: pytest.fixture) -> None:
        """stitcher → кнопка «Тест» disabled, tooltip непустой (hardcode multi-input)."""
        ctx = _make_mock_ctx()
        dummy_cb = MagicMock()

        btn = _get_test_button(ctx, "stitcher", open_sandbox_cb=dummy_cb)
        qtbot.addWidget(btn)

        assert not btn.isEnabled(), "кнопка должна быть disabled для stitcher (multi-input)"
        assert btn.toolTip(), "tooltip должен быть непустым для stitcher"

    def test_open_sandbox_switches_content(self, qtbot: pytest.fixture) -> None:
        """Клик «Тест» для grayscale → content_stack показывает PluginSandboxWidget.

        Проверяет полную цепочку:
          _PluginSection.action_buttons() → btn.click() → _on_test_clicked()
          → PluginSandboxWidget создан → open_sandbox() вызван
          → content_stack.currentWidget() is PluginSandboxWidget
        """
        ctx = _make_mock_ctx()
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)

        # Принудительно создаём секцию grayscale через tab (lazy)
        tab.select_tree_key("grayscale")

        # Получаем секцию из presenter-кэша
        section = tab._presenter.section("grayscale")
        # Может быть None если presenter ещё не создал; создадим напрямую
        if section is None:
            from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import _PluginSection

            section = _PluginSection(ctx, "grayscale", "grayscale", open_sandbox_cb=tab.open_sandbox)
        else:
            # Патчим callback на реальный tab.open_sandbox
            section._open_sandbox_cb = tab.open_sandbox

        # Получаем кнопку «Тест»
        buttons = section.action_buttons()
        assert buttons, "action_buttons() должен вернуть кнопку"
        btn = buttons[0]
        qtbot.addWidget(btn)

        assert btn.isEnabled(), "кнопка «Тест» для grayscale должна быть enabled"

        # Клик → _on_test_clicked → создаёт PluginSandboxWidget → open_sandbox
        btn.click()

        # Проверяем: currentWidget() — PluginSandboxWidget
        current = tab._content_stack.currentWidget()
        assert isinstance(current, PluginSandboxWidget), (
            f"После клика «Тест» content_stack должен показывать PluginSandboxWidget, получили: {type(current)}"
        )

    def test_sandbox_widget_singleton_per_section(self, qtbot: pytest.fixture) -> None:
        """Повторный клик «Тест» не создаёт новый PluginSandboxWidget."""
        ctx = _make_mock_ctx()
        open_calls: list = []

        def tracking_cb(name: str, widget) -> None:
            open_calls.append(widget)

        section = _PluginSection(ctx, "grayscale", "grayscale", open_sandbox_cb=tracking_cb)

        # Первый клик
        btns1 = section.action_buttons()
        qtbot.addWidget(btns1[0])
        btns1[0].click()

        # Второй клик — новую кнопку из action_buttons() создаём снова,
        # но _sandbox_widget уже есть → тот же объект
        btns2 = section.action_buttons()
        qtbot.addWidget(btns2[0])
        btns2[0].click()

        assert len(open_calls) == 2, "callback должен быть вызван дважды"
        assert open_calls[0] is open_calls[1], "PluginSandboxWidget должен быть singleton per section"
