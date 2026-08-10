# -*- coding: utf-8 -*-
"""Тесты ObservabilityTailActivator (Task 5.11) — намерение объявляется ОДИН раз.

Прежняя редакция проверяла цикл подписки по процессам и переподписку по
``supervisor.event="recovered"``. Этой логики больше нет: её забрал брокер на
оркестраторе — вместе с резидуалом F4, из-за которого ручной рестарт и hot-swap
оставляли новую инкарнацию без хвоста (``recovered`` они не публикуют).

Что проверяется теперь: один выстрел, правильный адресат, и что GUI больше НЕ
разбирает состав системы.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTailActivator
from multiprocess_prototype.frontend.widgets.tabs.observability.tail_activator import (
    DEFAULT_TAIL_LEVEL,
)

SUBSCRIBE_ALL = "observability.tail.subscribe_all"


class RecordingSend:
    """Мок send_command: копит (target, command, args)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, target, command, args):
        self.calls.append((target, command, args))


def _delta(path, value=None):
    return {"data_type": "state_delta", "path": path, "value": value}


def test_announces_intent_once_to_the_broker():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("processes.cam.state.fps", 30))

    assert send.calls == [("ProcessManager", SUBSCRIBE_ALL, {"subscriber": "gui", "level": DEFAULT_TAIL_LEVEL})]


def test_further_deltas_do_not_produce_more_commands():
    """Один выстрел, а не цикл: дельт ``processes.*`` идут сотни в секунду."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    for path in (
        "processes.cam.state.fps",
        "processes.preprocessor.state.fps",
        "processes.stitcher.workers.w1.status",
        "processes.cam.supervisor.event",
    ):
        act.on_state_delta(_delta(path, 1))

    assert len(send.calls) == 1


def test_gui_does_not_name_a_single_process():
    """Состав системы — забота брокера; в конверте GUI нет ни одного имени процесса."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("processes.cam.state.fps", 30))

    target, _command, args = send.calls[0]
    assert target == "ProcessManager"
    assert set(args) == {"subscriber", "level"}, f"в конверте появилось лишнее знание о системе: {args}"
    assert args["subscriber"] == "gui"


