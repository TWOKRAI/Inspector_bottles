# -*- coding: utf-8 -*-
"""
HubStatsChannel — снапшот окна агрегации в stats-слот ObservabilityHub (задача 2.1).

Плоскость stats до этой задачи никуда не доезжала: дорога `hub → drain → стор
и живой хвост` была живой (`observability_wiring.drain_process_observability`),
но слот stats у hub'а наполнял единственный владелец — `WorkerManager`, а он
метрик не эмитит. Отсюда `kind=stats = 0` в сторе и структурно пустая вкладка
«Статистика» при работающей плоскости.

Канал закрывает ровно этот разрыв и ничего больше: `StatsManager` остаётся
ЕДИНСТВЕННЫМ агрегатором (решение владельца РТ-1(а)), а его готовый снапшот
окна кладётся в hub одной записью — оттуда существующий дренаж по heartbeat
доносит её до `store.append_records` и до форвардеров живого хвоста.

**Одна запись на СНАПШОТ, а не на метрику.** Разложить снапшот по метрикам было
бы естественнее для формы hub'а (`_emit_stat`), но арифметика запрещает:
8 процессов × 20 метрик × 360 окон/ч = 57 600 строк/ч — в 11 раз больше всего
сегодняшнего темпа стора (~5 040 строк/ч), и потолок в 200 000 строк
оборачивался бы за ~3.5 часа вместо ~40.

**Маркер агрегата обязателен** (`STATS_AGGREGATE_KEY`): по нему drain-адаптер НЕ
возвращает снапшот в `StatsManager` (иначе весь агрегат складывался бы там в
одну БЕЗЫМЯННУЮ метрику, отравляя каждое следующее окно — замер и точная форма
вреда в ADR-CRM-015), и по нему же нормализатор display-вида собирает запись целиком, а не из
четырёх ключей сырой метрики. Ставит его писатель, то есть этот канал, — и
берёт из той же константы, что читают оба потребителя: три написания одного
признака разошлись бы молча, и запись прошла бы петлёй мимо предохранителя.

Сам hub — duck-typed (нужен один метод `emit_stats_record`), чтобы канал
тестировался без поднятия подсистемы наблюдаемости.
"""

from typing import Any, Dict, List

from ...channel_routing_module.interfaces import IChannel
from ...channel_routing_module.observability import STATS_AGGREGATE_KEY

#: Имя канала в реестре ``StatsManager``. Служебное — как ``log_stats``:
#: описания в секции ``channels`` у него нет, но снять и вернуть его через
#: ``sink.disable``/``sink.enable`` оператор вправе так же, как остальные.
STATS_HUB_CHANNEL = "hub_stats"


class HubStatsChannel(IChannel):
    """Канал «снапшот окна → stats-слот hub'а наблюдаемости»."""

    def __init__(self, hub: Any, name: str = STATS_HUB_CHANNEL) -> None:
        """
        Args:
            hub: объект с методом ``emit_stats_record(payload) -> dict``
                (``ObservabilityHub``).
            name: имя канала в реестре менеджера.
        """
        self._hub = hub
        self._name = name
        #: Накопленный счётчик потерь stats-канала hub'а на момент прошлой
        #: записи — по его ПРИРОСТУ виден `drop_oldest`, который отвечает
        #: «success». См. `write`.
        self._last_dropped = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "hub"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Положить снапшот окна в hub одной записью.

        На входе — то, что строит ``AggregationWindow._build_snapshot``:
        ``{timestamp, metrics: [агрегаты], total_count}``.

        ``total_count`` берётся ИЗ СНАПШОТА, а не считается по списку: это число
        метрик В ОКНЕ, и с потолком кардинальности 2.2 доехавших стало меньше, а
        «сколько их было» меняться не должно. Разность и есть число опущенных —
        её называет вслух текст записи (``snapshot_message``).

        **Остальные ключи снапшота едут КАК ЕСТЬ** (2.2). Перечислять их
        поимённо значило бы завести второе место, где описан состав снапшота, —
        и потерять новое поле молча: ровно этот довод уже записан у
        нормализатора display-вида, а здесь стояла его нарушенная копия.
        Задача 2.2 добавила ``bucket_bounds`` (границы бакетов, один раз на
        снапшот) и пару ``series_dropped``/``dropped_series``; без сквозного
        прокида бакеты в сторе были бы нечитаемы, а число опущенных — невидимо.
        ``timestamp`` не едет своим именем: он переименован в ``window_ts``.
        """
        try:
            if self._hub is None:
                return {"status": "error", "error": "hub not set", "channel": self.name}

            metrics: List[Any] = data.get("metrics") or []
            payload = {k: v for k, v in data.items() if k not in ("timestamp", "metrics", "total_count")}
            payload.update(
                {
                    STATS_AGGREGATE_KEY: True,
                    "metrics": metrics,
                    "total_count": data.get("total_count", len(metrics)),
                    # Момент ЗАКРЫТИЯ окна. Конверт hub'а проставит свой ``ts`` —
                    # момент, когда запись легла в канал; на живом процессе они
                    # различаются на цену записи, но при заторе дренажа разность
                    # и есть возраст снапшота, а восстановить её потом не из чего.
                    "window_ts": data.get("timestamp"),
                }
            )
            result = self._hub.emit_stats_record(payload)
            # Ответ hub'а НЕ переписывается на «success» (находка ревью 2.1):
            # канал bounded, при заторе дренажа он вытесняет, и рапорт об успехе
            # заставлял бы арифметику «эмитировано = доставлено + подавлено»
            # сходиться поверх вытеснения. Отказ подхватит общий писатель базы
            # (`channel_refused_records`), а не только счётчик внутри hub'а.
            #
            # Две формы вытеснения, и вторая молчит статусом: при `drop_newest`
            # канал отвечает `dropped`, а при `drop_oldest` (дефолт hub'а) он
            # отвечает `success` и лишь растит счётчик — свежую запись он принял,
            # выбросив ЧУЖУЮ старую. Поэтому судим ещё и по приросту счётчика.
            # Писатель здесь один (поток окна агрегации), гонки на `_last_dropped`
            # нет; появится второй — придётся считать иначе.
            if not isinstance(result, dict):
                return {"status": "success", "channel": self.name}
            dropped = result.get("dropped")
            grew = isinstance(dropped, int) and dropped > self._last_dropped
            if grew:
                self._last_dropped = dropped
            if result.get("status") not in (None, "success") or grew:
                return {**result, "status": "dropped", "channel": self.name}
            return {"status": "success", "channel": self.name}
        except Exception as e:  # noqa: BLE001 — сбой канала не рушит flush окна
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        """Закрыть канал: no-op — буфер и его жизненный цикл принадлежат hub'у."""

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.channel_type,
            "active": self._hub is not None,
        }
