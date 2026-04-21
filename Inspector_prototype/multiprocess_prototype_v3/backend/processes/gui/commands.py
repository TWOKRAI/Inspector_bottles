"""Команды и register-хендлеры для GuiProcess.

GUI не регистрирует команды в command_manager — вместо этого
отправляет команды через GuiCommandHandler (frontend/commands/).
Файл — заглушка для единообразия структуры.
Добавляй команды по мере роста входящих IPC-команд в GUI.
"""


def build_command_table() -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command()."""
    return {}


def build_register_handlers() -> dict:
    """Возвращает {field_name: handler} для apply_register_update()."""
    return {}
