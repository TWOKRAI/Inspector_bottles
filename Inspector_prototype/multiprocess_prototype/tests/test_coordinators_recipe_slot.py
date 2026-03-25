# multiprocess_prototype/tests/test_coordinators_recipe_slot.py
"""Pure helpers in frontend/coordinators + FrontendAppContext accessors (no Qt)."""

from __future__ import annotations

from multiprocess_prototype.frontend.app_context import FrontendAppContext
from multiprocess_prototype.frontend.coordinators import parse_clamped_recipe_slot_text


def test_frontend_app_context_ui_accessors():
    ctx = FrontendAppContext(
        config={
            "recipes_tab": {"rt": 1},
            "settings_tab": {"st": 2},
            "cropped_regions_tab": {"cr": 3},
            "post_processing_tab": {"pp": 6},
            "camera_tab": {"cam": 4},
            "recipe_access": {"ra": 0},
            "processing_tab_ui": {"pt": 5},
        },
        registers_manager=None,
        camera_callbacks_map={},
        camera_type="simulator",
    )
    assert ctx.get_recipes_tab_ui() == {"rt": 1}
    assert ctx.get_settings_tab_ui() == {"st": 2}
    assert ctx.get_cropped_regions_tab_ui() == {"cr": 3}
    assert ctx.get_post_processing_tab_ui() == {"pp": 6}
    assert ctx.get_camera_tab_ui() == {"cam": 4}
    assert ctx.get_recipe_access() == {"ra": 0}
    assert ctx.get_processing_tab_ui() == {"pt": 5}


def test_parse_clamped_recipe_slot_text_numeric():
    assert (
        parse_clamped_recipe_slot_text(
            " 3 ",
            min_index=0,
            max_index=10,
            fallback_on_invalid=0,
        )
        == 3
    )


def test_parse_clamped_recipe_slot_text_clamp():
    assert (
        parse_clamped_recipe_slot_text(
            "99",
            min_index=0,
            max_index=5,
            fallback_on_invalid=0,
        )
        == 5
    )


def test_parse_clamped_recipe_slot_text_invalid_uses_fallback():
    assert (
        parse_clamped_recipe_slot_text(
            "x",
            min_index=1,
            max_index=5,
            fallback_on_invalid=2,
        )
        == 2
    )
