# -*- coding: utf-8 -*-
"""
AggregationWindow — буферная стратегия с агрегацией метрик.

Реализует IBufferStrategy. Вместо простого батчинга агрегирует метрики
за окно: counter — сумма, gauge — последнее, timing — min/max/avg/p95,
histogram — распределение. При flush() отправляет агрегированный снапшот.
"""

import time
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...channel_routing_module.interfaces import IBufferStrategy
from .cardinality_guard import CardinalityGuard
from .metric_record import DEFAULT_DURATION_BUCKETS_SEC, DISTRIBUTION_TYPES, MetricRecord, MetricType


def _metric_key(name: str, tags: Optional[Dict] = None) -> str:
    """Ключ для группировки метрик (name + sorted tags)."""
    if not tags:
        return name
    parts = [name] + [f"{k}:{v}" for k, v in sorted(tags.items())]
    return "|".join(parts)


class AggregationWindow(IBufferStrategy):
    """Буфер с агрегацией метрик перед flush.

    enqueue(channel, data): data должен содержать type, name, value/tags.
    flush: агрегирует все метрики, вызывает flush_fn(channel, [snapshot])
    для каждого канала.
    """

    def __init__(
        self,
        flush_fn: Callable[[str, List[Dict[str, Any]]], Any],
        flush_interval: float = 10.0,
        guard: Optional[CardinalityGuard] = None,
    ) -> None:
        """
        Args:
            flush_fn: fn(channel_name: str, batch: List[dict]) -> int — вызывается
                      при flush; возвращает, сколько записей каналы ПРИНЯЛИ
                      (контракт Ф0.3). batch содержит один элемент — снапшот.
            flush_interval: Интервал периодического flush, сек.
            guard: потолок числа серий в окне (2.2). ``None`` — без потолка:
                   окно, поднятое отдельно от менеджера, не обязано знать про
                   конфиг. Страж ПЕРЕЖИВАЕТ подмену окна — его владелец
                   ``StatsManager``, а не окно (см. ``_swap_aggregation_window``).
        """
        self._flush_fn = flush_fn
        self._flush_interval = flush_interval
        self._guard = guard

        self._lock = threading.Lock()
        self._metrics: Dict[str, MetricRecord] = {}
        self._channels_seen: set = set()

        self._total_enqueued: int = 0
        self._total_flushes: int = 0
        self._errors: int = 0
        # P5: «отдано» и «записано» — разные числа. До этой правки окно вообще не
        # смотрело на результат flush_fn: сток мог не принять ни одной записи, а
        # по книгам окна всё выглядело сброшенным. Тот же класс, что стрелял в
        # Ф0.3 у BatchBuffer (`total_flushed` означал «отдано»).
        self._total_flushed: int = 0
        self._flush_failed: int = 0
        # 3.2/Р-4г: сколько ПУСТЫХ снапшотов не поехало стокам. Подавление — это
        # намеренная не-доставка, и она обязана быть видна числом: иначе «плоскость
        # молчит, потому что нечего слать» не отличить от «плоскость молчит, потому
        # что сломалась».
        self._empty_suppressed: int = 0

        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def flush_interval(self) -> float:
        """Темп ЭТОГО окна, сек — публично, потому что его спрашивают снаружи.

        B1: readback темпа обязан читаться из живого окна, а не пересчитываться
        из конфига (пересчёт совпал бы с конфигом даже при несработавшей
        пересборке — это и есть «effective = эхо запроса», major-13).
        """
        return self._flush_interval

    def _ensure_record(
        self,
        name: str,
        metric_type: MetricType,
        tags: Optional[Dict] = None,
    ) -> Optional[MetricRecord]:
        """Получить или создать MetricRecord. ``None`` — потолок серий (2.2)."""
        key = _metric_key(name, tags or {})
        record = self._metrics.get(key)
        if record is not None:
            return record
        if self._guard is not None and not self._guard.allow(key, self._metrics, name):
            return None
        record = MetricRecord(
            name=name,
            metric_type=metric_type,
            tags=dict(tags or {}),
        )
        self._metrics[key] = record
        return record

    def _merge_data(self, data: Dict[str, Any]) -> None:
        """Добавить данные в агрегацию."""
        mtype = data.get("type", "counter")
        name = data.get("name", "unknown")
        tags = data.get("tags") or {}
        value = data.get("value", 1.0)

        try:
            mt = MetricType(mtype) if isinstance(mtype, str) else mtype
        except (ValueError, TypeError):
            mt = MetricType.COUNTER

        rec = self._ensure_record(name, mt, tags)
        if rec is None:
            # Потолок серий. Наблюдение в окно не попадает — но эмиссия УЖЕ
            # состоялась: tap'ы её получили, счётчик ``_total_enqueued`` её
            # посчитал, и число опущенных поедет в самой записи снапшота.
            return

        if mt == MetricType.COUNTER:
            rec.add_counter(float(value))
        elif mt == MetricType.GAUGE:
            rec.set_gauge(float(value))
        elif mt == MetricType.TIMING:
            rec.add_timing(float(value))
        elif mt == MetricType.HISTOGRAM:
            rec.add_histogram(float(value))

    def enqueue(
        self,
        channel: str,
        data: Dict[str, Any],
        priority: str = "normal",
    ) -> None:
        """Добавить метрику в агрегацию."""
        with self._lock:
            self._channels_seen.add(channel)
            self._merge_data(data)
            self._total_enqueued += 1
        # Голоса стража тут НЕТ сознательно: путь горячий, а предупреждение на
        # этом такте несло бы числа первой секунды. Говорит страж на закрытии
        # окна — обоснование в ``CardinalityGuard.speak``.

    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительно сбросить буфер."""
        if channel is not None:
            self._flush_channel(channel)
        else:
            self.flush_all()

    def flush_all(self, include_empty: bool = False) -> None:
        """Сбросить все каналы — отправить агрегированный снапшот.

        **Пустой снапшот по умолчанию НЕ отдаётся** (задача 3.2, решение владельца Р-4г).
        До этого строка ``metrics snapshot (ts=…, count=0): []`` уходила в лог каждые
        10 с у каждого из восьми процессов и была главным источником фона плоскости.

        Args:
            include_empty: отдать снапшот, даже если метрик в окне нет. Финальный сброс
                при :meth:`stop` зовёт с ``True`` намеренно: по наличию снапшота в окне
                останова снаружи судят, что статистика дожила до конца
                (``probe_b3_shutdown_order_live``, проверка S4). Вариант «не эмитить
                вовсе» снёс бы этот признак вместе с фоном.

        Ноль каналов — нечего и подавлять: снапшот некому отдать, и ``include_empty``
        здесь ничего не меняет.
        """
        with self._lock:
            channels = list(self._channels_seen)
            snapshot, refused = self._build_snapshot()
            self._metrics.clear()
            # Счётчик сбросов растёт ВСЕГДА, даже когда снапшот подавлен: сброс
            # состоялся (окно опустошено, такт прошёл), не состоялась только доставка.
            # Снаружи по этому счётчику мерят ТЕМП окна (probe_b1_stats_tempo_live),
            # и тихий процесс не имеет права выглядеть как остановившееся окно.
            self._total_flushes += 1
            suppressed = not snapshot["metrics"] and not include_empty
            if suppressed:
                self._empty_suppressed += 1

        # Голос стража — ВНЕ лока и ДО подавления пустого снапшота: закрытие
        # окна состоялось в обоих случаях, а предупреждение про потолок не
        # имеет права зависеть от того, поехал снапшот или нет. Отчёт передаётся
        # аргументом — тот САМЫЙ, что уехал в снапшот: страж своё состояние уже
        # обнулил внутри `_build_snapshot`, и читать его тут было бы чтением
        # нулей (ровно этим голос окна и врал — «опущено серий 0» при верном
        # `series_dropped`).
        if self._guard is not None:
            self._guard.speak(refused)
        if suppressed:
            return

        for ch in channels:
            self._call_flush_fn(ch, [snapshot])

    def _build_snapshot(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Построить агрегированный снапшот. Возвращает ``(снапшот, отчёт стража)``.

        **Отчёт возвращается наружу намеренно.** Закрытие окна забирает у стража
        периодные числа ровно ОДИН раз (``take_report`` чистит множество ключей
        и имена эпизода), а потребителей у них два: запись снапшота и голос
        оператору. Пока голос читал состояние стража сам, он читал уже
        обнулённое — и правильность держалась на порядке двух вызовов, который
        ничем не принуждался. Возврат парой этот порядок делает невозможным
        нарушить: у голоса просто нет второго источника.

        ``total_count`` — сколько СЕРИЙ было в окне, а не сколько доехало:
        доехавшие плюс РАЗЛИЧНЫЕ опущенные потолком. По этому числу снаружи
        судят о живости окна (``probe_b3_shutdown_order_live``, заголовок
        строки ``performance.log``, текст записи в сторе), и арифметика
        «сколько метрик было» не должна меняться от того, поместились они или
        нет. Разность ``total_count − len(metrics)`` и есть число опущенных —
        её называет вслух ``record_display.snapshot_message``, место под неё
        было оставлено задачей 2.1 заранее.

        **Различные серии, а не отказанные эмиссии** (находка ревью,
        воспроизведена запуском): страж зовут заново на КАЖДУЮ эмиссию
        отказанной серии — ключа в словаре так и нет, — поэтому счётчик
        эмиссий рос без всякой связи с числом серий. Шесть эмиссий трёх
        отказанных серий давали ``total_count=12`` при шести настоящих, и
        запись противоречила сама себе: «опущено 9» рядом с тремя именами.
        Число эмиссий не выброшено — оно отвечает на свой законный вопрос и
        едет рядом под именем ``observations_dropped``.

        ``bucket_bounds`` едет ОДИН раз на снапшот и ТОЛЬКО когда в нём есть
        хоть одна timing/histogram-метрика (Р2.2-3). В каждой записи границы
        стоили бы ~90 байт на метрику на дороге с пределом строки 2048 байт;
        не ехать вовсе они не могут — константа со временем меняется, а запись
        живёт в сторе ~93 часа, и бакеты без границ через сутки нечитаемы.
        """
        metrics_list = [rec.aggregate() for rec in self._metrics.values()]
        has_distribution = any(rec.metric_type in DISTRIBUTION_TYPES for rec in self._metrics.values())
        refused = (
            self._guard.take_report()
            if self._guard is not None
            else {"series": 0, "observations": 0, "series_is_lower_bound": False, "names": []}
        )
        snapshot: Dict[str, Any] = {
            "timestamp": time.time(),
            "metrics": metrics_list,
            "total_count": len(metrics_list) + int(refused["series"]),
        }
        if has_distribution:
            snapshot["bucket_bounds"] = list(DEFAULT_DURATION_BUCKETS_SEC)
        if refused["series"] or refused["observations"]:
            # Ключи появляются только при ненулевом отказе: постоянные нули
            # весили бы в каждой записи на дороге с пределом строки, а «судить
            # поимённо» требует именно имён, а не одного числа-суммы.
            snapshot["series_dropped"] = int(refused["series"])
            snapshot["observations_dropped"] = int(refused["observations"])
            snapshot["dropped_series"] = list(refused["names"])
            if refused["series_is_lower_bound"]:
                # Множество различных ключей упёрлось в тот же потолок. Признак
                # едет ТОЛЬКО когда он истинен, но молчать о нём нельзя:
                # заниженное число, выглядящее точным, читатель примет за факт.
                snapshot["series_dropped_is_lower_bound"] = True
        return snapshot, refused

    def _flush_channel(self, channel: str, include_empty: bool = False) -> None:
        """Сбросить один канал (отправляет полный снапшот).

        Пустой снапшот подавляется так же, как в :meth:`flush_all` — адресный сброс
        это вторая дорога к тем же стокам, и починка одной из двух оставила бы фон
        живым на соседней развилке.
        """
        with self._lock:
            snapshot, refused = self._build_snapshot()
            self._metrics.clear()
            self._total_flushes += 1
            suppressed = not snapshot["metrics"] and not include_empty
            if suppressed:
                self._empty_suppressed += 1

        if self._guard is not None:
            self._guard.speak(refused)
        if suppressed:
            return

        self._call_flush_fn(channel, [snapshot])

    def _call_flush_fn(self, channel: str, batch: List[Dict[str, Any]]) -> None:
        """Отдать пачку стоку и УЧЕСТЬ, сколько он принял.

        Сток, вернувший не число (старый контракт), считается принявшим всё:
        иначе подъём контракта задним числом объявил бы потерянным то, что на
        самом деле записано. Расхождение при этом не прячется — оно видно как
        отсутствие роста ``flush_failed`` при заведомо мёртвом стоке.
        """
        try:
            result = self._flush_fn(channel, batch)
        except Exception:
            self._errors += 1
            self._flush_failed += len(batch)
            return
        accepted = result if isinstance(result, int) else len(batch)
        self._total_flushed += accepted
        self._flush_failed += max(0, len(batch) - accepted)

    def start(self) -> None:
        """Запустить фоновый поток периодического flush."""
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_worker,
            name="aggregation-window-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Остановить таймер и выполнить финальный flush.

        ``include_empty=True``: финальный снапшот отдаётся даже пустым. Он не про
        метрики, а про то, что плоскость дошла до останова живой — единственная
        запись, по которой это видно снаружи после смерти логгера.
        """
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
        self._timer_thread = None
        # Этот слив тихий ПО ПОСТРОЕНИЮ — он идёт сразу за уже осушённым
        # буфером. Право на голос он не возвращает, и помечать его для этого не
        # надо: страж сам видит, что такт не наблюдал ни одной попытки завести
        # серию (`CardinalityGuard._seen_this_tick`). Через `stop()` идёт и
        # подмена окна на `config.reload`, где страж переживает окно.
        self.flush_all(include_empty=True)

    def _timer_worker(self) -> None:
        """Периодический flush."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._flush_interval)
            if not self._stop_event.is_set():
                try:
                    self.flush_all()
                except Exception:
                    pass

    @property
    def stats(self) -> Dict[str, Any]:
        """Статистика буфера."""
        with self._lock:
            pending = len(self._metrics)
        return {
            "type": "aggregation",
            # B1: темп едет вместе со счётчиками сбросов — иначе `total_flushes`
            # снаружи не с чем сопоставить, и «сбросов стало вдвое меньше»
            # неотличимо от «процесс стал тише».
            "flush_interval": self._flush_interval,
            "total_enqueued": self._total_enqueued,
            "total_flushes": self._total_flushes,
            "total_flushed": self._total_flushed,
            "flush_failed": self._flush_failed,
            # 3.2: подавленные пустые снапшоты. Разница с `flush_failed` смысловая —
            # там потеря, здесь намеренная не-доставка, и путать их нельзя.
            "empty_suppressed": self._empty_suppressed,
            "errors": self._errors,
            "pending_metrics": pending,
            "channels": list(self._channels_seen),
            "running": bool(self._timer_thread and self._timer_thread.is_alive()),
        }
