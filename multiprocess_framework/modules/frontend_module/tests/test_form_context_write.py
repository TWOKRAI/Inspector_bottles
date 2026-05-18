# -*- coding: utf-8 -*-
"""Тесты FormContext.write — запись через ActionBus с coalescing и undo/redo.

4 unit-теста + 1 интеграционный (undo round-trip).
Тесты используют фейковый ActionBuilder и FieldSetHandler из прототипа.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegister:
    """Простой регистр с одним полем enabled."""

    enabled: bool = False


class _FakeRegistersManager:
    """Минимальный RM для тестов: get_register, set_field_value, subscribe."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "robot_control": _FakeRegister(enabled=False),
        }
        self._subs: dict[tuple[str, str], list] = {}

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> dict:
        return {}

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, value)
        for cb in list(self._subs.get((register_name, field_name), [])):
            cb(value)
        return True, None

    def subscribe(self, register_name: str, field_name: str, callback: Any) -> None:
        key = (register_name, field_name)
        self._subs.setdefault(key, []).append(callback)


class _FakeActionBuilder:
    """ActionBuilder для тестов без зависимости от V2ActionBuilder."""

    @staticmethod
    def field_set_timed(
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
    ) -> Action:
        return Action(
            action_type="field_set",
            register_name=register_name,
            field_name=field_name,
            forward_patch={"value": new_value},
            backward_patch={"value": old_value},
            undoable=True,
        )


class _FakeFieldSetHandler:
    """Минимальный handler: apply/revert через rm.set_field_value."""

    def apply(self, action: Action, rm: Any) -> None:
        value = action.forward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)

    def revert(self, action: Action, rm: Any) -> None:
        value = action.backward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)


class _RaisingFieldSetHandler:
    """Handler, который бросает исключение при apply."""

    def apply(self, action: Action, rm: Any) -> None:
        raise RuntimeError("handler exploded")

    def revert(self, action: Action, rm: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_rm():
    return _FakeRegistersManager()


@pytest.fixture
def bus_with_handler(fake_rm):
    """ActionBus с зарегистрированным FieldSetHandler."""
    bus = ActionBus(fake_rm, max_history=50)
    bus.register_handler("field_set", _FakeFieldSetHandler())
    return bus


@pytest.fixture
def form_ctx(fake_rm, bus_with_handler):
    """FormContext для тестов."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=_FakeActionBuilder,
    )


# ---------------------------------------------------------------------------
# Unit-тесты
# ---------------------------------------------------------------------------


class TestFormContextWrite:
    """4 unit-теста + 1 интеграционный на FormContext.write."""

    def test_write_creates_action_in_undo_stack(self, form_ctx, bus_with_handler, fake_rm):
        """Успешный write: action появляется в undo_stack, значение в RM обновлено."""
        ok = form_ctx.write("robot_control", "enabled", True, False)
        assert ok is True

        # Значение в RM обновлено
        assert fake_rm.get_register("robot_control").enabled is True

        # Action в undo_stack
        last = bus_with_handler.last_action()
        assert last is not None
        assert last.action_type == "field_set"
        assert last.register_name == "robot_control"
        assert last.field_name == "enabled"
        assert last.forward_patch["value"] is True
        assert last.backward_patch["value"] is False

    def test_write_returns_false_when_handler_rejects(self, fake_rm):
        """write возвращает False если pre_execute_hook отклоняет action."""
        bus = ActionBus(fake_rm, max_history=50)
        bus.register_handler("field_set", _FakeFieldSetHandler())
        bus.set_pre_execute_hook(lambda _action: False)

        rejected_msgs: list[str] = []
        ctx = FormContext(
            registers_manager=fake_rm,
            action_bus=bus,
            action_builder=_FakeActionBuilder,
            on_write_rejected=lambda msg: rejected_msgs.append(msg),
        )

        ok = ctx.write("robot_control", "enabled", True, False)
        assert ok is False

        # Значение НЕ изменилось
        assert fake_rm.get_register("robot_control").enabled is False

        # on_write_rejected был вызван
        assert len(rejected_msgs) == 1
        assert "rejected" in rejected_msgs[0].lower() or "no handler" in rejected_msgs[0].lower()

    def test_write_returns_false_on_exception(self, fake_rm):
        """write возвращает False если handler.apply бросает исключение."""
        bus = ActionBus(fake_rm, max_history=50)
        bus.register_handler("field_set", _RaisingFieldSetHandler())

        rejected_msgs: list[str] = []
        ctx = FormContext(
            registers_manager=fake_rm,
            action_bus=bus,
            action_builder=_FakeActionBuilder,
            on_write_rejected=lambda msg: rejected_msgs.append(msg),
        )

        ok = ctx.write("robot_control", "enabled", True, False)
        assert ok is False

        # on_write_rejected вызван с описанием ошибки
        assert len(rejected_msgs) == 1
        assert "ActionBus error" in rejected_msgs[0]

    def test_undo_rolls_back_value(self, form_ctx, bus_with_handler, fake_rm):
        """bus.undo() после write откатывает значение в RM."""
        form_ctx.write("robot_control", "enabled", True, False)
        assert fake_rm.get_register("robot_control").enabled is True

        # Undo
        bus_with_handler.undo()
        assert fake_rm.get_register("robot_control").enabled is False

    def test_write_without_on_write_rejected_callback(self, fake_rm):
        """write без on_write_rejected не падает при отклонении."""
        bus = ActionBus(fake_rm, max_history=50)
        bus.register_handler("field_set", _FakeFieldSetHandler())
        bus.set_pre_execute_hook(lambda _action: False)

        ctx = FormContext(
            registers_manager=fake_rm,
            action_bus=bus,
            action_builder=_FakeActionBuilder,
            # on_write_rejected=None — по умолчанию
        )

        # Не должно бросить исключение
        ok = ctx.write("robot_control", "enabled", True, False)
        assert ok is False
