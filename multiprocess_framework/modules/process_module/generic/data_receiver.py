"""DataReceiver — компонент приёма IPC и трансформации в items.

Receive loop:
  IPC msg → FrameShmMiddleware.restore_frame() → item → ItemCollector.on_item()
  Периодически: ItemCollector.check_timeouts()

Используется GenericProcess как LOOP worker.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from . import frame_trace
from . import perf_probes
from .cycle_metrics import CycleMetricsRecorder
from ...router_module.middleware.frame_shm_middleware import SHM_DROPPED_KEY, SHM_VIEWS_KEY, FrameShmMiddleware
from .collector_registry import ItemCollector


class _StampedBatch(list):
    """Коллекция items с меткой постановки в очередь (``perf_counter``).

    Метку читает PipelineExecutor, чтобы посчитать ожидание в chain_queue. Остаётся
    обычным ``list`` для всех потребителей.
    """

    __slots__ = ("enq_ts",)


class DataReceiver:
    """Приём data-plane IPC → item → ItemCollector → chain_queue.

    Args:
        receive_fn: callable для получения IPC сообщений (process.receive_message)
        shm_middleware: FrameShmMiddleware для восстановления frame из SHM
        item_collector: ItemCollector (буфер fan-in/join, DI из Plugins/_shared/fanin)
        chain_queue: очередь для готовых коллекций items → PipelineExecutor
        lag_alert_threshold_sec: порог для backpressure alert (Q6)
        log_info: callback для логирования
        log_error: callback для ошибок
    """

    def __init__(
        self,
        receive_fn: Callable,
        shm_middleware: FrameShmMiddleware | None,
        item_collector: ItemCollector,
        chain_queue: queue.Queue,
        lag_alert_threshold_sec: float = 2.0,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
        log_debug: Callable[[str], None] | None = None,
        node_name: str = "",
        max_lag_items: int = 0,
        clock: Callable[[], float] | None = None,
        inflight_budget: int = 0,
        ipc_depth_fn: Callable[[], int | None] | None = None,
    ) -> None:
        self._receive = receive_fn
        # Ф7 G.5.a — снятие двойной конверсии на data-plane. Флаг читается ОДИН раз
        # (не на кадр): FW_DATA_PLANE_DICTS on → просим router отдавать plain dict
        # (return_messages=False), без пересборки Message.from_dict → to_dict() ниже.
        # Дефолт off = бит-в-бит прежнее (router рождает Message, guard to_dict его
        # разбирает). Откат = флаг off.
        from multiprocess_framework.modules.config_module.feature_flags import is_enabled

        self._return_messages = not is_enabled("FW_DATA_PLANE_DICTS")
        # Имя процесса-узла — для frame-trace transport-спана (from -> node).
        self._node = node_name
        self._shm = shm_middleware
        self._collector = item_collector
        self._chain_queue = chain_queue
        self._lag_threshold = lag_alert_threshold_sec
        # Потолок отставания: сколько коллекций разрешено копить перед исполнителем.
        # 0 = прежнее поведение (блокировать и ждать, Q6). >0 = «догоняющий буфер»:
        # держим не более N свежих, самые старые выбрасываем. См. _bound_lag.
        self._max_lag_items = max(0, int(max_lag_items))
        self._clock = clock or time.monotonic
        self._lag_dropped_total = 0
        self._lag_dropped_since_log = 0
        self._lag_log_window = 5.0
        self._lag_last_log = 0.0
        # Task 4.7c (C3): бюджет кадров в полёте B и чтение глубины СВОЕЙ IPC data-очереди.
        # Транзит (кадры между очередью и приёмником) не навязывается размером очереди, а
        # меряется: глубина > B - lag -> счётчик. B = 0 — получатель не за кольцом, не меряем.
        self._inflight_budget = max(0, int(inflight_budget))
        self._ipc_depth_fn = ipc_depth_fn
        self._ipc_queue_depth: int | None = None
        self._transit_over_budget = 0
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        # Kwargs-safe no-op по умолчанию (F6d, ревью 2026-07-13): реальный
        # ProcessModule._log_debug тоже kwargs-safe (несёт trace_id=... как extra
        # для LogRecord, Ф7 G.6). Периодический per-frame TRACE снят в Ф7 G.1 —
        # latency этапов теперь через perf_probes (см. self._perf ниже).
        self._log_debug = log_debug or frame_trace.noop_log

        # Метрики
        self._overload_events = 0
        self._last_timeout_check = 0.0

        # Тайминг цикла приёма для телеметрии GUI. Воркер receive-driven:
        # меряем только итерации с реально полученным сообщением, а не
        # холостые spin'ы при пустом receive (иначе effective_hz отражал бы
        # частоту опроса, а не реальный поток данных).
        self._cycle_metrics = CycleMetricsRecorder(target_interval_s=0.0)
        # Task 4.5d: EMA времени транспорта между процессами (первый отсчёт задаёт значение).
        self._transport_ms = 0.0
        self._transport_seen = False
        # HP-1 (Ф7 G.1): per-stage latency (receive/restore), за флагом
        # FW_PERF_PROBES, дефолт OFF — см. perf_probes.py.
        self._perf = perf_probes.LatencyProbes()

        # stop_event текущего run_loop — сохраняется при запуске воркера,
        # используется в on_items_ready для stop-aware backpressure.
        self._stop_event: threading.Event | None = None

    def get_cycle_metrics(self) -> dict:
        """Снимок тайминга цикла приёма (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера →
        heartbeat → ProcessMonitor.state.fps/latency_ms → GUI. При включённых
        perf-пробах (FW_PERF_PROBES=1) дополнительно несёт ``perf_probes``:
        p50/p99/count по этапам receive/restore (HP-1, Ф7 G.1).
        """
        metrics = self._cycle_metrics.get_cycle_metrics()
        if perf_probes.enabled():
            metrics["perf_probes"] = self._perf.get_stats()
        # Task 4.5d: ключ есть всегда (0.0 до первого отсчёта) — ноль здесь показание.
        metrics["transport_ms"] = round(self._transport_ms, 2)
        # Task 4.7c (C3): gauge глубины IPC data-очереди; ключа нет, пока глубину ни разу не прочли.
        if self._ipc_queue_depth is not None:
            metrics["ipc_queue_depth"] = self._ipc_queue_depth
        return metrics

    def _note_ipc_depth(self) -> None:
        """Снять глубину IPC data-очереди и учесть превышение транзитного запаса (C3).

        Зовётся на каждое полученное сообщение. Глубина > ``B - max_lag_items`` значит, что
        кадров в пути больше запаса, и самый старый из них рискует пережить свой кадр.
        Падение чтения глубины не должно ронять приём: платформа без qsize даёт None.
        """
        if self._ipc_depth_fn is None:
            return
        try:
            depth = self._ipc_depth_fn()
        except Exception as exc:  # noqa: BLE001 — измерение не вправе остановить приём
            self._log_error(f"DataReceiver: не удалось прочитать глубину IPC-очереди: {exc}")
            return
        self._ipc_queue_depth = depth
        if depth is not None and self._inflight_budget > 0 and depth > self._inflight_budget - self._max_lag_items:
            self._transit_over_budget += 1

    @property
    def ipc_queue_depth(self) -> int | None:
        """Последняя прочитанная глубина IPC data-очереди (None — не читали / узнать нельзя)."""
        return self._ipc_queue_depth

    @property
    def transit_over_budget(self) -> int:
        """Сколько раз глубина IPC data-очереди превысила транзитный запас ``B - lag``."""
        return self._transit_over_budget

    def _note_transport(self, msg: dict) -> None:
        """Снять штамп отправки ``_t_sent_ns`` с сообщения и обновить EMA ``transport_ms``.

        Штамп вынимается ВСЕГДА, даже испорченный: ключ не должен дойти до коллектора и
        далее до отправки вниз по цепочке (там штамп ставит уже свой отправитель).

        Почему ``perf_counter_ns``: на Windows он общесистемный, поэтому штамп родителя
        сопоставим с часами дочернего процесса (замер лида: дельта родитель/потомок
        0.6-0.8 мс); ``time.time()`` ходит шагами по 15.6 мс и для миллисекунд не годится.

        Что входит в число: отправка -> межпроцессная очередь данных -> unpickle ->
        SHM-restore. Вместе с ``queue_wait_ms`` (ожидание в chain_queue) и ``plugin_ms``
        объясняет, из чего сложилась задержка кадра (цель владельца - требования к мощности).
        Затор исполнителя сюда тоже попадает: пока приём блокирован на ``put`` в chain_queue,
        следующий кадр ждёт во входящей очереди. Рост вместе с ``queue_wait_ms`` = упор в
        исполнитель получателя, а не в транспорт (ревью 4.5, итерация 2, N1).
        """
        data = msg.get("data", msg)
        sent = data.pop("_t_sent_ns", None) if isinstance(data, dict) else None
        if not isinstance(sent, int) or isinstance(sent, bool):
            return
        ms = (time.perf_counter_ns() - sent) / 1e6
        if self._transport_seen:
            self._transport_ms += 0.1 * (ms - self._transport_ms)
        else:
            self._transport_ms = ms
            self._transport_seen = True

    def _bound_lag(self, items: list[dict]) -> bool:
        """Догоняющий буфер: держать не более ``max_lag_items`` свежих коллекций.

        Зачем. Живой стенд 2026-08-12 (`webcam_sketch`): исполнитель `lines` тянет
        3.3 к/с, источник даёт 21 к/с. Внутренняя очередь (64) и очередь транспорта
        (50) наполнялись доверху, и картинка Line-art отставала от реальности
        примерно на **34 секунды** — при том что кадры всё равно терялись: транспорт
        вытеснил 1646 штук (``queue_data_evicted`` у `seg`). То есть гарантия «не
        дропаем» уже не действовала, а платили за неё задержкой.

        Что делает. Перед укладкой новой КАДРОВОЙ коллекции выбрасывает самые СТАРЫЕ
        кадровые коллекции, пока их в очереди не останется меньше потолка. Отставание
        сверху ограничено ``max_lag_items / темп исполнителя``: 4 коллекции при 3.3 к/с —
        1.2 с, «несколько кадров, чтобы догнать пробку», а не секунды накопления.

        **Считаются только кадры (Task 4.7c, C1).** Бюджет кольца — про кадры: потолок
        должен держать «в полёте» не больше B кадров, а сигнал без кадра (кнопка, команда)
        слот кольца не занимает. Раньше потолок считал сообщения и вытеснял сигнал вместе
        с кадрами. Коллекция кадровая, если хоть один её item несёт ``_shm_views`` или
        ``frame`` — в том числе join, где сигнал склеен с кадром. Сигнальная коллекция
        потолком не вытесняется и в счёт не идёт (идёт обычным ``put``).

        Потеря — со счётом и голосом: счётчик ``lag_dropped_total`` растёт всегда,
        WARNING печатается не чаще раза в 5 с и несёт число выброшенных за окно
        (иначе строка на кадр сама стала бы нагрузкой — тот же приём, что у
        ``drop_oldest`` транспорта).

        Returns:
            True — коллекция уложена (вызывающему делать нечего).
            False — потолок не применим (сигнал) либо уложить не удалось (гонка с
            потребителем): пусть работает прежняя дорога с блокировкой, а не тихая потеря.
        """
        if not self._is_frame_collection(items):
            return False
        dropped = 0
        chain = self._chain_queue
        # Выборочное удаление из середины очереди — только под mutex Queue (иначе гонка
        # с get() потребителя), и после него обязательно not_full.notify(): блокированный в
        # put() производитель ждёт на not_full и без сигнала не узнал бы, что место освободилось.
        with chain.mutex:
            pending = chain.queue
            frame_idx = [i for i, coll in enumerate(pending) if self._is_frame_collection(coll)]
            excess = len(frame_idx) - self._max_lag_items + 1
            if excess > 0:
                for i in reversed(frame_idx[:excess]):  # с конца: индексы оставшихся не плывут
                    del pending[i]
                dropped = excess
                # Приёмник — единственный производитель chain_queue, поэтому notify защитный и сегодня
                # ненаблюдаем (замер: без него все тесты зелёные).
                chain.not_full.notify(dropped)
        try:
            chain.put_nowait(items)
        except queue.Full:
            # Гонка: место заняли между удалением и put (или очередь забита сигналами). Не теряем
            # молча — уходим на прежнюю дорогу (блокирующий put с алертом).
            self._note_lag_drops(dropped)
            return False
        self._note_lag_drops(dropped)
        return True

    @staticmethod
    def _is_frame_collection(items: list[dict]) -> bool:
        """Кадровая ли коллекция: хоть один item несёт ``_shm_views`` или ``frame`` (C1)."""
        return any(isinstance(it, dict) and (SHM_VIEWS_KEY in it or "frame" in it) for it in items)

    def _note_lag_drops(self, dropped: int) -> None:
        """Учесть выброшенные коллекции; голос — не чаще раза в окно, с числом."""
        if not dropped:
            return
        self._lag_dropped_total += dropped
        self._lag_dropped_since_log += dropped
        now = self._clock()
        if now - self._lag_last_log < self._lag_log_window:
            return
        self._lag_last_log = now
        count, self._lag_dropped_since_log = self._lag_dropped_since_log, 0
        self._log_error(
            f"DataReceiver: исполнитель не успевает — выброшено {count} устаревших коллекций "
            f"за последние {self._lag_log_window:g} с (всего {self._lag_dropped_total}); "
            f"потолок отставания {self._max_lag_items}"
        )

    @property
    def lag_dropped_total(self) -> int:
        """Сколько устаревших коллекций выброшено потолком отставания."""
        return self._lag_dropped_total

    def on_items_ready(self, items: list[dict]) -> None:
        """Callback от ItemCollector — коллекция готова, кладём в chain_queue.

        Backpressure (Q6): block + alert. Никогда не дропаем в нормальной работе.

        При взведённом stop_event (shutdown) — прекращаем ожидание освобождения
        очереди: downstream consumer уже остановлен, ждать бессмысленно. Item
        дропается (единственный случай) чтобы воркер мог выйти gracefully.
        """
        # Метка ставится один раз, до всех путей put: ожидание из-за backpressure
        # считается ожиданием исполнителя намеренно.
        items = _StampedBatch(items)
        items.enq_ts = time.perf_counter()
        if self._max_lag_items and self._bound_lag(items):
            return
        try:
            self._chain_queue.put(items, timeout=self._lag_threshold)
        except queue.Full:
            # Алерт: pipeline overload
            self._overload_events += 1
            self._log_error(
                f"DataReceiver: pipeline overload (queue full > {self._lag_threshold}s), "
                f"events={self._overload_events}. Ждём освобождения..."
            )
            # Stop-aware backpressure: chunked put с проверкой stop_event.
            # В нормальной работе блокируем до освобождения (Q6 — не дропаем).
            # При shutdown (stop_event взведён) — выходим, чтобы не зависнуть:
            # downstream consumer уже гасится и очередь никто не дочитает.
            while True:
                if self._stop_event is not None and self._stop_event.is_set():
                    # Downstream остановлен — дропаем и выходим (shutdown path)
                    self._log_error("DataReceiver: stop_event set during backpressure wait — dropping item (shutdown)")
                    return
                try:
                    self._chain_queue.put(items, timeout=0.1)
                    return  # успешно положили
                except queue.Full:
                    continue  # ещё не освободилась — проверим stop_event снова

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """LOOP worker: receive IPC → restore frame → ItemCollector.

        Args:
            stop_event: сигнал остановки
            pause_event: сигнал паузы
        """
        # Сохраняем stop_event для on_items_ready (stop-aware backpressure).
        self._stop_event = stop_event
        self._last_timeout_check = time.monotonic()

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Периодическая проверка timeouts (каждые ~100ms)
            now = time.monotonic()
            if now - self._last_timeout_check > 0.1:
                self._collector.check_timeouts()
                self._last_timeout_check = now

            # Receive IPC с timeout. return_messages=False (флаг FW_DATA_PLANE_DICTS)
            # → router отдаёт plain dict без пересборки Message (Ф7 G.5.a).
            msg = self._receive(
                timeout=0.05,
                channel_types=["data"],
                return_messages=self._return_messages,
            )
            if msg is None:
                continue

            # Task 4.7c (C3): глубина IPC-очереди на каждое полученное сообщение.
            self._note_ipc_depth()

            # Тайминг полезной итерации (restore + build + on_item), без учёта
            # ожидания на пустом receive. perf_counter (не monotonic): работа
            # subмиллисекундная, а monotonic на Windows имеет ~15мс гранулярность.
            t_start = time.perf_counter()

            # Message → dict: middleware и pipeline работают с plain dict.
            # HP-1 (Ф7 G.1): perf-проба этапа "receive" (десериализация, БЕЗ
            # учёта времени блокирующего ожидания в self._receive() выше) — за
            # флагом FW_PERF_PROBES, дефолт OFF, см. perf_probes.py.
            with self._perf.measure("receive"):
                if hasattr(msg, "to_dict"):
                    msg = msg.to_dict()

            # Восстановить frame из SHM. HP-1: perf-проба этапа "restore".
            if self._shm:
                with self._perf.measure("restore"):
                    msg = self._shm.restore_frame(msg)
                # 4.4c: item атомарен — сообщение с нечитаемой SHM-ссылкой отброшено целиком
                # (метку ставит restore_frame, счётчик уже учтён там). Ни item, ни ``mask=None``.
                if self._is_shm_dropped(msg):
                    continue

            # Task 4.5d: время транспорта — до построения item, чтобы штамп не утёк в него.
            self._note_transport(msg)

            # Построить item из msg
            item = self._build_item(msg)

            # Ф3.3: приём идёт в СВОЁМ потоке, и его записи (восстановление из
            # SHM, отказы fan-in) без этого остались бы без следа кадра —
            # ContextVar границу потока не пересекает.
            with frame_trace.log_correlation(item):
                # frame-trace: время передачи от предыдущего узла к этому.
                frame_trace.record_transport(item, self._node)

                # Передать в коллектор
                self._collector.on_item(item)

            # Полный цикл обработки одного сообщения → телеметрия.
            self._cycle_metrics.record(time.perf_counter() - t_start)

    @staticmethod
    def _is_shm_dropped(msg: dict) -> bool:
        """Есть ли на сообщении метка ``_shm_dropped`` (её ставит ``restore_frame``, 4.4c)."""
        data = msg.get("data", msg)
        return isinstance(data, dict) and bool(data.get(SHM_DROPPED_KEY))

    def _build_item(self, msg: dict) -> dict:
        """Построить item из IPC сообщения.

        Извлекает data-поля из msg, сохраняет frame.
        """
        # msg может содержать "data" dict или быть flat
        data = msg.get("data", {})
        if isinstance(data, dict):
            item = dict(data)
        else:
            item = {}

        # frame восстановлен SHM middleware и лежит в msg["frame"]
        if "frame" in msg:
            item["frame"] = msg["frame"]

        # Стандартные поля из msg-уровня.
        # sender/data_type — для корреляции в join-коллекторе (Этап 1) и io-debug:
        # sender ставится на msg-уровне (process_communication.send_to_process) и иначе
        # потерялся бы при build; data_type помечает поток (frame/overlay/detections/...).
        for key in (
            "camera_id",
            "seq_id",
            "total_regions",
            "region_name",
            "frame_id",
            "timestamp",
            "sender",
            "data_type",
        ):
            if key in msg and key not in item:
                item[key] = msg[key]

        return item

    @property
    def overload_events(self) -> int:
        """Количество событий backpressure overload."""
        return self._overload_events
