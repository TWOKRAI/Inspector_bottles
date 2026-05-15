"""Тесты ActionBusRegistersManager — мост между framework-фасадами и ActionBus.

5 unit-тестов + 1 интеграционный pytest-qt round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_prototype.frontend.actions.action_bus_register_adapter import (
    ActionBusRegistersManager,
)
from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import (
    FieldSetHandler,
)


# ---------------------------------------------------------------------------
# Фейковый RegistersManager (паттерн из test_controls_v2_base.py)
# ---------------------------------------------------------------------------


@dataclass
class _Field:
    value: Any


@dataclass
class _FakeRegister:
    """Простой регистр с одним полем enabled."""

    enabled: bool = False


class _FakeRegistersManager:
    """Минимальный RM для тестов: get_register, set_field_value, subscribe, get_field_metadata."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "robot_control": _FakeRegister(enabled=False),
        }
        self._subs: dict[tuple[str, str], list] = {}
        self._meta: dict[tuple[str, str], dict] = {
            ("robot_control", "enabled"): {"description": "Включена ли отбраковка"},
        }

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> dict:
        return self._meta.get((register_name, field_name), {})

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

    def unsubscribe(self, register_name: str, field_name: str, callback: Any) -> None:
        key = (register_name, field_name)
        lst = self._subs.get(key)
        if lst and callback in lst:
            lst.remove(callback)


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
    bus.register_handler("field_set", FieldSetHandler())
    return bus


@pytest.fixture
def adapter(fake_rm, bus_with_handler):
    """ActionBusRegistersManager для тестов."""
    return ActionBusRegistersManager(fake_rm, bus_with_handler, V2ActionBuilder)


# ---------------------------------------------------------------------------
# Unit-тесты
# ---------------------------------------------------------------------------


class TestActionBusRegistersManagerUnit:
    """5 unit-тестов на ActionBusRegistersManager."""

    def test_write_builds_field_set_action_with_correct_coalesce_key(self, adapter, bus_with_handler):
        """write строит field_set action с правильным coalesce_key."""
        ok, err = adapter.set_field_value("robot_control", "enabled", True)
        assert ok is True
        assert err is None

        # Проверить, что action в undo_stack
        last = bus_with_handler.last_action()
        assert last is not None
        assert last.action_type == "field_set"
        assert last.register_name == "robot_control"
        assert last.field_name == "enabled"
        assert last.forward_patch["value"] is True
        assert last.backward_patch["value"] is False
        # coalesce_key должен начинаться с "field:robot_control.enabled:"
        assert last.coalesce_key.startswith("field:robot_control.enabled:")

    def test_write_calls_bus_execute_and_returns_true(self, adapter, bus_with_handler, fake_rm):
        """write вызывает bus.execute(action) и возвращает (True, None)."""
        ok, err = adapter.set_field_value("robot_control", "enabled", True)
        assert ok is True
        assert err is None
        # Значение должно быть обновлено через FieldSetHandler → rm.set_field_value
        reg = fake_rm.get_register("robot_control")
        assert reg.enabled is True

    def test_write_returns_false_when_bus_rejects(self, fake_rm):
        """write возвращает (False, err) если bus отклоняет (pre_execute_hook returns False)."""
        bus = ActionBus(fake_rm, max_history=50)
        bus.register_handler("field_set", FieldSetHandler())
        # Установить pre_execute_hook, который всё блокирует
        bus.set_pre_execute_hook(lambda action: False)
        adapter = ActionBusRegistersManager(fake_rm, bus, V2ActionBuilder)

        ok, err = adapter.set_field_value("robot_control", "enabled", True)
        assert ok is False
        assert "rejected" in err.lower() or "no handler" in err.lower()
        # Значение НЕ должно было измениться
        assert fake_rm.get_register("robot_control").enabled is False

    def test_read_subscribe_metadata_delegate_to_real_rm(self, adapter, fake_rm):
        """read/subscribe/get_field_metadata/get_register делегируются в реальный RM."""
        # get_register
        reg = adapter.get_register("robot_control")
        assert reg is not None
        assert reg is fake_rm.get_register("robot_control")

        # get_field_metadata
        meta = adapter.get_field_metadata("robot_control", "enabled")
        assert meta == {"description": "Включена ли отбраковка"}

        # subscribe
        received: list = []
        adapter.subscribe("robot_control", "enabled", lambda v: received.append(v))
        # Прямой set на RM чтобы проверить callback
        fake_rm.set_field_value("robot_control", "enabled", True)
        assert received == [True]

    def test_coalescing_two_fast_writes_one_action_in_undo_stack(self, adapter, bus_with_handler, fake_rm):
        """Coalescing: два быстрых write → один action в undo_stack."""
        # Оба вызова в рамках одного time-bucket (1.5s)
        adapter.set_field_value("robot_control", "enabled", True)
        adapter.set_field_value("robot_control", "enabled", False)

        # В undo_stack должен быть один (merged) action
        history = bus_with_handler.history(100)
        assert len(history) == 1
        merged = history[0]
        # forward_patch от последнего write, backward_patch от первого
        assert merged.forward_patch["value"] is False
        assert merged.backward_patch["value"] is False  # old до первого write


