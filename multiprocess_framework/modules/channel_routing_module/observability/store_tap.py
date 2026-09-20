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
модуль не импортирует logger_module НА УРОВНЕ МОДУЛЯ (иначе core-слой получил бы
обратную связь кольцом на пакетных `__init__`); голос об исходе слива берётся
ленивым импортом внутри функции — см. `_voice_flush_outcome`.
На вход `write` приходит `LogRecord.to_dict()`:
    {timestamp, level('ERROR'…), scope, message, module, extra{...}}
нормализуется в стор-запись kind (по умолчанию 'error').

## Task 3.3: запись стала АСИНХРОННОЙ — и это смена контракта, а не оптимизация

До Task 3.3 последней строкой `write` было `store.append_records([rec])`: пачка
из одной записи, `executemany` на один ряд и `commit` на КАЖДУЮ запись,
синхронно в потоке эмитента. Цена до и после — в `STATUS.md` модуля, раздел
«Цена лог-записи у эмитента» (одно место на весь модуль). Теперь `write` кладёт
нормализованную строку в `BatchDrainWorker` и возвращает управление; в стор
пачку уносит фоновый поток.

Два следствия, которые обязан знать вызывающий:

1. **`write()` больше не знает, приняла ли строку БД.** Прежний ответ
   `{"status": "error"}` означал «стор бросил»; теперь ответ говорит только о
   ПОСТАНОВКЕ (`success` / `dropped` при переполнении очереди). Судьба записи
   выясняется у `flush()`/`close()` парой «записано / потеряно».
2. **Читать стор сразу после `write()` больше нельзя** — между ними встала
   очередь. Кто читает свои же записи (тесты, диагностика), обязан позвать
   `flush(timeout)` или `close()`; в проде читатель — другой процесс, и там
   этого окна не было и раньше.
