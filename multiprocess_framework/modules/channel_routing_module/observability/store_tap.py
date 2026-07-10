# -*- coding: utf-8 -*-
"""
StoreTapChannel — tap-sink LoggerCore, пишущий записи в ObservabilityStore (Ф5.20a).

По дизайну Ф5.16 error/critical идут write-through в РЕАЛЬНЫЙ error_manager
(минуя буфер hub — SIGKILL обходит finally/atexit). Значит `hub.drain_all()`
ошибки НЕ содержит, и стор, наполняемый только из drain-петли, вкладку «Ошибки»
не покажет. Решение (владелец 2026-07-09): повесить этот tap на error_manager —
он ловит КАЖДУЮ error/critical-запись у реального sink'а (тот же проверенный
механизм, что log_tail: `LoggerCore.add_log_tap(channel, min_level)`), и кладёт
её в стор. log/stats при этом идут в стор пачкой из drain-петли (батчинг).

Канал — IChannel-совместимый (`write(dict)` / `name` / `close()`), duck-typed:
модуль НЕ импортирует logger_module (иначе core-слой получил бы обратную связь).
На вход `write` приходит `LogRecord.to_dict()`:
    {timestamp, level('ERROR'…), scope, message, module, extra{...}}
нормализуется в стор-запись kind (по умолчанию 'error').
"""

from __future__ import annotations

from typing import Any, Dict

from ..interfaces import IChannel
from .observability_store import KIND_ERROR, ObservabilityStore


class StoreTapChannel(IChannel):
    """Tap-sink (IChannel): LogRecord-dict → ObservabilityStore.append_records."""

    def __init__(
        self,
        store: ObservabilityStore,
        kind: str = KIND_ERROR,
        name: str = "observability_store_tap",
        process: str = "",
    ) -> None:
        """
        Args:
            store: целевой ObservabilityStore.
            kind: kind стор-записи (обычно 'error' — tap висит на error_manager).
            name: имя tap'а (хэндл для remove_log_tap).
            process: имя процесса-источника (5.21 (c)) — стор проставит колонку
                ``process``; пусто → падаем на ``module`` LogRecord.
        """
        self._store = store
        self._kind = kind
        self._name = name
        self._process = process

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "observability_store_tap"

    def write(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализовать LogRecord-dict и добавить в стор. Ошибку глушим (tail не критичен)."""
        rec = {
            "kind": self._kind,
            "process": self._process,
            "module": record_dict.get("module", ""),
            "ts": record_dict.get("timestamp", 0.0),
            "severity": str(record_dict.get("level", "")).lower(),
            "message": record_dict.get("message", ""),
            "context": record_dict.get("extra", {}),
        }
        try:
            self._store.append_records([rec])
        except Exception:  # nosec B110 — сбой стора не должен ронять логирование
            return {"status": "error", "channel": self._name}
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        """IChannel-совместимость: tap закрывается без побочных эффектов (стор общий)."""
