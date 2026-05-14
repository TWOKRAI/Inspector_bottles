"""Тесты SourceProducer — produce() loop + send."""

import threading
import time


from multiprocess_framework.modules.process_module.generic.source_producer import (
    SourceProducer,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
)


# --- Тестовые плагины ---


class FakeSource(ProcessModulePlugin):
    name = "fake_cam"
    category = "source"

    def __init__(self):
        super().__init__()
        self._count = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        self._count += 1
        return [{"frame": f"frame_{self._count}", "camera_id": 0, "frame_id": self._count}]


class EmptySource(ProcessModulePlugin):
    name = "empty"
    category = "source"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        return []


class FailSource(ProcessModulePlugin):
    name = "fail_source"
    category = "source"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        raise RuntimeError("camera disconnected")


class TestSendItem:
    """_send_item: routing + send."""

    def test_send_to_chain_targets(self):
        """Item без target → отправка в chain_targets."""
        sent = []
        producer = SourceProducer(
            plugin=FakeSource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["processor", "gui"],
        )
        producer._send_item({"val": 1})
        assert len(sent) == 2
        assert sent[0][0] == "processor"
        assert sent[1][0] == "gui"

    def test_send_with_item_target(self):
        """Item с target → отправка в указанный."""
        sent = []
        producer = SourceProducer(
            plugin=FakeSource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["default"],
        )
        producer._send_item({"val": 1, "target": "special"})
        assert len(sent) == 1
        assert sent[0][0] == "special"


class TestRunLoop:
    """run_loop интеграция."""

    def test_produces_and_sends(self):
        """Produce loop генерирует items и отправляет."""
        sent = []
        source = FakeSource()
        producer = SourceProducer(
            plugin=source,
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=100.0,  # Быстрый для теста
        )

        stop_event = threading.Event()
        pause_event = threading.Event()

        t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.15)
        stop_event.set()
        t.join(timeout=1)

        # Должен был произвести несколько кадров
        assert len(sent) >= 5
        assert sent[0][1]["data"]["frame_id"] == 1

    def test_empty_produce_no_send(self):
        """produce() returns [] → ничего не отправляется."""
        sent = []
        producer = SourceProducer(
            plugin=EmptySource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=100.0,
        )

        stop_event = threading.Event()
        pause_event = threading.Event()

        t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.1)
        stop_event.set()
        t.join(timeout=1)

        assert len(sent) == 0

    def test_error_in_produce_continues(self):
        """RuntimeError в produce() → логируется, loop продолжается."""
        errors = []
        sent = []
        producer = SourceProducer(
            plugin=FailSource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=100.0,
            log_error=errors.append,
        )

        stop_event = threading.Event()
        pause_event = threading.Event()

        t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.1)
        stop_event.set()
        t.join(timeout=1)

        assert len(errors) >= 1
        assert "camera disconnected" in errors[0]
        assert len(sent) == 0

    def test_pause_stops_producing(self):
        """pause_event → produce не вызывается."""
        source = FakeSource()
        sent = []
        producer = SourceProducer(
            plugin=source,
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=100.0,
        )

        stop_event = threading.Event()
        pause_event = threading.Event()
        pause_event.set()  # Пауза

        t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.1)
        stop_event.set()
        t.join(timeout=1)

        assert source._count == 0
        assert len(sent) == 0

    def test_fps_throttle(self):
        """target_fps=10 → ~10 кадров в секунду (не 100+)."""
        sent = []
        producer = SourceProducer(
            plugin=FakeSource(),
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
            chain_targets=["out"],
            target_fps=10.0,
        )

        stop_event = threading.Event()
        pause_event = threading.Event()

        t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
        t.start()
        time.sleep(0.35)
        stop_event.set()
        t.join(timeout=1)

        # При 10 FPS за 0.35 сек ≈ 3-4 кадра (с учётом погрешности)
        assert 2 <= len(sent) <= 6
