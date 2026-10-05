# -*- coding: utf-8 -*-
"""Тесты observability hot-reload (Phase 3, Task 3.3).

Контракт: правка файла с секцией observability → ConfigFileWatcher → reconfigure
менеджеров без рестарта; watcher корректно останавливается; отсутствующий файл → None.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.logger_module import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    make_observability_on_reload,
    start_observability_watcher,
)


class _FakeManager:
    """Записывает аргументы reconfigure для проверки on_reload."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def reconfigure(self, config: Dict[str, Any]) -> bool:
        self.calls.append(config)
        return True


def _write_yaml(path: Path, log_level: str) -> None:
    path.write_text(
        f"observability:\n  log_level: {log_level}\n  console: true\n  file: true\n",
        encoding="utf-8",
    )


def test_on_reload_calls_all_three() -> None:
    """on_reload читает секцию observability и зовёт reconfigure у всех трёх менеджеров."""
    logger, error, stats = _FakeManager(), _FakeManager(), _FakeManager()
    on_reload = make_observability_on_reload(logger=logger, error=error, stats=stats)

    cfg = Config(initial_data={"observability": {"log_level": "DEBUG"}})
    on_reload(cfg)

    assert logger.calls and logger.calls[-1]["default_level"] == "DEBUG"
    assert error.calls and "default_level" in error.calls[-1]
    assert stats.calls and "log_level" in stats.calls[-1]


def test_on_reload_skips_none_managers() -> None:
    """None-менеджеры пропускаются без ошибки."""
    logger = _FakeManager()
    on_reload = make_observability_on_reload(logger=logger, error=None, stats=None)
    on_reload(Config(initial_data={"observability": {"log_level": "WARNING"}}))
    assert logger.calls[-1]["default_level"] == "WARNING"


def test_hot_reload_reconfigures_logger(tmp_path: Path) -> None:
    """Правка файла → реальный LoggerManager перестроен через watchdog (default_level + кэш).

    Задача Т-3 (находка HR-4). Дедлайн ожидания был 6 с, и на этом числе тест дал
    1 провал в полной фреймворковой сьюте (7803 теста) при трёх зелёных соло за 0.5 с.
    Класс известный — «порог по часам меряет кучу»: утверждение теста звучит
    «файл прочитан и логгер перестроен», а шестисекундный дедлайн незаметно
    добавлял к нему второе, незаявленное — «уложился в 6 с на машине, которая в
    этот момент крутит ещё 7800 тестов». Краснело именно второе.

    Поэтому дедлайн поднят до 60 с: цикл выходит по первому же успеху, так что
    цена штатного прогона не изменилась (те же ~0.5 с), а под нагрузкой тест
    судит механизм, а не планировщик. Ждать МЕНЬШЕ здесь нечего: не перестроился
    вовсе — красное придёт всё равно, просто позже.

    Кэш решений напрямую не проверяется: ``default_level`` меняется в ``logger_core.py:987``, а
    ``invalidate_decision_cache()`` зовётся лишь в ``:1012`` (~1 мс позже, в потоке watchdog) —
    утверждение «кэш пуст» попадало в это окно (Атлас 0.8, Linux CI: 2 прогона из 3). Проверяется
    наблюдаемое следствие: ответ ``should_log``, закэшенный до смены уровня, после reload верен.
    """
    yaml_path = tmp_path / "system.yaml"
    _write_yaml(yaml_path, "INFO")

    logger = LoggerManager(manager_name="TestLogger")
    logger.initialize()
    assert logger.config.default_level == "INFO"

    watcher = start_observability_watcher(
        config_path=yaml_path,
        logger=logger,
        debounce_seconds=0.2,
    )
    assert watcher is not None and watcher.is_running

    try:
        # Прогреть кэш решений should_log, затем сменить уровень файлом.
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope

        # Ключ, ответ которого зависит от уровня: под INFO DEBUG-запись отвергнута, и этот False
        # закэширован — переживи он reload, тест краснеет.
        assert logger.should_log(LogScope.DEBUG, LogLevel.DEBUG, "probe") is False
        time.sleep(0.3)  # выйти за дебаунс
        _write_yaml(yaml_path, "DEBUG")

        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if logger.should_log(LogScope.DEBUG, LogLevel.DEBUG, "probe") is True:
                break
            time.sleep(0.1)

        assert logger.should_log(LogScope.DEBUG, LogLevel.DEBUG, "probe") is True, "закэшированный False пережил reload"
        assert logger.config.default_level == "DEBUG", "watcher не перестроил logger из файла"
    finally:
        watcher.stop()
        logger.shutdown()


def test_watcher_stop(tmp_path: Path) -> None:
    """stop() корректно останавливает фоновый поток (нет висящих)."""
    yaml_path = tmp_path / "system.yaml"
    _write_yaml(yaml_path, "INFO")
    watcher = start_observability_watcher(config_path=yaml_path, logger=_FakeManager())
    assert watcher is not None and watcher.is_running
    watcher.stop()
    assert watcher.is_running is False


def test_missing_file_returns_none(tmp_path: Path) -> None:
    """Отсутствующий файл → None (процесс не падает)."""
    watcher = start_observability_watcher(
        config_path=tmp_path / "nope.yaml",
        logger=_FakeManager(),
    )
    assert watcher is None
