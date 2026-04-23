"""
Unit-тесты ActionBuilder (Phase 7, Task 7D.4).

Проверяем все методы фабрики: field_set, region_add/remove/modify,
step_*, display_*, profile_switch, recipe_switch, command.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень multiprocess_prototype_v3 в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder
from frontend.actions.schemas import ActionType


class TestFieldSet:
    """Тесты ActionBuilder.field_set()."""

    def test_field_set_action_type(self):
        """field_set → action_type=FIELD_SET."""
        action = ActionBuilder.field_set("settings", "threshold", 50, 0)
        assert action.action_type == ActionType.FIELD_SET

    def test_field_set_coalesce_key_format(self):
        """field_set → coalesce_key="field:{register}.{field}"."""
        action = ActionBuilder.field_set("settings", "threshold", 50, 0)
        assert action.coalesce_key == "field:settings.threshold"

    def test_field_set_forward_patch_value(self):
        """field_set → forward_patch содержит new_value."""
        action = ActionBuilder.field_set("reg", "field", 42, 0)
        assert action.forward_patch["value"] == 42

    def test_field_set_backward_patch_value(self):
        """field_set → backward_patch содержит old_value."""
        action = ActionBuilder.field_set("reg", "field", 42, 7)
        assert action.backward_patch["value"] == 7

    def test_field_set_undoable_true(self):
        """field_set → undoable=True."""
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        assert action.undoable is True

    def test_field_set_register_name(self):
        """field_set → register_name установлен корректно."""
        action = ActionBuilder.field_set("my_register", "my_field", 1, 0)
        assert action.register_name == "my_register"

    def test_field_set_field_name(self):
        """field_set → field_name установлен корректно."""
        action = ActionBuilder.field_set("reg", "my_field", 1, 0)
        assert action.field_name == "my_field"


class TestRegionAdd:
    """Тесты ActionBuilder.region_add()."""

    def test_region_add_action_type(self):
        """region_add → action_type=REGION_ADD."""
        action = ActionBuilder.region_add(
            "cam_0",
            {"name": "roi_1"},
            None,
            register_name="processing",
        )
        assert action.action_type == ActionType.REGION_ADD

    def test_region_add_description_contains_region_name(self):
        """region_add → description содержит имя региона."""
        action = ActionBuilder.region_add(
            "cam_0",
            {"name": "my_roi"},
            None,
            register_name="processing",
        )
        assert "my_roi" in action.description

    def test_region_add_undoable_true(self):
        """region_add → undoable=True."""
        action = ActionBuilder.region_add(
            "cam_0",
            {"name": "roi"},
            None,
            register_name="processing",
        )
        assert action.undoable is True

    def test_region_add_forward_patch_has_camera_id(self):
        """region_add → forward_patch содержит camera_id."""
        action = ActionBuilder.region_add(
            "cam_1",
            {"name": "roi"},
            None,
            register_name="processing",
        )
        assert action.forward_patch["camera_id"] == "cam_1"


class TestRegionRemove:
    """Тесты ActionBuilder.region_remove()."""

    def test_region_remove_action_type(self):
        """region_remove → action_type=REGION_REMOVE."""
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", "before_state", "after_state", register_name="processing"
        )
        assert action.action_type == ActionType.REGION_REMOVE

    def test_region_remove_undoable_true(self):
        """region_remove → undoable=True."""
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", "before", "after", register_name="proc"
        )
        assert action.undoable is True

    def test_region_remove_forward_patch_has_pipeline_after(self):
        """region_remove → forward_patch содержит pipeline_after."""
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", "before", "after_state", register_name="proc"
        )
        assert action.forward_patch["pipeline_after"] == "after_state"

    def test_region_remove_backward_patch_has_pipeline_before(self):
        """region_remove → backward_patch содержит pipeline_before."""
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", "before_state", "after", register_name="proc"
        )
        assert action.backward_patch["pipeline_before"] == "before_state"


class TestRegionModify:
    """Тесты ActionBuilder.region_modify()."""

    def test_region_modify_uses_field_set_type(self):
        """region_modify → action_type=FIELD_SET (нет отдельного REGION_MODIFY)."""
        action = ActionBuilder.region_modify(
            "cam_0", "roi_1", "before", "after", register_name="processing"
        )
        assert action.action_type == ActionType.FIELD_SET

    def test_region_modify_has_coalesce_key(self):
        """region_modify → coalesce_key не None."""
        action = ActionBuilder.region_modify(
            "cam_0", "roi_1", "before", "after", register_name="processing"
        )
        assert action.coalesce_key is not None

    def test_region_modify_coalesce_key_contains_region_and_camera(self):
        """region_modify → coalesce_key содержит register, camera_id и region_name."""
        action = ActionBuilder.region_modify(
            "cam_2", "my_roi", "before", "after", register_name="proc"
        )
        assert "cam_2" in action.coalesce_key
        assert "my_roi" in action.coalesce_key
        assert "proc" in action.coalesce_key

    def test_region_modify_undoable_true(self):
        """region_modify → undoable=True."""
        action = ActionBuilder.region_modify(
            "cam_0", "roi_1", "before", "after", register_name="proc"
        )
        assert action.undoable is True


class TestStepAdd:
    """Тесты ActionBuilder.step_add()."""

    def test_step_add_action_type(self):
        """step_add → action_type=STEP_ADD."""
        action = ActionBuilder.step_add("region_0", {"op": "blur"}, [])
        assert action.action_type == ActionType.STEP_ADD

    def test_step_add_undoable_true(self):
        """step_add → undoable=True."""
        action = ActionBuilder.step_add("region_0", "blur_node", [])
        assert action.undoable is True

    def test_step_add_register_name_is_region_id(self):
        """step_add → register_name = region_id."""
        action = ActionBuilder.step_add("my_region", "node", [])
        assert action.register_name == "my_region"


class TestStepModify:
    """Тесты ActionBuilder.step_modify()."""

    def test_step_modify_has_coalesce_key(self):
        """step_modify → coalesce_key содержит region_id и node_id."""
        action = ActionBuilder.step_modify("region_0", "node_1", "before", "after")
        assert action.coalesce_key is not None
        assert "region_0" in action.coalesce_key
        assert "node_1" in action.coalesce_key

    def test_step_modify_action_type(self):
        """step_modify → action_type=STEP_MODIFY."""
        action = ActionBuilder.step_modify("region_0", "node_1", {}, {"param": 5})
        assert action.action_type == ActionType.STEP_MODIFY


class TestDisplaySubscribe:
    """Тесты ActionBuilder.display_subscribe()."""

    def test_display_subscribe_undoable_false(self):
        """display_subscribe → undoable=False (не попадает в undo-стек)."""
        action = ActionBuilder.display_subscribe("camera_0", {})
        assert action.undoable is False

    def test_display_subscribe_action_type(self):
        """display_subscribe → action_type=DISPLAY_SUBSCRIBE."""
        action = ActionBuilder.display_subscribe("camera_0", {})
        assert action.action_type == ActionType.DISPLAY_SUBSCRIBE


class TestDisplayUnsubscribe:
    """Тесты ActionBuilder.display_unsubscribe()."""

    def test_display_unsubscribe_undoable_false(self):
        """display_unsubscribe → undoable=False."""
        action = ActionBuilder.display_unsubscribe("camera_0")
        assert action.undoable is False

    def test_display_unsubscribe_action_type(self):
        """display_unsubscribe → action_type=DISPLAY_UNSUBSCRIBE."""
        action = ActionBuilder.display_unsubscribe("camera_0")
        assert action.action_type == ActionType.DISPLAY_UNSUBSCRIBE


class TestLayoutChange:
    """Тесты ActionBuilder.layout_change()."""

    def test_layout_change_undoable_true(self):
        """layout_change → undoable=True (смену раскладки можно отменить)."""
        action = ActionBuilder.layout_change("QUAD", [], [])
        assert action.undoable is True

    def test_layout_change_action_type(self):
        """layout_change → action_type=LAYOUT_CHANGE."""
        action = ActionBuilder.layout_change("SINGLE", [], [])
        assert action.action_type == ActionType.LAYOUT_CHANGE


class TestProfileSwitch:
    """Тесты ActionBuilder.profile_switch()."""

    def test_profile_switch_action_type(self):
        """profile_switch → action_type=PROFILE_SWITCH."""
        action = ActionBuilder.profile_switch("prof_1", {}, {})
        assert action.action_type == ActionType.PROFILE_SWITCH

    def test_profile_switch_is_single_action(self):
        """profile_switch → создаётся 1 Action, не N по числу полей."""
        action = ActionBuilder.profile_switch(
            "prof_1",
            {"field1": 1, "field2": 2, "field3": 3},
            {"field1": 10, "field2": 20, "field3": 30},
        )
        # Проверяем, что вернули один Action (не список)
        assert hasattr(action, "action_id")
        assert hasattr(action, "action_type")

    def test_profile_switch_forward_patch_contains_profile_id(self):
        """profile_switch → forward_patch["profile_id"] = profile_id."""
        action = ActionBuilder.profile_switch("my_profile", {}, {"key": "val"})
        assert action.forward_patch["profile_id"] == "my_profile"

    def test_profile_switch_forward_patch_contains_snapshot(self):
        """profile_switch → forward_patch["snapshot"] = registers_snapshot_after."""
        snapshot_after = {"threshold": 50}
        action = ActionBuilder.profile_switch("prof_1", {}, snapshot_after)
        assert action.forward_patch["snapshot"] == snapshot_after

    def test_profile_switch_backward_patch_contains_snapshot(self):
        """profile_switch → backward_patch["snapshot"] = registers_snapshot_before."""
        snapshot_before = {"threshold": 0}
        action = ActionBuilder.profile_switch("prof_1", snapshot_before, {})
        assert action.backward_patch["snapshot"] == snapshot_before

    def test_profile_switch_undoable_true(self):
        """profile_switch → undoable=True."""
        action = ActionBuilder.profile_switch("prof_1", {}, {})
        assert action.undoable is True


class TestRecipeSwitch:
    """Тесты ActionBuilder.recipe_switch()."""

    def test_recipe_switch_action_type(self):
        """recipe_switch → action_type=RECIPE_SWITCH."""
        action = ActionBuilder.recipe_switch("slot_1", {}, {})
        assert action.action_type == ActionType.RECIPE_SWITCH

    def test_recipe_switch_forward_patch_contains_slot_id(self):
        """recipe_switch → forward_patch["slot_id"] = slot_id."""
        action = ActionBuilder.recipe_switch("slot_2", {}, {"data": 1})
        assert action.forward_patch["slot_id"] == "slot_2"

    def test_recipe_switch_undoable_true(self):
        """recipe_switch → undoable=True."""
        action = ActionBuilder.recipe_switch("slot_1", {}, {})
        assert action.undoable is True


class TestCommand:
    """Тесты ActionBuilder.command()."""

    def test_command_undoable_false(self):
        """command → undoable=False (side-effect без undo)."""
        action = ActionBuilder.command("Запустить калибровку")
        assert action.undoable is False

    def test_command_action_type(self):
        """command → action_type=COMMAND."""
        action = ActionBuilder.command("Test command")
        assert action.action_type == ActionType.COMMAND

    def test_command_description_set(self):
        """command → description установлена."""
        action = ActionBuilder.command("Моя команда")
        assert action.description == "Моя команда"

    def test_command_empty_patches(self):
        """command → forward_patch и backward_patch пустые."""
        action = ActionBuilder.command("cmd")
        assert action.forward_patch == {}
        assert action.backward_patch == {}
