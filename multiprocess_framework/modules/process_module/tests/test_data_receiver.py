"""Тесты DataReceiver — приём IPC → item → InspectorManager → chain_queue."""

import queue
import threading
import time


from multiprocess_framework.modules.process_module.generic.data_receiver import (
    DataReceiver,
)
from multiprocess_framework.modules.process_module.generic.inspector_manager import (
    InspectorManager,
)


class TestBuildItem:
    """_build_item: IPC msg → item dict."""

    def test_flat_msg(self):
        """msg с полями верхнего уровня."""
        inspector = InspectorManager()
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
        inspector = InspectorManager()
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
        inspector = InspectorManager()
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

        inspector = InspectorManager()
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
        inspector = InspectorManager()
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
        inspector = InspectorManager()
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
