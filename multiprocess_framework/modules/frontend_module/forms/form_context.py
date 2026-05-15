"""FormContext — единый контекст для создания form-виджетов.

Объединяет: RegistersManager, ActionBus, action_builder, access_level,
опциональные callable-хуки on_write_rejected / on_access_denied.

Живёт в framework чтобы прототип мог быть переиспользован как библиотека.
V2ActionBuilder, RegistersManagerV2 и AppContext остаются в прототипе пока,
но FormContext не зависит от них напрямую — использует Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.bus import ActionBus
    from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui


class ActionBuilderProtocol(Protocol):
    """Минимальный интерфейс action_builder, нужный FormContext.

    Позволяет типизировать action_builder без прямого импорта V2ActionBuilder
    (который живёт в прототипе). Соблюдает Layer-rule: FW не импортирует prototype.
    """

    @staticmethod
    def field_set_timed(register: str, field: str, new_value: Any, old_value: Any) -> Any:
        """Построить field_set action с временной меткой для coalescing."""
        ...


@dataclass(frozen=True)
class FormContext:
    """Единый контекст для построения form-виджетов.

    Заменяет FormBuildingContext из прототипа. BindingConfig передаётся
    отдельно — он специфичен для конкретного поля.

    Поля:
        registers_manager:  IRegistersManagerGui — источник данных регистров.
        action_bus:         ActionBus — шина действий для undo/redo.
        action_builder:     Объект/класс, реализующий ActionBuilderProtocol.
        access_level:       Текущий уровень доступа пользователя (0 = гость).
        on_write_rejected:  Опциональный callback при отклонённой записи.
        on_access_denied:   Опциональный callback при недостаточном доступе.
    """

    registers_manager: "IRegistersManagerGui"
    action_bus: "ActionBus"
    action_builder: "ActionBuilderProtocol"
    access_level: int = 0
    on_write_rejected: Optional[Callable[[str], None]] = None
    on_access_denied: Optional[Callable[[str], None]] = None

    def write(
        self,
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
    ) -> bool:
        """Записать значение через ActionBus с coalescing + undo/redo.

        Используется framework-фасадами вместо прямого rm.set_field_value,
        чтобы изменения попали в undo_stack и IPC bridge.

        Returns:
            True если ActionBus принял action и handler.apply прошёл.
            False если pre_execute_hook отклонил, handler not found,
                или handler.apply бросил исключение.
        """
        # Thread-guard: subscriber-callbacks из RM._notify_observers идут
        # синхронно в текущем потоке. Контракт: всё пишем из GUI thread.
        try:
            from PySide6.QtCore import QThread
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None and QThread.currentThread() != app.thread():
                raise RuntimeError("FormContext.write must be called from GUI thread")
        except ImportError:
            pass  # PySide6 не доступен (CI без Qt) — пропускаем guard

        action = self.action_builder.field_set_timed(register_name, field_name, new_value, old_value)
        try:
            result = self.action_bus.execute(action)
        except Exception as exc:
            if self.on_write_rejected is not None:
                self.on_write_rejected(f"ActionBus error: {exc!r}")
            return False

        if not result:
            if self.on_write_rejected is not None:
                self.on_write_rejected("ActionBus rejected or no handler")
            return False
        return True
