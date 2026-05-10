"""Тесты Phase 6 конструктора — Display monitoring & WireMetrics.

Группы:
  1. WireMetrics + WireDataBridge  (7 тестов)
  2. WireMetricsBadge               (5 тестов)
  3. DisplayTargetNode               (4 теста)
  4. WireInspectorPanel display combo (5 тестов)

Запуск:
    python -m pytest multiprocess_prototype/tests/unit/test_constructor_phase6_display_monitoring.py -v
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Заглушки для circular import — паттерн из test_constructor_phase5*.py
# ---------------------------------------------------------------------------

_STUB_MODULES = [
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.display_tab",
    "multiprocess_prototype.frontend.widgets.base.recipe_panel_base",
    "multiprocess_prototype.frontend.widgets.base.navigation_panel_base",
    "multiprocess_prototype.frontend.widgets.base.cards_field_factory",
    "multiprocess_prototype.frontend.coordinators",
    "multiprocess_prototype.frontend.touch_keyboard_bind",
    "multiprocess_prototype.frontend.widgets.recipes",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.panel_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.schemas",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.auto_save",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.slot_combo_model",
    # NodeGraphQt — недоступен в тестовом окружении без GUI
    "NodeGraphQt",
    "NodeGraphQt.qgraphics",
    "NodeGraphQt.qgraphics.node_base",
]
for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Настройка заглушек NodeGraphQt для DisplayTargetNode
_mock_ngq = sys.modules["NodeGraphQt"]
_mock_ngq.BaseNode = MagicMock
_mock_ngq.qgraphics = MagicMock()
_mock_ngq.qgraphics.node_base = MagicMock()
_mock_ngq.qgraphics.node_base.NodeItem = MagicMock


# ===========================================================================
# Группа 1: WireMetrics + WireDataBridge
# ===========================================================================


class TestWireMetricsDefaults:
    """WireMetrics() должен иметь нулевые значения по умолчанию."""

    def test_wire_metrics_default(self) -> None:
        """WireMetrics() имеет fps=0.0, latency_ms=0.0, buffer_fill=0.0."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireMetrics

        m = WireMetrics()
        assert m.fps == 0.0
        assert m.latency_ms == 0.0
        assert m.buffer_fill == 0.0

    def test_get_metrics_unknown_key(self, qapp) -> None:
        """get_metrics() для неизвестного ключа возвращает дефолтный WireMetrics (все нули)."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import (
            WireDataBridge,
            WireMetrics,
        )

        bridge = WireDataBridge()
        result = bridge.get_metrics("nonexistent_wire")

        assert isinstance(result, WireMetrics)
        assert result.fps == 0.0
        assert result.latency_ms == 0.0
        assert result.buffer_fill == 0.0


class TestWireDataBridgeOnMetricsReceived:
    """Тесты метода on_metrics_received."""

    def test_on_metrics_received_emits_signal(self, qapp, qtbot) -> None:
        """on_metrics_received с данными → metrics_changed эмитирован."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()

        with qtbot.waitSignal(bridge.metrics_changed, timeout=1000) as blocker:
            bridge.on_metrics_received({
                "wire_0": {"fps": 30.0, "latency_ms": 5.0, "buffer_fill": 0.5}
            })

        assert "wire_0" in blocker.args[0]

    def test_on_metrics_received_empty_no_signal(self, qapp, qtbot) -> None:
        """on_metrics_received с пустым dict → сигнал НЕ эмитируется."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()
        received = []
        bridge.metrics_changed.connect(lambda d: received.append(d))

        bridge.on_metrics_received({})

        assert len(received) == 0

    def test_on_metrics_received_clamps_buffer_fill(self, qapp) -> None:
        """buffer_fill > 1.0 → значение зажимается в 1.0."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()
        bridge.on_metrics_received({
            "wire_x": {"fps": 10.0, "latency_ms": 1.0, "buffer_fill": 5.0}
        })

        metrics = bridge.get_metrics("wire_x")
        assert metrics.buffer_fill <= 1.0

    def test_on_metrics_received_stores_values(self, qapp) -> None:
        """on_metrics_received правильно сохраняет fps и latency_ms."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()
        bridge.on_metrics_received({
            "wire_a": {"fps": 25.0, "latency_ms": 8.5, "buffer_fill": 0.3}
        })

        m = bridge.get_metrics("wire_a")
        assert m.fps == 25.0
        assert m.latency_ms == 8.5


class TestWireDataBridgeTimers:
    """Тесты управления таймерами мониторинга."""

    def test_metrics_timer_start_stop(self, qapp) -> None:
        """start_monitoring() запускает таймеры; stop_monitoring() их останавливает."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()

        # Изначально оба таймера неактивны
        assert not bridge._poll_timer.isActive()
        assert not bridge._metrics_timer.isActive()

        bridge.start_monitoring()
        assert bridge._poll_timer.isActive()
        assert bridge._metrics_timer.isActive()

        bridge.stop_monitoring()
        assert not bridge._poll_timer.isActive()
        assert not bridge._metrics_timer.isActive()

    def test_set_metrics_interval(self, qapp) -> None:
        """set_metrics_interval(500) устанавливает interval == 500."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()
        bridge.set_metrics_interval(500)

        assert bridge._metrics_timer.interval() == 500

    def test_set_metrics_interval_min_clamp(self, qapp) -> None:
        """set_metrics_interval(50) → interval >= 200 (минимальный clamp)."""
        from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireDataBridge

        bridge = WireDataBridge()
        bridge.set_metrics_interval(50)

        assert bridge._metrics_timer.interval() >= 200


# ===========================================================================
# Группа 2: WireMetricsBadge
# ===========================================================================


class TestWireMetricsBadge:
    """Тесты overlay-badge с метриками wire-канала."""

    def test_badge_created_hidden(self, qapp) -> None:
        """Новый WireMetricsBadge начальное состояние — скрыт (isVisible() == False)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        assert not badge.isVisible()

    def test_badge_update_metrics_visible(self, qapp) -> None:
        """update_metrics(30, 5, 0.5) → badge становится видимым."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        badge.update_metrics(30.0, 5.0, 0.5)

        assert badge.isVisible()

    def test_badge_update_metrics_text_contains_fps(self, qapp) -> None:
        """update_metrics(30, 5, 0.5) → текст содержит '30fps'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        badge.update_metrics(30.0, 5.0, 0.5)

        assert "30fps" in badge._text

    def test_badge_all_zeros_hidden(self, qapp) -> None:
        """update_metrics(0, 0, 0) → badge скрывается."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        # Сначала показываем
        badge.update_metrics(10.0, 2.0, 0.3)
        assert badge.isVisible()

        # Потом сбрасываем в нули
        badge.update_metrics(0.0, 0.0, 0.0)
        assert not badge.isVisible()

    def test_badge_text_format(self, qapp) -> None:
        """update_metrics форматирует строку '30fps | 5.0ms | 50%'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        badge.update_metrics(30.0, 5.0, 0.5)

        # Проверяем наличие всех ключевых частей формата
        assert "fps" in badge._text
        assert "ms" in badge._text
        assert "%" in badge._text

    def test_badge_update_position_no_pipe(self, qapp) -> None:
        """update_position(None) → badge скрывается (защита от None pipe)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.wire_metrics_badge import (
            WireMetricsBadge,
        )

        badge = WireMetricsBadge()
        # Сначала делаем видимым
        badge.update_metrics(15.0, 3.0, 0.4)
        assert badge.isVisible()

        # Передаём None — должен скрыться
        badge.update_position(None)
        assert not badge.isVisible()


# ===========================================================================
# Группа 3: DisplayTargetNode
# ===========================================================================


class TestDisplayTargetNode:
    """Тесты ноды display-окна на канвасе конструктора."""

    def _make_mock_display_node(self) -> MagicMock:
        """Создать mock DisplayTargetNode с хранилищем свойств."""
        node = MagicMock()
        _props: dict = {}
        node.get_property.side_effect = lambda k: _props.get(k, "")
        node.set_property.side_effect = lambda k, v: _props.update({k: v})
        node.view = MagicMock()
        node.name.return_value = "DisplayTargetNode_1"
        return node

    def test_display_node_type_constant(self) -> None:
        """DISPLAY_NODE_TYPE == 'constructor.nodes.DisplayTargetNode'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.display_target_node import (
            DISPLAY_NODE_TYPE,
        )

        assert DISPLAY_NODE_TYPE == "constructor.nodes.DisplayTargetNode"

    def test_display_node_identifier(self) -> None:
        """DisplayTargetNode.__identifier__ == 'constructor.nodes'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.display_target_node import (
            DisplayTargetNode,
        )

        assert DisplayTargetNode.__identifier__ == "constructor.nodes"

    def _call_set_display_data(self, node: MagicMock, *args) -> None:
        """Вызвать set_display_data с патченным DisplayNodeItem.

        Аналогично паттерну из test_constructor_phase5_route_node.py:
        заменяем DisplayNodeItem пустым классом, чтобы isinstance()
        работал корректно с MagicMock-объектами.
        """
        import multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.display_target_node as _mod
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.display_target_node import (
            DisplayTargetNode,
        )

        original = _mod.DisplayNodeItem
        _mod.DisplayNodeItem = type("DisplayNodeItem", (), {})  # пустой класс
        try:
            DisplayTargetNode.set_display_data(node, *args)
        finally:
            _mod.DisplayNodeItem = original

    def test_display_node_set_display_data_stores_key(self) -> None:
        """set_display_data() сохраняет display_key через set_property."""
        node = self._make_mock_display_node()
        self._call_set_display_data(node, "win_0", "Main", 30)

        node.set_property.assert_any_call("display_key", "win_0")

    def test_display_node_set_display_data_stores_name(self) -> None:
        """set_display_data() сохраняет display_name через set_property."""
        node = self._make_mock_display_node()
        self._call_set_display_data(node, "win_0", "Main", 30)

        node.set_property.assert_any_call("display_name", "Main")

    def test_display_node_set_display_data_fallback_name(self) -> None:
        """set_display_data() с пустым name → display_name = display_key."""
        node = self._make_mock_display_node()
        self._call_set_display_data(node, "win_0", "", 30)

        # Если name пустой, display_name должен быть = display_key
        node.set_property.assert_any_call("display_name", "win_0")


# ===========================================================================
# Группа 4: WireInspectorPanel — display combo
# ===========================================================================


class TestWireInspectorPanelDisplayCombo:
    """Тесты display combo в WireInspectorPanel."""

    def test_wire_inspector_has_display_combo(self, qapp, qtbot) -> None:
        """WireInspectorPanel содержит QComboBox _display_combo."""
        from PySide6.QtWidgets import QComboBox
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        assert hasattr(panel, "_display_combo")
        assert isinstance(panel._display_combo, QComboBox)

    def test_set_available_displays_fills_combo(self, qapp, qtbot) -> None:
        """set_available_displays([...]) заполняет combo нужным числом элементов."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        displays = [
            {"key": "win_0", "name": "Main"},
            {"key": "win_1", "name": "Secondary"},
        ]
        panel.set_available_displays(displays)

        # combo содержит "(нет)" + 2 display = 3 элемента
        assert panel._display_combo.count() == 3

    def test_set_available_displays_first_item_is_none(self, qapp, qtbot) -> None:
        """Первый элемент combo — '(нет)' с userData=None."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        panel.set_available_displays([{"key": "win_0", "name": "Main"}])

        assert panel._display_combo.itemData(0) is None

    def test_display_combo_emits_wire_changed_with_display_target(self, qapp, qtbot) -> None:
        """Выбор display → wire_changed эмитируется с ключом 'display_target'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        # Устанавливаем wire_key чтобы сигнал эмитировался
        panel.show_wire("test_wire", {"source": "a.out", "target": "b.in", "transport": "router"})

        panel.set_available_displays([{"key": "win_0", "name": "Main"}])

        with qtbot.waitSignal(panel.wire_changed, timeout=1000) as blocker:
            panel._display_combo.setCurrentIndex(1)  # выбираем "Main (win_0)"

        wire_key, changed_dict = blocker.args
        assert wire_key == "test_wire"
        assert "display_target" in changed_dict

    def test_show_wire_selects_correct_display(self, qapp, qtbot) -> None:
        """show_wire с display_target → combo выбирает правильный display."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        panel.set_available_displays([
            {"key": "win_0", "name": "Main"},
            {"key": "win_1", "name": "Secondary"},
        ])

        panel.show_wire("wire_1", {
            "source": "cam.out",
            "target": "proc.in",
            "transport": "router",
            "display_target": "win_1",
        })

        # Combo должен показывать win_1
        assert panel._display_combo.currentData() == "win_1"

    def test_clear_resets_display_combo_to_index_0(self, qapp, qtbot) -> None:
        """clear() → display_combo сбрасывается на index 0 ('(нет)')."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        qtbot.addWidget(panel)

        panel.set_available_displays([{"key": "win_0", "name": "Main"}])
        panel.show_wire("wire_1", {
            "source": "a.out", "target": "b.in",
            "transport": "router", "display_target": "win_0",
        })
        # Убеждаемся что combo выбрано на win_0
        assert panel._display_combo.currentIndex() == 1

        panel.clear()
        assert panel._display_combo.currentIndex() == 0
