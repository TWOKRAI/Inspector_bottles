# multiprocess_framework\modules\process_manager_module\docs\examples\proc_dict_canonical_examples.py
"""
Эталонные примеры proc_dict для SystemLauncher.add_process(name, proc_dict).

Источник контракта: docs/CONFIG_CONTRACT.md, launcher/schema.py (DEFAULT_PROCESS_SCHEMA).
Фреймворк принимает только dict; нормализация: merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA).

Этот файл — справочник, не точка входа приложения. Не импортируйте из production-кода.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Минимальный ввод (до нормализации). Достаточно ключа "class".
# ---------------------------------------------------------------------------
EXAMPLE_MINIMAL_INPUT: Dict[str, Any] = {
    "class": "my_app.processes.worker.MyProcess",
}

# ---------------------------------------------------------------------------
# После нормализации (как хранит SystemLauncher после add_process).
# Совпадает с merge_with_defaults(EXAMPLE_MINIMAL_INPUT, DEFAULT_PROCESS_SCHEMA).
# ---------------------------------------------------------------------------
EXAMPLE_MINIMAL_NORMALIZED: Dict[str, Any] = {
    "class": "my_app.processes.worker.MyProcess",
    "queues": {},
    "priority": "normal",
    "workers": {},
}

# ---------------------------------------------------------------------------
# С очередями и приоритетом (типичный фрагмент).
# ---------------------------------------------------------------------------
EXAMPLE_WITH_QUEUES_AND_PRIORITY: Dict[str, Any] = {
    "class": "my_app.processes.camera.CameraProcess",
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "priority": "high",
    "workers": {},
}

# ---------------------------------------------------------------------------
# С воркерами (каждый воркер — dict с полем class; остальное — по приложению).
# ---------------------------------------------------------------------------
EXAMPLE_WITH_WORKERS: Dict[str, Any] = {
    "class": "my_app.processes.processor.ProcessorProcess",
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "priority": "high",
    "workers": {
        "io_worker": {"class": "my_app.workers.io_worker.IoWorker"},
        "post": {"class": "my_app.workers.post.PostWorker"},
    },
}

# ---------------------------------------------------------------------------
# Расширение приложения (опциональные поля из CONFIG_CONTRACT.md).
# config — обычно model_dump() схемы процесса; memory — описание SHM;
# managers — logger/error/stats/router и т.д. (потребляет spawner/runner).
# Значения ниже — условные, для структуры.
# ---------------------------------------------------------------------------
EXAMPLE_FULL_APP_STYLE: Dict[str, Any] = {
    "class": "my_app.processes.gui.GuiProcess",
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "priority": "normal",
    "workers": {},
    "config": {
        "window_title": "Inspector",
        "window_width": 1024,
        "window_height": 600,
        "poll_interval_ms": 16,
    },
    "memory": {
        "camera_frame": (1080, 1920, 3),
        "coll": 2,
    },
    "managers": {
        "logger": {
            "default_level": "INFO",
            "channels": {},
        },
        "error": {
            "error_file_path": "./logs/errors.log",
        },
        "stats": {"enable_logging": True},
        "router": {"duplicate_messages_to_logger": False},
    },
}


# Должно совпадать с process_manager_module/launcher/schema.py — DEFAULT_PROCESS_SCHEMA
_DEFAULT_PROCESS_SCHEMA: Dict[str, Any] = {
    "class": "",
    "queues": {},
    "priority": "normal",
    "workers": {},
}


def demo_normalize_minimal() -> None:
    """
    Проверка нормализации как в SystemLauncher.add_process (без импорта всего пакета).

    Запуск (из корня репозитория Inspector_prototype):
        set PYTHONPATH=multiprocess_framework\\modules
        python multiprocess_framework/modules/process_manager_module/docs/examples/proc_dict_canonical_examples.py
    """
    from multiprocess_framework.modules.data_schema_module import merge_with_defaults

    out = merge_with_defaults(EXAMPLE_MINIMAL_INPUT, _DEFAULT_PROCESS_SCHEMA)
    assert out == EXAMPLE_MINIMAL_NORMALIZED, (out, EXAMPLE_MINIMAL_NORMALIZED)
    print("normalize(minimal): OK")


if __name__ == "__main__":
    demo_normalize_minimal()
