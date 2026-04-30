"""
Unit-тесты всех 6 handlers (Phase 7, Task 7D.4).

Проверяем: FieldSetHandler, RegionActionHandler, ChainActionHandler,
DisplayActionHandler, ProfileSwitchHandler, RecipeSwitchHandler.
Без Qt, без реальной БД — только мок-зависимости.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Добавляем корень multiprocess_prototype в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder
from frontend.actions.handlers.chain_handler import ChainActionHandler
from frontend.actions.handlers.display_handler import DisplayActionHandler
from frontend.actions.handlers.field_set_handler import FieldSetHandler
from frontend.actions.handlers.profile_handler import ProfileSwitchHandler
from frontend.actions.handlers.recipe_handler import RecipeSwitchHandler
from frontend.actions.handlers.region_handler import RegionActionHandler
from frontend.actions.schemas import Action, ActionType

# ---------------------------------------------------------------------------
# Мок RegistersManager
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data = {}  # {(register_name, field_name): value}
        self.calls = []  # история вызовов set_field_value

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        self.calls.append((register_name, field_name, value))
        return (True, None)

    def get_field_value(self, register_name, field_name):
        return self._data.get((register_name, field_name))

    def get_register(self, register_name):
        return None

    def model_dump_all(self):
        result = {}
        for (reg, field), val in self._data.items():
            result.setdefault(reg, {})[field] = val
        return result


# ---------------------------------------------------------------------------
# Тесты FieldSetHandler
# ---------------------------------------------------------------------------


class TestFieldSetHandler:
    """Тесты обработчика FIELD_SET действий."""

    def test_apply_calls_set_field_value_with_forward_patch_value(self):
        """apply → rm.set_field_value вызван с forward_patch['value']."""
        rm = MockRM()
        handler = FieldSetHandler()
        action = ActionBuilder.field_set("settings", "threshold", 42, 0)
        handler.apply(action, rm)
        assert ("settings", "threshold", 42) in rm.calls

    def test_apply_writes_correct_value(self):
        """apply → значение записано в регистр."""
        rm = MockRM()
        handler = FieldSetHandler()
        action = ActionBuilder.field_set("reg", "field", 99, 0)
        handler.apply(action, rm)
        assert rm.get_field_value("reg", "field") == 99

    def test_revert_calls_set_field_value_with_backward_patch_value(self):
        """revert → rm.set_field_value вызван с backward_patch['value']."""
        rm = MockRM()
        handler = FieldSetHandler()
        action = ActionBuilder.field_set("settings", "threshold", 42, 7)
        handler.revert(action, rm)
        assert ("settings", "threshold", 7) in rm.calls

    def test_revert_restores_old_value(self):
        """revert → старое значение восстановлено в регистре."""
        rm = MockRM()
        handler = FieldSetHandler()
        action = ActionBuilder.field_set("reg", "field", 100, 5)
        handler.revert(action, rm)
        assert rm.get_field_value("reg", "field") == 5

    def test_apply_missing_register_name_no_exception(self):
        """apply без register_name → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = FieldSetHandler()
        # Создаём action вручную без register_name
        action = Action(
            action_type=ActionType.FIELD_SET,
            register_name=None,
            field_name="field",
            forward_patch={"value": 1},
        )
        handler.apply(action, rm)  # не должно бросить исключение
        assert len(rm.calls) == 0

    def test_apply_missing_field_name_no_exception(self):
        """apply без field_name → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = FieldSetHandler()
        action = Action(
            action_type=ActionType.FIELD_SET,
            register_name="reg",
            field_name=None,
            forward_patch={"value": 1},
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0


# ---------------------------------------------------------------------------
# Тесты RegionActionHandler
# ---------------------------------------------------------------------------


class TestRegionActionHandler:
    """Тесты обработчика REGION_ADD / REGION_REMOVE действий."""

    def test_apply_writes_pipeline_after_to_rm(self):
        """apply → rm.set_field_value вызван с pipeline_after."""
        rm = MockRM()
        handler = RegionActionHandler()
        pipeline_after = [{"region": "roi_1"}]
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", "before_state", pipeline_after, register_name="processing"
        )
        handler.apply(action, rm)
        assert ("processing", "vision_pipeline", pipeline_after) in rm.calls

    def test_revert_writes_pipeline_before_to_rm(self):
        """revert → rm.set_field_value вызван с pipeline_before."""
        rm = MockRM()
        handler = RegionActionHandler()
        pipeline_before = [{"region": "original"}]
        action = ActionBuilder.region_remove(
            "cam_0", "roi_1", pipeline_before, "after_state", register_name="processing"
        )
        handler.revert(action, rm)
        assert ("processing", "vision_pipeline", pipeline_before) in rm.calls

    def test_apply_missing_register_name_no_exception(self):
        """apply без register_name → warning, нет исключения."""
        rm = MockRM()
        handler = RegionActionHandler()
        action = Action(
            action_type=ActionType.REGION_ADD,
            register_name=None,
            forward_patch={"pipeline_after": []},
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0

    def test_apply_missing_pipeline_after_no_exception(self):
        """apply с pipeline_after=None → warning, нет исключения."""
        rm = MockRM()
        handler = RegionActionHandler()
        action = Action(
            action_type=ActionType.REGION_ADD,
            register_name="processing",
            forward_patch={"pipeline_after": None},
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0


# ---------------------------------------------------------------------------
# Тесты ProfileSwitchHandler
# ---------------------------------------------------------------------------


class TestProfileSwitchHandler:
    """Тесты обработчика PROFILE_SWITCH действий."""

    def test_apply_writes_snapshot_fields_to_rm(self):
        """apply → поля из forward_patch['snapshot'] записаны в rm."""
        rm = MockRM()
        handler = ProfileSwitchHandler()
        snapshot_after = {"settings": {"threshold": 50, "mode": "fast"}}
        action = ActionBuilder.profile_switch("prof_1", {}, snapshot_after)
        handler.apply(action, rm)
        assert rm.get_field_value("settings", "threshold") == 50
        assert rm.get_field_value("settings", "mode") == "fast"

    def test_revert_restores_backward_snapshot(self):
        """revert → поля из backward_patch['snapshot'] восстановлены в rm."""
        rm = MockRM()
        handler = ProfileSwitchHandler()
        snapshot_before = {"settings": {"threshold": 0, "mode": "slow"}}
        action = ActionBuilder.profile_switch("prof_1", snapshot_before, {})
        handler.revert(action, rm)
        assert rm.get_field_value("settings", "threshold") == 0
        assert rm.get_field_value("settings", "mode") == "slow"

    def test_apply_missing_snapshot_no_exception(self):
        """apply без snapshot → warning, нет исключения."""
        rm = MockRM()
        handler = ProfileSwitchHandler()
        action = Action(
            action_type=ActionType.PROFILE_SWITCH,
            forward_patch={},  # нет snapshot
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0

    def test_apply_flat_snapshot_uses_settings_register(self):
        """apply с плоским snapshot (без вложенных dict) → записывает в SETTINGS_REGISTER."""
        from multiprocess_prototype.registers.constants import SETTINGS_REGISTER

        rm = MockRM()
        handler = ProfileSwitchHandler()
        # Плоский формат: {field_name: value}
        flat_snapshot = {"camera_count": 2}
        action = Action(
            action_type=ActionType.PROFILE_SWITCH,
            forward_patch={"snapshot": flat_snapshot},
        )
        handler.apply(action, rm)
        assert rm.get_field_value(SETTINGS_REGISTER, "camera_count") == 2


# ---------------------------------------------------------------------------
# Тесты RecipeSwitchHandler
# ---------------------------------------------------------------------------


class TestRecipeSwitchHandler:
    """Тесты обработчика RECIPE_SWITCH действий."""

    def test_apply_writes_forward_snapshot_to_rm(self):
        """apply → поля из forward_patch['snapshot'] записаны в rm."""
        rm = MockRM()
        handler = RecipeSwitchHandler()
        snapshot_after = {"processing": {"blur_radius": 5, "threshold": 128}}
        action = ActionBuilder.recipe_switch("slot_1", {}, snapshot_after)
        handler.apply(action, rm)
        assert rm.get_field_value("processing", "blur_radius") == 5
        assert rm.get_field_value("processing", "threshold") == 128

    def test_revert_restores_backward_snapshot(self):
        """revert → поля из backward_patch['snapshot'] восстановлены."""
        rm = MockRM()
        handler = RecipeSwitchHandler()
        snapshot_before = {"processing": {"blur_radius": 1}}
        action = ActionBuilder.recipe_switch("slot_1", snapshot_before, {})
        handler.revert(action, rm)
        assert rm.get_field_value("processing", "blur_radius") == 1

    def test_apply_missing_snapshot_no_exception(self):
        """apply без snapshot → warning, нет исключения."""
        rm = MockRM()
        handler = RecipeSwitchHandler()
        action = Action(
            action_type=ActionType.RECIPE_SWITCH,
            forward_patch={},  # нет snapshot
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0


# ---------------------------------------------------------------------------
# Тесты ChainActionHandler
# ---------------------------------------------------------------------------


class TestChainActionHandler:
    """Тесты обработчика STEP_ADD/REMOVE/MODIFY/REORDER действий."""

    def test_apply_with_pipeline_after_writes_to_rm(self):
        """apply с pipeline_after → rm.set_field_value вызван с vision_pipeline."""
        rm = MockRM()
        handler = ChainActionHandler()
        pipeline_after = [{"step": "blur"}]
        action = Action(
            action_type=ActionType.STEP_ADD,
            register_name="region_0",
            forward_patch={"pipeline_after": pipeline_after},
        )
        handler.apply(action, rm)
        assert ("region_0", "vision_pipeline", pipeline_after) in rm.calls

    def test_apply_with_nodes_snapshot_after_writes_to_rm(self):
        """apply с nodes_snapshot_after → rm.set_field_value вызван."""
        rm = MockRM()
        handler = ChainActionHandler()
        nodes_after = [{"node_id": "n1"}]
        action = Action(
            action_type=ActionType.STEP_REMOVE,
            register_name="region_0",
            forward_patch={"nodes_snapshot_after": nodes_after},
        )
        handler.apply(action, rm)
        assert ("region_0", "vision_pipeline", nodes_after) in rm.calls

    def test_apply_missing_data_no_exception(self):
        """apply без данных → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = ChainActionHandler()
        action = Action(
            action_type=ActionType.STEP_ADD,
            register_name="region_0",
            forward_patch={},  # нет данных
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0

    def test_apply_step_modify_no_rm_call(self):
        """apply для STEP_MODIFY с node_after → rm.set_field_value НЕ вызывается."""
        rm = MockRM()
        handler = ChainActionHandler()
        action = Action(
            action_type=ActionType.STEP_MODIFY,
            register_name="region_0",
            forward_patch={"node_id": "n1", "node_after": {"param": 5}},
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0  # STEP_MODIFY не пишет pipeline целиком


# ---------------------------------------------------------------------------
# Тесты DisplayActionHandler
# ---------------------------------------------------------------------------


class TestDisplayActionHandler:
    """Тесты обработчика DISPLAY_SUBSCRIBE/UNSUBSCRIBE/LAYOUT_CHANGE действий."""

    def test_apply_display_subscribe_no_exception(self):
        """apply для DISPLAY_SUBSCRIBE → только debug-лог, нет исключения."""
        rm = MockRM()
        handler = DisplayActionHandler(display_router=None)
        action = ActionBuilder.display_subscribe("camera_0", {})
        handler.apply(action, rm)  # не должно бросить исключение

    def test_apply_display_unsubscribe_no_exception(self):
        """apply для DISPLAY_UNSUBSCRIBE → только debug-лог, нет исключения."""
        rm = MockRM()
        handler = DisplayActionHandler(display_router=None)
        action = ActionBuilder.display_unsubscribe("camera_0")
        handler.apply(action, rm)  # не должно бросить исключение

    def test_apply_layout_change_calls_display_router_methods(self):
        """apply для LAYOUT_CHANGE → вызывает display_router.unsubscribe_all и subscribe."""
        rm = MockRM()
        mock_router = MagicMock()
        handler = DisplayActionHandler(display_router=mock_router)

        # Создаём подписки как объекты с subscription_id
        sub1 = MagicMock()
        sub1.subscription_id = "sub_1"
        subs_after = [sub1]

        action = ActionBuilder.layout_change("QUAD", [], subs_after)
        handler.apply(action, rm)

        mock_router.unsubscribe_all.assert_called_once()
        mock_router.subscribe.assert_called_once_with(sub1)

    def test_revert_layout_change_calls_display_router_with_backward_subs(self):
        """revert для LAYOUT_CHANGE → вызывает router с subscriptions_before."""
        rm = MockRM()
        mock_router = MagicMock()
        handler = DisplayActionHandler(display_router=mock_router)

        sub_before = MagicMock()
        sub_before.subscription_id = "sub_0"
        subs_before = [sub_before]

        action = ActionBuilder.layout_change("QUAD", subs_before, [])
        handler.revert(action, rm)

        mock_router.unsubscribe_all.assert_called_once()
        mock_router.subscribe.assert_called_once_with(sub_before)

    def test_apply_layout_change_no_router_no_exception(self):
        """apply для LAYOUT_CHANGE без router → warning, нет исключения."""
        rm = MockRM()
        handler = DisplayActionHandler(display_router=None)
        action = ActionBuilder.layout_change("SINGLE", [], [])
        handler.apply(action, rm)  # не должно бросить исключение
