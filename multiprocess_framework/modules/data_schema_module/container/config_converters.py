# -*- coding: utf-8 -*-
"""
Конвертеры config → dict для передачи в модули фреймворка.

Dict at Boundary: конфиги (HasBuild) преобразуются в dict перед передачей
в SystemLauncher, ErrorManager и др. Модули фреймворка не зависят от data_schema.

Использование:

    from multiprocess_framework.modules.data_schema_module import process

    launcher.add_process(*process(Process1Config(), Worker1Config()))
"""
from typing import List, Tuple

from ..interfaces import HasBuild


def config_to_dict(config: HasBuild) -> Tuple[str, dict]:
    """
    Преобразовать конфиг в (name, dict).

    config должен иметь build() -> (name, dict).
    """
    if hasattr(config, "build") and callable(config.build):
        return config.build()
    raise TypeError(
        f"config must have build() -> (name, dict), got {type(config).__name__}"
    )


def configs_to_dicts(*configs: HasBuild) -> List[Tuple[str, dict]]:
    """Преобразовать несколько конфигов в список (name, dict)."""
    return [config_to_dict(c) for c in configs]


def build_process_with_workers(
    process_config: HasBuild,
    *worker_configs: HasBuild,
) -> Tuple[str, dict]:
    """
    Собрать (name, proc_dict) с воркерами для add_process().

    process_config.build() → (name, proc_dict)
    worker_configs.build() → (worker_name, worker_dict)

    Returns:
        (process_name, proc_dict) — готово для launcher.add_process(name, proc_dict)
    """
    name, proc_dict = config_to_dict(process_config)
    if worker_configs:
        workers_dict = {}
        for w in worker_configs:
            wn, wd = config_to_dict(w)
            workers_dict[wn] = wd
        proc_dict["workers"] = workers_dict
    return name, proc_dict


def process(process_config: HasBuild, *worker_configs: HasBuild) -> Tuple[str, dict]:
    """
    Собрать (name, proc_dict). Короткий алиас для build_process_with_workers.

    launcher.add_process(*process(Process1Config(), Worker1Config()))
    """
    return build_process_with_workers(process_config, *worker_configs)
