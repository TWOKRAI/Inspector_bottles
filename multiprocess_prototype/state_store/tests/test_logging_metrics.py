"""test_logging_metrics.py — Тесты для LoggingMiddleware и MetricsMiddleware (Task 4b+.4).

Проверяет:
- LoggingMiddleware: логирование set/merge/delete, фильтрация exclude_patterns
- MetricsMiddleware: счётчики операций, разбивка по источникам, reset, get_stats
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest
from state_store.core.delta import Delta, MISSING
from state_store.middleware.logging_mw import LoggingMiddleware
from state_store.middleware.metrics import MetricsMiddleware


# ---------------------------------------------------------------------------
# Фабричные функции для тестовых объектов
# ---------------------------------------------------------------------------


def make_delta(
    path: str = "cameras.0.fps",
    old_value: object = 25,
    new_value: object = 30,
    source: str = "gui",
) -> Delta:
    """Создать тестовую Delta с заданными параметрами."""
    return Delta(path=path, old_value=old_value, new_value=new_value, source=source)


# ---------------------------------------------------------------------------
# Тесты LoggingMiddleware
# ---------------------------------------------------------------------------


class TestLoggingMiddleware:
    """Тесты для LoggingMiddleware."""

    def test_name(self):
        """Имя middleware должно быть 'logging'."""
        mw = LoggingMiddleware()
        assert mw.name == "logging"

    def test_after_set_логирует_изменение(self):
        """after_set вызывает log с path, old/new, source."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(logger=mock_logger, level="DEBUG")

        delta = make_delta(path="cameras.0.fps", old_value=25, new_value=30, source="gui")
        mw.after_set(delta, {})

        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        # Первый аргумент — уровень
        assert call_args[0][0] == logging.DEBUG
        # В форматной строке должен быть path
        assert "cameras.0.fps" in str(call_args)

    def test_after_set_exclude_patterns_совпадение_не_логирует(self):
        """Если path матчит exclude_patterns — after_set не логирует."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(
            logger=mock_logger,
            exclude_patterns=["cameras.**.actual_fps"],
        )

        delta = make_delta(path="cameras.0.state.actual_fps")
        mw.after_set(delta, {})

        mock_logger.log.assert_not_called()

    def test_after_set_exclude_patterns_не_совпадение_логирует(self):
        """Если path НЕ матчит exclude_patterns — after_set логирует."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(
            logger=mock_logger,
            exclude_patterns=["cameras.**.actual_fps"],
        )

        delta = make_delta(path="cameras.0.config.fps")
        mw.after_set(delta, {})

        mock_logger.log.assert_called_once()

    def test_after_merge_логирует_количество_изменений(self):
        """after_merge логирует количество видимых дельт."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(logger=mock_logger, level="INFO")

        deltas = [
            make_delta(path="cam.fps", old_value=25, new_value=30, source="recipe"),
            make_delta(path="cam.width", old_value=1920, new_value=1280, source="recipe"),
        ]
        mw.after_merge(deltas, {})

        # Ожидаем минимум 1 вызов log (summary + по дельте)
        assert mock_logger.log.call_count >= 1
        # Первый вызов должен содержать "2" (количество изменений)
        first_call = mock_logger.log.call_args_list[0]
        assert "2" in str(first_call) or 2 in first_call[0]

    def test_after_merge_все_excluded_не_логирует(self):
        """Если все дельты отфильтрованы — merge не логирует ничего."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(
            logger=mock_logger,
            exclude_patterns=["debug.**"],
        )

        deltas = [
            make_delta(path="debug.fps"),
            make_delta(path="debug.latency"),
        ]
        mw.after_merge(deltas, {})

        mock_logger.log.assert_not_called()

    def test_after_delete_логирует(self):
        """after_delete логирует удаление."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(logger=mock_logger)

        delta = make_delta(path="cameras.1", old_value={"fps": 30}, new_value=MISSING)
        mw.after_delete(delta, {})

        mock_logger.log.assert_called_once()
        call_str = str(mock_logger.log.call_args)
        assert "cameras.1" in call_str

    def test_is_excluded_glob_double_star(self):
        """_is_excluded корректно работает с ** паттернами."""
        mw = LoggingMiddleware(exclude_patterns=["cameras.**.fps"])

        assert mw._is_excluded("cameras.0.fps") is True
        assert mw._is_excluded("cameras.0.config.fps") is True
        assert mw._is_excluded("cameras.0.config.width") is False

    def test_is_excluded_single_star(self):
        """_is_excluded корректно работает с * паттернами."""
        mw = LoggingMiddleware(exclude_patterns=["cameras.*.fps"])

        assert mw._is_excluded("cameras.0.fps") is True
        assert mw._is_excluded("cameras.1.fps") is True
        # * не проваливается на два уровня
        assert mw._is_excluded("cameras.0.config.fps") is False

    def test_is_excluded_точное_совпадение(self):
        """_is_excluded работает с точными паттернами (без wildcards)."""
        mw = LoggingMiddleware(exclude_patterns=["system.debug.verbose"])

        assert mw._is_excluded("system.debug.verbose") is True
        assert mw._is_excluded("system.debug.level") is False

    def test_уровень_логирования_info(self):
        """При level='INFO' используется logging.INFO."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(logger=mock_logger, level="INFO")

        delta = make_delta()
        mw.after_set(delta, {})

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.INFO

    def test_пустые_exclude_patterns_логирует_всё(self):
        """Без exclude_patterns все пути логируются."""
        mock_logger = MagicMock()
        mw = LoggingMiddleware(logger=mock_logger)

        mw.after_set(make_delta(path="a.b.c"), {})
        mw.after_set(make_delta(path="x.y.z"), {})

        assert mock_logger.log.call_count == 2

    def test_caplog_интеграция(self, caplog):
        """Интеграционный тест через caplog: реальный логгер."""
        mw = LoggingMiddleware(level="DEBUG")

        with caplog.at_level(logging.DEBUG, logger="state_store.changes"):
            delta = make_delta(path="gui.button.state", old_value=False, new_value=True)
            mw.after_set(delta, {})

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "gui.button.state" in record.message
        assert record.levelno == logging.DEBUG


