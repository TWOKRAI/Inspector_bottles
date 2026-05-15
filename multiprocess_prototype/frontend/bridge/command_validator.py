"""CommandValidator — валидация IPC-команд перед отправкой.

Проверяет: плагин существует в каталоге, поле существует в registers,
значение проходит Pydantic-валидацию. Отсекает невалидные команды
на стороне GUI до отправки в IPC.

Pure Python, без Qt, независимо тестируемый блок конструктора.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# --- Протоколы ---


@runtime_checkable
class ICommandCatalog(Protocol):
    """Минимальный интерфейс CommandCatalog для валидатора."""

    def get_plugin(self, plugin_name: str) -> Any | None: ...
    def resolve_action_command(self, plugin_name: str, command_name: str) -> Any | None: ...


@runtime_checkable
class IRegistersManager(Protocol):
    """Минимальный интерфейс RegistersManager для валидатора."""

    def get_fields(self, plugin_name: str) -> list[Any]: ...
    def validate(self, plugin_name: str, field_name: str, value: Any) -> tuple[bool, str | None]: ...


# --- Результат ---


@dataclass(frozen=True)
class ValidationResult:
    """Результат валидации команды."""

    ok: bool
    error: str | None = None

    @staticmethod
    def success() -> ValidationResult:
        return ValidationResult(ok=True)

    @staticmethod
    def fail(error: str) -> ValidationResult:
        return ValidationResult(ok=False, error=error)


# --- Валидатор ---


class CommandValidator:
    """Валидация команд перед отправкой в IPC.

    Принимает CommandCatalog и RegistersManager через DI.
    Каждый метод возвращает ValidationResult(ok, error).
    """

    def __init__(
        self,
        catalog: ICommandCatalog,
        registers_manager: IRegistersManager,
    ) -> None:
        self._catalog = catalog
        self._rm = registers_manager

    def validate_field_command(
        self,
        plugin_name: str,
        field_name: str,
        value: Any,
    ) -> ValidationResult:
        """Валидировать команду изменения поля.

        Проверки:
        1. Плагин существует в каталоге
        2. Поле существует в registers
        3. Значение проходит Pydantic-валидацию
        """
        # 1. Плагин в каталоге?
        pc = self._catalog.get_plugin(plugin_name)
        if pc is None:
            return ValidationResult.fail(f"Плагин '{plugin_name}' не найден в каталоге команд")

        # 2. Поле существует?
        # FieldInfo (multiprocess_prototype.registers.field_info) использует
        # атрибут `field_name`. Pydantic FieldInfo (legacy fallback) — `name`.
        fields = self._rm.get_fields(plugin_name)
        field_names = {getattr(f, "field_name", None) or getattr(f, "name", None) for f in fields}
        if field_name not in field_names:
            return ValidationResult.fail(f"Поле '{field_name}' не найдено в регистре '{plugin_name}'")

        # 3. Значение валидно?
        ok, err = self._rm.validate(plugin_name, field_name, value)
        if not ok:
            return ValidationResult.fail(f"Невалидное значение для '{plugin_name}.{field_name}': {err}")

        return ValidationResult.success()

    def validate_action_command(
        self,
        plugin_name: str,
        command_name: str,
    ) -> ValidationResult:
        """Валидировать явную команду (start/stop и т.п.).

        Проверки:
        1. Плагин существует в каталоге
        2. Команда существует у плагина
        """
        pc = self._catalog.get_plugin(plugin_name)
        if pc is None:
            return ValidationResult.fail(f"Плагин '{plugin_name}' не найден в каталоге команд")

        resolved = self._catalog.resolve_action_command(plugin_name, command_name)
        if resolved is None:
            return ValidationResult.fail(f"Команда '{command_name}' не найдена у плагина '{plugin_name}'")

        return ValidationResult.success()
