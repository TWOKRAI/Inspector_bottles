"""
ActionBus -- шина выполнения действий с undo/redo и coalescing.

Единственная точка входа для мутации состояния через Action.
Содержит undo/redo стеки, handler-реестр, callback-уведомления
и coalescing для группировки последовательных однотипных изменений.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable

from .schemas import Action

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.persistence.interfaces import IActionLogWriter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Протоколы
# ---------------------------------------------------------------------------


@runtime_checkable
class IRegistersManagerGui(Protocol):
    """Протокол для RegistersManager на стороне GUI."""

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        """Установить значение поля регистра. Возвращает (ok, error_msg)."""
        ...


@runtime_checkable
class ActionHandler(Protocol):
    """Протокол обработчика действия (apply / revert)."""

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить действие (forward)."""
        ...

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить действие (backward)."""
        ...


# ---------------------------------------------------------------------------
# ActionBus
# ---------------------------------------------------------------------------


class ActionBus:
    """
    Шина действий с undo/redo, coalescing и callback-уведомлениями.

    Один экземпляр на приложение (создаётся при инициализации frontend).
    """

    def __init__(
        self,
        rm: IRegistersManagerGui,
        *,
        max_history: int = 200,
    ) -> None:
        self._rm = rm
        self._max_history = max_history

        self._undo_stack: list[Action] = []
        self._redo_stack: list[Action] = []
        self._handlers: dict[str, ActionHandler] = {}
        self._change_callbacks: list[Callable[[], None]] = []

        # Последнее событие: ("execute" | "undo" | "redo", action)
        # Нужно для статус-бара
        self._last_event: tuple[str, Action] | None = None

        # Опциональный writer для персистентного логирования действий
        self._log_writer: IActionLogWriter | None = None

        # Pre-execute хук: вызывается перед handler.apply() в execute().
        # hook(action) -> bool: True — выполнять, False — заблокировать.
        # Undo/redo хук НЕ проходят — блокируется только новая мутация.
        self._pre_execute_hook: Callable[[Action], bool] | None = None
        self._on_blocked_callback: Callable[[Action], None] | None = None

        # Post-execute callbacks: вызываются ПОСЛЕ успешного handler.apply()
        # в execute() (не при undo/redo). Принимают Action как аргумент.
        # Используются для audit middleware (PR4).
        self._post_execute_callbacks: list[Callable[[Action], None]] = []

    # ------------------------------------------------------------------
    # Регистрация обработчиков
    # ------------------------------------------------------------------

    def register_handler(
        self,
        action_type: str,
        handler: ActionHandler,
    ) -> None:
        """Зарегистрировать handler для конкретного action_type."""
        self._handlers[action_type] = handler

    # ------------------------------------------------------------------
    # Log writer
    # ------------------------------------------------------------------

    def set_log_writer(self, writer: IActionLogWriter | None) -> None:
        """Установить ActionLogWriter для персистентного логирования действий.

        writer=None отключает логирование (полезно в тестах или при выключенной БД).
        """
        self._log_writer = writer

    # ------------------------------------------------------------------
    # Pre-execute hook (AD-1, PR2 auth-rbac)
    # ------------------------------------------------------------------

    def set_pre_execute_hook(
        self,
        hook: Callable[[Action], bool],
        on_blocked: Callable[[Action], None] | None = None,
    ) -> None:
        """Установить pre-execute хук.

        hook(action) -> bool: True — выполнять, False — заблокировать.
        on_blocked(action): вызывается при блокировке (например, показ диалога).
        Один хук (last-write wins). Если уже установлен — заменяется.
        """
        self._pre_execute_hook = hook
        self._on_blocked_callback = on_blocked

    def clear_pre_execute_hook(self) -> None:
        """Сбросить pre-execute хук."""
        self._pre_execute_hook = None
        self._on_blocked_callback = None

    # ------------------------------------------------------------------
    # Post-execute callbacks (PR4 audit)
    # ------------------------------------------------------------------

    def add_post_execute_callback(self, cb: Callable[[Action], None]) -> None:
        """Добавить post-execute callback.

        Вызывается после успешного handler.apply() в execute().
        Undo/redo не триггерят этот callback — только новые действия.

        Args:
            cb: Вызываемый объект, принимающий Action как единственный аргумент.
        """
        if cb not in self._post_execute_callbacks:
            self._post_execute_callbacks.append(cb)

    def remove_post_execute_callback(self, cb: Callable[[Action], None]) -> None:
        """Убрать post-execute callback.

        Args:
            cb: Ранее зарегистрированный callback.
        """
        try:
            self._post_execute_callbacks.remove(cb)
        except ValueError:
            pass

    def _notify_post_execute(self, action: Action) -> None:
        """Вызвать все зарегистрированные post-execute callbacks.

        Исключение из одного callback не прерывает остальные.
        """
        for cb in self._post_execute_callbacks:
            try:
                cb(action)
            except Exception:
                logger.exception(
                    "Ошибка в post-execute callback %r, action_type=%s",
                    cb,
                    action.action_type,
                )

    # ------------------------------------------------------------------
    # Основные операции
    # ------------------------------------------------------------------

    def execute(self, action: Action) -> None:
        """
        Выполнить действие: вызвать handler.apply, добавить в undo_stack.

        Coalescing: если coalesce_key совпадает с последним в стеке,
        merged action заменяет последний (backward_patch от старого,
        forward_patch от нового).

        COMMAND (undoable=False): выполняется, но НЕ добавляется в стек.

        Pre-execute hook: если задан и вернул False — action не выполняется,
        undo_stack не изменяется, on_blocked вызывается. Undo/redo хук не проходят.
        """
        # Pre-execute hook (AD-1, PR2 auth-rbac)
        if self._pre_execute_hook is not None:
            if not self._pre_execute_hook(action):
                if self._on_blocked_callback is not None:
                    self._on_blocked_callback(action)
                return

        handler = self._handlers.get(action.action_type)
        if handler is None:
            logger.warning(
                "Handler не зарегистрирован для %s, action пропущен",
                action.action_type,
            )
            return

        # Применяем действие
        handler.apply(action, self._rm)

        # Post-execute callbacks (audit middleware и др.)
        # Вызываются сразу после apply, до undo-стека
        self._notify_post_execute(action)

        # COMMAND -- не попадает в undo-стек
        if not action.undoable:
            self._last_event = ("execute", action)
            self._notify_callbacks()
            return

        # Coalescing
        if (
            action.coalesce_key is not None
            and self._undo_stack
            and self._undo_stack[-1].coalesce_key == action.coalesce_key
        ):
            prev = self._undo_stack[-1]
            # Merged action: backward_patch от первого, всё остальное от нового
            merged = action.model_copy(
                update={"backward_patch": prev.backward_patch},
            )
            self._undo_stack[-1] = merged
        else:
            self._undo_stack.append(action)

        # Ограничение размера стека
        if len(self._undo_stack) > self._max_history:
            # Удаляем самые старые записи
            overflow = len(self._undo_stack) - self._max_history
            self._undo_stack = self._undo_stack[overflow:]

        # Новое действие сбрасывает redo-стек
        self._redo_stack.clear()

        self._last_event = ("execute", action)
        self._notify_callbacks()

        # Логируем undoable actions через writer (если установлен)
        if self._log_writer is not None:
            # Берём актуальный (возможно merged) action из вершины стека
            logged_action = self._undo_stack[-1] if self._undo_stack else action
            self._log_writer.enqueue(logged_action)

    def record(self, action: Action) -> None:
        """Записать действие, уже применённое извне, в undo-стек (без вызова handler.apply).

        Используется для profile_switch / recipe_switch -- когда switch уже выполнен,
        но действие нужно зафиксировать для undo/redo.
        """
        # COMMAND -- не попадает в undo-стек
        if not action.undoable:
            self._last_event = ("execute", action)
            self._notify_callbacks()
            return

        # Coalescing
        if (
            action.coalesce_key is not None
            and self._undo_stack
            and self._undo_stack[-1].coalesce_key == action.coalesce_key
        ):
            prev = self._undo_stack[-1]
            merged = action.model_copy(
                update={"backward_patch": prev.backward_patch},
            )
            self._undo_stack[-1] = merged
        else:
            self._undo_stack.append(action)

        # Ограничение размера стека
        if len(self._undo_stack) > self._max_history:
            overflow = len(self._undo_stack) - self._max_history
            self._undo_stack = self._undo_stack[overflow:]

        # Новое действие сбрасывает redo-стек
        self._redo_stack.clear()

        self._last_event = ("execute", action)
        self._notify_callbacks()

        # Логируем через writer (если установлен)
        if self._log_writer is not None:
            logged_action = self._undo_stack[-1] if self._undo_stack else action
            self._log_writer.enqueue(logged_action)

    def undo(self) -> Action | None:
        """
        Отменить последнее действие.

        Вызывает handler.revert, перемещает action в redo_stack.
        Возвращает отменённый Action или None, если стек пуст.
        """
        if not self._undo_stack:
            return None

        action = self._undo_stack.pop()

        handler = self._handlers.get(action.action_type)
        if handler is None:
            logger.warning(
                "Handler не зарегистрирован для %s при undo, action пропущен",
                action.action_type,
            )
            return None

        handler.revert(action, self._rm)
        self._redo_stack.append(action)

        self._last_event = ("undo", action)
        self._notify_callbacks()
        return action

    def redo(self) -> Action | None:
        """
        Повторить последнее отменённое действие.

        Вызывает handler.apply, возвращает action в undo_stack.
        Возвращает повторённый Action или None, если стек пуст.
        """
        if not self._redo_stack:
            return None

        action = self._redo_stack.pop()

        handler = self._handlers.get(action.action_type)
        if handler is None:
            logger.warning(
                "Handler не зарегистрирован для %s при redo, action пропущен",
                action.action_type,
            )
            return None

        handler.apply(action, self._rm)
        self._undo_stack.append(action)

        self._last_event = ("redo", action)
        self._notify_callbacks()
        return action

    def undo_to(self, target_action_id: str) -> int:
        """
        Откатить undo-стек до action с указанным action_id (включительно).

        Возвращает количество выполненных шагов undo.
        Если action_id не найден в стеке -- возвращает 0, ничего не делает.
        """
        # Проверяем, что target_action_id есть в стеке
        target_idx = None
        for i, a in enumerate(self._undo_stack):
            if a.action_id == target_action_id:
                target_idx = i
                break

        if target_idx is None:
            logger.warning(
                "action_id=%s не найден в undo-стеке",
                target_action_id,
            )
            return 0

        # Откатываем от вершины стека до target_idx (включительно)
        steps = len(self._undo_stack) - target_idx
        for _ in range(steps):
            result = self.undo()
            if result is None:
                break

        return steps

    # ------------------------------------------------------------------
    # Запросы состояния
    # ------------------------------------------------------------------

    def can_undo(self) -> bool:
        """Есть ли действия для отмены."""
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        """Есть ли действия для повтора."""
        return len(self._redo_stack) > 0

    def history(self, n: int = 20) -> list[Action]:
        """Последние n действий из undo-стека (от старых к новым)."""
        return list(self._undo_stack[-n:])

    def last_action(self) -> Action | None:
        """Последний Action в undo-стеке или None."""
        return self._undo_stack[-1] if self._undo_stack else None

    @property
    def last_event(self) -> tuple[str, Action] | None:
        """Последнее событие: ('execute'|'undo'|'redo', action)."""
        return self._last_event

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        """Подписаться на уведомления об изменениях (execute/undo/redo)."""
        if cb not in self._change_callbacks:
            self._change_callbacks.append(cb)

    def remove_change_callback(self, cb: Callable[[], None]) -> None:
        """Отписаться от уведомлений."""
        try:
            self._change_callbacks.remove(cb)
        except ValueError:
            pass

    def _notify_callbacks(self) -> None:
        """Вызвать все зарегистрированные callbacks."""
        for cb in self._change_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Ошибка в change callback %r", cb)

    # ------------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Полностью очистить undo/redo стеки и last_event."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_event = None
        self._notify_callbacks()
