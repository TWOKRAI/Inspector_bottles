# -*- coding: utf-8 -*-
"""Публичные контракты code_reader.

Единственный файл, от которого должны зависеть внешние модули
(`Plugins/`, `multiprocess_prototype/`). Protocol вместо ABC — structural
subtyping, как в `Services/hikvision_camera/interfaces.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from Services.code_reader.core.result import ReadResult, ReadStatus

__all__ = ["CodeReaderSinkProtocol", "ReadResult", "ReadStatus", "ResultHandler"]

ResultHandler = Callable[[ReadResult], None]


@runtime_checkable
class CodeReaderSinkProtocol(Protocol):
    """Контракт приёмника результатов считывателя.

    Реализация `core.sink.ResultSink` принимает по TCP от прибора в режиме
    `TCP Client`. Тот же контракт удобно закрыть заглушкой в тестах и
    симулятором на стенде, где железа нет.
    """

    @property
    def port(self) -> int:
        """Порт, на котором принимаются подключения."""
        ...

    @property
    def is_running(self) -> bool:
        """Идёт ли приём."""
        ...

    def start(self) -> None:
        """Начать принимать. Повторный вызов на запущенном — ошибка."""
        ...

    def stop(self, timeout: float = 2.0) -> None:
        """Прекратить приём. Вызов на незапущенном безопасен."""
        ...
