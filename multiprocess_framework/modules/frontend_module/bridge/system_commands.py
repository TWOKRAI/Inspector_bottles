"""system_commands — каталог system-level IPC-команд.

Отвечает на вопрос: КАКУЮ IPC-команду отправить?

Каждая функция: typed args → dict (IPC message payload).
Чистый Python, без побочных эффектов. Легко тестировать,
легко читать в дебагере (print(build_hot_add(...))).

Зависит от wire_protocol.WireConfig (для build_wire_setup).
Pure Python, 0 зависимостей на Qt или IPC-транспорт.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Импорт только для аннотаций типов — не создаёт runtime-зависимости
    from .wire_protocol import WireConfig


__all__ = [
    "SYSTEM_COMMANDS",
    "build_process_start",
    "build_process_stop",
    "build_process_restart",
    "build_hot_add_process",
    "build_hot_remove_process",
    "build_wire_setup",
    "build_wire_teardown",
]


# --- Process lifecycle ---


def build_process_start(process_name: str) -> dict[str, Any]:
    """Команда запуска существующего процесса."""
    return {
        "cmd": "process.start",
        "process_name": process_name,
    }


def build_process_stop(process_name: str) -> dict[str, Any]:
    """Команда остановки процесса."""
    return {
        "cmd": "process.stop",
        "process_name": process_name,
    }


def build_process_restart(process_name: str) -> dict[str, Any]:
    """Команда перезапуска процесса (stop → start)."""
    return {
        "cmd": "process.restart",
        "process_name": process_name,
    }


# --- Hot add/remove ---


def build_hot_add_process(
    process_name: str,
    plugin_name: str,
    plugin_config: dict[str, Any] | None = None,
    *,
    auto_start: bool = True,
) -> dict[str, Any]:
    """Команда горячего добавления нового процесса.

    ProcessManager создаёт GenericProcess с указанным плагином.
    Если auto_start=True — запускает сразу после создания.
    """
    return {
        "cmd": "process.hot_add",
        "process_name": process_name,
        "plugin_name": plugin_name,
        # Пустой dict если plugin_config не задан
        "plugin_config": plugin_config if plugin_config is not None else {},
        "auto_start": auto_start,
    }


def build_hot_remove_process(
    process_name: str,
    *,
    graceful: bool = True,
) -> dict[str, Any]:
    """Команда горячего удаления процесса.

    graceful=True: stop → дождаться завершения → удалить.
    graceful=False: kill → удалить немедленно.
    """
    return {
        "cmd": "process.hot_remove",
        "process_name": process_name,
        "graceful": graceful,
    }


# --- Wire management ---


def build_wire_setup(wire: "WireConfig") -> dict[str, Any]:
    """Команда создания wire (SHM-канал между процессами).

    Вызывает wire.with_defaults() для авто-заполнения shm_name и owner_process.
    Отправляется в ProcessManager, который:
    1. Создаёт SHM-регион (shm_name, buffer_slots)
    2. Отправляет wire.configure source + target процессам
    """
    # Заполняем дефолты перед формированием IPC-сообщения
    w = wire.with_defaults()
    return {
        "cmd": "wire.setup",
        "wire_key": w.wire_key,
        "source": w.source,
        "target": w.target,
        "source_process": w.source_process,
        "target_process": w.target_process,
        "transport": w.transport,
        "shm_config": {
            "shm_name": w.shm_config.shm_name,
            "buffer_slots": w.shm_config.buffer_slots,
            "owner_process": w.shm_config.owner_process,
            "strategy": w.shm_config.strategy,
        },
    }


def build_wire_teardown(
    wire_key: str,
    source_process: str,
    target_process: str,
) -> dict[str, Any]:
    """Команда удаления wire по ключу.

    ProcessManager останавливает передачу данных,
    освобождает SHM-регион и уведомляет source/target процессы.
    """
    return {
        "cmd": "wire.teardown",
        "wire_key": wire_key,
        "source_process": source_process,
        "target_process": target_process,
    }


# --- Реестр всех system-команд (для документации и валидации) ---

SYSTEM_COMMANDS: dict[str, str] = {
    "process.start": "Запуск существующего процесса",
    "process.stop": "Остановка процесса",
    "process.restart": "Перезапуск процесса",
    "process.hot_add": "Горячее добавление нового процесса",
    "process.hot_remove": "Горячее удаление процесса",
    "wire.setup": "Создание SHM-канала между процессами",
    "wire.teardown": "Удаление SHM-канала",
}
