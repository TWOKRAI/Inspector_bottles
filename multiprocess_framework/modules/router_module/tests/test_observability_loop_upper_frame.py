"""Петля хвоста замьючена НА ВСЮ глубину стека, а не на один кадр (Ф7.х, B-3 + M-1).

Ф7.3 замьютила провал доставки в ``_deliver_by_targets`` и на этом остановилась.
Сквозное ревью Ф7 воспроизвело, что кадром выше ``_do_send`` по тому же отказу
зовёт ``_report_send_error``, а тот пишет ERROR-запись и растит общий ``errors``.
Итог измерен: **500 отказов доставки хвоста = 500 ERROR-записей и errors=500**, а
``errors`` публикуется как аномалия ``router_errors`` в ``system_overview`` — то
есть объём диагностики сам порождал ложную тревогу о транспорте. Ровно та
слепота Б-6, ради которой задача 7.3 и заводилась.

Плюс M-1: на УСПЕШНОМ пути ``_resolve_channels`` писал DEBUG «no route» на каждую
запись хвоста (адресная доставка через ``targets`` — штатная дорога обеих команд
хвоста). Усилитель 1:1, видимый в артефактах живого прогона.

В каждом классе есть контраст на НЕ хвостовом грузе: без него «молчит» неотличимо
от «логирование сломано целиком», а счётчик — от «счётчиков нет вовсе».
"""

from __future__ import annotations

from ..core.router_manager import QUEUE_OBSERVABILITY, RouterManager
from ..interfaces import IMessageChannel


