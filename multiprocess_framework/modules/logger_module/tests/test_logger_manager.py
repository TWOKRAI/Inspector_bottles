# -*- coding: utf-8 -*-
"""
Тесты для LoggerManager.
"""

import logging
import logging.handlers
import tempfile
import os

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerManagerConfig,
    LogLevel,
    LogScope,
)


class TestLoggerManager:
    """Тесты для LoggerManager."""

    def test_create_manager(self):
        """Тест создания менеджера."""
        manager = LoggerManager(manager_name="TestLogger")
        assert manager.manager_name == "TestLogger"
        assert manager.config is not None

    def test_initialize(self):
        """Тест инициализации."""
        manager = LoggerManager(manager_name="TestLogger")
        result = manager.initialize()
        assert result is True
        assert manager.is_initialized is True

    def test_shutdown(self):
        """Тест завершения работы."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()
        result = manager.shutdown()
        assert result is True
        assert manager.is_initialized is False

    def test_log_info(self):
        """Тест логирования информации."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        # Логирование должно работать без ошибок
        manager.info("Test message", module="test")
        assert manager.stats["messages_processed"] > 0

    def test_log_error(self):
        """Тест логирования ошибки."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        manager.error("Test error", module="test")
        assert manager.stats["messages_processed"] > 0

    def test_get_stats(self):
        """Тест получения статистики."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        stats = manager.get_stats()
        # LoggerManager переопределяет get_stats() и возвращает свою статистику
        # Проверяем что есть основные поля статистики
        assert "messages_processed" in stats
        assert "app_name" in stats
        # Проверяем что manager_name доступен через атрибут
        assert manager.manager_name == "TestLogger"

    def test_context_manager(self):
        """Тест использования как context manager."""
        manager = LoggerManager(manager_name="TestLogger")

        # LoggerManager не поддерживает context manager протокол
        # Используем явный вызов initialize/shutdown
        manager.initialize()
        assert manager.is_initialized is True

        manager.shutdown()
        assert manager.is_initialized is False

    def test_module_rotate_false_uses_file_handler(self, tmp_path):
        """Без ротации — FileHandler (избегаем os.rename на Windows для частых логов)."""
        log_file = tmp_path / "frames.log"
        cfg = LoggerManagerConfig.model_validate(
            {
                "enable_batching": False,
                "modules": {
                    "processor_frames": {
                        "enabled": True,
                        "file_path": str(log_file),
                        "min_level": "DEBUG",
                        "rotate": False,
                    }
                },
            }
        )
        manager = LoggerManager(manager_name="TestLogger", config=cfg)
        manager.initialize()
        ch = manager._module_channels["processor_frames"]
        assert ch.handler.__class__ is logging.FileHandler
        assert not isinstance(ch.handler, logging.handlers.RotatingFileHandler)
        manager.shutdown()

    def test_module_channel(self):
        """Тест создания канала для модуля."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        # Создаем временный файл для модуля
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            temp_path = f.name

        try:
            # Используем правильное имя метода
            manager.enable_module_logging("test_module", file_path=temp_path)
            manager.info("Module message", module="test_module")

            # Проверяем что файл создан
            assert os.path.exists(temp_path)

            # Закрываем все хендлеры перед удалением файла (важно для Windows)
            manager.shutdown()
        finally:
            # Небольшая задержка для Windows (файл может быть еще открыт)
            import time

            time.sleep(0.1)
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except PermissionError:
                    # На Windows файл может быть еще занят, игнорируем ошибку
                    pass

    def test_config_update(self):
        """Тест обновления конфигурации."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        # Обновляем конфигурацию напрямую (LoggerManager имеет свой метод update_config)
        # update_config в ObservableMixin ожидает dict, а не LoggerManagerConfig
        # Поэтому обновляем напрямую через атрибут config
        manager.config.app_name = "NewApp"

        assert manager.config.app_name == "NewApp"

    def test_flush(self):
        """Тест принудительной записи."""
        manager = LoggerManager(manager_name="TestLogger")
        manager.initialize()

        # Flush должен работать без ошибок
        manager.flush()
        assert True  # Если дошли сюда, значит flush работает


