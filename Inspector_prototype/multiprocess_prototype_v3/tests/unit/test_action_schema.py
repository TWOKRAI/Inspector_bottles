"""
Unit-тесты схемы Action (Phase 7, Task 7D.4).

Проверяем: auto-UUID, auto-timestamp, roundtrip model_dump/model_validate,
сериализацию forward_patch с различными типами.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем корень multiprocess_prototype_v3 в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.schemas import Action, ActionType


class TestActionAutoFields:
    """Проверка автоматически заполняемых полей Action."""

    def test_action_creates_with_non_empty_uuid(self):
        """Action() создаётся с непустым action_id (UUID4)."""
        action = Action(action_type=ActionType.FIELD_SET)
        assert isinstance(action.action_id, str)
        assert len(action.action_id) > 0

    def test_action_uuid_is_unique(self):
        """Два Action() получают разные action_id."""
        a1 = Action(action_type=ActionType.FIELD_SET)
        a2 = Action(action_type=ActionType.FIELD_SET)
        assert a1.action_id != a2.action_id

    def test_action_creates_with_positive_timestamp(self):
        """Action() создаётся с timestamp > 0 (unix epoch)."""
        action = Action(action_type=ActionType.FIELD_SET)
        assert action.timestamp > 0.0

    def test_action_timestamp_is_recent(self):
        """Timestamp Action близок к текущему времени."""
        import time

        before = time.time()
        action = Action(action_type=ActionType.FIELD_SET)
        after = time.time()
        assert before <= action.timestamp <= after


class TestActionRoundtrip:
    """Проверка roundtrip model_dump / model_validate."""

    def test_roundtrip_preserves_action_id(self):
        """Roundtrip сохраняет action_id."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 42},
            backward_patch={"value": 0},
        )
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.action_id == action.action_id

    def test_roundtrip_preserves_action_type(self):
        """Roundtrip сохраняет action_type."""
        action = Action(action_type=ActionType.REGION_ADD)
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.action_type == ActionType.REGION_ADD

    def test_roundtrip_preserves_forward_patch(self):
        """Roundtrip сохраняет forward_patch."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            forward_patch={"value": 99, "extra": "hello"},
        )
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.forward_patch == {"value": 99, "extra": "hello"}

    def test_roundtrip_preserves_backward_patch(self):
        """Roundtrip сохраняет backward_patch."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            backward_patch={"value": 0},
        )
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.backward_patch == {"value": 0}

    def test_roundtrip_preserves_timestamp(self):
        """Roundtrip сохраняет timestamp без потери точности."""
        action = Action(action_type=ActionType.COMMAND)
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.timestamp == pytest.approx(action.timestamp)

    def test_roundtrip_preserves_coalesce_key(self):
        """Roundtrip сохраняет coalesce_key."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            coalesce_key="field:settings.threshold",
        )
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.coalesce_key == "field:settings.threshold"

    def test_roundtrip_preserves_undoable_false(self):
        """Roundtrip сохраняет undoable=False."""
        action = Action(action_type=ActionType.COMMAND, undoable=False)
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.undoable is False

    def test_roundtrip_preserves_description(self):
        """Roundtrip сохраняет description."""
        action = Action(action_type=ActionType.COMMAND, description="Тестовая команда")
        data = action.model_dump()
        restored = Action.model_validate(data)
        assert restored.description == "Тестовая команда"


class TestActionForwardPatchTypes:
    """Проверка сериализации forward_patch с различными типами."""

    def test_forward_patch_with_int(self):
        """forward_patch с int значением сохраняется корректно."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            forward_patch={"value": 123},
        )
        assert action.forward_patch["value"] == 123

    def test_forward_patch_with_float(self):
        """forward_patch с float значением сохраняется корректно."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            forward_patch={"value": 3.14},
        )
        assert action.forward_patch["value"] == pytest.approx(3.14)

    def test_forward_patch_with_string(self):
        """forward_patch со строкой сохраняется корректно."""
        action = Action(
            action_type=ActionType.FIELD_SET,
            forward_patch={"value": "hello"},
        )
        assert action.forward_patch["value"] == "hello"

    def test_forward_patch_with_list(self):
        """forward_patch со списком сохраняется корректно."""
        action = Action(
            action_type=ActionType.REGION_ADD,
            forward_patch={"pipeline_after": [1, 2, 3]},
        )
        assert action.forward_patch["pipeline_after"] == [1, 2, 3]

    def test_forward_patch_with_nested_dict(self):
        """forward_patch с вложенным dict сохраняется корректно."""
        snapshot = {"settings": {"threshold": 50, "mode": "auto"}}
        action = Action(
            action_type=ActionType.PROFILE_SWITCH,
            forward_patch={"profile_id": "profile_1", "snapshot": snapshot},
        )
        assert action.forward_patch["snapshot"] == snapshot

    def test_forward_patch_with_none_value(self):
        """forward_patch с None значением сохраняется корректно."""
        action = Action(
            action_type=ActionType.REGION_ADD,
            forward_patch={"pipeline_after": None},
        )
        assert action.forward_patch["pipeline_after"] is None

    def test_default_forward_patch_is_empty_dict(self):
        """forward_patch по умолчанию — пустой dict."""
        action = Action(action_type=ActionType.COMMAND)
        assert action.forward_patch == {}

    def test_default_backward_patch_is_empty_dict(self):
        """backward_patch по умолчанию — пустой dict."""
        action = Action(action_type=ActionType.COMMAND)
        assert action.backward_patch == {}
