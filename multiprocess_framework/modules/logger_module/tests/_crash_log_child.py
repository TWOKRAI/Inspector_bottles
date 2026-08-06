# -*- coding: utf-8 -*-
"""Дочерний процесс для пары Ф0.9 «ERROR за 100 мс до аварийной смерти».

Запускается тестом ``test_error_floor.py`` как ОТДЕЛЬНЫЙ процесс:

    python _crash_log_child.py <baseline|fixed> <log_dir> [nosinks]

  * ``baseline`` — воспроизводит поведение ДО фикса: ``is_error_level``
    подменён на «всегда False» И приёмник подменён на ОТКЛАДЫВАЮЩИЙ (копит
    записи в памяти, пишет только на ``close``). Это болезнь.

    До Ф7.4 откладывал сам фреймворк: батч-буфер держал запись до
    ``batch_interval``. Батчинг снят, отложенной записи в проде больше нет —
    поэтому болезнь приходится вносить приёмником. Пара сохранена сознательно:
    без воспроизведения болезни «лечение» ничего не доказывает, а гарантия
    «ошибка на диске до смерти процесса» переживёт любую будущую попытку
    снова что-нибудь отложить.
  * ``fixed``    — прод-путь как есть.
  * ``nosinks``  — третий аргумент: собрать конфиг БЕЗ единого включённого
    приёмника ошибок. Проверяет конфиго-независимость floor'а.

Подмена делается здесь, а не флагом в проде: ветка «до фикса» не должна
существовать в рабочем коде (правило «флаги не должны стать костылями»).

После записи ERROR процесс печатает ``logged`` в stdout и засыпает надолго —
убивает его родитель, чтобы ни ``shutdown()``, ни ``atexit``, ни ``close``
приёмника не успели ничего сбросить.

Имя начинается с ``_`` — файл не собирается pytest (``python_files = test_*.py``).
"""

import sys
import time

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)

#: Маркер, который родитель ищет в записи.
CRASH_MARKER = "URGENT-FLUSH-CRASH-MARKER"

#: Уникальный фрагмент traceback'а — доказывает, что запись НЕ усечена.
TRACEBACK_MARKER = "_deliberate_boom"

#: Сколько ждать смерти от родителя (процесс должен быть убит задолго до этого).
_SLEEP_UNTIL_KILLED = 60.0


def _deliberate_boom() -> None:
    """Функция с говорящим именем — её имя обязано оказаться в traceback."""
    raise ValueError(CRASH_MARKER)


def main(mode: str, log_dir: str, sinks: str = "with-sinks") -> None:
    from multiprocess_framework.modules.logger_module.core import logger_core
    from multiprocess_framework.modules.error_module.core import error_manager as error_manager_mod
    from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

    if mode == "baseline":
        # До Ф0.9 ошибка ничем не отличалась от INFO: уходила в пачку и ждала.
        # Подменять надо ОБА неймспейса: severity-путь ErrorManager — полный
        # override, он импортировал предикат к себе и на патч logger_core не
        # смотрит. Первая редакция патчила только logger_core — и baseline
        # позеленел (то есть болезнь не воспроизвелась), тест это поймал.
        logger_core.is_error_level = lambda _level: False
        error_manager_mod.is_error_level = lambda _level: False

        # Отложенный приёмник вместо снятого батч-буфера: копит в память,
        # на диск отдаёт только при закрытии — которого не будет, процесс убьют.
        from multiprocess_framework.modules.logger_module.channels import log_channel as _lc

        class _DeferringFileChannel(_lc.FileChannel):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self._deferred = []

            def write(self, record):
                self._deferred.append(record)
                return {"status": "success", "channel": self.name}

            def close(self):  # pragma: no cover — в baseline до close не доходит
                for rec in self._deferred:
                    super().write(rec)
                self._deferred.clear()
                super().close()

        _lc.register_sink_factory("file", _DeferringFileChannel)

    channels = {}
    scopes_channels = []
    if sinks != "nosinks":
        channels["errors_file"] = LoggerChannelSchema(
            name="errors_file",
            type="file",
            enabled=True,
            file_path="errors.log",
            rotate=False,
        )
        scopes_channels = ["errors_file"]

    config = LoggerManagerConfig(
        app_name="error_floor_pair",
        log_directory=log_dir,
        modules={},
        channels=channels,
        scopes={
            "SYSTEM": LoggerScopeSchema(
                enabled=True,
                min_level="DEBUG",
                channels=scopes_channels,
            )
        },
    )

    manager = ErrorManager(config=config)
    manager.initialize()

    # Немного обычных записей ДО ошибки: они должны лечь на диск раньше неё
    # (порядок), а в baseline — умереть вместе с процессом.
    for i in range(5):
        manager.info(f"routine before crash {i}", module="crash_test")

    try:
        _deliberate_boom()
    except ValueError as exc:
        manager.log_exception(exc, "падение перед смертью", module="crash_test")

    print("logged", flush=True)
    time.sleep(_SLEEP_UNTIL_KILLED)


if __name__ == "__main__":
    main(*sys.argv[1:])