def test_waits_for_the_first_process_delta():
    """Дельта ``processes.*`` — первое доказательство, что оркестратор отвечает;
    команда, посланная раньше, ушла бы в пустоту молча."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("system.chain_fps", 30))
    act.on_state_delta({"data_type": "gui_local_metric", "path": "processes.cam.x", "value": 1})
    act.on_state_delta({"data_type": "observability_record", "records": []})

    assert send.calls == []
    assert act.announced is False


class _RecordingLog:
    """Журнал вместо реального логгера: копит (уровень, отформатированное сообщение)."""

    def __init__(self) -> None:
        self.lines: list[tuple] = []

    def warning(self, msg, *args):
        self.lines.append(("WARNING", msg % args if args else msg))

    def error(self, msg, *args):
        self.lines.append(("ERROR", msg % args if args else msg))


def test_transport_failure_is_retried_and_never_silent():
    """Находка 2 ревью 5.11: раньше пометка «объявлено» ставилась ДО отправки, а
    исключение уходило в `except: pass` — один сбой оставлял GUI без хвоста
    навсегда и молча. Теперь отказ громкий и повторяется до предела."""
    calls = {"n": 0}
    log = _RecordingLog()

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("router down")

    act = ObservabilityTailActivator(boom, "gui", log=log)

    for i in range(10):
        act.on_state_delta(_delta("processes.cam.state.fps", i))  # не должно бросить

    assert calls["n"] == 3, "повтор либо не случился, либо не ограничен"
    assert act.announced is False, "провалившаяся отправка не имеет права считаться объявлением"
    assert len(log.lines) == 3
    # Последняя попытка называет последствие, а не только факт сбоя.
    assert log.lines[-1][0] == "ERROR"
    assert "живого хвоста" in log.lines[-1][1]


def test_a_retry_after_a_hiccup_succeeds_and_stops():
    """Транспорт моргнул на первой дельте — вторая доносит намерение."""
    calls: list = []
    state = {"fail": True}

    def flaky(target, command, args):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("router down")
        calls.append((target, command, args))

    act = ObservabilityTailActivator(flaky, "gui", log=_RecordingLog())

    act.on_state_delta(_delta("processes.cam.state.fps", 1))
    act.on_state_delta(_delta("processes.cam.state.fps", 2))
    act.on_state_delta(_delta("processes.cam.state.fps", 3))

    assert calls == [("ProcessManager", SUBSCRIBE_ALL, {"subscriber": "gui", "level": DEFAULT_TAIL_LEVEL})]
    assert act.announced is True and act.attempts == 2


class TestGuiNamesTheLevel:
    """Н-2: панель наблюдаемости была ERROR-only ПО ПОСТРОЕНИЮ.

    Конверт GUI не нёс ключа ``level``, сервер подставлял свой дефолт ``ERROR`` —
    и на здоровом стенде панель пуста, а пустота неотличима от «всё хорошо».
    Починка хвоста оркестратора (1.1) этот путь не лечила: дефект жил у
    потребителя, ровно как «дефект на одном пути из трёх».

    Проверяется не только конверт (это имя ключа), но и то, что ключ переживает
    ГРАНИЦУ — реальную схему команды с ``extra='forbid'``. Прецедент записан в
    ``test_observability_tail_delivery``: тест с самодельным дублем был зелёным
    именно потому, что жил НИЖЕ границы, где контракт ключ запрещал.
    """

    @staticmethod
    def _envelope(level=..., gui_name: str = "gui") -> dict:
        send = RecordingSend()
        kwargs = {} if level is ... else {"level": level}
        act = ObservabilityTailActivator(send, gui_name, **kwargs)
        act.on_state_delta(_delta("processes.cam.state.fps", 30))
        return send.calls[0][2]

    def test_default_envelope_names_warning(self):
        """Р-1а: порог назван явно и совпадает с ``watch_like_gui`` драйвера."""
        assert self._envelope()["level"] == "WARNING", "GUI снова не называет порог — панель вернулась к ERROR-only"

    def test_the_level_survives_the_command_contract(self):
        """Граница: схема команды объявляет ``level``, значит ключ доедет до хендлера.

        ``extra='forbid'`` делает эту проверку двусторонней: не объяви контракт
        поле — и тест упадёт на валидации, а не «просто не увидит» потери.
        """
        from multiprocess_framework.modules.process_module.commands.command_contracts import (
            BUILTIN_COMMAND_CONTRACTS,
        )

        schema = BUILTIN_COMMAND_CONTRACTS[SUBSCRIBE_ALL]
        cleaned = schema(**self._envelope()).model_dump(exclude_none=True)

        assert cleaned == {"subscriber": "gui", "level": "WARNING"}, (
            f"порог не пережил границу контракта команды: {cleaned}"
        )

    def test_a_custom_level_reaches_the_envelope(self):
        """Ручка есть уже сегодня (Р-1: «ручка в UI — потом»), и она работает."""
        assert self._envelope(level="DEBUG")["level"] == "DEBUG"

    def test_explicit_none_means_process_default_not_a_second_error_constant(self):
        """``None`` — «не называть»: константу дефолта знает только процесс.

        Проверяется НЕ значение ``None`` в конверте (это тавтология), а его
        смысл на настоящем брокере: намерение с ``level=None`` разворачивается
        в подписку БЕЗ ключа, то есть решение о пороге остаётся у процесса.
        Подставь GUI здесь свой ``"ERROR"`` — и совпадение констант замаскировало
        бы вторую позицию дефолта до первого её изменения.
        """
        from multiprocess_framework.modules.process_manager_module.process.observability_broker import (
            ObservabilitySubscriptionBroker,
        )

        fanned: list[dict] = []
        broker = ObservabilitySubscriptionBroker(
            broadcast=lambda _command, data: (fanned.append(dict(data)), 1)[1],
            send_to=lambda *_a: True,
        )

        broker.subscribe_all(**self._envelope(level=None))

        assert fanned == [{"subscriber": "gui"}], f"«не назван» превратился в конкретный порог по дороге: {fanned}"

    def test_the_named_level_is_the_one_the_broker_fans_out(self):
        """Имя ключа GUI = имя ключа, которое читает брокер.

        Дубль на своём же словаре этого не доказывает: переименуй поле в брокере —
        и конверт-тесты остались бы зелёными, а хвост молчал бы снова. Здесь
        конверт GUI подаётся в НАСТОЯЩИЙ брокер фреймворка.
        """
        from multiprocess_framework.modules.process_manager_module.process.observability_broker import (
            ObservabilitySubscriptionBroker,
        )

        fanned: list[dict] = []
        broker = ObservabilitySubscriptionBroker(
            broadcast=lambda _command, data: (fanned.append(dict(data)), 1)[1],
            send_to=lambda *_a: True,
        )

        broker.subscribe_all(**self._envelope())

        assert fanned == [{"subscriber": "gui", "level": "WARNING"}], (
            f"порог GUI не доехал до конверта процессам: {fanned}"
        )


class TestPanelStopsBeingErrorOnly:
    """Сквозная пара на настоящих объектах: WARNING-запись доезжает, а раньше — нет.

    Конверт и контракт выше судят ключ. Гарантия же — доставленная запись, и
    только она отличает «панель жива» от «панель пуста по построению». Харнес —
    тот же, что у Ф6.х.5: настоящие ``ProcessModule`` и ``LoggerManager``,
    фейковый только router (граница процесса).
    """

    @staticmethod
    def _process(tmp_path):
        from unittest.mock import Mock

        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        class _CapturingRouter:
            def __init__(self) -> None:
                self.pushed: list[dict] = []

            def send_async(self, message: dict, priority: str = "normal") -> None:
                self.pushed.append(message)

        logger = LoggerManager(
            manager_name="GuiTailProbe",
            config={
                "app_name": "gui_tail",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
                "scopes": {
                    "SYSTEM": {"channels": ["a"]},
                    "BUSINESS": {"channels": ["a"]},
                    "DEBUG": {"channels": ["a"]},
                },
            },
        )
        logger.initialize()
        process = ProcessModule("camera_0")
        router = _CapturingRouter()
        process.router_manager = router
        process.logger_manager = logger
        process.error_manager = None
        process._observability_hub = Mock()
        return process, router, logger

    @staticmethod
    def _pushes(router) -> list:
        return [m for m in router.pushed if m.get("command") == "observability.record"]

    def test_warning_record_reaches_the_panel_with_the_gui_envelope(self, tmp_path):
        process, router, logger = self._process(tmp_path)
        envelope = TestGuiNamesTheLevel._envelope()
        try:
            res = process.subscribe_observability_tail(envelope["subscriber"], envelope["level"])
            assert res["success"] is True, res

            logger.warning("камера перегрелась", module="capture")

            assert self._pushes(router), "WARNING не доехал до панели — Н-2 жив"
            assert self._pushes(router)[0]["targets"] == ["gui"]
        finally:
            process.unsubscribe_observability_tail(None)
            logger.shutdown()

    def test_the_old_envelope_without_a_level_leaves_the_panel_error_only(self, tmp_path):
        """Вторая половина пары — воспроизведение дефекта до правки.

        Без неё «WARNING доехал» доказывал бы и порог «пропускать всё».
        """
        process, router, logger = self._process(tmp_path)
        try:
            res = process.subscribe_observability_tail("gui")  # конверт до задачи 1.2
            assert res["min_level"] == "ERROR"

            logger.warning("камера перегрелась", module="capture")
            assert self._pushes(router) == [], "дефолтный порог перестал отсекать WARNING"

            logger.error("камера отвалилась", module="capture")
            assert self._pushes(router), "ERROR обязан проходить и на дефолтном пороге"
        finally:
            process.unsubscribe_observability_tail(None)
            logger.shutdown()
