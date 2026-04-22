# multiprocess_framework\modules\process_module\docs\examples\process_config_canonical_examples.py
"""
Эталонные примеры конфигурации внутри process_module (Dict at Boundary).

ProcessModule получает dict в конструкторе и в ProcessConfigHandler; отдельных
«методов конфига» во фреймворке нет — только словари и доступ через get/set.

Источники: types/types.py (ProcessConfigDict), config/process_config_handler.py,
tests/test_process_config.py.

Этот файл — справочник. Не импортируйте из production-кода.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Форма ProcessConfigDict (TypedDict, total=False) — логические секции.
# Реальные данные приходят из runner/process_runner (bundle) или из ProcessData.
# ---------------------------------------------------------------------------
EXAMPLE_PROCESS_CONFIG_DICT_SHAPE: Dict[str, Any] = {
    "process": {
        "window_title": "App",
        "debug": False,
    },
    "managers": {
        "logger": {"level": "INFO"},
        "router": {},
    },
    "modules": {},
    "workers": {},
    "custom": {},
}

# ---------------------------------------------------------------------------
# Локальный конфиг, передаваемый в ProcessConfigHandler(process_name, config=...).
# Плоский dict; вложенный ключ "managers" поддерживается get_managers_config().
# ---------------------------------------------------------------------------
EXAMPLE_LOCAL_CONFIG_FLAT: Dict[str, Any] = {
    "key": "value",
    "poll_interval_ms": 16,
}

# ---------------------------------------------------------------------------
# Локальный конфиг с секцией managers (как в tests/test_process_config.py).
# ---------------------------------------------------------------------------
EXAMPLE_LOCAL_CONFIG_WITH_MANAGERS: Dict[str, Any] = {
    "managers": {
        "logger": {"level": "DEBUG"},
        "worker": {"max_workers": 4},
    },
}

# ---------------------------------------------------------------------------
# Канон SchemaBase + build(): managers внутри proc_dict["config"] (не на верхнем
# уровне). ProcessConfigHandler.get_managers_config() сводит к одному виду через
# normalize_managers_view (см. process_module/configs/managers_normalize.py).
# ---------------------------------------------------------------------------
EXAMPLE_LOCAL_CONFIG_NESTED_MANAGERS_IN_CONFIG: Dict[str, Any] = {
    "class": "my_pkg.process.MyProcess",
    "queues": {},
    "config": {
        "managers": {
            "logger": {"default_level": "INFO"},
            "console": {"enabled": True, "interactive": False},
        },
    },
}

# ---------------------------------------------------------------------------
# Стиль custom / ProcessData (см. ProcessConfigHandler + _CustomProcessConfig):
# component_managers_config и process_config в custom.
# ---------------------------------------------------------------------------
EXAMPLE_CUSTOM_PROCESS_DATA_STYLE: Dict[str, Any] = {
    "process_config": {
        "debug": True,
        "feature_flags": {"x": 1},
    },
    "component_managers_config": {
        "logger": {"level": "INFO"},
    },
}

# Живой вызов ProcessConfigHandler — в unit-тестах пакета (относительные импорты):
#   process_module/tests/test_process_config.py
# При плоском PYTHONPATH=.../modules импорт всего process_module может быть недоступен
# из-за относительных импортов внутри пакета; для проверки используйте pytest из каталога modules.


if __name__ == "__main__":
    print(
        "Эталонные dict выше — справочник. "
        "Запуск: pytest process_module/tests/test_process_config.py -q"
    )
