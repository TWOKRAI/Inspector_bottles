# -*- coding: utf-8 -*-
"""Тесты ImagePanelWidget.set_displays — пересборка слотов мульти-дисплея (pytest-qt).

Запуск (из ):
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_set_displays.py -v
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget


@pytest.fixture()
def panel(qtbot):
    w = ImagePanelWidget()
    qtbot.addWidget(w)
    return w


class TestSetDisplays:
    def test_builds_slots_for_enabled_displays(self, panel) -> None:
        panel.set_displays(
            [
                {"id": "main", "label": "Main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "label": "Mask", "enabled": True, "x": 100, "y": 0},
            ]
        )
        assert set(panel.slot_ids) == {"main", "mask"}

    def test_disabled_display_excluded(self, panel) -> None:
        panel.set_displays(
            [
                {"id": "main", "label": "Main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "label": "Mask", "enabled": False, "x": 100, "y": 0},
            ]
        )
        assert panel.slot_ids == ["main"]

    def test_empty_list_falls_back_to_main(self, panel) -> None:
        """Бэк-совместимость: пустой список → единственный слот 'main'."""
        panel.set_displays([])
        assert panel.slot_ids == ["main"]

    def test_all_disabled_falls_back_to_main(self, panel) -> None:
        panel.set_displays([{"id": "x", "enabled": False, "x": 0, "y": 0}])
        assert panel.slot_ids == ["main"]

    def test_order_by_position_x(self, panel) -> None:
        """Слоты упорядочены по position.x (заложено под свободные позиции)."""
        panel.set_displays(
            [
                {"id": "b", "enabled": True, "x": 200, "y": 0},
                {"id": "a", "enabled": True, "x": 50, "y": 0},
                {"id": "c", "enabled": True, "x": 100, "y": 0},
            ]
        )
        # Порядок виджетов в layout = a (50), c (100), b (200)
        layout = panel._layout
        ordered = [layout.itemAt(i).widget().slot_id for i in range(layout.count())]
        assert ordered == ["a", "c", "b"]

    def test_toggle_removes_then_readds_slot(self, panel) -> None:
        """Повторный вызов с изменённым enabled пересобирает слоты."""
        panel.set_displays(
            [
                {"id": "main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "enabled": True, "x": 100, "y": 0},
            ]
        )
        assert set(panel.slot_ids) == {"main", "mask"}
        # Выключаем mask
        panel.set_displays(
            [
                {"id": "main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "enabled": False, "x": 100, "y": 0},
            ]
        )
        assert panel.slot_ids == ["main"]
        # Снова включаем
        panel.set_displays(
            [
                {"id": "main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "enabled": True, "x": 100, "y": 0},
            ]
        )
        assert set(panel.slot_ids) == {"main", "mask"}

    def test_existing_slot_reused_not_duplicated(self, panel) -> None:
        panel.set_displays([{"id": "main", "enabled": True, "x": 0, "y": 0}])
        first = panel._slots["main"]
        panel.set_displays(
            [
                {"id": "main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "enabled": True, "x": 100, "y": 0},
            ]
        )
        # 'main' тот же инстанс (не пересоздан)
        assert panel._slots["main"] is first

    def test_frame_routed_to_correct_slot(self, panel, qtbot) -> None:
        """display_frame в конкретный слот не падает и не трогает другие слоты."""
        import numpy as np

        panel.set_displays(
            [
                {"id": "main", "enabled": True, "x": 0, "y": 0},
                {"id": "mask", "enabled": True, "x": 100, "y": 0},
            ]
        )
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        panel.display_frame("mask", frame)  # не должно бросать
        assert "mask" in panel.slot_ids
