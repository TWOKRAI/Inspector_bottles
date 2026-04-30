"""Тесты для PluginCardWidget и PluginChainEditor.

conftest.py подменяет tabs_setting.__init__ на stub,
что позволяет импортировать processes_tab напрямую.

ВАЖНО: patch.object на PySide6 QWidget-класс с Signal вызывает
access violation (баг PySide6 meta-object). Поэтому mock'им только
на уровне модуля, не класса.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.plugin_card_widget import (
    PluginCardWidget,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab import (
    plugin_chain_editor as pce_mod,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.plugin_chain_editor import (
    PluginChainEditor,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Гарантировать единственный экземпляр QApplication для тестов."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def sample_plugins() -> list[dict]:
    """Три плагина для тестов."""
    return [
        {
            "plugin_class": "CameraSource",
            "plugin_name": "camera_source",
            "category": "source",
        },
        {
            "plugin_class": "ColorMask",
            "plugin_name": "color_mask",
            "category": "processing",
        },
        {
            "plugin_class": "DisplayOutput",
            "plugin_name": "display_output",
            "category": "output",
        },
    ]


def _make_mock_entry(
    name: str,
    category: str,
    inputs: list[Port] | None = None,
    outputs: list[Port] | None = None,
):
    """Создать mock PluginEntry."""
    entry = MagicMock()
    entry.name = name
    entry.category = category
    entry.inputs = inputs or []
    entry.outputs = outputs or []
    return entry


def _make_mock_registry(entries_map: dict[str, MagicMock]):
    """Создать mock PluginRegistry с get() side_effect."""
    registry = MagicMock()
    registry.get.side_effect = lambda name: entries_map.get(name)
    return registry


def _make_compatible_entries() -> dict[str, MagicMock]:
    """Три совместимых плагина: camera(bgr) -> color_mask(bgr->gray) -> display(gray)."""
    camera_out = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")
    mask_in = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")
    mask_out = Port(name="mask", dtype="image/gray", shape="(H, W, 1)")
    display_in = Port(name="frame", dtype="image/gray", shape="(H, W, 1)")

    return {
        "camera_source": _make_mock_entry(
            "camera_source", "source", inputs=[], outputs=[camera_out]
        ),
        "color_mask": _make_mock_entry(
            "color_mask", "processing", inputs=[mask_in], outputs=[mask_out]
        ),
        "display_output": _make_mock_entry(
            "display_output", "output", inputs=[display_in], outputs=[]
        ),
    }


# ---------------------------------------------------------------------------
# Тесты PluginCardWidget
# ---------------------------------------------------------------------------


class TestPluginCardWidget:
    """Тесты для карточки плагина."""

    def test_card_displays_name(self, qapp):
        """Карточка отображает имя плагина."""
        data = {"plugin_name": "test_plugin", "category": "processing"}
        card = PluginCardWidget(plugin_data=data, index=0)
        labels = card.findChildren(QLabel)
        name_found = any("test_plugin" in lbl.text() for lbl in labels)
        assert name_found, "Имя плагина не найдено на карточке"

    def test_card_stores_data(self, qapp):
        """Карточка хранит plugin_data и index."""
        data = {"plugin_name": "abc", "category": "source"}
        card = PluginCardWidget(plugin_data=data, index=5)
        assert card.plugin_data is data
        assert card.index == 5

    def test_card_selected_signal(self, qapp, qtbot):
        """Клик по карточке эмитит selected(index)."""
        data = {"plugin_name": "x", "category": "output"}
        card = PluginCardWidget(plugin_data=data, index=2)
        card.show()

        with qtbot.waitSignal(card.selected, timeout=1000) as blocker:
            qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

        assert blocker.args == [2]

    def test_card_remove_signal(self, qapp, qtbot):
        """Кнопка X эмитит remove_requested(index)."""
        data = {"plugin_name": "x", "category": "output"}
        card = PluginCardWidget(plugin_data=data, index=3)
        card.show()

        buttons = card.findChildren(QPushButton)
        remove_btn = [b for b in buttons if "✕" in b.text()]
        assert remove_btn, "Кнопка ✕ не найдена"

        with qtbot.waitSignal(card.remove_requested, timeout=1000) as blocker:
            qtbot.mouseClick(remove_btn[0], Qt.MouseButton.LeftButton)

        assert blocker.args == [3]

    def test_card_move_signal(self, qapp, qtbot):
        """Кнопки ↑/↓ эмитят move_requested(index, direction)."""
        data = {"plugin_name": "x", "category": "processing"}
        card = PluginCardWidget(plugin_data=data, index=1)
        card.show()

        buttons = card.findChildren(QPushButton)
        up_btn = [b for b in buttons if "↑" in b.text()]
        down_btn = [b for b in buttons if "↓" in b.text()]
        assert up_btn and down_btn

        with qtbot.waitSignal(card.move_requested, timeout=1000) as blocker:
            qtbot.mouseClick(up_btn[0], Qt.MouseButton.LeftButton)
        assert blocker.args == [1, -1]

        with qtbot.waitSignal(card.move_requested, timeout=1000) as blocker:
            qtbot.mouseClick(down_btn[0], Qt.MouseButton.LeftButton)
        assert blocker.args == [1, 1]

    def test_card_selection_style(self, qapp):
        """set_selected меняет стиль карточки."""
        data = {"plugin_name": "x", "category": "source"}
        card = PluginCardWidget(plugin_data=data, index=0)
        assert not card.is_selected

        card.set_selected(True)
        assert card.is_selected

        card.set_selected(False)
        assert not card.is_selected


# ---------------------------------------------------------------------------
# Тесты PluginChainEditor
# ---------------------------------------------------------------------------


class TestPluginChainEditor:
    """Тесты для редактора цепочки плагинов."""

    def test_set_chain_creates_cards(self, qapp, sample_plugins):
        """set_chain с 3 плагинами создаёт 3 карточки."""
        editor = PluginChainEditor()

        # mock на уровне модуля (не класса!) — иначе access violation PySide6
        with patch.object(pce_mod, "_HAS_REGISTRY", False):
            editor.set_chain("proc1", sample_plugins)

        assert len(editor._cards) == 3

    def test_compatibility_indicators_green(self, qapp, sample_plugins):
        """Между совместимыми плагинами — зелёный индикатор."""
        entries = _make_compatible_entries()
        registry = _make_mock_registry(entries)

        editor = PluginChainEditor()
        with (
            patch.object(pce_mod, "_HAS_REGISTRY", True),
            patch.object(pce_mod, "PluginRegistry", registry),
        ):
            editor.set_chain("proc1", sample_plugins)

        # Собрать индикаторы (QLabel между карточками)
        indicators = []
        for i in range(editor._inner_layout.count()):
            w = editor._inner_layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                indicators.append(w)

        assert len(indicators) == 2

        # camera_source -> color_mask: bgr -> bgr (совместимо, зелёный)
        assert "✕" not in indicators[0].text()
        assert "66BB6A" in indicators[0].styleSheet()

        # color_mask -> display_output: gray -> gray (совместимо, зелёный)
        assert "✕" not in indicators[1].text()
        assert "66BB6A" in indicators[1].styleSheet()

    def test_compatibility_indicators_red(self, qapp):
        """Между несовместимыми плагинами — красный индикатор."""
        plugins = [
            {"plugin_name": "camera_source", "category": "source"},
            {"plugin_name": "tensor_consumer", "category": "processing"},
        ]

        camera_out = Port(name="frame", dtype="image/bgr")
        tensor_in = Port(name="data", dtype="tensor/float32")

        entries = {
            "camera_source": _make_mock_entry(
                "camera_source", "source", inputs=[], outputs=[camera_out]
            ),
            "tensor_consumer": _make_mock_entry(
                "tensor_consumer", "processing", inputs=[tensor_in], outputs=[]
            ),
        }
        registry = _make_mock_registry(entries)

        editor = PluginChainEditor()
        with (
            patch.object(pce_mod, "_HAS_REGISTRY", True),
            patch.object(pce_mod, "PluginRegistry", registry),
        ):
            editor.set_chain("proc1", plugins)

        indicators = []
        for i in range(editor._inner_layout.count()):
            w = editor._inner_layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                indicators.append(w)

        assert len(indicators) == 1
        assert "✕" in indicators[0].text()
        assert "FF5252" in indicators[0].styleSheet()

    def test_empty_chain(self, qapp):
        """Пустая цепочка — только кнопка '+ Добавить плагин'."""
        editor = PluginChainEditor()
        editor.set_chain("proc1", [])

        assert len(editor._cards) == 0

        buttons = editor._inner.findChildren(QPushButton)
        add_buttons = [b for b in buttons if "Добавить" in b.text()]
        assert len(add_buttons) == 1

    def test_remove_signal(self, qapp, qtbot, sample_plugins):
        """Клик X на карточке эмитит plugin_removed."""
        editor = PluginChainEditor()

        with patch.object(pce_mod, "_HAS_REGISTRY", False):
            editor.set_chain("proc1", sample_plugins)

        editor.show()
        card = editor._cards[1]

        with qtbot.waitSignal(
            editor.plugin_removed, timeout=1000
        ) as blocker:
            buttons = card.findChildren(QPushButton)
            remove_btn = [b for b in buttons if "✕" in b.text()][0]
            qtbot.mouseClick(remove_btn, Qt.MouseButton.LeftButton)

        assert blocker.args == ["proc1", 1]

    def test_move_signal(self, qapp, qtbot, sample_plugins):
        """Кнопки ↑/↓ на карточке эмитят plugin_moved."""
        editor = PluginChainEditor()

        with patch.object(pce_mod, "_HAS_REGISTRY", False):
            editor.set_chain("proc1", sample_plugins)

        editor.show()
        card = editor._cards[1]

        buttons = card.findChildren(QPushButton)
        down_btn = [b for b in buttons if "↓" in b.text()][0]

        with qtbot.waitSignal(
            editor.plugin_moved, timeout=1000
        ) as blocker:
            qtbot.mouseClick(down_btn, Qt.MouseButton.LeftButton)

        assert blocker.args == ["proc1", 1, 2]

    def test_add_plugin_signal(self, qapp, qtbot):
        """Кнопка '+ Добавить плагин' эмитит add_plugin_requested."""
        editor = PluginChainEditor()
        editor.set_chain("proc1", [])
        editor.show()

        buttons = editor._inner.findChildren(QPushButton)
        add_btn = [b for b in buttons if "Добавить" in b.text()][0]

        with qtbot.waitSignal(
            editor.add_plugin_requested, timeout=1000
        ) as blocker:
            qtbot.mouseClick(add_btn, Qt.MouseButton.LeftButton)

        assert blocker.args == ["proc1"]

    def test_selected_plugin_index(self, qapp, qtbot, sample_plugins):
        """Клик по карточке обновляет selected_plugin_index."""
        editor = PluginChainEditor()

        with patch.object(pce_mod, "_HAS_REGISTRY", False):
            editor.set_chain("proc1", sample_plugins)

        assert editor.selected_plugin_index() is None

        editor.show()
        card = editor._cards[2]

        with qtbot.waitSignal(editor.plugin_selected, timeout=1000):
            qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

        assert editor.selected_plugin_index() == 2

    def test_unknown_compatibility(self, qapp):
        """Плагин не найден в registry — серый индикатор '?'."""
        plugins = [
            {"plugin_name": "unknown1", "category": "source"},
            {"plugin_name": "unknown2", "category": "processing"},
        ]

        editor = PluginChainEditor()
        with patch.object(pce_mod, "_HAS_REGISTRY", False):
            editor.set_chain("proc1", plugins)

        indicators = []
        for i in range(editor._inner_layout.count()):
            w = editor._inner_layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                indicators.append(w)

        assert len(indicators) == 1
        assert "?" in indicators[0].text()
        assert "888" in indicators[0].styleSheet()
