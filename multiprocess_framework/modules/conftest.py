# -*- coding: utf-8 -*-
"""
Pytest: логи по умолчанию не пишутся в дерево исходников modules/.

Каталог задаётся через MULTIPROCESS_LOG_DIR (см. logger_module.core.log_paths).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_early_log_buffer() -> None:
    """Ф6.4а: буфер ранних записей — ПРОЦЕССНОЕ состояние, и оно течёт между тестами.

    В проде это ровно то, что нужно: одна жизнь процесса — один старт, один
    слив. В прогоне процесс общий на тысячи тестов, поэтому запись, сделанная
    без менеджера в одном тесте, сливалась в первый же менеджер СЛЕДУЮЩЕГО и
    становилась там первой строкой файла (поймано тремя красными в
    ``test_fallback_handle`` и ``test_source_stamp_artifact``).

    Сброс до и после: «до» защищает тест от предшественника, «после» — от
    самого себя, если он упал на середине.
    """
    from .logger_module.adapters.std_facade import reset_early_buffer

    reset_early_buffer()
    yield
    reset_early_buffer()


@pytest.fixture(autouse=True)
def _reset_logger_manager_singleton() -> None:
    """Ф6.х.1: ``LoggerManager._instance`` — второе процессное состояние, текущее между тестами.

    Тест, забывший ``shutdown()``, оставлял живой менеджер (его потоки, каналы и
    tap'ы) всем последующим: измерено на ``test_send_error_visibility`` —
    перестановка одного файла меняла время прогона 16.8 с ↔ 88–95 с, из них
    72 с приходились на один чужой тест. Снимаем через ``shutdown()``: голое
    ``_instance = None`` не бампит эпоху наблюдаемости, и закэшированные фасады
    в ``std_facade._CACHE`` остались бы связаны с мёртвым менеджером.

    Определена ПОСЛЕ ``_reset_early_log_buffer`` намеренно: teardown идёт в
    обратном порядке, поэтому сперва снимается менеджер, потом чистится буфер —
    записи, набуференные самим shutdown-переходом, не переживают тест.
    """
    from .logger_module.core.logger_manager import LoggerManager

    def _shutdown_leftover() -> None:
        manager = LoggerManager._instance
        if manager is not None:
            manager.shutdown()

    _shutdown_leftover()
    yield
    _shutdown_leftover()


@pytest.fixture(scope="session", autouse=True)
def _multiprocess_framework_log_dir(tmp_path_factory: pytest.TempPathFactory) -> None:
    d = tmp_path_factory.mktemp("multiprocess_logs")
    previous = os.environ.get("MULTIPROCESS_LOG_DIR")
    os.environ["MULTIPROCESS_LOG_DIR"] = str(d)
    yield
    if previous is None:
        os.environ.pop("MULTIPROCESS_LOG_DIR", None)
    else:
        os.environ["MULTIPROCESS_LOG_DIR"] = previous
