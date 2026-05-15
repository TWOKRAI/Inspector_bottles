"""ActionBusRegistersManager — мост между framework-фасадами и ActionBus.

RegistersManagerLike-обёртка, превращающая set_field_value в ActionBus.execute(field_set).

read / subscribe / get_field_metadata / get_register делегируются в реальный RM.
set_field_value — единственное место разницы: строит field_set action и
отправляет в ActionBus, который вызывает FieldSetHandler.apply → rm.set_field_value
+ _notify_bridge (IPC в runtime worker через router_module).

Coalescing (V2ActionBuilder.field_set_timed, 1.5s bucket) — нативно через ActionBus.
Undo/Redo — нативно (action попадает в undo_stack).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from multiprocess_framework.modules.logger_module import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from multiprocess_framework.modules.actions_module.bus import ActionBus
    from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

    from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder


def _log(msg: str, level: str = "info") -> None:
    """Записать в LoggerManager (если инициализирован), иначе тихо."""
    lm = get_logger()
    if lm is None:
        return
    getattr(lm, level)(msg, module="action_bus_rm")


def _extract_field_value(reg: Any, field_name: str) -> Any:
    """Извлечь текущее значение поля из регистра.

    Повторяет логику RegisterAdapter._extract_value: если поле обёрнуто
    в объект с атрибутом `value` (legacy _Field) — разворачиваем.
    """
    val = getattr(reg, field_name, None)
    return getattr(val, "value", val) if val is not None else val


class ActionBusRegistersManager:
    """RegistersManagerLike-обёртка, превращающая write в ActionBus.execute(field_set).

    Фреймворк-фасады (CheckboxControl.create, NumericControl.create, ...)
    получают этот мост вместо «голого» RM — и автоматически наследуют
    coalescing, IPC bridge, undo/redo, audit pre/post hooks.
    """

    def __init__(
        self,
        real_rm: "IRegistersManagerGui",
        action_bus: "ActionBus",
        action_builder: "type[V2ActionBuilder]",
    ) -> None:
        self._rm = real_rm
        self._bus = action_bus
        self._builder = action_builder

    # ------------------------------------------------------------------
    # Делегирование read-операций в реальный RM
    # ------------------------------------------------------------------

    def get_register(self, name: str) -> Any:
        """Проксирование в реальный RM."""
        return self._rm.get_register(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> dict[str, Any]:
        """Проксирование в реальный RM."""
        return self._rm.get_field_metadata(register_name, field_name, **kwargs)

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: "Callable[[Any], None]",
    ) -> None:
        """Проксирование подписки в реальный RM."""
        if hasattr(self._rm, "subscribe"):
            self._rm.subscribe(register_name, field_name, callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: "Callable[[Any], None]",
    ) -> None:
        """Проксирование отписки в реальный RM."""
        if hasattr(self._rm, "unsubscribe"):
            self._rm.unsubscribe(register_name, field_name, callback)

    # ------------------------------------------------------------------
    # Write через ActionBus
    # ------------------------------------------------------------------

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        """Превратить write в ActionBus.execute(field_set_timed).

        Coalescing (1.5s bucket), undo/redo, IPC bridge — автоматически
        через ActionBus → FieldSetHandler.apply → rm.set_field_value + _notify_bridge.

        Returns:
            (True, None) — handler.apply() выполнился успешно.
            (False, error_msg) — ActionBus отклонил или handler error.
        """
        # Runtime thread guard: вызов из worker thread сломает blockSignals.
        # RuntimeError вместо assert — работает и при `python -O`.
        if not _is_gui_thread():
            raise RuntimeError("ActionBusRegistersManager.set_field_value must be called from GUI thread")

        # Извлечь текущее (old) значение для backward_patch
        reg = self._rm.get_register(register_name)
        old_value = _extract_field_value(reg, field_name) if reg is not None else None

        _log(f"[trace bus_rm] set_field_value: {register_name}.{field_name} = {value!r} (old={old_value!r})")

        # ПОРЯДОК АРГУМЕНТОВ: field_set_timed(register, field, NEW, OLD)
        # Перепутывание new/old → инвертированный undo (баг из ревью)
        action = self._builder.field_set_timed(
            register_name,
            field_name,
            value,
            old_value,
        )

        try:
            result = self._bus.execute(action)
        except Exception as exc:
            _log(f"[trace bus_rm] ActionBus.execute raised: {exc!r}", level="error")
            return (False, f"ActionBus handler error: {exc!r}")

        _log(f"[trace bus_rm] ActionBus.execute returned {result!r}")

        if result is True:
            return (True, None)
        return (False, "ActionBus rejected or no handler")


def _is_gui_thread() -> bool:
    """Проверить, что текущий поток — GUI thread."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            # В тестах без QApplication — пропускаем проверку
            return True
        return QThread.currentThread() == app.thread()
    except ImportError:
        return True