"""

from __future__ import annotations

import weakref
from typing import Any, Dict, Tuple

from ..interfaces import IChannel
from .batch_drain import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CLOSE_TIMEOUT_SEC,
    DEFAULT_FLUSH_INTERVAL_SEC,
    BatchDrainWorker,
)
from .observability_store import ObservabilityStore
from .record_display import KIND_LOG, kind_for_severity, severity_number_for

#: Имя счётчика вытеснений ПЛОСКОСТИ ИСТОРИИ (Task 3.3, К-Т3).
#:
#: Живёт здесь, а не в :mod:`.batch_drain`: счётчик именует плоскость, а не
#: механизм. Трек ``otel-export`` возьмёт тот же класс дренажа со СВОИМ именем
#: (``dropped_overflow``), и класс, зашивший это слово, перестал бы быть общим.
STORE_EVICTED_COUNTER = "store_evicted"

#: Потолок очереди записей, ждущих слива в стор (Task 3.3).
#:
#: **Это дефолт для tap'а, поднятого БЕЗ конфига** (тест, утилита, чужой
#: вызывающий). У процесса ёмкость приходит ручкой
#: ``observability.history.queue_capacity`` — той же дорогой, что порог и
#: пределы ретеншена; схема (``ObservabilityHistoryConfig.queue_capacity``)
#: держит то же число, и расходиться им нельзя.
#:
#: Почему 4096: на самом громком замеренном темпе старта процесса (1225 INFO за
#: 120 с у восьми процессов — замер Task 3.2) это запас порядка на нештатный
#: всплеск при такте дренажа 100 мс.
DEFAULT_STORE_QUEUE_CAPACITY = 4096

#: Имя поля-маркера в ``extra`` записи: КАКАЯ плоскость уже владеет строкой стора.
ORIGIN_FIELD = "origin"

#: Значение маркера: инцидент уже учтён ПЛОСКОСТЬЮ ОШИБОК (Task 1.3a).
#: Ставит его сама плоскость (``ErrorManager.track_error``) и тот, кто выпускает
#: ГОЛОС о факте, который туда уже записан (``HealthState`` и диагностическая
#: команда ``health.report``). Смысл ровно один: «строка стора у этого инцидента
#: уже есть, второй раз не заводить».
ORIGIN_ERROR_MANAGER = "error_manager"

#: Значение маркера: строка — ЧЕЛОВЕЧЕСКАЯ КОПИЯ снапшота метрик (Task 3.1, К1).
#: Ставит его ``LogStatsChannel``, который пишет снапшот в ``performance.log``
#: для чтения глазами; в стор тот же снапшот едет ДРУГОЙ дорогой — структурно,
#: через hub (``HubStatsChannel`` → ``kind=stats``).
#:
#: **Правило ДРУГОЕ, чем у :data:`ORIGIN_ERROR_MANAGER`, и копировать прежнее
#: нельзя.** Там маркер значит «строку берёт РОВНО ОДИН tap — владелец плоскости
#: ошибок»: у инцидента две дороги, и надо выбрать одну. Здесь — «не берёт НИ
#: ОДИН tap»: владелец дороги в стор не tap вовсе, а hub, и никакая роль tap'а
#: не делает лог-копию нужной. Реализация, скопировавшая развилку
#: ``owns_error_plane``, пропускала бы дубль у не-владельца и писала бы его у
#: владельца — то есть на боевой раскладке дубль остался бы жив.
#:
#: Цена дубля замерена, а не предположена (живой файл ``observability.db``,
#: 4575 с, 8 процессов): 781 строка/ч и 962 КиБ/ч — **19 % строк и 39 % БАЙТОВ**
#: стора; горизонт при ``max_rows=200 000`` 47.5 ч → 58.3 ч после снятия.
ORIGIN_STATS_SNAPSHOT = "stats_snapshot"


class StoreTapChannel(IChannel):
    """Tap-sink (IChannel): LogRecord-dict → ObservabilityStore.append_records."""

    def __init__(
        self,
        store: ObservabilityStore,
        name: str = "observability_store_tap",
        process: str = "",
        owns_error_plane: bool = False,
        queue_capacity: int = DEFAULT_STORE_QUEUE_CAPACITY,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_sec: float = DEFAULT_FLUSH_INTERVAL_SEC,
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
        # Task 3.3: запись больше не идёт в стор из потока эмитента. Воркер
        # знает только «вызываемое, принимающее список» — связанный метод, а не
        # стор целиком (см. :mod:`.batch_drain`).
        self._worker = BatchDrainWorker(
            store.append_records,
            queue_capacity,
            counter_name=STORE_EVICTED_COUNTER,
            batch_size=batch_size,
            flush_interval_sec=flush_interval_sec,
            name=f"{name}.queue",
        )
        self._closed = False
        # Дверь для читателя своих же записей: стор умеет дожать очереди тех,
        # кто в него пишет (ссылка слабая — см. ``register_writer``).
        store.register_writer(self._worker)
        # Страховка от УТЕЧКИ, а не замена ``close()``. Живой пример:
        # ``reapply_observability_store_level`` ставит НОВЫЙ tap под тем же
        # именем, а ``add_tap`` идемпотентен по имени — старый объект просто
        # теряется, и без финализатора его поток дренажа жил бы до конца
        # процесса, а очередь исчезла бы молча (тот же дефект Д-2, только
        # этажом выше). Финализатор молчит, когда терять нечего, и говорит,
        # когда есть: строку об исходе имеет право выпустить только тот, кто
        # закрылся ЯВНО, — иначе голос звучал бы из сборщика мусора в
        # произвольный момент чужого теста.
        self._finalizer = weakref.finalize(self, _drain_orphaned_worker, self._worker, name)

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

        Записи с маркером :data:`ORIGIN_STATS_SNAPSHOT` пропускаются БЕЗУСЛОВНО,
        любым tap'ом — владелец этой дороги не tap, а hub (Task 3.1, К1). Роль
        tap'а тут ни при чём, поэтому проверка стоит ДО развилки
        ``owns_error_plane``: любая попытка выразить её через ту же развилку
        оставила бы дубль живым у tap'а-владельца плоскости ошибок, то есть
        ровно на боевой раскладке.

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
        if origin == ORIGIN_STATS_SNAPSHOT:
            # ``success`` с НАЗВАННОЙ причиной, а не отказ: запись учтена, дорога
            # у неё одна (hub), потери нет — та же семантика, что у ``deduplicated``
            # соседней ветки. Значением ключа едет сам маркер, а не ``True``:
            # читателю возврата важно, ЧТО именно пропущено, — маркеров у поля
            # ``origin`` уже два, и «пропущено по origin» без имени пришлось бы
            # доискивать в исходнике.
            return {"status": "success", "channel": self._name, "skipped_origin": ORIGIN_STATS_SNAPSHOT}
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
        return self._worker.write(rec)

    # ------------------------------------------------------------------
    # Останов (Task 3.3, критерии 7 и 9)
    # ------------------------------------------------------------------

    def flush(self, timeout: float = DEFAULT_CLOSE_TIMEOUT_SEC) -> Tuple[int, int]:
        """Дожать очередь до дедлайна: ``(записано, потеряно)`` — итоги tap'а."""
        return self._worker.flush(timeout)

    def close(self, timeout: float = DEFAULT_CLOSE_TIMEOUT_SEC) -> None:
        """Дожать очередь и НАЗВАТЬ исход в журнале. Стор общий — он не трогается.

        Строка ``store flush: N записано, M потеряно`` — литерал контракта
        (Task 3.3, критерий 7; трек ``otel-export`` ждёт именно её). Она же
        закрывает девятый критерий: у записи, принятой ``write()`` за миг до
        останова, есть ровно два исхода — строка в сторе или число ``M``;
        третьего («исчезла молча») быть не должно.

        Окно голоса здесь **ноль**, а не политика процесса: строка выпускается
        один раз за жизнь tap'а, дросселировать нечего, а подавить её окном,
        занятым соседним tap'ом того же процесса, значило бы потерять исход
        второй половины плоскости. Переменная часть стоит В ТЕКСТЕ вопреки
        общему правилу — потому что текст здесь и есть контракт, а ключ окна
        постоянен, так что разъехаться им не с чем.
        """
        if self._closed:
            return
        self._closed = True
        self._finalizer.detach()
        written, lost = self._worker.close(timeout)
        _voice_flush_outcome(written, lost, self._name)


