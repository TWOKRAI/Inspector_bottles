# -*- coding: utf-8 -*-
"""
StoreTapChannel — tap-sink LoggerCore, пишущий записи в ObservabilityStore (Ф5.20a).

По дизайну Ф5.16 (+ уточнение R1/R3 2026-07-10) error/critical идут write-through
в РЕАЛЬНЫЕ менеджеры, минуя буфер hub (SIGKILL обходит finally/atexit): через
error_manager (track_error) И через logger_manager (расщепитель logger-слота
пишет error/critical лог напрямую). Значит `hub.drain_all()` ошибки НЕ содержит,
и стор, наполняемый только из drain-петли, вкладку «Ошибки» не покажет. Решение
(владелец 2026-07-09): повесить этот tap на error_manager И logger_manager — он
ловит КАЖДУЮ error/critical-запись у реального sink'а (тот же проверенный
механизм, что log_tail: `LoggerCore.add_tap(channel, min_level)`), и кладёт
её в стор РОВНО один раз (write-through исключает переигровку из drain → нет
дубля). log (severity < ERROR)/stats при этом идут в стор пачкой из drain-петли.

Канал — IChannel-совместимый (`write(dict)` / `name` / `close()`), duck-typed:
модуль НЕ импортирует logger_module (иначе core-слой получил бы обратную связь).
На вход `write` приходит `LogRecord.to_dict()`:
    {timestamp, level('ERROR'…), scope, message, module, extra{...}}
нормализуется в стор-запись kind (по умолчанию 'error').
"""

from __future__ import annotations

from typing import Any, Dict

from ..interfaces import IChannel
from .observability_store import ObservabilityStore
from .record_display import KIND_LOG, kind_for_severity, severity_number_for


class StoreTapChannel(IChannel):
    """Tap-sink (IChannel): LogRecord-dict → ObservabilityStore.append_records."""

    def __init__(
        self,
        store: ObservabilityStore,
        name: str = "observability_store_tap",
        process: str = "",
    ) -> None:
        """
        Args:
            store: целевой ObservabilityStore.
            name: имя tap'а (хэндл для remove_tap).
            process: имя процесса-источника (5.21 (c)) — стор проставит колонку
                ``process``; пусто → падаем на ``module`` LogRecord.

        Параметра ``kind`` больше нет (Ф5.2, Б-4): вид записи считает её важность,
        а не конструктор канала. Прежний дефолт ``'error'`` и был дефектом — tap
        висит на ДВУХ менеджерах, и всё, что проходило порог на logger'е, ложилось
        в стор ошибкой.
        """
        self._store = store
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
        severity = str(record_dict.get("level", "")).lower()
        rec = {
            # Ф5.2 (Б-4): вид считает важность записи, тем же правилом и тем же
            # порогом, что и live-хвост — иначе одна запись приезжала бы во вкладку
            # логом, а в историю ошибкой.
            "kind": kind_for_severity(severity_number_for(KIND_LOG, severity)),
            "process": self._process,
            "module": record_dict.get("module", ""),
            "ts": record_dict.get("timestamp", 0.0),
            "severity": severity,
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
