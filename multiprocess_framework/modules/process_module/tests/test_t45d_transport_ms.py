# -*- coding: utf-8 -*-
"""Task 4.5d (transport-single-policy) — приёмочные тесты времени транспорта между процессами.

Зачем. Чтобы разложить задержку кадра на этапы («transport + queue_wait + plugin_ms»),
нужно знать, сколько кадр провёл в межпроцессной очереди данных (maxsize 50): ``queue_wait_ms``
(4.5a) покрывает только внутрипроцессную ``chain_queue``. ``time.perf_counter_ns()`` на Windows
общесистемный, поэтому штамп отправителя сопоставим с часами получателя.

Контракт (черный ящик, реализацию не читал):

* ``SourceProducer`` и ``PipelineExecutor`` штампуют КАЖДЫЙ исходящий item полем
  ``_t_sent_ns`` (int, ``time.perf_counter_ns()``) прямо перед отправкой — всегда, независимо
  от ``FW_FRAME_TRACE``. Штамп лежит в ``msg["data"]`` отправленного сообщения.
* ``DataReceiver`` после SHM-restore вынимает ``_t_sent_ns`` из данных сообщения (в коллектор
  штамп НЕ попадает), считает ``(now_ns - sent) / 1e6`` мс и ведёт EMA (alpha 0.1, первый отсчёт
  = сам отсчёт). ``get_cycle_metrics()["transport_ms"]`` — float, ключ есть всегда (0.0 до первого
  отсчёта). Сообщение без штампа (или с не-int штампом) — без исключения, значение не меняется,
  item всё равно доходит до коллектора. Сообщение, отброшенное SHM-restore (``_shm_dropped``),
  в счёт не идёт.
* ``build_worker_telemetry`` пробрасывает ``transport_ms`` воркера (round 1, включая 0) под
  гейтом ``allowed_metrics``; метрика объявлена в каталоге.

Ожидаемые значения — литералы. Всё, что может зависнуть, гоняется в daemon-потоке с
join-дедлайном.
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    gated_metrics,
)
from multiprocess_framework.modules.process_module.generic.collector_registry import (
    PassThroughCollector,
)
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_worker_telemetry,
)
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #

_MS = 1_000_000  # наносекунд в миллисекунде


@pytest.fixture(autouse=True)
def _frame_trace_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Трассировка кадров выключена (дефолт): штамп транспорта от неё не зависит."""
    monkeypatch.delenv("FW_FRAME_TRACE", raising=False)


def _run_in_thread(target, *args) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def _stop_and_join(t: threading.Thread, stop: threading.Event, deadline_s: float = 3.0) -> None:
    stop.set()
    t.join(timeout=deadline_s)
    assert not t.is_alive(), "воркер не остановился за дедлайн (зависание)"


