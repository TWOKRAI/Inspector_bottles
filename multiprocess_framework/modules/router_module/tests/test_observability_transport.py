"""Транспорт хвоста наблюдаемости: своя очередь и разорванная петля (Ф7.3).

Шторм Б-6 (live `webcam_sketch`, ~25 мин) состоял из трёх звеньев, каждое из
которых порождало новую запись в тот же хвост, чей отказ доставки её и вызвал:

  (а) полная never-drop очередь → ``Full`` → ERROR в ``QueueRegistry``;
  (б) вытеснение → throttled WARNING;
  (в) провал доставки → ``_log_debug`` в ``_deliver_by_targets``.

Здесь сторожится звено (в) во всех трёх его формах (очередь, канал, relay) и
адрес груза у обоих отправителей. Звенья (а) и (б) — в
``shared_resources_module/tests/test_observability_queue_split.py``.

Проверка «записи нет» опирается на НАБЛЮДАЕМЫЙ эффект — перехват ``_log_debug``
самого роутера, — и в каждом классе есть контраст на не-хвостовом грузе: без него
«молчит» неотличимо от «логирование сломано целиком».
"""

from __future__ import annotations

import pytest

from ..core.router_manager import QUEUE_OBSERVABILITY, RouterManager


class _Registry:
    """Мини queue_registry: очередь есть только у перечисленных (процесс, qtype)."""

    def __init__(self, present: set[tuple[str, str]], failing: bool = False) -> None:
        self._present = present
        self._failing = failing
        self.sent: list[tuple[str, str, dict]] = []

    def get_queue(self, process: str, qtype: str):
        return object() if (process, qtype) in self._present else None

    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        if self._failing:
            raise RuntimeError("очередь недоступна")
        if (process, qtype) not in self._present:
            # Настоящий QueueRegistry на отсутствующую очередь возвращает False, а не
            # «доставлено». Первая редакция этого дубля отвечала True всегда — и страж
            # на гейт релея пережил свою инъекцию: билет «доезжал» прямым путём в
            # очередь, которой нет, и подмена гейта ничего не меняла.
            return False
        self.sent.append((process, qtype, msg))
        return True


class _Router(RouterManager):
    """Роутер без процесса, с перехватом собственных DEBUG-записей."""

    def __init__(self, registry) -> None:
        super().__init__(manager_name="router_test")
        self.queue_registry = registry
        self.debug_records: list[str] = []

    def _log_debug(self, message, *args, **kwargs):  # noqa: D102 — перехват
        self.debug_records.append(message() if callable(message) else str(message))


def _ticket(qtype: str) -> dict:
    return {
        "type": "event",
        "command": "log.record",
        "sender": "camera_0",
        "targets": ["gui"],
        "queue_type": qtype,
        "data": {"record": {"message": "x"}},
    }


class TestSendersUseTheirOwnQueueClass:
    """Адрес груза у обоих отправителей — не ``system``."""

    def test_router_push_channel(self):
        from ....modules.logger_module.channels.router_push_channel import RouterPushChannel

        sent: list[dict] = []
        channel = RouterPushChannel(
            "tail",
            router=type("R", (), {"send_async": lambda self, m, priority="normal": sent.append(m)})(),
            subscriber="backend_ctl",
            sender="camera_0",
        )

        channel.write({"level": "DEBUG", "message": "x"})

        assert sent[0]["queue_type"] == QUEUE_OBSERVABILITY

    def test_record_forward_channel(self):
        from ....modules.channel_routing_module.observability.record_forward_channel import (
            RecordForwardChannel,
        )

        sent: list[dict] = []
        channel = RecordForwardChannel(
            router=type("R", (), {"send_async": lambda self, m, priority="normal": sent.append(m)})(),
            subscriber="gui",
            sender="camera_0",
        )

        channel.write({"level": "ERROR", "message": "x"})

        assert sent[0]["queue_type"] == QUEUE_OBSERVABILITY


