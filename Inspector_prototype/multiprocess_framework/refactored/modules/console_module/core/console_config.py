"""
ConsoleConfig — конфигурация ConsoleManager.

Три уровня использования:
  Уровень 1 (пассивный):  enabled=True  — показать терминал
  Уровень 2 (активный):   команды в runtime через CommandManager
  Уровень 3 (God Mode):   interactive=True — ввод → CommandManager → RouterManager
"""
from ...data_schema_module.core.schema_base import SchemaBase


class ConsoleConfig(SchemaBase):
    """Конфигурация ConsoleManager."""

    enabled: bool = False
    """Показать основной терминал при инициализации."""

    interactive: bool = False
    """Включить чтение ввода (stdin → CommandManager)."""

    title: str = ""
    """Заголовок окна. Если пустой — используется имя процесса."""

    redirect_stdout: bool = False
    """Перенаправить sys.stdout / sys.stderr в ConsoleManager.write()."""