def _wait_until(pred, deadline_s: float = 3.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return bool(pred())


class _CountingSource(ProcessModulePlugin):
    """Источник: каждый produce() отдаёт один кадр."""

    name = "t45d_cam"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self._n = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        self._n += 1
        return [{"frame": f"f{self._n}", "camera_id": 0, "frame_id": self._n}]


# --------------------------------------------------------------------------- #
# RED 1-2. Отправитель штампует каждый исходящий item
# --------------------------------------------------------------------------- #


class TestSenderStampsItems:
    def test_t45d_pipeline_executor_stamps_every_sent_item(self) -> None:
        """Пачка из 3 items → 3 сообщения, у каждого в data int ``_t_sent_ns`` внутри
        [до, после] по perf_counter_ns. Штамп ставит сам исполнитель (руками не штампуем)."""
        sent: list[tuple[str, dict]] = []
        ex = PipelineExecutor(
            plugins=[],  # пустая цепочка: items проходят как есть
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        q: queue.Queue = queue.Queue()
        ex.bind_queue(q)
        q.put([{"frame_id": 1}, {"frame_id": 2}, {"frame_id": 3}])

        before = time.perf_counter_ns()
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(ex.run, stop, pause)
        try:
            assert _wait_until(lambda: len(sent) >= 3), "пачка не отправлена"
        finally:
            _stop_and_join(t, stop)
        after = time.perf_counter_ns()

        assert len(sent) == 3
        for _target, msg in sent:
            stamp = msg["data"].get("_t_sent_ns")
            assert isinstance(stamp, int) and not isinstance(stamp, bool), f"нет int-штампа: {stamp!r}"
            assert before <= stamp <= after

    def test_t45d_source_producer_stamps_every_sent_item(self) -> None:
        """Источник отправил >= 3 кадров → у каждого в data int ``_t_sent_ns`` в окне вызова."""
        sent: list[tuple[str, dict]] = []
        producer = SourceProducer(
            plugin=_CountingSource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=100.0,
        )

        before = time.perf_counter_ns()
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(producer.run_loop, stop, pause)
        try:
            assert _wait_until(lambda: len(sent) >= 3), "источник не отправил кадры"
        finally:
            _stop_and_join(t, stop)
        after = time.perf_counter_ns()

        snapshot = list(sent)
        assert len(snapshot) >= 3
        for _target, msg in snapshot:
            stamp = msg["data"].get("_t_sent_ns")
            assert isinstance(stamp, int) and not isinstance(stamp, bool), f"нет int-штампа: {stamp!r}"
            assert before <= stamp <= after


# --------------------------------------------------------------------------- #
# Приёмник: стенд с поддельным receive
# --------------------------------------------------------------------------- #


class _ReceiverRig:
    """DataReceiver + поддельный receive, отдающий сообщения по одному.

    ``script`` — список «возрастов штампа» в мс (или иной фабрики сообщения). Штамп считается
    в момент выдачи сообщения (perf_counter_ns() - age), поэтому возраст на приёме =
    заданный + реальная задержка обработки. ``None`` в списке = «штампа нет».
    """

    def __init__(self, script: list, shm=None) -> None:
        self._script = list(script)
        self.calls = 0
        self.chain_q: queue.Queue = queue.Queue()
        self.receiver = DataReceiver(
            receive_fn=self._receive,
            shm_middleware=shm,
            item_collector=PassThroughCollector(),
            chain_queue=self.chain_q,
        )
        self.receiver._collector._on_ready = self.receiver.on_items_ready
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None

    def _receive(self, **kwargs):
        self.calls += 1
        if not self._script:
            return None
        spec = self._script.pop(0)
        data: dict = {"frame_id": self.calls}
        if isinstance(spec, dict):  # готовое дополнение к data (нештатные штампы, метки)
            data.update(spec)
        elif spec is not None:  # возраст штампа в мс
            data["_t_sent_ns"] = time.perf_counter_ns() - int(spec * _MS)
        return {"data": data, "camera_id": 0}

    def push(self, spec) -> None:
        """Подать ещё одно сообщение уже во время работы приёмника."""
        self._script.append(spec)

    def start(self) -> None:
        self._thread = _run_in_thread(self.receiver.run_loop, self._stop, self._pause)

    def stop(self) -> None:
        assert self._thread is not None
        _stop_and_join(self._thread, self._stop)

    def drain_items(self) -> list[dict]:
        out: list[dict] = []
        while True:
            try:
                out.extend(self.chain_q.get_nowait())
            except queue.Empty:
                return out

    def wait_consumed(self, n_items_delivered: int) -> None:
        """Ждать, пока обработано n сообщений (cycles) и опустошён скрипт."""
        assert _wait_until(
            lambda: self.receiver.get_cycle_metrics()["cycles"] >= n_items_delivered and not self._script
        ), "приёмник не обработал сообщения за дедлайн"


# --------------------------------------------------------------------------- #
# RED 3-6. DataReceiver: transport_ms
# --------------------------------------------------------------------------- #


class TestReceiverTransportMs:
    def test_t45d_receiver_measures_age_and_strips_stamp(self) -> None:
        """Штамп 20 мс назад → transport_ms в [19, 35]; ключ есть и равен 0.0 до отсчётов;
        в коллектор штамп не попадает."""
        rig = _ReceiverRig([20])
        # Ключ есть всегда, до первого отсчёта — 0.0 (float).
        before = rig.receiver.get_cycle_metrics()["transport_ms"]
        assert before == 0.0 and isinstance(before, float)

        rig.start()
        try:
            rig.wait_consumed(1)
        finally:
            rig.stop()

        items = rig.drain_items()
        assert len(items) == 1
        assert "_t_sent_ns" not in items[0], "штамп транспорта протёк в item коллектора"
        value = rig.receiver.get_cycle_metrics()["transport_ms"]
        assert isinstance(value, float)
        assert 19.0 <= value <= 35.0

    def test_t45d_receiver_transport_ms_is_ema_alpha_0_1(self) -> None:
        """Отсчёты ~20 и ~120 мс → EMA = 0.9*20 + 0.1*120 = 30 (допуск на джиттер): [27, 36].
        Не последний отсчёт (120), не alpha 0.5 (70), не 0.1*20 = 2 (первый отсчёт не сглажен)."""
        rig = _ReceiverRig([20, 120])
        rig.start()
        try:
            rig.wait_consumed(2)
        finally:
            rig.stop()
        assert len(rig.drain_items()) == 2
        value = rig.receiver.get_cycle_metrics()["transport_ms"]
        assert 27.0 <= value <= 36.0

    @pytest.mark.parametrize(
        "bad_stamp",
        [None, {"_t_sent_ns": "not-an-int"}],
        ids=["no_stamp", "non_int_stamp"],
    )
    def test_t45d_receiver_ignores_unstamped_or_bad_stamp(self, bad_stamp) -> None:
        """Сообщение без штампа / со строкой вместо int: без исключения, transport_ms не
        меняется, item доходит до коллектора. Якорь: первый отсчёт ~20 мс уже учтён."""
        rig = _ReceiverRig([20])
        rig.start()
        try:
            rig.wait_consumed(1)
            before = rig.receiver.get_cycle_metrics()["transport_ms"]
            assert 19.0 <= before <= 35.0, "якорь: первый отсчёт учтён"

            rig.push(bad_stamp)  # второе сообщение подаём уже после снимка «до»
            rig.wait_consumed(2)
            time.sleep(0.05)  # запас: если поле «поплывёт», оно успеет
        finally:
            rig.stop()
        items = rig.drain_items()
        assert len(items) == 2, "item без штампа не дошёл до коллектора"
        assert rig.receiver.get_cycle_metrics()["transport_ms"] == before

    def test_t45d_receiver_shm_dropped_message_is_not_counted(self) -> None:
        """Сообщение, отброшенное SHM-restore (``_shm_dropped``), не попадает в transport_ms:
        если бы попало, штамп «500 мс назад» дал бы 0.9*20 + 0.1*500 = 68. Якорь: первое
        (нормальное) сообщение учтено, ~20 мс."""

        class _DroppingShm:
            """SHM-заглушка: сообщение с data['drop'] помечает как отброшенное."""

            def restore_frame(self, msg: dict) -> dict:
                if msg["data"].get("drop"):
                    msg["data"]["_shm_dropped"] = True
                return msg

        rig = _ReceiverRig([20, {"drop": True, "_t_sent_ns": time.perf_counter_ns() - 500 * _MS}], shm=_DroppingShm())
        rig.start()
        try:
            # Отброшенное сообщение цикл не завершает (cycles не растёт) — ждём по вызовам receive.
            assert _wait_until(lambda: rig.calls >= 4 and not rig._script), "скрипт не выбран"
            time.sleep(0.05)
        finally:
            rig.stop()
        items = rig.drain_items()
        assert len(items) == 1, "якорь: отброшенное сообщение не должно дойти до коллектора"
        value = rig.receiver.get_cycle_metrics()["transport_ms"]
        assert 19.0 <= value <= 35.0


# --------------------------------------------------------------------------- #
# RED 7. build_worker_telemetry пробрасывает поле
# --------------------------------------------------------------------------- #


class TestBuildWorkerTelemetryForwardsTransport:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(4.26, 4.3), (0.0, 0.0)],
        ids=["rounded_to_1", "zero_is_forwarded"],
    )
    def test_t45d_transport_ms_forwarded_when_allowed(self, raw, expected) -> None:
        snapshot = {"w1": {"status": "running", "transport_ms": raw}}
        result = build_worker_telemetry(snapshot, "proc", None)
        assert result is not None
        path, data = result
        assert path == "processes.proc"
        w = data["workers"]["w1"]
        assert "transport_ms" in w
        assert w["transport_ms"] == expected

    def test_t45d_gate_blocks_transport_ms(self) -> None:
        """allowed={"fps"} → transport_ms не попадает в payload.
        Якорь (иначе зелёный вакуумно): без гейта поле на месте."""
        snapshot = {"w1": {"status": "running", "transport_ms": 4.26}}
        _, ungated = build_worker_telemetry(snapshot, "proc", None)
        assert ungated["workers"]["w1"]["transport_ms"] == 4.3

        _, gated = build_worker_telemetry(snapshot, "proc", {"fps"})
        w = gated["workers"]["w1"]
        assert "transport_ms" not in w
        assert w["status"] == "running"  # status — always-on, вне гейта


# --------------------------------------------------------------------------- #
# RED 8. каталог метрик
# --------------------------------------------------------------------------- #


class TestMetricCatalog:
    def test_t45d_transport_ms_is_declared(self) -> None:
        names = gated_metrics()
        assert "fps" in names, "якорь: каталог фреймворка читается"
        assert "transport_ms" in names
