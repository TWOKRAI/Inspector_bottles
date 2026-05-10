"""Команды для ProcessorWorkerProcess.

Фабричная функция получает ссылку на процесс и возвращает dict.
"""
from __future__ import annotations


def build_command_table(worker_process) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        worker_process: ProcessorWorkerProcess instance.
    """

    def cmd_health(data: dict) -> dict:
        """Health-check: возвращает статус и количество кэшированных операций."""
        return {
            "status": "ok",
            "worker_index": worker_process._worker_index,
            "cached_operations": len(worker_process._operations),
            "catalog_size": len(worker_process._catalog),
        }

    def cmd_catalog_reload(data: dict) -> dict:
        """Перезагрузить каталог операций и сбросить кэш экземпляров."""
        return worker_process.reload_catalog()

    return {
        "health": cmd_health,
        "catalog_reload": cmd_catalog_reload,
    }
