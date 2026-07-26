# -*- coding: utf-8 -*-
"""Дочерний процесс для пары Ф0.1 «ERROR за 100 мс до аварийной смерти».

Запускается тестом ``test_urgent_flush.py`` как ОТДЕЛЬНЫЙ процесс:

    python _crash_log_child.py <baseline|fixed> <log_dir>

  * ``baseline`` — воспроизводит поведение ДО фикса: ``buffer_priority``
    подменён на константу ``"normal"``, то есть третий аргумент ``enqueue``
    снова не несёт информации об уровне. Это болезнь.
  * ``fixed``    — прод-путь как есть.

Подмена делается здесь, а не флагом в проде: ветка «до фикса» не должна
существовать в рабочем коде (правило «флаги не должны стать костылями»).

После записи ERROR процесс печатает ``logged`` в stdout и засыпает надолго —
убивает его родитель, чтобы ни ``shutdown()``, ни ``atexit``, ни таймер
``BatchBuffer`` не успели сбросить пачку. Единственный шанс записи попасть
на диск — немедленный сброс по ``priority="urgent"``.

Имя начинается с ``_`` — файл не собирается pytest (``python_files = test_*.py``).
"""

import sys
import time

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)

#: Маркер, который родитель ищет в файле лога.
CRASH_MARKER = "URGENT-FLUSH-CRASH-MARKER"

#: Сколько ждать смерти от родителя (процесс должен быть убит задолго до этого).
_SLEEP_UNTIL_KILLED = 60.0


def main(mode: str, log_dir: str) -> None:
    from multiprocess_framework.modules.logger_module.core import logger_core

    if mode == "baseline":
        logger_core.buffer_priority = lambda _level: "normal"

    from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

    config = LoggerManagerConfig(
        app_name="urgent_flush_pair",
        log_directory=log_dir,
        enable_batching=True,
        # Ни один другой триггер сброса не должен сработать: ни размер пачки,
        # ни таймер. Остаётся ровно priority-ветка.
        batch_size=10_000,
        batch_interval=_SLEEP_UNTIL_KILLED * 10,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file",
                type="file",
                enabled=True,
                file_path="system.log",
                rotate=False,
            )
        },
        scopes={
            "SYSTEM": LoggerScopeSchema(
                enabled=True,
                min_level="DEBUG",
                channels=["system_file"],
            )
        },
    )

    manager = LoggerManager(manager_name="CrashLogger", config=config)
    manager.initialize()
    manager.error(CRASH_MARKER, module="crash_test")

    print("logged", flush=True)
    time.sleep(_SLEEP_UNTIL_KILLED)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
