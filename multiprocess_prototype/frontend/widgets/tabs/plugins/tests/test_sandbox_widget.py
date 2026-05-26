"""Тесты для PluginSandboxWidget — vertical slice (Task 6.2).

Покрывает:
- test_widget_creates_for_compatible_plugin    — виджет для grayscale без исключений
- test_apply_button_disabled_initially         — кнопка disabled при старте
- test_show_result_displays_pixmaps            — show_result → after_label.pixmap() не None
- test_show_error_shows_label                  — show_error → label видим

Используется qtbot (pytest-qt, qt_api = pyside6).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Вспомогательные моки
# ---------------------------------------------------------------------------


class _MockEntry:
    """Mock для PluginEntry."""

    def __init__(
        self,
        name: str,
        category: str,
        plugin_class=None,
        inputs: list | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.plugin_class = plugin_class
        self.inputs = inputs or []


class _MockRegistry:
    """Mock для PluginRegistry."""

    def __init__(self, entries: list[_MockEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def get(self, name: str) -> _MockEntry | None:
        return self._entries.get(name)

    def list(self) -> list[_MockEntry]:
        return list(self._entries.values())


def _make_ctx(registry=None) -> MagicMock:
    """Собрать минимальный mock AppContext."""
    ctx = MagicMock()
    ctx.plugin_registry.return_value = registry
    return ctx


# ---------------------------------------------------------------------------
# Фикстура с реальными плагинами (grayscale)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _import_real_plugins():
    """Импортировать реальные плагины чтобы они зарегистрировались в PluginRegistry."""
    import importlib

    importlib.import_module("Plugins.processing.grayscale.plugin")


@pytest.fixture()
def real_registry():
    """PluginRegistry с реально зарегистрированными плагинами."""
    from multiprocess_framework.modules.process_module.plugins import PluginRegistry

    return PluginRegistry


@pytest.fixture()
def ctx_with_real_registry(real_registry):
    """AppContext с реальным PluginRegistry."""
    return _make_ctx(registry=real_registry)


# ---------------------------------------------------------------------------
# Фикстура presenter'а для grayscale
# ---------------------------------------------------------------------------


@pytest.fixture()
def grayscale_presenter(ctx_with_real_registry):
    """SandboxPresenter для grayscale плагина."""
    from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

    return SandboxPresenter(ctx_with_real_registry)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestPluginSandboxWidgetCreation:
    """Тесты создания виджета."""

    def test_widget_creates_for_compatible_plugin(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """Виджет для grayscale создаётся без исключений."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Виджет создан — заголовок содержит имя плагина
        assert widget is not None
        assert widget._plugin_name == "grayscale"

    def test_apply_button_disabled_initially(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """Кнопка «Применить» должна быть disabled пока нет загруженного кадра."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # При старте _current_frame is None → кнопка disabled
        assert widget._current_frame is None
        assert not widget._btn_apply.isEnabled()

    def test_apply_button_text_initially(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """Начальный текст кнопки «Применить»."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        assert widget._btn_apply.text() == "Применить"


class TestShowResult:
    """Тесты метода show_result."""

    def test_show_result_displays_pixmaps(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """show_result с двумя numpy-кадрами 10×10 → after_label.pixmap() не None."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Два реальных BGR кадра 10×10
        before = np.full((10, 10, 3), fill_value=100, dtype=np.uint8)
        after = np.full((10, 10, 3), fill_value=200, dtype=np.uint8)

        widget.show_result(before, after)

        # Оба лейбла должны содержать пиксмапу
        assert widget.before_label.pixmap() is not None
        assert not widget.before_label.pixmap().isNull()
        assert widget.after_label.pixmap() is not None
        assert not widget.after_label.pixmap().isNull()

    def test_show_result_after_none_does_not_crash(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """show_result(before, after=None) не бросает исключений, before показывается."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        before = np.zeros((10, 10, 3), dtype=np.uint8)

        # after=None — не должно падать
        widget.show_result(before, None)

        # before_label должен показать кадр
        assert widget.before_label.pixmap() is not None
        # after_label остаётся пустым (None-пиксмап или null)
        after_px = widget.after_label.pixmap()
        # after_label может быть None (нет пиксмапы) или null pixmap
        if after_px is not None:
            assert after_px.isNull()


class TestShowError:
    """Тесты метода show_error."""

    def test_show_error_shows_label(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """После show_error('bad') — error label видим."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Изначально ошибки нет
        assert widget._lbl_error.isHidden()

        widget.show_error("bad file")

        # Лейбл должен стать видимым
        assert not widget._lbl_error.isHidden()
        assert widget._lbl_error.text() == "bad file"

    def test_show_error_empty_string_hides_label(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """show_error('') — label скрывается (не падает)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Сначала показываем ошибку
        widget.show_error("какая-то ошибка")
        assert not widget._lbl_error.isHidden()

        # Затем скрываем пустой строкой — не должно упасть
        widget.show_error("")
        assert widget._lbl_error.isHidden()


class TestSetRunning:
    """Тесты метода set_running."""

    def test_set_running_true_disables_button(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """set_running(True) — кнопка disabled + текст 'Применяется…'."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Имитируем загруженный кадр (чтобы кнопка была enabled)
        widget._current_frame = np.zeros((5, 5, 3), dtype=np.uint8)
        widget._btn_apply.setEnabled(True)

        widget.set_running(True)

        assert not widget._btn_apply.isEnabled()
        assert "Применяется" in widget._btn_apply.text()

    def test_set_running_false_enables_button(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """set_running(False) после True — кнопка enabled + текст 'Применить'."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Загруженный кадр — чтобы set_running(False) мог включить кнопку
        widget._current_frame = np.zeros((5, 5, 3), dtype=np.uint8)

        widget.set_running(True)
        widget.set_running(False)

        assert widget._btn_apply.isEnabled()
        assert widget._btn_apply.text() == "Применить"


class TestApplyFlow:
    """Тесты E2E flow: frame → apply → show_result."""

    def test_apply_with_grayscale_fills_after_label(
        self,
        qtbot,
        grayscale_presenter,
    ) -> None:
        """Устанавливаем _current_frame вручную, вызываем apply → after_label.pixmap() не None."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget

        widget = PluginSandboxWidget(grayscale_presenter, "grayscale")
        qtbot.addWidget(widget)

        # Устанавливаем кадр напрямую (минуя QFileDialog)
        frame = np.full((10, 10, 3), fill_value=128, dtype=np.uint8)
        widget._current_frame = frame
        widget._btn_apply.setEnabled(True)

        # Применяем
        widget._on_apply_clicked()

        # after_label должен показать результат grayscale
        assert widget.after_label.pixmap() is not None
        assert not widget.after_label.pixmap().isNull()
