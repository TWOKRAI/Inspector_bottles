# -*- coding: utf-8 -*-
"""Тесты pure-логики мульти-дисплея: build_panel_displays / build_frame_routing /
resolve_display_id (без Qt).

Запуск (из ):
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_recipe_displays.py -v
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import (
    build_frame_routing,
    build_panel_displays,
    resolve_display_id,
)


# ---------------------------------------------------------------------------
# build_panel_displays
# ---------------------------------------------------------------------------


class TestBuildPanelDisplays:
    def test_none_recipe_returns_empty(self) -> None:
        assert build_panel_displays(None) == []

    def test_no_displays_section_returns_empty(self) -> None:
        assert build_panel_displays({"blueprint": {}}) == []

    def test_extracts_id_label_enabled_position(self) -> None:
        recipe = {
            "displays": [
                {"id": "main", "name": "Кадр", "enabled": True, "position": {"x": 10, "y": 5}},
                {"id": "mask", "name": "Маска", "enabled": False, "position": {"x": 0, "y": 0}},
            ]
        }
        result = build_panel_displays(recipe)
        assert result == [
            {"id": "main", "label": "Кадр", "enabled": True, "x": 10, "y": 5},
            {"id": "mask", "label": "Маска", "enabled": False, "x": 0, "y": 0},
        ]

    def test_enabled_defaults_true_when_absent(self) -> None:
        """Бэк-совместимость: дисплей без enabled → True."""
        recipe = {"displays": [{"id": "d1", "name": "D1"}]}
        result = build_panel_displays(recipe)
        assert result[0]["enabled"] is True

    def test_label_fallbacks_to_id_when_name_empty(self) -> None:
        recipe = {"displays": [{"id": "d1", "name": ""}]}
        assert build_panel_displays(recipe)[0]["label"] == "d1"

    def test_skips_entries_without_id(self) -> None:
        recipe = {"displays": [{"name": "no-id"}, {"id": "ok"}]}
        result = build_panel_displays(recipe)
        assert [d["id"] for d in result] == ["ok"]

    def test_position_missing_defaults_zero(self) -> None:
        recipe = {"displays": [{"id": "d1"}]}
        d = build_panel_displays(recipe)[0]
        assert d["x"] == 0 and d["y"] == 0


# ---------------------------------------------------------------------------
# build_frame_routing
# ---------------------------------------------------------------------------


class TestBuildFrameRouting:
    def test_none_recipe_returns_empty(self) -> None:
        assert build_frame_routing(None) == {}

    def test_no_bindings_returns_empty(self) -> None:
        assert build_frame_routing({"blueprint": {}}) == {}

    def test_maps_process_to_display(self) -> None:
        """node_id 'process.plugin.port' → process = первый сегмент."""
        recipe = {
            "blueprint": {
                "displays": [
                    {"node_id": "draw.overlay_draw.frame", "display_id": "main"},
                    {"node_id": "maskview.mask_to_frame.frame", "display_id": "mask"},
                ]
            }
        }
        routing = build_frame_routing(recipe)
        assert routing == {"draw": "main", "maskview": "mask"}

    def test_skips_incomplete_bindings(self) -> None:
        recipe = {
            "blueprint": {
                "displays": [
                    {"node_id": "draw.x.frame"},  # без display_id
                    {"display_id": "mask"},  # без node_id
                    {"node_id": "ok.p.frame", "display_id": "main"},
                ]
            }
        }
        assert build_frame_routing(recipe) == {"ok": "main"}

    def test_last_binding_wins_on_process_collision(self) -> None:
        recipe = {
            "blueprint": {
                "displays": [
                    {"node_id": "p.a.frame", "display_id": "d1"},
                    {"node_id": "p.b.frame", "display_id": "d2"},
                ]
            }
        }
        assert build_frame_routing(recipe) == {"p": "d2"}


# ---------------------------------------------------------------------------
# resolve_display_id
# ---------------------------------------------------------------------------


class TestResolveDisplayId:
    def test_known_sender_routed(self) -> None:
        routing = {"draw": "main", "maskview": "mask"}
        assert resolve_display_id({"sender": "maskview"}, routing) == "mask"

    def test_unknown_sender_falls_back_to_default(self) -> None:
        routing = {"draw": "main"}
        assert resolve_display_id({"sender": "other"}, routing) == "main"

    def test_missing_sender_falls_back(self) -> None:
        assert resolve_display_id({}, {"draw": "main"}, default="main") == "main"

    def test_empty_routing_falls_back(self) -> None:
        assert resolve_display_id({"sender": "draw"}, {}) == "main"
