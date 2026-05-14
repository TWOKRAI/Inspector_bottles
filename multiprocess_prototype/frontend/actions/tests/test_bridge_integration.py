"""Тесты интеграции FieldSetHandler с TopologyBridge.

Проверяем:
- apply + bridge → bridge.on_field_set вызван
- revert + bridge → bridge.on_field_set вызван с old_value
- bridge=None → поведение без изменений (обратная совместимость)
- bridge.on_field_set возвращает False → log, не блокирует apply
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler


# --- Mock-объекты ---


@dataclass
class MockAction:
    """Мок Action с register_name, field_name, forward/backward_patch."""

    register_name: str = "color_mask"
    field_name: str = "h_min"
    forward_patch: dict[str, Any] | None = None
    backward_patch: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.forward_patch is None:
            self.forward_patch = {"value": 50}
        if self.backward_patch is None:
            self.backward_patch = {"value": 0}


class MockRM:
    """Мок RegistersManager."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, str | None]:
        self.calls.append((register_name, field_name, value))
        return True, None


class MockBridge:
    """Мок TopologyBridge — записывает on_field_set вызовы."""

    def __init__(self, return_value: bool = True) -> None:
        self._return = return_value
        self.calls: list[tuple[str, str, Any]] = []

    def on_field_set(self, plugin_name: str, field_name: str, value: Any) -> bool:
        self.calls.append((plugin_name, field_name, value))
        return self._return


# --- Тесты ---


class TestFieldSetHandlerWithBridge:
    def test_apply_calls_bridge(self) -> None:
        """apply → rm.set_field_value + bridge.on_field_set."""
        rm = MockRM()
        bridge = MockBridge()
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.apply(MockAction(), rm)

        assert len(rm.calls) == 1
        assert rm.calls[0] == ("color_mask", "h_min", 50)
        assert len(bridge.calls) == 1
        assert bridge.calls[0] == ("color_mask", "h_min", 50)

    def test_revert_calls_bridge(self) -> None:
        """revert → rm.set_field_value(old) + bridge.on_field_set(old)."""
        rm = MockRM()
        bridge = MockBridge()
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.revert(MockAction(), rm)

        assert rm.calls[0] == ("color_mask", "h_min", 0)
        assert bridge.calls[0] == ("color_mask", "h_min", 0)

    def test_no_bridge_backward_compat(self) -> None:
        """bridge=None → работает как раньше, без ошибок."""
        rm = MockRM()
        handler = FieldSetHandler()

        handler.apply(MockAction(), rm)

        assert len(rm.calls) == 1
        # Никаких исключений

    def test_bridge_reject_does_not_block_apply(self) -> None:
        """bridge.on_field_set() = False → apply всё равно выполнен в rm."""
        rm = MockRM()
        bridge = MockBridge(return_value=False)
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.apply(MockAction(), rm)

        # rm обновлён
        assert len(rm.calls) == 1
        # bridge вызван, но отклонил — это OK
        assert len(bridge.calls) == 1

    def test_apply_with_empty_register_name(self) -> None:
        """Пустой register_name → ни rm, ни bridge не вызываются."""
        rm = MockRM()
        bridge = MockBridge()
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.apply(MockAction(register_name=""), rm)

        assert len(rm.calls) == 0
        assert len(bridge.calls) == 0

    def test_apply_rm_fail_no_bridge_call(self) -> None:
        """rm.set_field_value() вернул (False, err) → bridge НЕ вызывается."""

        class FailRM:
            def set_field_value(self, reg: str, field: str, val: Any) -> tuple[bool, str | None]:
                return False, "validation error"

        bridge = MockBridge()
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.apply(MockAction(), FailRM())

        # bridge НЕ вызван, т.к. rm отклонил
        assert len(bridge.calls) == 0

    def test_multiple_apply_revert_cycle(self) -> None:
        """Цикл apply → revert — оба вызывают bridge."""
        rm = MockRM()
        bridge = MockBridge()
        handler = FieldSetHandler(topology_bridge=bridge)

        handler.apply(MockAction(), rm)
        handler.revert(MockAction(), rm)

        assert len(bridge.calls) == 2
        assert bridge.calls[0][2] == 50  # forward
        assert bridge.calls[1][2] == 0  # backward