class _DeadRegistry:
    """Очередей нет ни у кого: любая адресная доставка проваливается."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def get_queue(self, process: str, qtype: str):
        return None

    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        return False


class _Router(RouterManager):
    """Роутер без процесса, с перехватом СВОИХ записей обеих плоскостей."""

    def __init__(self, registry=None) -> None:
        super().__init__(manager_name="router_loop_test")
        self.queue_registry = registry if registry is not None else _DeadRegistry()
        self.debug_records: list[str] = []
        self.error_records: list[str] = []
        self.tracked_errors: list[Exception] = []
        #: Подставные каналы: реестр требует настоящий ``IChannel``, а здесь
        #: проверяется поведение ``_do_send``, а не регистрация.
        self.stub_channels: list = []

    def _resolve_channels(self, msg_dict):  # noqa: D102 — подмена резолва
        if self.stub_channels:
            return list(self.stub_channels)
        return super()._resolve_channels(msg_dict)

    def _log_debug(self, message, *args, **kwargs):  # noqa: D102 — перехват
        self.debug_records.append(message() if callable(message) else str(message))

    def _log_error(self, message, *args, **kwargs):  # noqa: D102 — перехват
        self.error_records.append(message() if callable(message) else str(message))

    def _track_error(self, error, context=None):  # noqa: D102 — перехват
        self.tracked_errors.append(error)


def _tail_message() -> dict:
    """Живая форма записи хвоста — та, что кладёт RouterPushChannel."""
    return {
        "type": "event",
        "sender": "camera_0",
        "targets": ["backend_ctl"],
        "queue_type": QUEUE_OBSERVABILITY,
        "command": "log.record",
        "data": {"process": "camera_0", "record": {"level": "DEBUG", "message": "x"}},
    }


def _business_message() -> dict:
    """Контраст: обычный груз того же вида доставки."""
    return {
        "type": "command",
        "sender": "camera_0",
        "targets": ["gui"],
        "queue_type": "system",
        "command": "process.stop",
        "data": {},
    }


class TestTailDeliveryFailureDoesNotFeedItsOwnQueue:
    """B-3: провал доставки хвоста считается, но не пишется и не растит ``errors``."""

    def test_five_hundred_failures_leave_errors_at_zero(self):
        """Число взято из воспроизведения ревью: было 500 записей и errors=500."""
        router = _Router()

        for _ in range(500):
            router._do_send(_tail_message())

        stats = router.get_stats()["router"]
        assert stats["errors"] == 0, "отказ доставки хвоста растит общий errors — аномалия router_errors ложная"
        assert router.error_records == [], "отказ доставки хвоста пишет ERROR-запись — петля Б-6 жива"
        assert router.tracked_errors == [], "отказ доставки хвоста уходит в плоскость ошибок"
        assert stats["observability_delivery_failed"] == 500, "потеря молчит: ни записи, ни счётчика"
        assert stats["observability_errors_delivery_failed"] == 500, "форма отказа не названа отдельным ключом"

    def test_the_same_failure_on_business_cargo_is_loud(self):
        """Контраст. Молчание обязано быть свойством ГРУЗА, а не сломанного логирования."""
        router = _Router()

        router._do_send(_business_message())

        stats = router.get_stats()["router"]
        assert stats["errors"] == 1, "отказ доставки обычного груза перестал считаться"
        assert router.error_records, "отказ доставки обычного груза замолчал — замьютили лишнее"
        assert stats.get("observability_delivery_failed", 0) == 0

    def test_channel_error_on_the_tail_is_muted_too(self):
        """Второй вход в петлю: канал принял билет и вернул ошибку.

        Живой случай — отвалившийся сокет-подписчик, отвечающий
        ``no clients connected`` на КАЖДУЮ запись.
        """
        router = _Router()

        class _FailingChannel:
            name = "backend_ctl"

            def send(self, msg):
                return {"status": "error", "reason": "no clients connected"}

        router.stub_channels = [_FailingChannel()]

        for _ in range(50):
            router._do_send(_tail_message())

        stats = router.get_stats()["router"]
        assert stats["errors"] == 0
        assert router.error_records == []
        assert stats["observability_delivery_failed"] == 50

    def test_exception_inside_send_is_muted_but_named_separately(self):
        """Исключение под штормом повторяется так же, поэтому мьютится — но своим ключом.

        «Замьючено» не равно «неразличимо»: отказ доставки и сбой отправки
        лечатся разным, и счётчик обязан их разводить.
        """
        router = _Router()

        class _RaisingChannel:
            name = "backend_ctl"

            def send(self, msg):
                raise RuntimeError("транспорт сломан")

        router.stub_channels = [_RaisingChannel()]

        router._do_send(_tail_message())

        stats = router.get_stats()["router"]
        assert stats["errors"] == 0
        assert router.error_records == []
        assert stats["observability_errors_exception"] == 1
        assert stats["observability_delivery_failed"] == 1


class TestTailDoesNotAmplifyOnTheHealthyPath:
    """M-1: «маршрута нет» — штатная дорога хвоста, а не диагноз."""

    def test_no_debug_record_per_tail_record(self):
        """Усилитель 1:1 на успешном пути: 42 записи давали 42 строки «no route»."""
        router = _Router()

        for _ in range(42):
            router._resolve_channels(_tail_message())

        no_route = [line for line in router.debug_records if "no route" in line]
        assert no_route == [], f"хвост пишет «no route» на каждую запись: {len(no_route)} строк на 42 записи"

    def test_business_cargo_still_reports_a_missing_route(self):
        """Контраст: у обычного груза отсутствие маршрута — это по-прежнему новость."""
        router = _Router()

        router._resolve_channels(_business_message())

        assert any("no route" in line for line in router.debug_records), (
            "замьютили не только хвост — отсутствие маршрута обычного груза стало невидимым"
        )


class _NoClientsChannel(IMessageChannel):
    """Настоящая форма отказа моста 1.1b: сокет без подключённого подписчика.

    Наследование от ``IMessageChannel`` несущее: ``register_channel`` проверяет
    интерфейс, и утиный стаб он молча отвергает — тест тогда едет ОЧЕРЕДНЫМ
    путём и канального кадра не видит вовсе (поймано инъекцией И-B: предсказано
    2 красных, получен 1).
    """

    @property
    def name(self):
        return "backend_ctl"

    @property
    def channel_type(self):
        return "socket"

    def send(self, m):
        return {"status": "error", "reason": "no clients connected"}

    def poll(self, t=0.0):
        return []

    def start_listening(self, cb):
        return False

    def stop_listening(self):
        return True

    def close(self):
        pass

    def is_open(self):
        return True

    def get_stats(self):
        return {}


class TestTheLossIsCountedExactlyOnce:
    """Ф7.х.2 (Н-1 верификации корзины): одна потерянная запись = один инкремент.

    Первая редакция мьюта добавила счёт в ``_report_send_error`` и НЕ сняла
    инкременты в ``_deliver_by_targets``/``_deliver_via_channel`` — один отказ
    проходил оба кадра и считался дважды (200 на 100 потерь). Оба теста той
    редакции стояли по разные стороны шва (один звал нижний кадр напрямую,
    другой подменял ``_resolve_channels`` и в нижний не заходил) — поэтому здесь
    путь ПОЛНЫЙ: ``_do_send`` без подмен, с настоящим каналом в реестре, оба
    кадра проходятся, арифметика проверяется литералом.
    """

    N = 50

    def _drive(self, router, qtype: str = QUEUE_OBSERVABILITY) -> None:
        for i in range(self.N):
            msg = _tail_message()
            msg["queue_type"] = qtype
            msg["data"]["record"]["message"] = f"r{i}"
            router._do_send(msg)

    def test_channel_refusal_counts_once_per_record(self) -> None:
        """Путь канала: no clients connected → ровно N, не 2N."""
        router = _Router()
        router.register_channel(_NoClientsChannel())
        self._drive(router)
        stats = router.get_stats()["router"]
        assert stats.get("observability_delivery_failed") == self.N, (
            "потеря считается не по одному разу на запись — "
            f"ожидали {self.N}, получили {stats.get('observability_delivery_failed')}"
        )
        assert stats.get("errors", 0) == 0

    def test_queue_refusal_counts_once_per_record(self) -> None:
        """Путь очереди: send_to_queue вернул False → ровно N."""
        router = _Router()  # _DeadRegistry: очередь есть у всех, приём — ни у кого
        for i in range(self.N):
            msg = _tail_message()
            msg["targets"] = ["gui"]
            msg["data"]["record"]["message"] = f"r{i}"
            router._do_send(msg)
        stats = router.get_stats()["router"]
        assert stats.get("observability_delivery_failed") == self.N
        assert stats.get("errors", 0) == 0
