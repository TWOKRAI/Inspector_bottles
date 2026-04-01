"""
ConsoleConfig — конфигурация ConsoleManager.

Три уровня использования:
  Уровень 1 (пассивный):  enabled=True  — показать терминал
  Уровень 2 (активный):   команды в runtime через CommandManager
  Уровень 3 (God Mode):   interactive=True — ввод → CommandManager → RouterManager
"""
from ...data_schema_module import FieldMeta, register_schema, SchemaBase
from typing import Annotated  

register_schema("ConsoleConfig")
class ConsoleConfig(SchemaBase):
    """Конфигурация ConsoleManager."""

    enabled: Annotated[
        bool,
        FieldMeta("Включен", info="Показать основной терминал при инициализации."),
    ] = False

    interactive: Annotated[
        bool,
        FieldMeta("Интерактив", info="Включить чтение ввода (stdin → CommandManager)."),
    ] = False

    title: Annotated[
        str,
        FieldMeta("Заголовок", info="Заголовок окна. Если пустой — используется имя процесса."),
    ] = ""

    redirect_stdout: Annotated[
        bool,
        FieldMeta("Перенаправить stdout", info="Перенаправить sys.stdout / sys.stderr в ConsoleManager.write()."),
    ] = False
