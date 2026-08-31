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

#: Имя поля-маркера в ``extra`` записи: КАКАЯ плоскость уже владеет строкой стора.
ORIGIN_FIELD = "origin"

#: Значение маркера: инцидент уже учтён ПЛОСКОСТЬЮ ОШИБОК (Task 1.3a).
#: Ставит его сама плоскость (``ErrorManager.track_error``) и тот, кто выпускает
#: ГОЛОС о факте, который туда уже записан (``HealthState`` и диагностическая
#: команда ``health.report``). Смысл ровно один: «строка стора у этого инцидента
#: уже есть, второй раз не заводить».
ORIGIN_ERROR_MANAGER = "error_manager"


class StoreTapChannel(IChannel):
    """Tap-sink (IChannel): LogRecord-dict → ObservabilityStore.append_records."""

    def __init__(
        self,
        store: ObservabilityStore,
        name: str = "observability_store_tap",
        process: str = "",
        owns_error_plane: bool = False,
    ) -> None:
        """
        Args:
            store: целевой ObservabilityStore.
            name: имя tap'а (хэндл для remove_tap).
            process: имя процесса-источника (5.21 (c)) — стор проставит колонку
                ``process``; пусто → падаем на ``module`` LogRecord.
            owns_error_plane: этот tap висит НА ПЛОСКОСТИ ОШИБОК и потому пишет
                записи с маркером :data:`ORIGIN_ERROR_MANAGER`. Все остальные
                tap'ы такие записи ПРОПУСКАЮТ (Task 1.3a, дедуп ПУТЕЙ): один
                инцидент едет двумя дорогами — фактом в плоскость ошибок и
                голосом в журнал, — и до маркера обе дороги клали в стор по
                строке. Дефолт ``False`` («я не плоскость ошибок») выбран
                намеренно: забытый флаг даёт пропуск дубля, а не дубль.

        Параметра ``kind`` больше нет (Ф5.2, Б-4): вид записи считает её важность,
        а не конструктор канала. Прежний дефолт ``'error'`` и был дефектом — tap
        висит на ДВУХ менеджерах, и всё, что проходило порог на logger'е, ложилось
        в стор ошибкой.
        """
        self._store = store
        self._name = name
        self._process = process
        self._owns_error_plane = bool(owns_error_plane)

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "observability_store_tap"

    def write(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализовать LogRecord-dict и добавить в стор. Ошибку глушим (tail не критичен).

        Записи с маркером :data:`ORIGIN_ERROR_MANAGER` в ``extra`` пропускаются
        всеми tap'ами, кроме того, что сам висит на плоскости ошибок
        (``owns_error_plane=True``): у такого инцидента строка стора уже есть.

        Пропуск возвращается как ``success`` — потому что он ИМ И ЯВЛЯЕТСЯ:
        запись учтена, дороги у неё одна, и «отказ» здесь означал бы для читателя
        возврата потерю, которой не было. Довод про счётчик, стоявший здесь
        раньше, был ЛОЖЕН и снят ревью Task 1.3a: раздача tap'ам
        (``ChannelRoutingManager``, докстринг у ``tap_write_errors``) судит только
        факт ИСКЛЮЧЕНИЯ и возврат ``write()`` не читает вовсе — она даже называет
        ``StoreTapChannel.write`` поимённо среди тех, чей ``{"status": "error"}``
        засчитывается как принятая запись. Замер: tap, вернувший ``status="error"``
        без исключения, даёт ``accepted=1, tap_write_errors=0``; контроль, где tap
        бросает, — ``accepted=0, tap_write_errors=1``. То есть счётчик потерь не
        зависит от того, что вернуть, и защищать его выбором ``success`` было не от
        чего.
        """
        extra = record_dict.get("extra") or {}
        origin = extra.get(ORIGIN_FIELD) if isinstance(extra, dict) else None
        if origin == ORIGIN_ERROR_MANAGER and not self._owns_error_plane:
            return {"status": "success", "channel": self._name, "deduplicated": True}
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
        if origin:
            # Маркер поднимается на ВЕРХНИЙ уровень строки стора. Иначе он лежал
            # бы на дне (``extra.context.origin``): нормализатор
            # ``hub_record_to_display`` кладёт весь ``context`` записи одним
            # значением внутрь ``extra``, и «кто владеет этой строкой» стало бы
            # видно только тому, кто знает про два уровня вложенности.
            rec[ORIGIN_FIELD] = origin
        try:
            self._store.append_records([rec])
        except Exception:  # nosec B110 — сбой стора не должен ронять логирование
            return {"status": "error", "channel": self._name}
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        """IChannel-совместимость: tap закрывается без побочных эффектов (стор общий)."""
