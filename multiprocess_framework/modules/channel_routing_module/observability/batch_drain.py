# -*- coding: utf-8 -*-
"""BatchDrainWorker — дренаж пачкой из фонового потока поверх :class:`BoundedChannel`.

**Что это.** Разъём между быстрым эмитентом и медленным стоком. Эмитент зовёт
:meth:`BatchDrainWorker.write` и платит только цену постановки в кольцевой буфер;
собственный поток забирает накопленное пачками и отдаёт стоку —
одним вызовом на пачку, а не на запись. Задача Task 3.3 плана
``observability-closure``: последняя строка ``StoreTapChannel.write`` звала
``store.append_records([rec])`` — ``executemany`` на ОДИН ряд и ``commit`` на
КАЖДУЮ запись, синхронно в потоке эмитента. Числа «до/после» живут в ОДНОМ
месте — ``channel_routing_module/STATUS.md``, раздел «Цена лог-записи у
эмитента»; копия здесь разошлась бы с ним на первом же перезамере (замеров у
этой задачи было три, и все настоящие).

**Класс не знает про свой сток.** Ни класса стора наблюдаемости, ни SQLite, ни
сети здесь нет вовсе — и это утверждение стережёт тест, читающий ИСХОДНИК этого
файла: ``sink`` — любое вызываемое, принимающее список записей, либо любой
объект с методом ``append_records(list)`` (две формы приняты намеренно —
см. :func:`_resolve_sink`). Это условие переиспользования: тот же класс берёт
трек ``otel-export`` (Task 2.4), у которого за очередью **сеть**, а не файл.
По той же причине имя счётчика потерь — **параметр** (``counter_name``):
плоскость истории передаёт своё имя, трек otel — своё. Счётчик именует
ПЛОСКОСТЬ, а не механизм; класс, зашивший чужое имя, перестаёт быть общим
ровно в этом месте, поэтому ни одного имени плоскости в этом файле нет —
включая докстринги (сторож читает их наравне с кодом).

## Учёт: «принято = записано + потеряно», и это проверяемо

Каждый вызов :meth:`write` попадает ровно в одну из трёх корзин, и третьего
исхода («исчезла молча») нет ни на одном пути, включая аварийный:

* **записано** — сток принял запись (``_written``);
* **потеряно на переполнении** — буфер был полон (счётчик ``BoundedChannel``);
* **потеряно у стока / на останове** — сток бросил или вернул меньше, чем ему
  дали; либо остаток не дожали до дедлайна ``close()``.

:meth:`totals` отдаёт пару, :meth:`flush` возвращает её же. **Пара — НАКОПЛЕННЫЕ
итоги за жизнь экземпляра, а не дельта этого вызова.** Дельта здесь была бы
недостоверна: фоновый поток пишет параллельно, и «сколько дожал именно этот
``flush``» зависело бы от планировщика — ровно тот класс дефекта, когда счётчик
означает «передано», а читатель понимает «записано».

## Почему поток, а не запись на месте

``flush()`` умеет всю работу сам, и в тестах этого хватает. В проде — нет: без
фонового потока записи копились бы до потолка между останóвами и вытеснялись.
Поток спит на :class:`threading.Event` и просыпается либо по такту
``flush_interval_sec``, либо досрочно, когда глубина дошла до ``batch_size``.

**У стока РОВНО ОДИН писатель — поток дренажа.** Отсюда сразу два свойства:
порядок записей (второй писатель перемешал бы пачки) и честность дедлайна —
``flush(timeout)`` не зовёт сток сам, а будит поток и ждёт прогресса. Прервать
заблокировавшийся вызов в своём же кадре нельзя, поэтому ``flush``, сливающий
очередь собственными руками, соблюдал бы ``timeout`` только против стока,
который БРОСАЕТ; сток, который ЖДЁТ, уносил бы вызывающего с собой (замер на
зависшем стоке: ``flush(timeout=0.05)`` не вернулся за 5 с).

Импорт голоса (``log_windowed``) ЛЕНИВЫЙ и внутри функции — по той же причине,
что у ``base_manager.mixins.observable_mixin``: ``logger_module`` тянет
``channel_routing_module``, и импорт на уровне модуля замкнул бы цикл на
пакетных ``__init__``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .bounded_channel import DROP_OLDEST, BoundedChannel

#: Размер ОДНОЙ пачки, уезжающей стоку одним вызовом (одна транзакция у SQLite).
DEFAULT_BATCH_SIZE = 100

#: Такт фонового дренажа, сек: «N записей ИЛИ 100 мс» — вторая половина правила.
DEFAULT_FLUSH_INTERVAL_SEC = 0.1

#: Дедлайн по умолчанию для :meth:`BatchDrainWorker.close`.
DEFAULT_CLOSE_TIMEOUT_SEC = 2.0


def _resolve_sink(sink: Any) -> Callable[[List[Dict[str, Any]]], Any]:
    """Привести сток к вызываемому «принять список записей».

    Приняты ДВЕ формы, и это не всеядность ради всеядности:

    * вызываемое — ``store.append_records`` (связанный метод), лямбда, функция
      отправки в сеть у трека otel;
    * объект с методом ``append_records(list)`` — сам стор, двойник стора в
      тесте, любой приёмник пачки.

    Вторая форма нужна потому, что приёмочный набор Task 3.3 передаёт именно
    объект-двойник, а первая — потому что связанный метод не тянет за собой
    владельца и держит обещание «класс не знает про стор». Отказ громкий и на
    месте вызова конструктора: тихо проглотить неподходящий сток значило бы
    потерять всё, что в него положат, и узнать об этом на останове.
    """
    if callable(sink):
        return sink
    append = getattr(sink, "append_records", None)
    if callable(append):
        return append
    raise TypeError(
        "sink обязан быть вызываемым (список записей) либо объектом с методом "
        f"append_records(list); получено {type(sink).__name__}"
    )


class BatchDrainWorker:
    """Очередь с потолком + фоновый дренаж пачкой + ``flush(timeout)`` с исходом.

    Пример:
        w = BatchDrainWorker(sink.append_records, 4096, counter_name="<имя плоскости>")
        w.write({"kind": "log", ...})     # цена — постановка в кольцевой буфер
        written, lost = w.close()         # дожать остаток и назвать исход
    """

    def __init__(
        self,
        sink: Any,
        capacity: int = 1024,
        *,
        counter_name: str,
        overflow: str = DROP_OLDEST,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_sec: float = DEFAULT_FLUSH_INTERVAL_SEC,
        name: str = "batch_drain",
        voice_window_sec: Optional[float] = None,
    ) -> None:
        """
        Args:
            sink: приёмник пачки — вызываемое ``f(list)`` либо объект с
                ``append_records(list)``. Возврат-число трактуется как «сколько
                принято»: разница с длиной пачки считается потерей (стор так и
                отвечает на ``database is locked`` — 0 при непустой пачке).
            capacity: потолок очереди в записях (>= 1).
            counter_name: имя счётчика вытеснений — ПАРАМЕТР, а не литерал:
                под этим именем счётчик отдаётся в :meth:`counters` и звучит в
                голосе.
            overflow: политика переполнения ``BoundedChannel``.
            batch_size: сколько записей уезжает стоку ОДНИМ вызовом; он же —
                порог досрочного пробуждения потока.
            flush_interval_sec: такт фонового дренажа, сек (> 0).
            name: имя для журнала и ключа окна голоса.
            voice_window_sec: окно голоса о потере, сек; ``None`` — политика
                процесса (``observability.voices.default_window_sec``, 5 с).
        """
        if int(batch_size) < 1:
            raise ValueError(f"batch_size должен быть >= 1, получено {batch_size}")
        if float(flush_interval_sec) <= 0:
            raise ValueError(f"flush_interval_sec должен быть > 0, получено {flush_interval_sec}")

        self._sink = _resolve_sink(sink)
        self._name = str(name)
        self._counter_name = str(counter_name)
        self._batch_size = int(batch_size)
        self._interval = float(flush_interval_sec)
        self._voice_window_sec = voice_window_sec
        self._channel = BoundedChannel(self._name, capacity, overflow)

        # У стока РОВНО ОДИН писатель — поток дренажа. Это не про порядок (его
        # держал бы и лок), а про ДЕДЛАЙН: заблокировавшийся сток нельзя
        # прервать в своём же кадре, поэтому ``flush()`` не имеет права звать
        # сток сам — иначе его ``timeout`` бросал бы вызывающего внутрь сети
        # или залоченной БД на всё время их зависания. Замер, на котором это
        # поймано: сток, ждущий события, — ``flush(timeout=0.05)`` не вернулся
        # за 5 с. ``flush`` теперь ЖДЁТ прогресса на ``_progress`` и уходит по
        # дедлайну; работа остаётся в потоке.
        self._progress = threading.Condition()
        self._inflight_items = 0
        self._abandoned = False
        self._counters_lock = threading.Lock()
        self._written = 0
        self._lost_sink = 0
        self._lost_closed = 0
        self._dropped_after_close = 0

        self._wake = threading.Event()
        # Приёмный лок: закрывает окно между «я ещё открыт» и «положил в канал».
        self._intake_lock = threading.Lock()
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Приём (горячий путь эмитента)
    # ------------------------------------------------------------------

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Положить запись в очередь. Не блокирует и не ходит к стоку.

        Returns:
            Ответ ``BoundedChannel.write`` (``status``/``channel``/``dropped``)
            либо ``{"status": "dropped", ...}``, если воркер уже закрыт.
        """
        # Решение «принимаю» и сама постановка — под ОДНИМ локом (ревью, Б-2).
        # Прежняя редакция читала флаг, а клала в канал уже вне его: эмитент,
        # вытесненный планировщиком между двумя шагами, получал ``success``, а
        # запись ложилась в канал ПОСЛЕ последнего ``drain()`` останова — её не
        # было ни в сторе, ни в ``written``, ни в ``lost``. Воспроизведено с
        # расширенным окном: принято 2, записано+потеряно 1. Считать её
        # постфактум было нельзя: на другом исходе гонки ту же запись досчитал
        # бы ``close()`` остатком канала, и она уехала бы в потери ДВАЖДЫ.
        # Приёмный лок берётся только на постановку (O(1) у обоих участников),
        # поэтому цена эмитента остаётся ценой постановки.
        with self._intake_lock:
            if self._closed:
                # Запись после останова — потеря, а не тишина: её считает
                # ОТДЕЛЬНАЯ корзина, потому что переполнением она не является.
                with self._counters_lock:
                    self._dropped_after_close += 1
                return {"status": "dropped", "channel": self._name, "closed": True}
            before = self._channel.dropped
            result = self._channel.write(record)
        if self._channel.dropped != before:
            self._voice_overflow()

        if self._thread is None:
            self._ensure_thread()
        # Досрочное пробуждение — только на пересечении порога: `is_set()` это
        # чтение атрибута, а `set()` берёт лок Event'а, и звать его на каждой
        # записи после порога значило бы платить локом за уже отданный сигнал.
        if not self._wake.is_set() and len(self._channel) >= self._batch_size:
            self._wake.set()
        return result

    # ------------------------------------------------------------------
    # Дренаж
    # ------------------------------------------------------------------

    def _push(self, items: Sequence[Dict[str, Any]]) -> None:
        """Отдать записи стоку пачками по ``batch_size``.

        Единственный вызывающий — поток дренажа; исключение одно и оно
        проверяемое: :meth:`_drain_inline`, который работает лишь когда потока
        нет или он мёртв (то есть конкурента у стока всё равно нет).

        Записи, ВЗЯТЫЕ из очереди, но ещё не отданные стоку, числятся «в
        полёте» (:attr:`_inflight_items`) — без этого учёта они не лежали бы ни
        в очереди, ни в счётчиках, и останов при зависшем стоке отчитался бы
        нулём при двадцати принятых (воспроизведено: ``close()`` вернул
        ``(0, 0)``). После того как ``close()`` объявил остаток потерянным
        (:attr:`_abandoned`), ни одна пачка не имеет права ещё и записаться в
        ``written`` — иначе тот же остаток был бы посчитан дважды.
        """
        for start in range(0, len(items), self._batch_size):
            if self._abandoned:
                break
            chunk = list(items[start : start + self._batch_size])
            try:
                accepted = self._sink(chunk)
            except Exception as exc:  # сток упал — пачка потеряна, но НЕ молча
                if not self._abandoned:
                    with self._counters_lock:
                        self._lost_sink += len(chunk)
                    self._voice_sink_failure(len(chunk), exc)
                self._note_inflight_done(len(chunk))
                continue
            # Сток, вернувший число, судит сам: `append_records` отвечает 0 на
            # `database is locked`. Не-число (None у произвольного вызываемого)
            # читается как «принял всё» — иначе всякий сток без возврата
            # выглядел бы полностью потерянным.
            if isinstance(accepted, int) and not isinstance(accepted, bool):
                taken = max(0, min(len(chunk), accepted))
            else:
                taken = len(chunk)
            missed = len(chunk) - taken
            if not self._abandoned:
                with self._counters_lock:
                    self._written += taken
                    self._lost_sink += missed
                if missed:
                    self._voice_sink_failure(missed, None)
            self._note_inflight_done(len(chunk))

    def _drain_inline(self) -> None:
        """Слить очередь В ТЕКУЩЕМ потоке. Только когда потока дренажа нет или он мёртв.

        Нужен ради ЖИВУЧЕСТИ: если поток так и не поднялся (записей ещё не
        было) или умер, ``flush()`` обязан всё равно донести записи, а не
        отсидеть дедлайн и объявить их потерянными.
        """
        items = self._channel.drain()
        if items:
            self._push(items)

    def _take_batch(self) -> List[Dict[str, Any]]:
        """Забрать пачку из канала И отметить её «в полёте» — ОДНОЙ секцией (ревью, Б-1).

        Прежняя редакция делала это двумя шагами, и в зазоре между ними
        ``flush()`` видел пустой канал при нулевом ``_inflight_items`` — то есть
        «дожимать нечего» при непереданной стоку пачке. Воспроизведение с
        расширенным окном: ``flush(timeout=5.0)`` вернул за 0.0 мс с
        ``(0, 0)``, а запись приехала к стоку через 500 мс; естественным
        прогоном при ``switchinterval=1e-6`` — 81 ложь на 4000 повторов (2 %).

        Это важнее, чем выглядит: ``flush``/``flush_writers`` — единственная
        дверь читателя к своим же записям, и дверь, умеющая соврать «пусто»,
        возвращает ровно ту вакуумность, которую снимали правки тестов.

        Порядок локов (``_progress`` → лок канала) тот же, что у :meth:`flush`,
        обратного нигде нет; ``drain()`` под ним O(1).
        """
        with self._progress:
            items = self._channel.drain()
            if items:
                self._inflight_items += len(items)
            self._progress.notify_all()
        return items

    def _note_inflight_done(self, count: int) -> None:
        """Судьба пачки решена (записана либо потеряна) — полёт окончен."""
        with self._progress:
            self._inflight_items = max(0, self._inflight_items - count)
            self._progress.notify_all()

    def _wake_flush_waiters(self) -> None:
        with self._progress:
            self._progress.notify_all()

    def _run(self) -> None:
        """Тело фонового потока: такт ``flush_interval_sec`` или досрочный сигнал."""
        while True:
            self._wake.wait(self._interval)
            self._wake.clear()
            closing = self._closed
            items = self._take_batch()
            if items:
                try:
                    self._push(items)
                finally:
                    # Страховка на случай выхода мимо штатного учёта: полёт
                    # обязан закончиться, иначе flush() ждал бы дедлайн зря.
                    self._note_inflight_done(len(items))
            else:
                self._wake_flush_waiters()
            if closing and len(self._channel) == 0:
                self._wake_flush_waiters()
                return

    def _ensure_thread(self) -> None:
        """Поднять поток дренажа на ПЕРВОЙ записи, а не в конструкторе.

        Экземпляров, которые создали и ни разу не написали, в дереве много
        (tap на менеджере, который не сработал ни разу); поток на каждый из них
        был бы платой за ничего.
        """
        with self._thread_lock:
            if self._thread is not None or self._closed:
                return
            self._thread = threading.Thread(target=self._run, name=f"batch-drain-{self._name}", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------
    # Останов и исход
    # ------------------------------------------------------------------

    def flush(self, timeout: float = DEFAULT_CLOSE_TIMEOUT_SEC) -> Tuple[int, int]:
        """Дожать очередь до дедлайна и вернуть ``(записано, потеряно)``.

        Пара — НАКОПЛЕННЫЕ итоги экземпляра (см. шапку модуля), а не дельта
        вызова.

        **Дедлайн честен против ЛЮБОГО стока, включая зависший.** Работу делает
        поток дренажа, а ``flush`` только будит его и ждёт прогресса: пока
        очередь не опустеет или пока не истечёт ``timeout``. Прежняя редакция
        сливала очередь сама и потому соблюдала дедлайн только против стока,
        который БРОСАЕТ, — сток, который ЖДЁТ, уносил вызывающего с собой
        (замер: ``flush(timeout=0.05)`` не вернулся за 5 с). Это тот же класс
        дефекта, ради которого К-Т2 и написан, только этажом ниже.

        Записи, оставшиеся в очереди по дедлайну, не числятся ни записанными,
        ни потерянными — их судьбу закрывает :meth:`close`.
        """
        thread = self._thread
        if thread is None or thread is threading.current_thread() or not thread.is_alive():
            # Передать работу некому (потока нет, он мёртв) либо мы САМИ и есть
            # поток дренажа — ждать себя было бы дедлоком.
            self._drain_inline()
            return self.totals()

        deadline = time.monotonic() + max(0.0, float(timeout))
        self._wake.set()
        with self._progress:
            while len(self._channel) or self._inflight_items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._progress.wait(remaining)
        return self.totals()

    def close(self, timeout: float = DEFAULT_CLOSE_TIMEOUT_SEC) -> Tuple[int, int]:
        """Закрыть приём, дожать остаток, назвать исход. Идемпотентно."""
        with self._thread_lock:
            already = self._closed
            # Флаг ставится под ПРИЁМНЫМ локом (Б-2): пока он взят, ни одна
            # запись не может пройти проверку «открыт» и лечь в канал после
            # того, как останов уже посчитал остаток.
            with self._intake_lock:
                self._closed = True
            thread = self._thread
        if already:
            return self.totals()

        self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            # Поток сам знает, когда закончил: его условие выхода — «закрыты и
            # очередь пуста». Join с дедлайном, потому что зависший сток не
            # имеет права держать останов процесса.
            thread.join(timeout=max(0.0, float(timeout)))
        if thread is None or not thread.is_alive():
            # Конкурента у стока нет — можно дожать здесь же (потока не было
            # вовсе или он уже закончил и мог не успеть забрать последнее).
            self._drain_inline()
        else:
            # Поток не уложился в дедлайн — он застрял В СТОКЕ (`database is
            # locked` дольше `busy_timeout`, мёртвый коллектор у трека otel).
            # Записи, которые он уже забрал из очереди, лежат у него в руках:
            # в очереди их нет, в счётчиках тоже — и без этой ветки останов
            # отчитался бы «0 записано, 0 потеряно» при двадцати принятых
            # (воспроизведено). Объявляем их ПОТЕРЯННЫМИ: пере-считать потерю
            # безопасно, недо-считать — это и есть «исчезла молча». Флаг
            # `_abandoned` запрещает потоку зачесть их вторым разом, если сток
            # всё же ответит.
            with self._progress:
                self._abandoned = True
                abandoned = self._inflight_items
                self._inflight_items = 0
            if abandoned:
                with self._counters_lock:
                    self._lost_closed += abandoned

        # Всё, что не дожали, — ПОТЕРЯ с именем, а не исчезнувшее. Забираем
        # остаток сами (drain опустошает буфер), поэтому close() канала ниже
        # уже ничего не досчитает — двойного счёта нет.
        leftovers = self._channel.drain()
        if leftovers:
            with self._counters_lock:
                self._lost_closed += len(leftovers)
        self._channel.close()
        return self.totals()

    # ------------------------------------------------------------------
    # Показания
    # ------------------------------------------------------------------

    def totals(self) -> Tuple[int, int]:
        """``(записано, потеряно)`` — накопленные итоги за жизнь экземпляра."""
        # Все слагаемые — ПОД ОДНИМ локом (ревью, М-4): та же дисциплина, что у
        # ``BoundedChannel.get_info`` этажом ниже и у ``counters()`` рядом.
        with self._counters_lock:
            lost = self._lost_sink + self._lost_closed + self._dropped_after_close + self._channel.dropped
            written = self._written
        return written, lost

    def counters(self) -> Dict[str, int]:
        """Счётчики под ИМЕНАМИ плоскости: ``counter_name`` — вытеснения."""
        with self._counters_lock:
            after_close = self._dropped_after_close
            return {
                # Вытеснение переполнением и отказ после останова — один факт
                # для читателя («принято write(), стоку не отдано»), поэтому
                # они складываются под именем, которое дал вызывающий.
                self._counter_name: self._channel.dropped + after_close,
                "sink_failed": self._lost_sink,
                "lost_on_close": self._lost_closed,
                "written": self._written,
            }

    def get_info(self) -> Dict[str, Any]:
        """Снимок очереди + счётчики (для readback и диагностики)."""
        info = self._channel.get_info()
        info.update(self.counters())
        info["batch_size"] = self._batch_size
        info["flush_interval_sec"] = self._interval
        info["closed"] = self._closed
        return info

    @property
    def depth(self) -> int:
        """Сколько записей ждёт дренажа прямо сейчас."""
        return len(self._channel)

    @property
    def capacity(self) -> int:
        return self._channel.capacity

    @property
    def counter_name(self) -> str:
        return self._counter_name

    def __len__(self) -> int:
        return len(self._channel)

    # ------------------------------------------------------------------
    # Голос (окном, не строкой на каждую потерю)
    # ------------------------------------------------------------------

    def _voice(self, key_suffix: str, message: str, **ctx: Any) -> None:
        """Сказать вслух не чаще окна. Импорт ленивый — см. шапку модуля."""
        try:
            from ...logger_module.core.windowed_voice import log_windowed

            log_windowed(
                f"batch_drain.{self._name}.{key_suffix}",
                self._voice_window_sec,
                "warning",
                message,
                **ctx,
            )
        except Exception:  # nosec B110 — голос не имеет права ронять эмитента
            pass

    def _voice_overflow(self) -> None:
        # Переменная часть — в ctx, постоянная — в тексте (иначе ключ окна и
        # текст разъезжаются). Значение едет под ИМЕНЕМ счётчика: читателю
        # строки важно, какой именно счётчик вырос.
        self._voice(
            "overflow",
            "очередь дренажа переполнена, запись вытеснена",
            **{self._counter_name: self._channel.dropped, "capacity": self._channel.capacity},
        )

    def _voice_sink_failure(self, count: int, exc: Optional[BaseException]) -> None:
        self._voice(
            "sink",
            "сток не принял пачку",
            records=count,
            reason=type(exc).__name__ if exc is not None else "отказ стока",
        )


__all__ = [
    "BatchDrainWorker",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CLOSE_TIMEOUT_SEC",
    "DEFAULT_FLUSH_INTERVAL_SEC",
]
