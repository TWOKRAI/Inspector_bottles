"""Тесты DataReceiver — приём IPC → item → InspectorManager → chain_queue."""

import queue
import threading
import time


from multiprocess_framework.modules.process_module.generic.data_receiver import (
    DataReceiver,
)
from multiprocess_framework.modules.process_module.generic.inspector_registry import (
    PassThroughInspector,
)


class TestBuildItem:
    """_build_item: IPC msg → item dict."""

    def test_flat_msg(self):
        """msg с полями верхнего уровня."""
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=queue.Queue(),
        )
        msg = {"frame": "ndarray", "camera_id": 1, "seq_id": 5, "data": {}}
        item = receiver._build_item(msg)
        assert item["frame"] == "ndarray"
        assert item["camera_id"] == 1
        assert item["seq_id"] == 5

    def test_nested_data(self):
        """msg с вложенным data dict."""
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=queue.Queue(),
        )
        msg = {
            "frame": "img",
            "data": {"camera_id": 2, "region_name": "left", "extra": "val"},
        }
        item = receiver._build_item(msg)
        assert item["frame"] == "img"
        assert item["camera_id"] == 2
        assert item["region_name"] == "left"
        assert item["extra"] == "val"


class TestOnItemsReady:
    """on_items_ready → chain_queue.put (backpressure Q6)."""

    def test_items_put_to_queue(self):
        """Items помещаются в chain_queue."""
        chain_q = queue.Queue(maxsize=10)
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=chain_q,
        )
        items = [{"val": 1}, {"val": 2}]
        receiver.on_items_ready(items)
        assert chain_q.get_nowait() == items

    def test_backpressure_blocks_not_drops(self):
        """Queue full → блокируется (не дропает). После освобождения — item доставлен."""
        chain_q = queue.Queue(maxsize=1)
        chain_q.put([{"blocking": True}])  # Заполняем

        inspector = PassThroughInspector()
        errors = []
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=chain_q,
            lag_alert_threshold_sec=0.05,
            log_error=errors.append,
        )

        # put в отдельном потоке (будет блокироваться)
        result = []

        def put_item():
            receiver.on_items_ready([{"new": True}])
            result.append("delivered")

        t = threading.Thread(target=put_item)
        t.start()

        time.sleep(0.1)  # Дать залогировать overload
        # Освободить место
        chain_q.get_nowait()
        t.join(timeout=1)

        assert "delivered" in result
        assert len(errors) >= 1  # Overload alert залогирован
        # Item доставлен
        delivered = chain_q.get_nowait()
        assert delivered == [{"new": True}]

    def test_backpressure_exits_on_stop_event(self):
        """Queue full + stop_event взведён → on_items_ready не блокируется (shutdown path)."""
        chain_q = queue.Queue(maxsize=1)
        chain_q.put([{"blocking": True}])  # Заполняем

        stop_event = threading.Event()
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=chain_q,
            lag_alert_threshold_sec=0.05,
        )
        # Симулируем run_loop — он сохраняет stop_event перед стартом
        receiver._stop_event = stop_event

        # Взводим stop_event заранее (как при shutdown)
        stop_event.set()

        t0 = time.time()
        receiver.on_items_ready([{"new": True}])
        elapsed = time.time() - t0

        # Должен выйти быстро (< 0.5с), не зависнуть на 5с
        assert elapsed < 0.5, f"on_items_ready заблокировалась на {elapsed:.2f}с при stop_event"
        # Очередь не изменилась (item дропнут)
        assert chain_q.qsize() == 1