# ---------------------------------------------------------------------------
# Тесты MetricsMiddleware
# ---------------------------------------------------------------------------


class TestMetricsMiddleware:
    """Тесты для MetricsMiddleware."""

    def test_name(self):
        """Имя middleware должно быть 'metrics'."""
        mw = MetricsMiddleware()
        assert mw.name == "metrics"

    def test_after_set_увеличивает_operations_total_set(self):
        """after_set увеличивает счётчик operations_total['set']."""
        mw = MetricsMiddleware()
        delta = make_delta(source="gui")

        mw.after_set(delta, {})
        stats = mw.get_stats()

        assert stats["operations_total"]["set"] == 1

    def test_after_set_несколько_операций(self):
        """Несколько after_set суммируются корректно."""
        mw = MetricsMiddleware()

        for _ in range(5):
            mw.after_set(make_delta(), {})

        assert mw.get_stats()["operations_total"]["set"] == 5

    def test_after_merge_увеличивает_operations_total_merge(self):
        """after_merge увеличивает счётчик operations_total['merge']."""
        mw = MetricsMiddleware()
        deltas = [make_delta(path="a.b"), make_delta(path="a.c")]

        mw.after_merge(deltas, {})
        stats = mw.get_stats()

        assert stats["operations_total"]["merge"] == 1

    def test_after_delete_увеличивает_operations_total_delete(self):
        """after_delete увеличивает счётчик operations_total['delete']."""
        mw = MetricsMiddleware()
        delta = make_delta(new_value=MISSING)

        mw.after_delete(delta, {})
        stats = mw.get_stats()

        assert stats["operations_total"]["delete"] == 1

    def test_operations_by_source_считает_правильно(self):
        """operations_by_source накапливает счётчики по источникам."""
        mw = MetricsMiddleware()

        mw.after_set(make_delta(source="gui"), {})
        mw.after_set(make_delta(source="gui"), {})
        mw.after_set(make_delta(source="camera_0"), {})

        stats = mw.get_stats()
        assert stats["operations_by_source"]["gui"] == 2
        assert stats["operations_by_source"]["camera_0"] == 1

    def test_operations_by_source_из_merge(self):
        """Источник merge берётся из первой дельты."""
        mw = MetricsMiddleware()

        deltas = [
            make_delta(path="a.x", source="recipe"),
            make_delta(path="a.y", source="recipe"),
        ]
        mw.after_merge(deltas, {})

        stats = mw.get_stats()
        assert stats["operations_by_source"]["recipe"] == 1

    def test_get_stats_возвращает_snapshot(self):
        """get_stats() возвращает независимую копию (изменение snapshot не влияет на метрики)."""
        mw = MetricsMiddleware()
        mw.after_set(make_delta(), {})

        stats = mw.get_stats()
        # Мутируем snapshot
        stats["operations_total"]["set"] = 999
        stats["operations_by_source"]["fake"] = 999

        # Оригинальные метрики не изменились
        fresh_stats = mw.get_stats()
        assert fresh_stats["operations_total"]["set"] == 1
        assert "fake" not in fresh_stats["operations_by_source"]

    def test_reset_обнуляет_всё(self):
        """reset() сбрасывает все счётчики в начальное состояние."""
        mw = MetricsMiddleware()

        mw.after_set(make_delta(source="gui"), {})
        mw.after_merge([make_delta()], {})
        mw.after_delete(make_delta(), {})
        mw.increment_rejected()

        mw.reset()
        stats = mw.get_stats()

        assert stats["operations_total"] == {"set": 0, "merge": 0, "delete": 0}
        assert stats["operations_rejected"] == 0
        assert stats["operations_by_source"] == {}
        assert stats["operations_total"]["set"] == 0

    def test_last_operation_time_обновляется(self):
        """last_operation_time обновляется после каждой операции."""
        mw = MetricsMiddleware()

        assert mw.get_stats()["last_operation_time"] == 0.0

        t_before = time.monotonic()
        mw.after_set(make_delta(), {})
        t_after = time.monotonic()

        last_time = mw.get_stats()["last_operation_time"]
        assert t_before <= last_time <= t_after

    def test_last_operation_time_merge(self):
        """last_operation_time обновляется после merge."""
        mw = MetricsMiddleware()

        t_before = time.monotonic()
        mw.after_merge([make_delta()], {})
        t_after = time.monotonic()

        last_time = mw.get_stats()["last_operation_time"]
        assert t_before <= last_time <= t_after

    def test_increment_rejected(self):
        """increment_rejected увеличивает operations_rejected."""
        mw = MetricsMiddleware()

        mw.increment_rejected()
        mw.increment_rejected()

        assert mw.get_stats()["operations_rejected"] == 2

    def test_before_set_не_модифицирует(self):
        """before_set не меняет value и не отклоняет операцию."""
        mw = MetricsMiddleware()

        proceed, value = mw.before_set("a.b", 42, "src", {})

        assert proceed is True
        assert value == 42

    def test_after_merge_пустые_deltas(self):
        """after_merge с пустым списком дельт не падает."""
        mw = MetricsMiddleware()

        mw.after_merge([], {})
        stats = mw.get_stats()

        assert stats["operations_total"]["merge"] == 1
        # Источник не записывается если нет дельт
        assert stats["operations_by_source"] == {}
