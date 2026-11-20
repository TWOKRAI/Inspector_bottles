# -*- coding: utf-8 -*-
"""Task 4c, Б1 (слепой тест REDS 7): DEBUG-журнал ``RegistersManager.set_field_value`` не пишет значение поля.

Значение уходит только подписчикам (и ``send_callback``); в журнал — имя регистра и поля без значения.
Харнес — настоящий ``LoggerManager`` с файловым каналом и ``default_level: DEBUG`` (по умолчанию INFO DEBUG
не пишет: тест без этого не видел бы строки вовсе). Имя поля НЕЙТРАЛЬНОЕ (``note``): значения секретных имён
(``token``/``secret``/``password``) маскирует сам ``logger_module/core/redaction.py``, и такой тест был бы
зелёным и до правки.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager

_MARKER = "S3CRET-VALUE-42"


class _NoteRegister(BaseModel):
    note: str = ""


@pytest.fixture
def logger_to_file(tmp_path: Path):
    log_file = tmp_path / "a.log"
    config: dict[str, Any] = {
        "app_name": "reg_log",
        "log_directory": str(tmp_path),
        "default_level": "DEBUG",
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(log_file)}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }
    mgr = LoggerManager(manager_name="RegLogProbe", config=config)
    mgr.initialize()
    yield mgr, log_file
    mgr.shutdown()


def _journal_lines(log_file: Path) -> list[str]:
    assert log_file.exists(), "канал не создал файл: журнал пуст целиком"
    return log_file.read_text(encoding="utf-8").splitlines()


def _write_marker(logger: LoggerManager) -> tuple[list[Any], tuple[bool, str | None]]:
    rm = RegistersManager(registers={"reg": _NoteRegister()}, logger=logger)
    received: list[Any] = []
    rm.subscribe("reg", "note", received.append)
    result = rm.set_field_value("reg", "note", _MARKER)
    return received, result


def test_set_field_value_debug_line_is_written_with_register_and_field_names(logger_to_file) -> None:
    """Предусловие, что тест не пустой: DEBUG-строка записи поля в файле есть и называет ``reg.note``."""
    logger, log_file = logger_to_file
    _, result = _write_marker(logger)
    assert result == (True, None)
    lines = _journal_lines(log_file)
    assert any("set_field_value:" in line and "reg.note" in line for line in lines), lines


def test_journal_does_not_contain_written_value(logger_to_file) -> None:
    logger, log_file = logger_to_file
    _, result = _write_marker(logger)
    assert result == (True, None)
    lines = _journal_lines(log_file)
    assert any("set_field_value:" in line for line in lines), f"предусловие: строка записи есть, журнал: {lines}"
    leaked = [line for line in lines if _MARKER in line]
    assert leaked == [], leaked


def test_subscriber_still_receives_written_value(logger_to_file) -> None:
    logger, _ = logger_to_file
    received, result = _write_marker(logger)
    assert result == (True, None)
    assert received == [_MARKER]
