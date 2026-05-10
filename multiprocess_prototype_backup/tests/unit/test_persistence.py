"""
Unit-тесты persistence-слоя ActionBus (Phase 7, Task 7D.4).

Проверяем: ActionLogRow roundtrip, ActionLogRotation, ActionLogRecovery.
Без реальной БД — только моки.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Добавляем корень multiprocess_prototype в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder
from frontend.actions.persistence.recovery import ActionLogRecovery
from frontend.actions.persistence.rotation import ActionLogRotation
from frontend.actions.persistence.schema_ext import (
    from_action_log_row,
    to_action_log_row,
)
from frontend.actions.schemas import Action, ActionType

# ---------------------------------------------------------------------------
# Мок RegistersManager
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data = {}

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
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
# Тесты ActionLogRow roundtrip
# ---------------------------------------------------------------------------


class TestActionLogRowRoundtrip:
    """Проверка конвертации Action → ActionLogRow → Action."""

    def test_roundtrip_preserves_action_id(self):
        """Roundtrip сохраняет action_id."""
        action = ActionBuilder.field_set("settings", "threshold", 42, 0)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.action_id == action.action_id

    def test_roundtrip_preserves_action_type(self):
        """Roundtrip сохраняет action_type как enum."""
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.action_type == ActionType.FIELD_SET

    def test_roundtrip_preserves_forward_patch(self):
        """Roundtrip сохраняет forward_patch (через JSON-сериализацию)."""
        action = ActionBuilder.field_set("reg", "field", 99, 0)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.forward_patch["value"] == 99

    def test_roundtrip_preserves_backward_patch(self):
        """Roundtrip сохраняет backward_patch."""
        action = ActionBuilder.field_set("reg", "field", 99, 7)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.backward_patch["value"] == 7

    def test_roundtrip_preserves_coalesce_key(self):
        """Roundtrip сохраняет coalesce_key."""
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.coalesce_key == action.coalesce_key

    def test_roundtrip_preserves_undoable(self):
        """Roundtrip сохраняет undoable."""
        action = ActionBuilder.command("cmd")
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.undoable is False

    def test_roundtrip_preserves_description(self):
        """Roundtrip сохраняет description."""
        action = ActionBuilder.command("Тестовая команда")
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.description == "Тестовая команда"

    def test_roundtrip_preserves_timestamp(self):
        """Roundtrip сохраняет timestamp."""
        action = ActionBuilder.field_set("reg", "f", 1, 0)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.timestamp == pytest.approx(action.timestamp)

    def test_to_action_log_row_serializes_patches_as_json_strings(self):
        """to_action_log_row → forward_patch_json и backward_patch_json — строки."""
        action = ActionBuilder.field_set("reg", "f", {"nested": True}, {})
        row = to_action_log_row(action)
        assert isinstance(row.forward_patch_json, str)
        assert isinstance(row.backward_patch_json, str)

    def test_roundtrip_profile_switch_snapshot(self):
        """Roundtrip для profile_switch со сложным snapshot."""
        snapshot = {"settings": {"threshold": 50, "mode": "fast"}}
        action = ActionBuilder.profile_switch("prof_1", {}, snapshot)
        row = to_action_log_row(action)
        restored = from_action_log_row(row)
        assert restored.forward_patch["snapshot"] == snapshot
        assert restored.action_type == ActionType.PROFILE_SWITCH

    def test_action_log_row_action_type_is_string(self):
        """ActionLogRow хранит action_type как строку (не enum)."""
        action = ActionBuilder.field_set("reg", "f", 1, 0)
        row = to_action_log_row(action)
        assert isinstance(row.action_type, str)
        assert row.action_type == "field_set"


# ---------------------------------------------------------------------------
# Тесты ActionLogRotation
# ---------------------------------------------------------------------------


class TestActionLogRotation:
    """Тесты ротации action_log при превышении порога."""

    def test_maybe_rotate_below_max_returns_false(self):
        """maybe_rotate с count < max_count → False, ротация не выполнена."""
        adapter = MagicMock()
        rotation = ActionLogRotation(adapter, max_count=100)
        result = rotation.maybe_rotate(50)
        assert result is False

    def test_maybe_rotate_at_max_count_returns_true(self):
        """maybe_rotate с count == max_count → ротация выполнена, возвращает True."""
        adapter = MagicMock()
        adapter.execute = MagicMock(return_value=None)
        rotation = ActionLogRotation(adapter, max_count=100)
        result = rotation.maybe_rotate(100)
        assert result is True

    def test_maybe_rotate_above_max_returns_true(self):
        """maybe_rotate с count > max_count → ротация выполнена, возвращает True."""
        adapter = MagicMock()
        adapter.execute = MagicMock(return_value=None)
        rotation = ActionLogRotation(adapter, max_count=100)
        result = rotation.maybe_rotate(200)
        assert result is True

    def test_maybe_rotate_calls_adapter_execute(self):
        """maybe_rotate при ротации → вызывает adapter.execute."""
        adapter = MagicMock()
        adapter.execute = MagicMock(return_value=None)
        rotation = ActionLogRotation(adapter, max_count=5)
        rotation.maybe_rotate(10)
        # Должно быть 2 вызова: CREATE TABLE + DELETE
        assert adapter.execute.call_count == 2

    def test_maybe_rotate_no_rotation_when_below_threshold(self):
        """maybe_rotate ниже порога → adapter.execute НЕ вызывается."""
        adapter = MagicMock()
        rotation = ActionLogRotation(adapter, max_count=1000)
        rotation.maybe_rotate(5)
        adapter.execute.assert_not_called()

    def test_maybe_rotate_returns_false_on_exception(self):
        """maybe_rotate при ошибке adapter → возвращает False (нет исключения)."""
        adapter = MagicMock()
        adapter.execute = MagicMock(side_effect=RuntimeError("DB error"))
        rotation = ActionLogRotation(adapter, max_count=10)
        result = rotation.maybe_rotate(20)
        assert result is False


# ---------------------------------------------------------------------------
# Тесты ActionLogRecovery
# ---------------------------------------------------------------------------


class TestActionLogRecovery:
    """Тесты восстановления состояния из action_log."""

    def _make_recovery(self, actions_in_log, handlers=None):
        """Создать ActionLogRecovery с мок-зависимостями."""
        from frontend.actions.bus import ActionBus

        rm = MockRM()
        bus = ActionBus(rm)

        # Регистрируем переданные handlers
        if handlers:
            for action_type, handler in handlers.items():
                bus.register_handler(action_type, handler)

        mock_repo = MagicMock()
        mock_repo.find_recent.return_value = actions_in_log

        recovery = ActionLogRecovery(
            repository=mock_repo,
            bus=bus,
            rm=rm,
            max_age_hours=24.0,
        )
        return recovery

    def test_recover_empty_log_returns_zero(self):
        """recover с пустым логом → возвращает 0 применённых действий."""
        recovery = self._make_recovery([])
        result = recovery.recover()
        assert result == 0

    def test_recover_applies_undoable_actions(self):
        """recover → применяет undoable actions через handler.apply."""
        from frontend.actions.handlers.field_set_handler import FieldSetHandler

        handler = FieldSetHandler()
        rm = MockRM()

        # Создаём action с timestamp в пределах 24 часов
        action = ActionBuilder.field_set("settings", "threshold", 50, 0)
        # Патчим timestamp чтобы точно попасть в окно
        action = action.model_copy(update={"timestamp": time.time()})

        from frontend.actions.bus import ActionBus

        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)

        mock_repo = MagicMock()
        mock_repo.find_recent.return_value = [action]

        recovery = ActionLogRecovery(repository=mock_repo, bus=bus, rm=rm, max_age_hours=24.0)
        result = recovery.recover()
        assert result == 1
        assert rm.get_field_value("settings", "threshold") == 50

    def test_recover_skips_non_undoable_actions(self):
        """recover → пропускает undoable=False actions."""
        action = ActionBuilder.command("cmd")
        action = action.model_copy(update={"timestamp": time.time()})
        recovery = self._make_recovery([action])
        result = recovery.recover()
        assert result == 0

    def test_recover_skips_old_actions(self):
        """recover → пропускает actions старше max_age_hours."""
        action = ActionBuilder.field_set("reg", "f", 1, 0)
        # Очень старый timestamp (30 часов назад)
        old_ts = time.time() - 30 * 3600
        action = action.model_copy(update={"timestamp": old_ts})
        recovery = self._make_recovery([action], max_age_hours=24.0)
        result = recovery.recover()
        assert result == 0

    def _make_recovery(self, actions_in_log, max_age_hours=24.0):
        """Создать ActionLogRecovery с мок-зависимостями (перегрузка)."""
        from frontend.actions.bus import ActionBus

        rm = MockRM()
        bus = ActionBus(rm)

        mock_repo = MagicMock()
        mock_repo.find_recent.return_value = actions_in_log

        recovery = ActionLogRecovery(
            repository=mock_repo,
            bus=bus,
            rm=rm,
            max_age_hours=max_age_hours,
        )
        return recovery

    def test_recover_repository_exception_returns_zero(self):
        """recover при ошибке репозитория → возвращает 0, нет исключения."""
        from frontend.actions.bus import ActionBus

        rm = MockRM()
        bus = ActionBus(rm)

        mock_repo = MagicMock()
        mock_repo.find_recent.side_effect = RuntimeError("DB error")

        recovery = ActionLogRecovery(repository=mock_repo, bus=bus, rm=rm, max_age_hours=24.0)
        result = recovery.recover()
        assert result == 0


class TestCompensateUndos:
    """Тесты статического метода _compensate_undos."""

    def test_compensate_removes_undo_pair(self):
        """_compensate_undos → удаляет пару [UNDO] и оригинал."""
        a1 = Action(
            action_type=ActionType.FIELD_SET,
            description="Изменить threshold",
            forward_patch={"value": 50},
            timestamp=1.0,
        )
        a2 = Action(
            action_type=ActionType.FIELD_SET,
            description="[UNDO] Изменить threshold",
            forward_patch={"value": 0},
            timestamp=2.0,
        )
        result = ActionLogRecovery._compensate_undos([a1, a2])
        assert len(result) == 0

    def test_compensate_keeps_unmatched_actions(self):
        """_compensate_undos → оставляет actions без [UNDO] пары."""
        a1 = Action(
            action_type=ActionType.FIELD_SET,
            description="Изменить threshold",
            forward_patch={"value": 50},
            timestamp=1.0,
        )
        a2 = Action(
            action_type=ActionType.FIELD_SET,
            description="Изменить mode",
            forward_patch={"value": "fast"},
            timestamp=2.0,
        )
        result = ActionLogRecovery._compensate_undos([a1, a2])
        assert len(result) == 2

    def test_compensate_removes_orphan_undo_record(self):
        """_compensate_undos → удаляет [UNDO] запись без оригинала."""
        a_undo = Action(
            action_type=ActionType.FIELD_SET,
            description="[UNDO] Несуществующее действие",
            forward_patch={"value": 0},
            timestamp=1.0,
        )
        result = ActionLogRecovery._compensate_undos([a_undo])
        assert len(result) == 0

    def test_compensate_empty_list_returns_empty(self):
        """_compensate_undos с пустым списком → пустой список."""
        result = ActionLogRecovery._compensate_undos([])
        assert result == []
