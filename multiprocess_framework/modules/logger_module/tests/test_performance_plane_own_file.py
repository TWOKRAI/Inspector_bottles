# -*- coding: utf-8 -*-
"""Ф2.6 — снапшот метрик уезжает из `system.log` в свой файл.

План: plans/observability-unified-routing.md, задача 2.6, рекомендация 1 ревью решений.

Живой повод числами (прогон 2026-08-03, 48 процессов): скоуп ``PERFORMANCE`` держал
5.27 МБ из 9.38 МБ ``system.log`` у ProcessManager (56%), 2.33 из 8.88 у gui (26%),
2.08 из 8.63 у region_splitter (24%). Одна строка снапшота весит около 7 КБ — список
метрик, отрендеренный в текст. Открывая ``system.log`` после инцидента, оператор
продирался через них.

Файл характеризационный: он фиксирует **изменение живого поведения**, а не защищает
прежнее. Снапшоты перестают попадать в ``system.log`` — это перенос, а не дублирование,
и выбран он сознательно, иначе разгрузки не случится вовсе. Оставить такое умолчанием
значило бы, что первый же прогон объявит фикс сломанным («метрики пропали из системного
лога»).

Проверка идёт по СОДЕРЖИМОМУ ФАЙЛОВ на диске, а не по полям конфига: сравнение
``config.scopes["PERFORMANCE"].channels`` с ожидаемым списком согласилось бы с любой
поломкой маршрута ниже конфига — гейта, резолва, записи.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.statistics_module.channels.log_stats_channel import (
    LogStatsChannel,
)

_MARK = "metrics snapshot"


@pytest.fixture()
def logger(tmp_path) -> Any:
    """Дефолты фреймворка как есть — правится ровно то, что проверяется.

    Ни каналы, ни скоупы не переопределяются: подмена дефолта своим набором
    доказала бы работоспособность механизма, а вопрос стоит про ПОСТАВЛЯЕМУЮ
    настройку. Ровно этот зазор оставил в бою 288 нулевых файлов при зелёных тестах.
    """
    manager = LoggerManager(
        config=LoggerManagerConfig(
            app_name="perf26",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    yield manager
    manager.shutdown()


def _read(tmp_path, name: str) -> str:
    path = tmp_path / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


class TestSnapshotLeavesTheSystemLog:
    def test_snapshot_lands_in_performance_log(self, logger: Any, tmp_path) -> None:
        LogStatsChannel(logger_manager=logger, name="log_stats").write(
            {"metrics": [{"name": "fps", "value": 21}], "total_count": 1, "timestamp": 0.0}
        )
        logger.flush()

        assert _MARK in _read(tmp_path, "performance.log")

    def test_snapshot_no_longer_lands_in_system_log(self, logger: Any, tmp_path) -> None:
        """Вторая половина пары. Без неё «уехало» неотличимо от «продублировалось»."""
        LogStatsChannel(logger_manager=logger, name="log_stats").write(
            {"metrics": [{"name": "fps", "value": 21}], "total_count": 1, "timestamp": 0.0}
        )
        logger.flush()

        assert _MARK not in _read(tmp_path, "system.log")

    def test_system_plane_still_reaches_the_system_log(self, logger: Any, tmp_path) -> None:
        """Разгрузка не должна была задеть соседний скоуп — пара к переносу."""
        logger.system(LogLevel.WARNING, "штатное предупреждение", module="проба")
        logger.flush()

        assert "штатное предупреждение" in _read(tmp_path, "system.log")