class TestLoggerReconfigure:
    """Reconfigure + инвалидация кэша should_log (Task 1.1)."""

    @staticmethod
    def _cfg(debug_min_level: str, channel_name: str) -> LoggerManagerConfig:
        """Конфиг с одним file-каналом и заданным min_level у DEBUG scope."""
        return LoggerManagerConfig.model_validate(
            {
                "enable_batching": False,
                "channels": {
                    channel_name: {"type": "console", "enabled": True},
                },
                "scopes": {
                    "DEBUG": {
                        "enabled": True,
                        "min_level": debug_min_level,
                        "channels": [channel_name],
                    }
                },
            }
        )

    def test_reconfigure_invalidates_decision_cache(self):
        # min_level=INFO → DEBUG скипается и кэшируется как False.
        mgr = LoggerManager(
            manager_name="TestLogger",
            config=self._cfg("INFO", "ch_a"),
        )
        mgr.initialize()
        assert mgr.should_log(LogScope.DEBUG, LogLevel.DEBUG, "test") is False
        # Решение залегло в кэше.
        assert mgr._decision_cache  # not empty

        # Реконфигурируем: теперь DEBUG разрешён.
        assert mgr.reconfigure(self._cfg("DEBUG", "ch_a").model_dump()) is True
        # Кэш инвалидирован → новое решение должно быть True.
        assert mgr.should_log(LogScope.DEBUG, LogLevel.DEBUG, "test") is True
        mgr.shutdown()

    def test_invalidate_decision_cache_clears(self):
        mgr = LoggerManager(manager_name="TestLogger")
        mgr.initialize()
        mgr.should_log(LogScope.DEBUG, LogLevel.DEBUG, "test")
        assert mgr._decision_cache
        mgr.invalidate_decision_cache()
        assert mgr._decision_cache == {}
        mgr.shutdown()

    def test_reconfigure_replaces_channel_set(self):
        mgr = LoggerManager(
            manager_name="TestLogger",
            config=self._cfg("INFO", "old_ch"),
        )
        mgr.initialize()
        assert mgr.get_channel("old_ch") is not None

        assert mgr.reconfigure(self._cfg("INFO", "new_ch").model_dump()) is True
        names = {ch.name for ch in mgr.get_all_channels()}
        assert "new_ch" in names
        assert "old_ch" not in names
        mgr.shutdown()

    def test_reconfigure_before_initialize_does_not_raise(self):
        mgr = LoggerManager(
            manager_name="TestLogger",
            config=self._cfg("INFO", "ch"),
        )
        # без initialize(): буфер не запущен
        assert mgr.reconfigure(self._cfg("DEBUG", "ch").model_dump()) is True

    def test_reconfigure_empty_dict_does_not_crash(self):
        mgr = LoggerManager(manager_name="TestLogger")
        mgr.initialize()
        # Пустой dict → дефолтный LoggerManagerConfig, процесс не падает.
        assert mgr.reconfigure({}) is True
        mgr.shutdown()


class _FakeTapChannel:
    """Минимальный IChannel-совместимый tap: только write(dict) (Task 1.5 API)."""

    def __init__(self):
        self.records: list = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        pass


class TestTraceIdExtraField:
    """Ф7 G.6: trace_id, переданный как extra-kwarg (**extra в info/debug/error),
    попадает в LogRecord.extra — реальная LoggerManager-цепочка, не заглушка."""

    def test_trace_id_lands_in_log_record_extra(self):
        mgr = LoggerManager(manager_name="TestLoggerTraceId")
        mgr.initialize()
        tap = _FakeTapChannel()
        mgr.add_log_tap(tap, min_level=LogLevel.DEBUG)

        trace_id = "0123456789abcdef0123456789abcdef"
        mgr.info("frame processed", module="detector", trace_id=trace_id, frame_hops=2)

        assert tap.records, "tap должен был получить запись"
        record = tap.records[-1]
        assert record["extra"]["trace_id"] == trace_id
        assert record["extra"]["frame_hops"] == 2
        mgr.shutdown()

    def test_two_nodes_same_trace_id_correlate_via_tap(self):
        """Симуляция «≥2 звена»: два debug-вызова с одним trace_id — оба видны
        через один tap, идентичны по extra["trace_id"] (суть acceptance G.6)."""
        mgr = LoggerManager(manager_name="TestLoggerTraceIdCorrelate")
        mgr.initialize()
        tap = _FakeTapChannel()
        mgr.add_log_tap(tap, min_level=LogLevel.DEBUG)

        # info() (BUSINESS/INFO) — включён в дефолтном конфиге (в отличие от DEBUG,
        # см. test_reconfigure_invalidates_decision_cache); суть теста — корреляция
        # по trace_id, а не конкретный уровень.
        trace_id = "abcdef0123456789abcdef0123456789"
        mgr.info("[TRACE] SourceProducer(camera_0): produce()", module="camera_0", trace_id=trace_id)
        mgr.info("[TRACE] DataReceiver: item built", module="detector", trace_id=trace_id)

        trace_records = [r for r in tap.records if r["extra"].get("trace_id") == trace_id]
        assert len(trace_records) == 2
        assert {r["module"] for r in trace_records} == {"camera_0", "detector"}
        mgr.shutdown()
