"""logging_mw.py — Middleware структурированного логирования state-изменений.

Логирует каждый set/merge/delete с path, source, old/new значениями.
Поддерживает фильтрацию шумных путей через exclude_patterns (glob-синтаксис).
Rejected операции всегда логируются как WARNING, независимо от фильтров.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.delta import Delta
from ..core import match_pattern, split_pattern
from .base import StateMiddleware


class LoggingMiddleware(StateMiddleware):
    """Структурированное логирование state-изменений.

    Уровни:
    - DEBUG (по умолчанию): каждый set/merge/delete с path + source + old/new
    - INFO: краткое summary (операция на path от source)

    Фильтрация: exclude_patterns=["**.state.actual_fps"] — не логировать шумные пути.

    Rejected операции логируются как WARNING (всегда, не фильтруются).
    """

    @property
    def name(self) -> str:
        return "logging"

    def __init__(
        self,
        logger: logging.Logger | None = None,
        level: str = "DEBUG",
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """
        Args:
            logger: объект логгера. По умолчанию — logging.getLogger("state_store.changes").
            level: уровень логирования ("DEBUG", "INFO", "WARNING" и т.д.).
            exclude_patterns: список glob-паттернов путей, которые не нужно логировать.
                Пример: ["**.state.actual_fps", "cameras.*.debug.*"]
        """
        self._log = logger or logging.getLogger("state_store.changes")
        self._level = getattr(logging, level.upper(), logging.DEBUG)
        self._exclude_patterns: list[str] = exclude_patterns or []

    # --- set ---

    def after_set(self, delta: Delta, context: dict) -> None:
        """Логировать успешный set. Исключённые пути пропускаются."""
        if self._is_excluded(delta.path):
            return

        self._log.log(
            self._level,
            "state.set %s: %r → %r (source=%s)",
            delta.path,
            delta.old_value,
            delta.new_value,
            delta.source,
        )

    # --- merge ---

    def after_merge(self, deltas: list[Delta], context: dict) -> None:
        """Логировать результат merge: количество изменений и источник."""
        # Фильтруем дельты по exclude_patterns для подсчёта реально залогированных
        visible = [d for d in deltas if not self._is_excluded(d.path)]

        if not visible:
            return

        source = visible[0].source if visible else "unknown"
        self._log.log(
            self._level,
            "state.merge %d изменений от source=%s",
            len(visible),
            source,
        )

        # Подробное логирование каждой дельты
        for delta in visible:
            self._log.log(
                self._level,
                "  state.set %s: %r → %r",
                delta.path,
                delta.old_value,
                delta.new_value,
            )

    # --- delete ---

    def after_delete(self, delta: Delta, context: dict) -> None:
        """Логировать успешный delete. Исключённые пути пропускаются."""
        if self._is_excluded(delta.path):
            return

        self._log.log(
            self._level,
            "state.delete %s: %r (source=%s)",
            delta.path,
            delta.old_value,
            delta.source,
        )

    # --- Вспомогательные методы ---

    def _is_excluded(self, path: str) -> bool:
        """Проверить, попадает ли path в exclude_patterns.

        Args:
            path: путь в дереве состояний (например, "cameras.0.state.actual_fps").

        Returns:
            True если путь совпадает хотя бы с одним паттерном исключения.
        """
        path_segs = tuple(path.split("."))
        for pattern in self._exclude_patterns:
            pattern_segs = split_pattern(pattern)
            if match_pattern(pattern_segs, path_segs):
                return True
        return False
