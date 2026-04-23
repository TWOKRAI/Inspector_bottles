"""Команды и register-хендлеры для DatabaseProcess.

Фабричные функции получают зависимости как аргументы и возвращают dict.
"""
from __future__ import annotations


def build_command_table(service, sql_manager) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: DatabaseService instance.
        sql_manager: SQLManager для прямых SQL-операций.
    """
    sql_cmd = sql_manager.execute_command

    def cmd_save_detections(msg: dict) -> dict:
        """Адаптер: распаковать детекции из args/data и передать в сервис."""
        args = msg.get("args", {}) or msg.get("data", {})
        return service.save_detections(args.get("detections", []))

    def cmd_flush(msg: dict) -> dict:
        """Принудительный flush буфера детекций в БД."""
        return service.flush()

    return {
        "db.query": sql_cmd,
        "db.execute": sql_cmd,
        "db.insert": sql_cmd,
        "db.save_detections": cmd_save_detections,
        "db.flush": cmd_flush,
    }


def build_register_handlers() -> dict:
    """Возвращает {field_name: handler} для apply_register_update()."""
    return {}