class TestDeliveryFailureDoesNotFeedTheTail:
    """Звено (в): провал доставки хвоста считается, но не пишется."""

    def test_queue_path_is_silent_and_does_not_count_here(self):
        """Нижний кадр молчит и НЕ считает (Ф7.х.2, Н-1 верификации).

        Потерю считает ``_report_send_error(muted=True)`` кадром выше — инкремент
        и здесь давал двойной учёт (200 на 100 потерь). Арифметику «ровно один
        раз» сторожит ``TestTheLossIsCountedExactlyOnce`` полным путём через
        ``_do_send``; этот тест — только про молчание нижнего кадра.
        """
        router = _Router(_Registry({("gui", QUEUE_OBSERVABILITY)}, failing=True))

        result, attempted = router._deliver_by_targets(_ticket(QUEUE_OBSERVABILITY))

        assert (result, attempted) == (None, 1)
        assert router.debug_records == []
        assert router.get_stats()["router"].get("observability_delivery_failed", 0) == 0, (
            "нижний кадр снова считает — вместе с кадром выше это двойной учёт"
        )

    def test_data_path_still_speaks(self):
        """Контраст: обычный груз при том же отказе по-прежнему пишет запись."""
        router = _Router(_Registry({("gui", "data")}, failing=True))
        ticket = {**_ticket("data"), "type": "data"}

        router._deliver_by_targets(ticket)

        assert len(router.debug_records) == 1
        assert "failed" in router.debug_records[0]
        assert router.get_stats()["router"].get("observability_delivery_failed", 0) == 0

    @pytest.mark.parametrize(
        "channel_result",
        [{"status": "error", "reason": "no clients connected"}, "raise"],
        ids=["канал вернул ошибку", "канал бросил"],
    )
    def test_channel_path_is_silent_and_does_not_count_here(self, channel_result):
        """Отвалившийся сокет-подписчик — второй вход в петлю: молчание без счёта.

        Счёт — кадром выше (см. ``test_queue_path_is_silent_and_does_not_count_here``).
        """
        router = _Router(_Registry(set()))

        class _Channel:
            name = "backend_ctl"

            def send(self, ticket):
                if channel_result == "raise":
                    raise RuntimeError("сокет закрыт")
                return channel_result

        ok = router._deliver_via_channel(_Channel(), "backend_ctl", _ticket(QUEUE_OBSERVABILITY))

        assert ok is False
        assert router.debug_records == []
        assert router.get_stats()["router"].get("observability_delivery_failed", 0) == 0, (
            "нижний кадр снова считает — вместе с кадром выше это двойной учёт"
        )

    def test_channel_success_is_silent_too(self):
        """Успех тоже молчит: запись на КАЖДУЮ доставленную запись — тот же объём."""
        router = _Router(_Registry(set()))

        class _Channel:
            name = "backend_ctl"

            def send(self, ticket):
                return {"status": "success"}

        assert router._deliver_via_channel(_Channel(), "backend_ctl", _ticket(QUEUE_OBSERVABILITY)) is True
        assert router.debug_records == []

    def test_channel_path_for_ordinary_cargo_still_speaks(self):
        router = _Router(_Registry(set()))

        class _Channel:
            name = "backend_ctl"

            def send(self, ticket):
                return {"status": "error", "reason": "no clients connected"}

        router._deliver_via_channel(_Channel(), "backend_ctl", _ticket("data"))

        assert len(router.debug_records) == 1


class TestRelayGoesByTheSameQueueItAsks:
    """Хаб-relay: хвост едет очередью хвоста, остальное — system-почтой."""

    def test_tail_relays_via_observability_queue(self):
        registry = _Registry({("ProcessManager", QUEUE_OBSERVABILITY)})
        router = _Router(registry)
        router._relay_hub = "ProcessManager"

        assert router._relay_via_hub(_ticket(QUEUE_OBSERVABILITY)) is True

        process, qtype, envelope = registry.sent[0]
        assert (process, qtype) == ("ProcessManager", QUEUE_OBSERVABILITY)
        assert envelope["queue_type"] == QUEUE_OBSERVABILITY
        assert envelope["command"] == "router.relay"
        assert router.debug_records == []

    def test_ordinary_cargo_relays_via_system(self):
        registry = _Registry({("ProcessManager", "system")})
        router = _Router(registry)
        router._relay_hub = "ProcessManager"

        assert router._relay_via_hub(_ticket("data")) is True

        assert registry.sent[0][1] == "system"
        assert len(router.debug_records) == 1

    def test_gate_asks_about_the_queue_the_relay_will_use(self):
        """Гейт релея спрашивает про ТУ ЖЕ очередь хаба, которой релей поедет.

        Стенд: у 'gui' очереди нет вовсе, у хаба есть только ``observability``.
        Спрашивая про system, гейт счёл бы хаб непригодным и билет пропал бы.
        """
        registry = _Registry({("ProcessManager", QUEUE_OBSERVABILITY)})
        router = _Router(registry)
        router._relay_hub = "ProcessManager"

        result, attempted = router._deliver_by_targets(_ticket(QUEUE_OBSERVABILITY))

        assert attempted == 1
        assert result is not None
        assert registry.sent[0][1] == QUEUE_OBSERVABILITY


class TestCountersReachTheSurface:
    """Счётчики потерь хвоста доходят до ``get_stats`` — единственный путь наружу."""

    def test_queue_counters_are_surfaced(self):
        class _Reg(_Registry):
            observability_evicted = 7
            observability_send_failed = 3

        router = _Router(_Reg(set()))

        stats = router.get_stats()["router"]

        assert stats["queue_observability_evicted"] == 7
        assert stats["queue_observability_send_failed"] == 3


def test_debug_probe_itself_works():
    """Страж стража: перехват действительно ловит записи роутера."""
    router = _Router(_Registry(set()))

    router._log_debug(lambda: "проверка перехвата")

    assert router.debug_records == ["проверка перехвата"]
