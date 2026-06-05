# -*- coding: utf-8 -*-
"""Тесты реестра sink-фабрик (Phase 2, Task 2.1).

Контракт: register_sink_factory(type, cls) добавляет тип канала в общий реестр,
create_channel(name, cfg) создаёт инстанс по cfg.type из реестра. Существующие
типы (file/console/http/frame_trace) сохраняются; повторная регистрация — last wins.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest

from multiprocess_framework.modules.logger_module import (
    register_sink_factory,
    get_registered_sink_types,
)
from multiprocess_framework.modules.logger_module.channels import log_channel
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    LogChannel,
    create_channel,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
)


@pytest.fixture(autouse=True)
def _restore_registry() -> Iterator[None]:
    """Реестр module-level — снимок до теста, восстановление после (нет протечки типов)."""
    snapshot = dict(log_channel._SINK_FACTORIES)
    try:
        yield
    finally:
        log_channel._SINK_FACTORIES.clear()
        log_channel._SINK_FACTORIES.update(snapshot)


class _MemorySink(LogChannel):
    """Фиктивный sink для теста: копит записи в памяти."""

    def __init__(self, config: LoggerChannelSchema) -> None:
        super().__init__(config)
        self.records: list[Dict[str, Any]] = []

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.records.append(record)
        return {"status": "ok"}


def _cfg(channel_type: str) -> LoggerChannelSchema:
    return LoggerChannelSchema(name="probe", type=channel_type, enabled=True)


def test_register_and_create() -> None:
    """Регистрируем кастомный тип → create_channel создаёт его инстанс."""
    register_sink_factory("memory", _MemorySink)
    ch = create_channel("probe", _cfg("memory"))
    assert isinstance(ch, _MemorySink)
    assert "memory" in get_registered_sink_types()


def test_duplicate_registration_last_wins() -> None:
    """Повторная регистрация того же типа переопределяет предыдущую."""

    class _Other(LogChannel):
        def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
            return {"status": "ok"}

    register_sink_factory("memory", _MemorySink)
    register_sink_factory("memory", _Other)
    ch = create_channel("probe", _cfg("memory"))
    assert isinstance(ch, _Other)


def test_unknown_type_raises_valueerror() -> None:
    """Неизвестный тип — поведение не изменилось (ValueError)."""
    with pytest.raises(ValueError, match="Unknown channel type"):
        create_channel("probe", _cfg("does_not_exist"))


def test_builtin_types_preserved() -> None:
    """Встроенные типы по-прежнему в реестре и создаются."""
    types = get_registered_sink_types()
    assert {"file", "console", "http", "frame_trace"} <= set(types)
    assert create_channel("c", _cfg("console")) is not None


def test_invalid_factory_raises_typeerror() -> None:
    """None / не-класс / класс без write() → TypeError; пустой type → TypeError."""
    with pytest.raises(TypeError):
        register_sink_factory("bad", None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        register_sink_factory("bad", "not_a_class")  # type: ignore[arg-type]

    class _NoWrite:
        pass

    with pytest.raises(TypeError):
        register_sink_factory("bad", _NoWrite)
    with pytest.raises(TypeError):
        register_sink_factory("", _MemorySink)
