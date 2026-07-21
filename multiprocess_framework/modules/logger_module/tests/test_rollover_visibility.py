# -*- coding: utf-8 -*-
"""Тесты видимости сбоя ротации ``_SafeRotatingFileHandler`` (log_channel.py).

Контракт (находка живого прогона webcam_sketch 2026-07-21): систематический
сбой ротации (Windows, несколько процессов держат файл) раньше глушился
молча (``except PermissionError: pass``) — без счётчика и без предупреждения,
из-за чего ``messages.log`` вырос до 645 МБ при лимите ~60 МБ. Теперь:

- сбой ротации растит счётчик и (троттлированно) даёт WARNING;
- успешная ротация счётчик НЕ растит и WARNING не даёт (пара ON/OFF);
- повторные сбои НЕ дают повторные WARNING (троттлинг по времени);
- запись логов продолжается несмотря на сбой ротации (fail-open не сломан).
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

from multiprocess_framework.modules.logger_module.channels.log_channel import (
    FileChannel,
    _SafeRotatingFileHandler,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
)

_LOGGER_NAME = "multiprocess_framework.modules.logger_module.channels.log_channel"


def _make_handler(tmp_path: Path) -> _SafeRotatingFileHandler:
    return _SafeRotatingFileHandler(
        filename=str(tmp_path / "probe.log"),
        maxBytes=1024,
        backupCount=3,
        encoding="utf-8",
    )


def _break_rollover(monkeypatch) -> None:
    """Подменить РОДИТЕЛЬСКИЙ doRollover — как будто файл занят другим процессом."""

    def _raise(self):
        raise PermissionError("[WinError 32] файл занят другим процессом")

    monkeypatch.setattr(logging.handlers.RotatingFileHandler, "doRollover", _raise)


class TestRolloverFailureVisibilityPair:
    """Пара ON/OFF: сбой ротации виден, успех — нет (одиночный зелёный не принимается)."""

    def test_permission_error_increments_counter_and_warns(self, tmp_path, monkeypatch, caplog) -> None:
        """ON: PermissionError -> счётчик вырос на 1, WARNING выдан и называет проблему прямо."""
        handler = _make_handler(tmp_path)
        _break_rollover(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            handler.doRollover()

        assert handler._rollover_failures == 1
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        text = caplog.text.lower()
        assert "не соблюда" in text, "предупреждение обязано прямо называть нарушение лимита"
        assert "неограниченно" in text, "предупреждение обязано прямо называть рост файла"
        handler.close()

    def test_success_does_not_increment_counter_or_warn(self, tmp_path, caplog) -> None:
        """OFF: реальная успешная ротация -> счётчик НЕ растёт, WARNING нет."""
        handler = _make_handler(tmp_path)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            handler.doRollover()  # родительский doRollover ничем не подменён — отработает штатно

        assert handler._rollover_failures == 0
        assert len(caplog.records) == 0
        handler.close()

    def test_success_after_failures_resets_counter(self, tmp_path, monkeypatch, caplog) -> None:
        """Счётчик — именно ПОДРЯД: успешная ротация обнуляет серию сбоев."""
        handler = _make_handler(tmp_path)
        _break_rollover(monkeypatch)
        handler.doRollover()
        handler.doRollover()
        assert handler._rollover_failures == 2

        monkeypatch.undo()  # вернуть настоящий doRollover родителя
        handler.doRollover()
        assert handler._rollover_failures == 0
        handler.close()


class TestRolloverWarningThrottle:
    """N сбоев подряд НЕ должны давать N предупреждений (троттлинг по времени)."""

    def test_repeated_failures_throttled_to_one_warning(self, tmp_path, monkeypatch, caplog) -> None:
        handler = _make_handler(tmp_path)
        _break_rollover(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            for _ in range(50):
                handler.doRollover()

        assert handler._rollover_failures == 50, "счётчик считает КАЖДЫЙ сбой"
        assert len(caplog.records) == 1, "но WARNING в пределах интервала — только один"
        handler.close()

    def test_throttle_window_expiry_allows_next_warning(self, tmp_path, monkeypatch, caplog) -> None:
        """По истечении интервала троттлинга — новое предупреждение разрешено."""
        handler = _make_handler(tmp_path)
        _break_rollover(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            handler.doRollover()
            assert len(caplog.records) == 1

            # Симулируем истечение интервала без реального sleep().
            handler._last_rollover_warning_ts -= handler._ROLLOVER_WARNING_INTERVAL_SEC + 1
            handler.doRollover()

        assert len(caplog.records) == 2
        assert handler._rollover_failures == 2
        handler.close()


class TestRolloverFailOpen:
    """Запись логов продолжается несмотря на постоянно неудачную ротацию."""

    def test_write_continues_when_rollover_fails(self, tmp_path, monkeypatch) -> None:
        cfg = LoggerChannelSchema(
            name="probe",
            type="file",
            enabled=True,
            file_path=str(tmp_path / "probe.log"),
            max_size=1,  # любая запись превышает лимит -> shouldRollover() всегда True
            backup_count=3,
        )
        channel = FileChannel(cfg)
        _break_rollover(monkeypatch)

        for i in range(5):
            result = channel.write(
                {
                    "module": "probe",
                    "level": "INFO",
                    "message": f"line {i}",
                    "timestamp": time.time(),
                }
            )
            assert result["status"] == "success", "сбой ротации не должен ронять запись (fail-open)"

        assert channel.handler._rollover_failures > 0, "ротация действительно ломалась все 5 раз"
        assert Path(cfg.file_path).exists()
        channel.close()