# ---------------------------------------------------------------------------
# Интеграционный pytest-qt round-trip тест
# ---------------------------------------------------------------------------


class TestActionBusRegistersManagerIntegration:
    """Интеграционный тест: CheckboxControl + ActionBusRegistersManager + undo."""

    def test_checkbox_click_creates_action_then_undo_reverts(self, qtbot):
        """Round-trip: CheckboxControl click → action в undo_stack → bus.undo() → view откат."""
        from multiprocess_framework.modules.frontend_module.components.base.config import (
            BindingConfig,
        )
        from multiprocess_framework.modules.frontend_module.components.checkbox import (
            CheckboxControl,
            CheckboxViewConfig,
        )

        # 1. Собрать инфраструктуру
        rm = _FakeRegistersManager()
        bus = ActionBus(rm, max_history=50)
        bus.register_handler("field_set", FieldSetHandler())
        bus_rm = ActionBusRegistersManager(rm, bus, V2ActionBuilder)

        # 2. Создать CheckboxControl через фасад фреймворка
        result = CheckboxControl.create(
            bus_rm,
            BindingConfig("robot_control", "enabled"),
            CheckboxViewConfig(label="Включено"),
        )
        qtbot.addWidget(result.widget)

        # Исходное состояние: register = False, checkbox = False
        assert rm.get_register("robot_control").enabled is False
        assert result.widget.get_value() is False

        # 3. Эмулируем клик пользователя: set_value (не silent) →
        #    presenter._on_changed → adapter.write → bus.execute → FieldSetHandler.apply
        result.widget.set_value(True)

        # 4. Assert: action в undo_stack, значение в RM обновлено
        assert bus.can_undo() is True
        assert rm.get_register("robot_control").enabled is True
        last = bus.last_action()
        assert last is not None
        assert last.action_type == "field_set"
        assert last.forward_patch["value"] is True

        # 5. Undo → значение в RM откатилось, view обновился
        bus.undo()
        assert rm.get_register("robot_control").enabled is False
        # View тоже должен откатиться (через subscribe callback)
        assert result.widget.get_value() is False

    def test_binding_aware_checkbox_in_register_view_single_action(self, qtbot):
        """Регрессия: binding-aware checkbox через RegisterView — один user-click = один action.

        До фикса: change_signal=value_changed попадал в RegisterView._on_editor_changed →
        field_changed → PluginsTab._on_field_changed → bus.execute(action2),
        параллельно presenter уже создавал action1. Результат: два action на один клик,
        Ctrl+Z откатывал только последний.

        После фикса: change_signal=None → RegisterView НЕ подключается к value_changed,
        write идёт только через presenter → ActionBusRegistersManager.
        """
        from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
        from multiprocess_prototype.frontend.forms.register_view import RegisterView
        from multiprocess_prototype.registers.field_info import FieldInfo

        # 1. Собрать инфраструктуру
        rm = _FakeRegistersManager()
        bus = ActionBus(rm, max_history=50)
        bus.register_handler("field_set", FieldSetHandler())

        form_ctx = FormContext(
            registers_manager=rm,
            action_bus=bus,
            action_builder=V2ActionBuilder,
        )

        # 2. Создать RegisterView с одним bool-полем через form_ctx
        fi = FieldInfo(
            plugin_name="robot_control",
            field_name="enabled",
            field_type=bool,
            default=False,
        )
        view = RegisterView([fi], form_ctx=form_ctx)
        qtbot.addWidget(view)

        # Подсчитаем сколько раз field_changed эмитится
        field_changed_count = [0]
        view.field_changed.connect(lambda *_args: field_changed_count.__setitem__(0, field_changed_count[0] + 1))

        # 3. Эмулируем user-click через set_value (не silent)
        editors = view.editors()
        key = list(editors.keys())[0]
        editor = editors[key]
        editor.widget.set_value(True)

        # 4. Assert: РОВНО один action в undo_stack (не два)
        history = bus.history(100)
        assert len(history) == 1, (
            f"Ожидался 1 action в undo_stack, получено {len(history)}. "
            "Двойная запись: RegisterView._on_editor_changed дублирует presenter path."
        )

        # 5. field_changed НЕ должен был эмититься для binding-aware поля
        # (change_signal=None → RegisterView не подключил _on_editor_changed)
        assert field_changed_count[0] == 0, (
            f"field_changed эмитился {field_changed_count[0]} раз(а) для binding-aware поля. "
            "change_signal должен быть None для binding-aware editors."
        )

        # 6. Undo корректно откатывает (один Ctrl+Z = полный откат)
        bus.undo()
        assert rm.get_register("robot_control").enabled is False
        assert editor.widget.get_value() is False
