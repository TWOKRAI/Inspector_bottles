"""
RegisterCommandHandler -- консольные команды для работы с регистрами.

Команды:
    reg list                    -- список зарегистрированных регистров
    reg get <name>              -- значения всех полей регистра
    reg set <name>.<field> <v>  -- изменить поле + отправить update через router
    reg info <name>             -- метаинформация (FieldMeta, FieldRouting)
    reg help                    -- справка

Standalone-класс. Зависимости -- через конструктор (registers_manager, router_manager).
Не наследует BaseManager.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RegisterCommandHandler:
    """
    Обработчик консольных команд ``reg ...``.

    Зависимости опциональны: если registers_manager не задан, все команды
    возвращают сообщение-заглушку. router_manager используется только
    для ``reg set`` (отправка broadcast).

    Использование::

        handler = RegisterCommandHandler(
            registers_manager=process.registers_manager,
            router_manager=process.router_manager,
        )
        # Регистрация в CommandManager:
        command_manager.register_command(
            "reg", handler.handle, expects_full_message=True,
        )
    """

    def __init__(
        self,
        registers_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
    ) -> None:
        self._registers = registers_manager
        self._router = router_manager

    # -- public setters (для позднего связывания) ----------------------------

    def set_registers_manager(self, manager: Any) -> None:
        """Установить / заменить registers_manager после создания."""
        self._registers = manager

    def set_router_manager(self, manager: Any) -> None:
        """Установить / заменить router_manager после создания."""
        self._router = manager

    # =========================================================================
    # Главный dispatch
    # =========================================================================

    def handle(self, message: Dict[str, Any]) -> str:
        """
        Точка входа. Вызывается CommandManager с ``expects_full_message=True``.

        Ожидаемый формат message::

            {
                "command": "reg",
                "args": ["list"] | ["get", "name"] | ["set", "name.field", "value"] | ...
                "source": "console",
                ...
            }

        Returns:
            Текстовый результат для вывода в терминал.
        """
        args: List[str] = message.get("args", [])
        if not args:
            return self._cmd_help()

        subcmd = args[0].lower()
        dispatch = {
            "list": self._cmd_list,
            "get": self._cmd_get,
            "set": self._cmd_set,
            "info": self._cmd_info,
            "help": lambda _: self._cmd_help(),
        }

        handler = dispatch.get(subcmd)
        if handler is None:
            return f"Unknown subcommand: '{subcmd}'\n\n{self._cmd_help()}"

        try:
            return handler(args[1:])
        except Exception as exc:
            logger.error("RegisterCommandHandler error: %s", exc, exc_info=True)
            return f"Error: {exc}"

    # =========================================================================
    # Subcommands
    # =========================================================================

    def _cmd_list(self, args: List[str]) -> str:
        """``reg list`` -- вывод списка зарегистрированных регистров."""
        if self._registers is None:
            return "RegistersManager is not available."

        names = self._registers.register_names()
        if not names:
            return "No registers."

        lines = ["Registers:"]
        for name in sorted(names):
            reg = self._registers.get_register(name)
            field_count = 0
            if reg is not None and hasattr(reg, "model_fields"):
                field_count = len(reg.model_fields)
            lines.append(f"  {name:<30s}  ({field_count} fields)")
        return "\n".join(lines)

    def _cmd_get(self, args: List[str]) -> str:
        """``reg get <name>`` -- вывод полей регистра с текущими значениями."""
        if self._registers is None:
            return "RegistersManager is not available."
        if not args:
            return "Usage: reg get <register_name>"

        name = args[0]
        reg = self._registers.get_register(name)
        if reg is None:
            return f"Register '{name}' not found."

        if hasattr(reg, "model_dump"):
            data = reg.model_dump()
        else:
            return f"Register '{name}' has no model_dump()."

        if not data:
            return f"Register '{name}' has no fields."

        # Определяем ширину колонок
        max_field = max(len(k) for k in data)
        max_field = max(max_field, 5)  # минимум "Field"

        lines = [f"Register: {name}", ""]
        header = f"  {'Field':<{max_field}s}  {'Value'}"
        lines.append(header)
        lines.append(f"  {'-' * max_field}  {'-' * 30}")
        for field_name, value in sorted(data.items()):
            lines.append(f"  {field_name:<{max_field}s}  {value!r}")
        return "\n".join(lines)

    def _cmd_set(self, args: List[str]) -> str:
        """``reg set <name>.<field> <value>`` -- изменить поле + router broadcast."""
        if self._registers is None:
            return "RegistersManager is not available."
        if len(args) < 2:
            return "Usage: reg set <register_name>.<field_name> <value>"

        target = args[0]
        raw_value = " ".join(args[1:])

        # Разбираем "register.field"
        if "." not in target:
            return (
                f"Invalid target '{target}'. "
                f"Expected format: <register_name>.<field_name>"
            )
        dot_idx = target.index(".")
        register_name = target[:dot_idx]
        field_name = target[dot_idx + 1:]

        if not register_name or not field_name:
            return "Both register name and field name are required."

        # Получаем регистр для определения типа поля
        reg = self._registers.get_register(register_name)
        if reg is None:
            return f"Register '{register_name}' not found."

        if not hasattr(reg, field_name):
            return f"Field '{field_name}' not found in register '{register_name}'."

        # Приведение типа значения
        value = self._cast_value(raw_value, getattr(reg, field_name))

        # Установка значения через RegistersManager (вызывает observers + send_callback).
        # broadcast уже обрабатывается внутри RegistersManager.set_field_value:
        # он вызывает send_callback для каждого resolve_dispatch_targets-канала.
        # Дополнительный вызов router_manager здесь не нужен.
        ok, error = self._registers.set_field_value(register_name, field_name, value)
        if not ok:
            return f"Failed to set {register_name}.{field_name}: {error}"

        return f"OK: {register_name}.{field_name} = {value!r}"

    def _cmd_info(self, args: List[str]) -> str:
        """``reg info <name>`` -- метаинформация (FieldMeta, FieldRouting)."""
        if self._registers is None:
            return "RegistersManager is not available."
        if not args:
            return "Usage: reg info <register_name>"

        name = args[0]
        reg = self._registers.get_register(name)
        if reg is None:
            return f"Register '{name}' not found."

        if not hasattr(reg, "model_fields"):
            return f"Register '{name}' has no model_fields."

        lines = [f"Register info: {name}", ""]

        for field_name in sorted(reg.model_fields):
            meta_dict = self._registers.get_field_metadata(name, field_name)
            lines.append(f"  {field_name}:")

            if not meta_dict:
                lines.append("    (no metadata)")
                continue

            for key, val in sorted(meta_dict.items()):
                if val is None or val == "" or val == [] or val == {}:
                    continue
                lines.append(f"    {key}: {val!r}")

            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # Help
    # =========================================================================

    def _cmd_help(self) -> str:
        """Вывод справки по командам ``reg``."""
        return "\n".join([
            "Register commands:",
            "",
            "  reg list                         List all registers",
            "  reg get <name>                   Show field values",
            "  reg set <name>.<field> <value>    Set field value",
            "  reg info <name>                  Show field metadata",
            "  reg help                         This help",
        ])

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _cast_value(raw: str, current: Any) -> Any:
        """
        Приведение строки к типу текущего значения поля.

        Поддерживает: bool, int, float, str.
        При ошибке -- возвращает строку как есть.
        """
        if isinstance(current, bool):
            return raw.lower() in ("true", "1", "yes", "on")
        if isinstance(current, int):
            try:
                return int(raw)
            except ValueError:
                # Может быть float-like: "3.0" -> 3
                try:
                    return int(float(raw))
                except ValueError:
                    return raw
        if isinstance(current, float):
            try:
                return float(raw)
            except ValueError:
                return raw
        return raw