def _voice_flush_outcome(written: int, lost: int, tap_name: str) -> None:
    """Сказать в журнал исход слива. Импорт ленивый — цикл на пакетных ``__init__``.

    ``logger_module`` тянет ``channel_routing_module`` (LoggerManager стоит на
    его каналах), поэтому импорт голоса на уровне модуля замкнул бы кольцо.
    Тот же приём и по той же причине — в
    ``base_manager.mixins.observable_mixin`` и в :mod:`.batch_drain`.
    """
    try:
        from ...logger_module.core.windowed_voice import log_windowed

        log_windowed(
            f"store_tap.flush.{tap_name}",
            0.0,  # без окна: строка одна за жизнь tap'а, дросселировать нечего
            "info",
            f"store flush: {written} записано, {lost} потеряно",
        )
    except Exception:  # nosec B110 — голос об останове не имеет права ронять останов
        pass


def _drain_orphaned_worker(worker: BatchDrainWorker, tap_name: str) -> None:
    """Финализатор осиротевшего tap'а: дожать очередь; сказать — только если потеряли.

    Молчание при ``lost == 0`` выбрано намеренно. Финализатор срабатывает в
    произвольный момент (сборка мусора, выход интерпретатора), и строка
    «всё хорошо», выпущенная в чужом такте, — это шум, который к тому же
    попадает в чужой ``caplog``. Строка о ПОТЕРЕ шумом не является: без неё
    запись исчезла бы молча, а это ровно тот дефект, ради которого задача
    делалась.
    """
    try:
        written, lost = worker.close()
        if lost:
            _voice_flush_outcome(written, lost, tap_name)
    except Exception:  # nosec B110 — на выходе интерпретатора ронять нечего и некому
        pass