class TestRunLoop:
    """run_loop интеграция."""

    def test_receive_and_forward(self):
        """receive_fn → build_item → InspectorManager → chain_queue."""
        messages = [
            {"frame": "img1", "camera_id": 0, "seq_id": 1, "data": {}},
            None,  # timeout — пропуск
        ]
        msg_iter = iter(messages)
        call_count = [0]

        def fake_receive(**kwargs):
            call_count[0] += 1
            if call_count[0] > 3:
                return None  # После обработки — возвращаем None
            try:
                return next(msg_iter)
            except StopIteration:
                return None

        chain_q = queue.Queue()
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=fake_receive,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=chain_q,
        )
        inspector._on_ready = receiver.on_items_ready

        stop_event = threading.Event()
        pause_event = threading.Event()

        t = threading.Thread(target=receiver.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.2)
        stop_event.set()
        t.join(timeout=1)

        # Проверяем что item попал в chain_queue
        assert not chain_q.empty()
        items = chain_q.get_nowait()
        assert items[0]["frame"] == "img1"
        assert items[0]["camera_id"] == 0

    def test_pause_stops_processing(self):
        """pause_event → receive не вызывается."""
        call_count = [0]

        def fake_receive(**kwargs):
            call_count[0] += 1
            return None

        chain_q = queue.Queue()
        inspector = PassThroughInspector()
        receiver = DataReceiver(
            receive_fn=fake_receive,
            shm_middleware=None,
            inspector_manager=inspector,
            chain_queue=chain_q,
        )

        stop_event = threading.Event()
        pause_event = threading.Event()
        pause_event.set()  # Пауза с самого начала

        t = threading.Thread(target=receiver.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.15)
        stop_event.set()
        t.join(timeout=1)

        # На паузе receive не должен вызываться (только sleep)
        assert call_count[0] == 0


class TestReturnMessagesFlag:
    """Ф7 G.5.a — флаг FW_DATA_PLANE_DICTS управляет return_messages на data-plane.

    Дефолт off = бит-в-бит прежнее (return_messages=True, router рождает Message);
    on = plain dict (return_messages=False, снятие двойной конверсии). Флаг читается
    ОДИН раз в __init__ (не на кадр). Контент кадра идентичен в обоих состояниях.
    """

    @staticmethod
    def _make_receiver(chain_q):
        captured = {"return_messages": None, "calls": 0}

        def fake_receive(**kwargs):
            captured["calls"] += 1
            captured["return_messages"] = kwargs.get("return_messages")
            if captured["calls"] == 1:
                return {"frame": "img1", "camera_id": 7, "seq_id": 3, "data": {}}
            return None

        receiver = DataReceiver(
            receive_fn=fake_receive,
            shm_middleware=None,
            inspector_manager=PassThroughInspector(),
            chain_queue=chain_q,
        )
        receiver._inspector._on_ready = receiver.on_items_ready
        return receiver, captured

    def _run_once(self, receiver):
        stop_event = threading.Event()
        pause_event = threading.Event()
        t = threading.Thread(target=receiver.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.15)
        stop_event.set()
        t.join(timeout=1)

    def test_flag_off_default_return_messages_true(self, monkeypatch):
        """Дефолт (флаг не задан) → return_messages=True (прежнее поведение)."""
        monkeypatch.delenv("FW_DATA_PLANE_DICTS", raising=False)
        chain_q = queue.Queue()
        receiver, captured = self._make_receiver(chain_q)
        assert receiver._return_messages is True
        self._run_once(receiver)
        assert captured["return_messages"] is True
        # Контент кадра дошёл до chain_queue.
        items = chain_q.get_nowait()
        assert items[0]["frame"] == "img1"
        assert items[0]["camera_id"] == 7

    def test_flag_on_return_messages_false(self, monkeypatch):
        """FW_DATA_PLANE_DICTS=1 → return_messages=False (plain dict, без пересборки)."""
        monkeypatch.setenv("FW_DATA_PLANE_DICTS", "1")
        chain_q = queue.Queue()
        receiver, captured = self._make_receiver(chain_q)
        assert receiver._return_messages is False
        self._run_once(receiver)
        assert captured["return_messages"] is False
        # Паритет контента: тот же кадр, что и при флаге off.
        items = chain_q.get_nowait()
        assert items[0]["frame"] == "img1"
        assert items[0]["camera_id"] == 7

    def test_flag_read_once_at_init(self, monkeypatch):
        """Флаг читается в __init__ (не на кадр): смена env после init не влияет."""
        monkeypatch.setenv("FW_DATA_PLANE_DICTS", "1")
        receiver, _ = self._make_receiver(queue.Queue())
        assert receiver._return_messages is False
        # Меняем env уже после конструктора — состояние не должно поменяться.
        monkeypatch.delenv("FW_DATA_PLANE_DICTS", raising=False)
        assert receiver._return_messages is False
