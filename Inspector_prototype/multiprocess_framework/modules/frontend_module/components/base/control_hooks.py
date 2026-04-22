# -*- coding: utf-8 -*-
"""
Хуки жизненного цикла записи в регистр и проверки прав — для подключения внешних менеджеров.

Не импортирует logger/error/statistics: приложение передаёт колбэки в ``ControlHooks``
и подключает их к ``LoggerManager`` / ``ErrorManager`` / и т.д. При необходимости
обёртка может пробрасывать события в ``pyqtSignal``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

ControlKind = Literal["checkbox", "numeric", "slider", "spinbox"]

# ---------------------------------------------------------------------------
# События (immutable): presenter собирает их и передаёт в колбэки ControlHooks.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlWriteRejectedEvent:
    """Запись в регистр отклонена (ошибка адаптера / регистра)."""

    register_name: str
    field_name: str
    message: str
    control_kind: ControlKind
    attempted_value: Any | None = None
    index: Optional[int] = None


@dataclass(frozen=True)
class ControlWriteCommittedEvent:
    """Успешная запись (для метрик / аудита; вызывать после подтверждения адаптера)."""

    register_name: str
    field_name: str
    value: Any
    control_kind: ControlKind
    index: Optional[int] = None


@dataclass(frozen=True)
class ControlAccessDeniedEvent:
    """Пользователь попытался изменить значение при ``not can_modify()`` (уровень доступа)."""

    register_name: str
    field_name: str
    control_kind: ControlKind
    index: Optional[int] = None
    attempted_value: Any | None = None


# ---------------------------------------------------------------------------
# Тонкие эмиттеры: не тянут зависимостей; binding — любой объект с полями register/field/index.
# ---------------------------------------------------------------------------


def emit_write_rejected(
    hooks: ControlHooks | None,
    binding: Any,
    control_kind: ControlKind,
    message: str,
    attempted_value: Any | None,
) -> None:
    if not hooks or not hooks.on_write_rejected:
        return
    hooks.on_write_rejected(
        ControlWriteRejectedEvent(
            register_name=binding.register_name,
            field_name=binding.field_name,
            message=message,
            control_kind=control_kind,
            attempted_value=attempted_value,
            index=getattr(binding, "index", None),
        )
    )


def emit_write_committed(
    hooks: ControlHooks | None,
    binding: Any,
    control_kind: ControlKind,
    value: Any,
) -> None:
    if not hooks or not hooks.on_write_committed:
        return
    hooks.on_write_committed(
        ControlWriteCommittedEvent(
            register_name=binding.register_name,
            field_name=binding.field_name,
            value=value,
            control_kind=control_kind,
            index=getattr(binding, "index", None),
        )
    )


def emit_access_denied(
    hooks: ControlHooks | None,
    binding: Any,
    control_kind: ControlKind,
    attempted_value: Any | None,
) -> None:
    if not hooks or not hooks.on_access_denied:
        return
    hooks.on_access_denied(
        ControlAccessDeniedEvent(
            register_name=binding.register_name,
            field_name=binding.field_name,
            control_kind=control_kind,
            index=getattr(binding, "index", None),
            attempted_value=attempted_value,
        )
    )


@dataclass
class ControlHooks:
    """
    Опциональные колбэки. Передаются в ``*Control.create(..., hooks=...)`` → хранятся в
    presenter; presenter вызывает их при успешной записи, отказе регистра и отказе по правам.

    Сигнатуры намеренно простые, чтобы их можно было связать с Qt::

        class Bridge(QObject):
            rejected = pyqtSignal(object)
            def on_rejected(self, ev: ControlWriteRejectedEvent) -> None:
                self.rejected.emit(ev)
    """

    on_write_rejected: Callable[[ControlWriteRejectedEvent], None] | None = None
    on_write_committed: Callable[[ControlWriteCommittedEvent], None] | None = None
    on_access_denied: Callable[[ControlAccessDeniedEvent], None] | None = None
