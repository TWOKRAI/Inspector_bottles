# -*- coding: utf-8 -*-
"""Брокер подписки на наблюдаемость (Task 5.11) — механизм и его проводка.

Тесты написаны от acceptance спеки 5.11, ДО реализации потребителей: подписчик
говорит «хочу всё» один раз, а оркестратор разворачивает намерение и доигрывает
его каждой свежей инкарнации.

Три группы:
  * ``TestBrokerMechanics`` — сам брокер в изоляции (три callable снаружи);
  * ``TestBrokerWiredIntoPM`` — проводка в живом PM (реальные объекты, а не
    фейк-гарнесс: иначе переименование продового атрибута оставило бы всё
    зелёным);
  * ``TestNoWaiting`` — отсутствие ожидания ответа ребёнка; блокирующий вызов
    гоняется в daemon-потоке с дедлайном join, чтобы регресс падал, а не висел.
"""

from __future__ import annotations

import threading
import time

import pytest

from ..process.observability_broker import (
    SUBSCRIBE_COMMAND,
    UNSUBSCRIBE_COMMAND,
    ObservabilitySubscriptionBroker,
)
from .conftest import MockProcess, make_pm


class _Transport:
    """Запись всех отправок брокера: (kind, target, command, data)."""

    def __init__(self, *, reached: int = 3, delivered: bool = True) -> None:
        self.sent: list[tuple] = []
        self._reached = reached
        self._delivered = delivered

    def broadcast(self, command: str, data: dict) -> int:
        self.sent.append(("broadcast", None, command, dict(data)))
        return self._reached

    def send_to(self, target: str, command: str, data: dict) -> bool:
        self.sent.append(("addressed", target, command, dict(data)))
        return self._delivered

    def commands(self) -> set:
        return {row[2] for row in self.sent}


class _OwnTailDouble:
    """Дубль «своего хвоста» оркестратора: пишет РОВНО то, чем его позвали.

    Подписка объявлена копией production-формы
    ``ProcessModule.subscribe_observability_tail(subscriber, level=None)``;
    снятие принимает ``*args/**kwargs`` НАМЕРЕННО — так лишний аргумент виден
    счётом, а не проглатывается дефолтом (сигнатура с ``level=None`` у снятия
    сделала бы инъекцию «шлём порог и туда» структурно невидимой).
    Сверка с оригиналом — ``test_the_subscribe_self_double_matches_production``.
    """

    def __init__(self, answer: dict | None = None) -> None:
        self.subscribes: list[tuple] = []
        self.unsubscribes: list[tuple] = []
        self._answer = answer or {"success": True, "process": "ProcessManager"}

    def subscribe(self, subscriber: str, level=None, *, wholesale: bool = False) -> dict:
        # Задача 5.6: дубль принимает третий аргумент и ЗАПОМИНАЕТ его:
        # без запоминания он бы терпел любое значение, включая неверное.
        self.subscribes.append((subscriber, level, wholesale))
        return dict(self._answer)

    def unsubscribe(self, *args, **kwargs) -> dict:
        self.unsubscribes.append((args, kwargs))
        return {"success": True}


def _broker(transport: _Transport, **kw) -> ObservabilitySubscriptionBroker:
    return ObservabilitySubscriptionBroker(
        broadcast=transport.broadcast,
        send_to=transport.send_to,
        **kw,
    )


class TestBrokerMechanics:
    """Один вызов вместо цикла по процессам + честный реестр намерений."""

    def test_subscribe_all_is_one_fan_out_not_a_loop_over_processes(self):
        """Acceptance: один вызов → ОДНА отправка, независимо от числа процессов."""
        t = _Transport(reached=7)
        res = _broker(t).subscribe_all("gui")

        assert res["success"] is True
        assert res["reached"] == 7
        assert len(t.sent) == 1
        kind, target, command, data = t.sent[0]
        assert (kind, target, command) == ("broadcast", None, SUBSCRIBE_COMMAND)
        assert data == {"subscriber": "gui", "scope": "all"}

    def test_subscribe_all_also_wires_orchestrator_own_tail(self):
        """«Хочу всё» включает оркестратор — он такой же источник записей."""
        t = _Transport()
        own: list[str] = []
        b = _broker(
            t,
            subscribe_self=lambda s, level=None, wholesale=False: (
                own.append(s) or {"success": True, "process": "ProcessManager"}
            ),
        )

        res = b.subscribe_all("gui")

        assert own == ["gui"]
        assert res["orchestrator"] == {"success": True, "process": "ProcessManager"}

    def test_orchestrator_without_hub_answers_honestly_and_does_not_break_fan_out(self):
        """Процесс без hub'а отказывает — раздача детям от этого не страдает."""
        t = _Transport(reached=4)
        b = _broker(
            t,
            subscribe_self=lambda s, level=None, wholesale=False: {
                "success": False,
                "reason": "observability hub не активен",
            },
        )

        res = b.subscribe_all("gui")

        assert res["reached"] == 4
        assert res["orchestrator"]["success"] is False

    def test_repeated_subscribe_keeps_one_intent_but_repeats_delivery(self):
        """Идемпотентность по подписчику; повтор раздачи — единственный способ
        подобрать процесс, до которого прошлая не доехала."""
        t = _Transport()
        b = _broker(t)

        b.subscribe_all("gui")
        b.subscribe_all("gui")

        assert b.subscriber_names() == ["gui"]
        assert len(t.sent) == 2

    def test_empty_subscriber_is_refused_and_records_nothing(self):
        t = _Transport()
        b = _broker(t)

        res = b.subscribe_all("   ")

        assert res["success"] is False and "subscriber" in res["reason"]
        assert b.subscriber_names() == [] and t.sent == []

    def test_unsubscribe_all_drops_intent_and_says_whether_it_held_one(self):
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")

        res = b.unsubscribe_all("gui")
        again = b.unsubscribe_all("gui")

        assert res["held"] is True and again["held"] is False
        assert b.subscriber_names() == []
        assert t.sent[-1][2] == UNSUBSCRIBE_COMMAND

    def test_unsubscribe_all_without_address_is_refused_not_a_purge(self):
        """Пустой адрес у процесса означает «снять всех» — здесь это снесло бы
        хвост соседнего потребителя."""
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")
        b.subscribe_all("backend_ctl")

        res = b.unsubscribe_all("")

        assert res["success"] is False
        assert b.subscriber_names() == ["backend_ctl", "gui"]

    def test_two_consumers_coexist_and_each_gets_its_own_envelope(self):
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")
        b.subscribe_all("backend_ctl")
        t.sent.clear()

        b.replay(target="camera_0", reason="instance.started")

        assert sorted(row[3]["subscriber"] for row in t.sent) == ["backend_ctl", "gui"]
        assert {row[1] for row in t.sent} == {"camera_0"}

    def test_replay_without_intents_sends_nothing(self):
        """Пустой реестр не платит ни одной отправкой на каждом старте процесса."""
        t = _Transport()
        assert _broker(t).replay(target="camera_0") == {"subscribers": [], "reached": 0}
        assert t.sent == []

    def test_forget_subscriber_drops_intent_of_a_process_taken_off_topology(self):
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")

        assert b.forget_subscriber("gui") is True
        assert b.forget_subscriber("gui") is False
        assert b.subscriber_names() == []

    def test_forget_subscriber_fans_out_unsubscribe_to_children(self):
        """B-5-1 (вторая половина): снятое намерение снимает и форвардеры на детях.

        До фикса ``forget_subscriber`` чистил только реестр PM, а форвардеры на
        детях оставались сиротами — вечно пушили записи мёртвому адресу (relay-шум
        на хаб). ``unsubscribe_all`` рассылку делает; реактивное снятие обязано
        так же.
        """
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")
        t.sent.clear()  # отсечь раздачу подписки — интересует только снятие

        assert b.forget_subscriber("gui") is True

        assert t.sent, "forget_subscriber промолчал детям — форвардер остался сиротой"
        assert all(row[2] == UNSUBSCRIBE_COMMAND for row in t.sent), f"снятие не unsubscribe: {t.sent}"
        assert any(row[0] == "broadcast" and row[3]["subscriber"] == "gui" for row in t.sent), (
            f"unsubscribe не разослан детям веером для 'gui': {t.sent}"
        )

    def test_forget_subscriber_of_unknown_name_stays_silent(self):
        """Не держали намерение — нечего и снимать: детей не тревожим."""
        t = _Transport()
        b = _broker(t)
        assert b.forget_subscriber("никогда") is False
        assert t.sent == [], f"снятие несуществующего намерения разослано детям: {t.sent}"

    def test_forget_session_fans_out_unsubscribe_for_each_doomed_address(self):
        """5.11-R1 + B-5-1: закрытие сессии снимает форвардеры её адресов на детях."""
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("backend_ctl.aaa")
        b.subscribe_all("backend_ctl.bbb")
        b.subscribe_all("gui")
        t.sent.clear()

        doomed = b.forget_session("aaa")

        assert doomed == ["backend_ctl.aaa"]
        unsub_targets = sorted(row[3]["subscriber"] for row in t.sent if row[2] == UNSUBSCRIBE_COMMAND)
        assert unsub_targets == ["backend_ctl.aaa"], f"снят не тот адрес (или не снят вовсе): {t.sent}"

    def test_forget_session_without_matches_stays_silent(self):
        """Ни одного адреса сессии — ни одной отправки детям (пустой doomed)."""
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")
        t.sent.clear()
        assert b.forget_session("никогда") == []
        assert t.sent == [], f"снятие пустой сессии разослано детям: {t.sent}"

    def test_transport_failure_is_reported_not_swallowed_and_not_raised(self):
        """Провал раздачи — обслуживание, а не lifecycle: не роняет, но и не молчит."""
        errors: list[str] = []

        def _boom(command, data):
            raise RuntimeError("очередь закрыта")

        b = ObservabilitySubscriptionBroker(
            broadcast=_boom,
            send_to=lambda *a: True,
            log_error=errors.append,
        )
        res = b.subscribe_all("gui")

        assert res["success"] is True and res["reached"] == 0
        assert "очередь закрыта" in res["error"]
        assert errors and "очередь закрыта" in errors[0]
        # Намерение записано ДО раздачи — иначе сбой транспорта тихо отменял бы
        # подписку, и следующая инкарнация тоже осталась бы без хвоста.
        assert b.subscriber_names() == ["gui"]

    def test_broker_only_ever_sends_subscribe_and_unsubscribe(self):
        """PM — брокер, не транзит: через него не идёт ни одна запись."""
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")
        b.replay(target="camera_0")
        b.replay()
        b.unsubscribe_all("gui")

        assert t.commands() == {SUBSCRIBE_COMMAND, UNSUBSCRIBE_COMMAND}

    def test_snapshot_tells_who_is_subscribed_and_whether_delivery_reached(self):
        """Readback: «хвоста нет» — это снятое намерение или не доехавшая раздача."""
        t = _Transport(reached=5)
        b = _broker(t)
        b.subscribe_all("gui")

        snap = b.snapshot()

        assert snap["count"] == 1
        entry = snap["subscribers"][0]
        assert entry["subscriber"] == "gui"
        assert entry["last_reached"] == 5
        assert entry["last_reason"] == "command"
        assert entry["replays"] == 1

    def test_snapshot_is_a_copy_not_a_live_handle(self):
        t = _Transport()
        b = _broker(t)
        b.subscribe_all("gui")

        b.snapshot()["subscribers"][0]["subscriber"] = "подменено"

        assert b.snapshot()["subscribers"][0]["subscriber"] == "gui"


class TestBrokerWiredIntoPM:
    """Проводка в ЖИВОМ PM: реальные методы, а не фейк-гарнесс."""

    @staticmethod
    def _pm_with_comm(configs=None):
        pm = make_pm(configs or {"camera_0": {"class": "x.Y"}})
        sent: list[dict] = []

        class _Comm:
            def broadcast(self, msg, exclude_self=True):
                sent.append({"kind": "broadcast", **msg})
                return 2

            def send_to_process(self, target, msg):
                sent.append({"kind": "addressed", "target": target, **msg})
                return True

        pm.communication = _Comm()
        return pm, sent

    def test_command_subscribe_all_reaches_children_through_pm_broadcast(self):
        pm, sent = self._pm_with_comm()

        res = pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})

        assert res["success"] is True and res["reached"] == 2
        assert [m["command"] for m in sent] == [SUBSCRIBE_COMMAND]
        assert sent[0]["data"] == {"subscriber": "gui", "scope": "all"}
        assert sent[0]["queue_type"] == "system"

    def test_command_unsubscribe_all_requires_an_address(self):
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()

        res = pm._cmd_observability_tail_unsubscribe_all({})

        assert res["success"] is False
        assert sent == []

    def test_fresh_incarnation_is_resubscribed_without_the_subscriber(self):
        """Acceptance: новый процесс подхватывается без участия подписчика."""
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()

        pm._mark_instance_started("camera_1")

        assert len(sent) == 1
        assert sent[0]["kind"] == "addressed" and sent[0]["target"] == "camera_1"
        assert sent[0]["command"] == SUBSCRIBE_COMMAND
        assert sent[0]["data"] == {"subscriber": "gui", "scope": "all"}

    def test_no_intent_no_traffic_on_process_start(self):
        pm, sent = self._pm_with_comm()

        pm._mark_instance_started("camera_1")

        assert sent == []

    def test_manual_restart_resubscribes_the_new_instance(self):
        """Именно этот путь GUI-триггер ``recovered`` не покрывал."""
        pm, sent = self._pm_with_comm({"camera_0": {"class": "x.Y", "priority": "normal"}})
        pm._process_registry._next_process_factory = {"camera_0": MockProcess("camera_0", alive=False)}
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()

        assert pm.restart_process("camera_0") is True

        resubs = [m for m in sent if m["command"] == SUBSCRIBE_COMMAND]
        assert len(resubs) == 1
        assert resubs[0]["target"] == "camera_0" and resubs[0]["data"] == {"subscriber": "gui", "scope": "all"}

    def test_start_process_path_also_resubscribes(self):
        pm, sent = self._pm_with_comm({"camera_0": {"class": "x.Y"}})
        pm._process_registry._processes["camera_0"] = MockProcess("camera_0", alive=False)
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()

        assert pm.start_process("camera_0") is True

        assert [m["target"] for m in sent if m["command"] == SUBSCRIBE_COMMAND] == ["camera_0"]

    def test_subscriber_taken_off_topology_is_forgotten(self):
        """Единственный сигнал о смерти подписчика, который есть по факту."""
        pm, sent = self._pm_with_comm({"gui": {"class": "x.Gui"}})
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        pm._cleanup_process_resources("gui")
        sent.clear()

        pm._mark_instance_started("camera_1")

        assert sent == []
        assert pm._observability_broker_obj().subscriber_names() == []

    def test_introspect_extra_exposes_the_broker(self):
        pm, _sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})

        extra = pm.observability_introspect_extra()

        assert extra["broker"]["count"] == 1
        assert extra["broker"]["subscribers"][0]["subscriber"] == "gui"

    def test_broker_survives_broken_transport_without_killing_the_start(self):
        pm, _sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})

        class _Dead:
            def broadcast(self, msg, exclude_self=True):
                raise RuntimeError("comm умер")

            def send_to_process(self, target, msg):
                raise RuntimeError("comm умер")

        pm.communication = _Dead()
        pm._mark_instance_started("camera_1")  # старт не имеет права упасть

        assert pm._observability_broker_obj().subscriber_names() == ["gui"]


class TestReplayWaitsForRealReadiness:
    """Раздача не приезжает раньше, чем инкарнация умеет принять команду.

    **Дефект найден живым прогоном 2026-07-29 (switch + ручной рестарт), не тестами
    — и это ровно тот класс, ради которого живой прогон и держат.** Раздача уходила
    сразу после ``process.start()``: message-loop ребёнка уже крутится (шаг 7
    ``initialize``), а команды регистрируются позже, в ``run()``. Живой лог ребёнка:
    ``No handler for key 'observability.tail.subscribe'`` — команда прочитана и
    выброшена, отправитель (fire-and-forget) не узнал об этом никогда, хвост
    подписчика пропал навсегда. У фейкового ребёнка хендлер есть всегда, поэтому
    все 6000+ зелёных тестов дефект не видели.
    """

    @staticmethod
    def _pm_with_comm(configs=None):
        return TestBrokerWiredIntoPM._pm_with_comm(configs)

    def _wait_for(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def test_replay_held_back_until_the_instance_declares_readiness(self):
        """Пара: пока событие не взведено — тишина; взвели — раздача пришла."""
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()
        event = threading.Event()
        pm._process_registry._ready_events["camera_1"] = event

        pm._mark_instance_started("camera_1")

        # До готовности — НИ ОДНОЙ отправки (иначе она уедет в окно «нет обработчика»).
        time.sleep(0.3)
        assert sent == [], f"раздача ушла до объявления готовности: {sent}"

        event.set()

        assert self._wait_for(lambda: len(sent) == 1), f"раздача не пришла после готовности: {sent}"
        assert sent[0]["target"] == "camera_1" and sent[0]["command"] == SUBSCRIBE_COMMAND

    def test_already_ready_instance_is_served_synchronously(self):
        """Событие уже взведено → раздача идёт немедленно, без отложенного потока."""
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()
        event = threading.Event()
        event.set()
        pm._process_registry._ready_events["camera_1"] = event

        pm._mark_instance_started("camera_1")

        assert len(sent) == 1 and sent[0]["target"] == "camera_1"

    def test_no_ready_signal_at_all_keeps_the_old_behaviour(self):
        """Реестр без ready_event (SRM-mode, старый bundle) → раздача сразу.

        Хуже, чем с сигналом, но лучше, чем не раздать вовсе: молчание оставило бы
        такого потребителя без хвоста навсегда.
        """
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()

        pm._mark_instance_started("camera_1")  # _ready_events пуст → None

        assert len(sent) == 1 and sent[0]["target"] == "camera_1"

    def test_deadline_expiry_still_delivers_and_says_so(self):
        """Не объявился за дедлайн → раздаём всё равно, но ГРОМКО.

        Молчаливый отказ здесь неотличим от «подписчик не подписывался».
        """
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()
        warnings: list = []
        pm._log_warning = lambda msg, *a, **k: warnings.append(str(msg))
        pm.update_config("observability_replay_ready_timeout_s", 0.2)
        pm._process_registry._ready_events["camera_1"] = threading.Event()  # НЕ взводим

        pm._mark_instance_started("camera_1")

        assert self._wait_for(lambda: len(sent) == 1, timeout=3.0), "по дедлайну раздача не состоялась"
        assert any("не объявил готовность" in w for w in warnings), f"дедлайн прошёл молча: {warnings}"

    def test_no_subscribers_no_thread_and_no_send(self):
        """Намерений нет → ни отправки, ни ожидания: цена не платится на КАЖДОМ старте."""
        pm, sent = self._pm_with_comm()
        pm._process_registry._ready_events["camera_1"] = threading.Event()  # НЕ взведено
        before = threading.active_count()

        pm._mark_instance_started("camera_1")

        assert sent == []
        assert threading.active_count() == before, "заведён поток ожидания при отсутствии подписчиков"

    def test_seam_does_not_block_the_message_loop(self):
        """Шов зовут из message_processor — ждать готовности синхронно нельзя.

        Вызов гоняется в daemon-потоке с дедлайном join: регресс (синхронное
        ожидание) ПАДАЕТ, а не вешает суиту.
        """
        pm, _sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        pm.update_config("observability_replay_ready_timeout_s", 30.0)
        pm._process_registry._ready_events["camera_1"] = threading.Event()  # НЕ взводим

        done = threading.Event()
        t = threading.Thread(target=lambda: (pm._mark_instance_started("camera_1"), done.set()), daemon=True)
        t.start()

        assert done.wait(2.0), "шов заблокировался в ожидании готовности инкарнации"


class TestNoWaiting:
    """Дедлок-путь автоподписки: PM не ждёт ответа ребёнка ни в одном хендлере."""

    @staticmethod
    def _run_with_deadline(fn, deadline: float = 5.0):
        """Прогнать в daemon-потоке с дедлайном: регресс ПАДАЕТ, а не висит."""
        done = threading.Event()
        box: dict = {}

        def _target():
            try:
                box["result"] = fn()
            finally:
                done.set()

        threading.Thread(target=_target, daemon=True).start()
        assert done.wait(deadline), "раздача подписки не вернулась — появилось ожидание ответа"
        return box.get("result")

    def test_subscribe_all_returns_although_no_child_ever_answers(self):
        """Фейки не отвечают вообще — и это не мешает команде вернуться."""
        t = _Transport()
        b = _broker(t)

        res = self._run_with_deadline(lambda: b.subscribe_all("gui"))

        assert res["success"] is True

    def test_slow_transport_does_not_turn_into_an_unbounded_wait(self):
        slow = _Transport()
        original = slow.broadcast

        def _slow(command, data):
            time.sleep(0.2)
            return original(command, data)

        b = ObservabilitySubscriptionBroker(broadcast=_slow, send_to=slow.send_to)
        started = time.monotonic()

        self._run_with_deadline(lambda: b.subscribe_all("gui"), deadline=3.0)

        assert time.monotonic() - started < 3.0

    def test_concurrent_replay_and_subscribe_do_not_deadlock_or_lose_intents(self):
        """Реестр пишут хендлеры команд, читает шов старта инкарнации."""
        t = _Transport()
        b = _broker(t)
        stop = threading.Event()

        def _churn():
            i = 0
            while not stop.is_set():
                b.subscribe_all(f"sub_{i % 3}")
                b.unsubscribe_all(f"sub_{(i + 1) % 3}")
                i += 1

        def _replays():
            while not stop.is_set():
                b.replay(target="camera_0")

        threads = [threading.Thread(target=_churn, daemon=True), threading.Thread(target=_replays, daemon=True)]
        for th in threads:
            th.start()
        time.sleep(0.3)
        stop.set()
        for th in threads:
            th.join(timeout=3.0)
            assert not th.is_alive(), "поток не завершился — реестр брокера встал"

        assert set(b.subscriber_names()) <= {"sub_0", "sub_1", "sub_2"}


@pytest.mark.parametrize("command", [SUBSCRIBE_COMMAND, UNSUBSCRIBE_COMMAND])
def test_broker_commands_are_the_per_process_ones(command):
    """Брокер не заводит третьего имени: он разворачивает намерение в те самые
    команды, которыми подписка жила до него."""
    assert command in ("observability.tail.subscribe", "observability.tail.unsubscribe")


class TestOrchestratorTailDeliversAtTheAskedLevel:
    """Н-1 сквозь настоящие объекты: INFO-запись САМОГО оркестратора доезжает до подписчика.

    Тесты выше судят конверт («чем позвали свой хвост»). Этого мало: конверт —
    имя параметра, а гарантия — доставленная запись. Здесь харнес такой же, как
    у Ф6.х.5 (``process_module/tests/test_observability_tail_delivery.py``):
    настоящий ``LoggerManager``, настоящая проводка
    ``subscribe_observability_tail`` → ``wire_observability_forward`` →
    ``RecordForwardChannel``; фейковый только router — это граница процесса.
    Вход — реальная команда PM, то есть цепочка целиком: команда → брокер →
    свой хвост → tap → пуш.

    Ровно это и мерила приёмка F1 живьём: ``watch_like_gui(INFO)`` → 163 события
    от семи детей и **0 от ProcessManager**.
    """

    @staticmethod
    def _pm_with_real_logger(tmp_path):
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        pm, sent = TestBrokerWiredIntoPM._pm_with_comm()

        class _CapturingRouter:
            def __init__(self) -> None:
                self.pushed: list[dict] = []

            def send_async(self, message: dict, priority: str = "normal") -> None:
                self.pushed.append(message)

        router = _CapturingRouter()
        logger = LoggerManager(
            manager_name="PMTailProbe",
            config={
                "app_name": "pm_tail",
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
        pm.router_manager = router
        pm.logger_manager = logger
        pm.error_manager = None
        pm._observability_forwarders = {}
        # Хаб нужен только как признак «подписка возможна»: batch-половина
        # структурно пуста (см. шапку wire_observability_forward), проверяется
        # tap-путь — тот самый, которым едут записи оркестратора.
        pm._observability_hub = object()
        return pm, router, logger, sent

    @staticmethod
    def _tail_pushes(router) -> list:
        return [m for m in router.pushed if m.get("command") == "observability.record"]

    def test_info_record_of_the_orchestrator_reaches_the_subscriber(self, tmp_path):
        """Заявленное свойство 1.1: подписка «хочу всё с INFO» открывает и хвост ПМ."""
        pm, router, logger, _sent = self._pm_with_real_logger(tmp_path)
        try:
            res = pm._cmd_observability_tail_subscribe_all({"subscriber": "gui", "level": "INFO"})
            assert res["orchestrator"]["success"] is True, res["orchestrator"]
            assert res["orchestrator"]["min_level"] == "INFO", (
                f"свой хвост заведён не на запрошенном пороге: {res['orchestrator']}"
            )

            logger.info("оркестратор жив и говорит на INFO", module="observability")

            pushes = self._tail_pushes(router)
            assert pushes, "INFO-запись оркестратора не доехала до подписчика — Н-1 жив"
            assert pushes[0]["targets"] == ["gui"]
        finally:
            pm.unsubscribe_observability_tail(None)
            logger.shutdown()

    def test_without_a_level_the_orchestrator_tail_stays_error_only(self, tmp_path):
        """Пара к предыдущему: дефолт НЕ сдвинут — INFO отсечён, ERROR проходит.

        Без этой половины «INFO доехал» доказывал бы и порог «пропускать всё»:
        зелёным был бы и брокер, подставляющий DEBUG всем подряд.
        """
        pm, router, logger, _sent = self._pm_with_real_logger(tmp_path)
        try:
            res = pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
            assert res["orchestrator"]["min_level"] == "ERROR", f"дефолт своего хвоста сдвинулся: {res['orchestrator']}"

            logger.info("рутина", module="unit")
            assert self._tail_pushes(router) == [], "дефолтный порог перестал отсекать INFO"

            logger.error("настоящая беда", module="unit")
            assert self._tail_pushes(router), "ERROR обязан проходить и на дефолтном пороге"
        finally:
            pm.unsubscribe_observability_tail(None)
            logger.shutdown()

    def test_fresh_fan_out_replay_keeps_the_orchestrator_tail_open(self, tmp_path):
        """Второй путь раздачи на настоящих объектах: веер не гасит свой хвост.

        Веерное доигрывание переставляет форвардер заново (подписка идемпотентна
        снятием прежних tap'ов). Потеряй оно порог — ПМ замолчал бы не сразу, а
        на первом же доигрывании, то есть тем незаметнее, чем реже рестарты.
        """
        pm, router, logger, _sent = self._pm_with_real_logger(tmp_path)
        try:
            pm._cmd_observability_tail_subscribe_all({"subscriber": "gui", "level": "INFO"})
            pm._replay_observability_subscriptions("instance.started")

            logger.info("после доигрывания", module="observability")

            assert self._tail_pushes(router), "после веерного доигрывания хвост ПМ вернулся к ERROR"
        finally:
            pm.unsubscribe_observability_tail(None)
            logger.shutdown()


class TestForgetSessionOnSocketClose:
    """5.11-R1: подписчик умирает вместе со своим соединением — и брокер узнаёт об этом.

    Живой замер ревью: три цикла «connect → watch_like_gui → close» оставляли ТРИ
    мёртвых намерения, каждое развёрнуто на 8 процессов. Хуже, чем до брокера:
    реконнект берёт новый session, поэтому старый адрес не знает уже никто (явный
    ``unsubscribe_all`` снять его не может в принципе), а шов инкарнации честно
    доигрывает мёртвые намерения КАЖДОМУ свежему процессу — подписка не затухает,
    а воскресает.
    """

    @staticmethod
    def _pm_with_comm():
        return TestBrokerWiredIntoPM._pm_with_comm()

    def test_session_close_drops_exactly_that_subscriber(self):
        pm, _sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "backend_ctl.aaa111"})
        pm._cmd_observability_tail_subscribe_all({"subscriber": "backend_ctl.bbb222"})
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})

        pm._forget_observability_session("aaa111")

        names = pm._observability_broker_obj().subscriber_names()
        assert "backend_ctl.aaa111" not in names, "намерение мёртвой сессии пережило закрытие сокета"
        assert set(names) == {"backend_ctl.bbb222", "gui"}, f"снято лишнее: {names}"

    def test_reconnect_cycles_do_not_accumulate_intents(self):
        """N циклов «подписался → соединение закрылось» → ноль намерений.

        Пара к замеру ревью: было count=N, стало 0.
        """
        pm, _sent = self._pm_with_comm()
        for i in range(5):
            sid = f"sess{i}"
            pm._cmd_observability_tail_subscribe_all({"subscriber": f"backend_ctl.{sid}"})
            pm._forget_observability_session(sid)
        assert pm._observability_broker_obj().subscriber_names() == []

    def test_dead_subscriber_is_not_replayed_to_fresh_incarnations(self):
        """Главное следствие: шов инкарнации не воскрешает снятую подписку."""
        pm, sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "backend_ctl.dead01"})
        pm._forget_observability_session("dead01")
        sent.clear()

        pm._mark_instance_started("camera_1")

        assert sent == [], f"мёртвое намерение доиграно свежей инкарнации: {sent}"

    def test_unknown_session_is_a_quiet_noop(self):
        pm, _sent = self._pm_with_comm()
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        pm._forget_observability_session("никогда-не-существовала")
        assert pm._observability_broker_obj().subscriber_names() == ["gui"]

    def test_signal_never_breaks_the_channel(self):
        """Колбэк зовут из read-потока канала: упасть он права не имеет."""
        pm, _sent = self._pm_with_comm()
        broker = pm._observability_broker_obj()
        broker.forget_session = lambda _sid: (_ for _ in ()).throw(RuntimeError("boom"))
        pm._forget_observability_session("aaa")  # не должно бросить


class TestLevelIsPartOfTheIntent:
    """A1 (Б-1б): порог едет по всей цепочке и переживает переподписку.

    До A1 слова ``level`` в этом файле не было ни разу — и ровно там жил
    блокер: подписка «хочу всё с INFO» доезжала до процесса без порога,
    процесс подставлял свой ERROR, и живой хвост молчал на здоровом стенде
    (40 минут подписки → 0 событий при росте стора на 1931 строку).

    Опасность механизма, ради которой нужны эти тесты: раздачу делают ДВА
    пути — команда подписчика и шов «поднялась свежая инкарнация». Положи
    уровень только в первый — и каждый рестарт процесса молча возвращает
    подписку к дефолту, тем незаметнее, чем реже рестарты.
    """

    def test_subscribe_all_carries_the_level_into_the_fan_out(self):
        t = _Transport()
        res = _broker(t).subscribe_all("gui", level="INFO")

        assert res["level"] == "INFO"
        _kind, _target, _command, data = t.sent[0]
        assert data == {"subscriber": "gui", "level": "INFO", "scope": "all"}, (
            "порог не доехал до процесса — подписка молча вернётся к дефолту ERROR"
        )

    def test_replay_carries_the_level_from_the_intent(self):
        """Шов инкарнации: переподписка обязана нести ТОТ ЖЕ порог (инъекция и-4).

        Раздачу через ``replay`` делает не подписчик, а оркестратор, и запроса
        у него уже нет. Уровень поэтому хранится в намерении, а не передаётся
        аргументом первой раздачи.
        """
        t = _Transport()
        broker = _broker(t)
        broker.subscribe_all("gui", level="DEBUG")
        t.sent.clear()

        broker.replay(target="camera_1")

        assert t.sent, "переподписка свежей инкарнации не состоялась вовсе"
        _kind, target, command, data = t.sent[0]
        assert (target, command) == ("camera_1", SUBSCRIBE_COMMAND)
        # Задача 5.6: replay воспроизводит ОПТОВОЕ намерение брокера, а значит
        # несёт маркер тоже: без него переподписка свежей инкарнации молча
        # понижала бы порог, заданный оператором прицельно — тот же блокер Н2-1,
        # только срабатывающий при рестарте, то есть ещё незаметнее.
        assert data == {"subscriber": "gui", "level": "DEBUG", "scope": "all"}, (
            "свежая инкарнация подписана БЕЗ порога либо без маркера оптовости"
        )

    def test_level_is_visible_in_the_readback(self):
        """Механизм, о котором нельзя спросить, через час неотличим от сломанного."""
        broker = _broker(_Transport())
        broker.subscribe_all("gui", level="WARNING")

        entry = broker.snapshot()["subscribers"][0]
        assert entry["level"] == "WARNING"

    def test_resubscribe_with_another_level_updates_the_intent(self):
        """Смена порога — законная операция, а не «намерение уже есть, игнорируем»."""
        t = _Transport()
        broker = _broker(t)
        broker.subscribe_all("gui", level="ERROR")
        broker.subscribe_all("gui", level="INFO")
        t.sent.clear()

        broker.replay(target="camera_1")

        _kind, _target, _command, data = t.sent[0]
        assert data["level"] == "INFO", "переподписка несёт устаревший порог"
        assert broker.snapshot()["subscribers"][0]["level"] == "INFO"

    def test_absent_level_puts_no_key_at_all(self):
        """«Не назван» ≠ «ERROR»: константа дефолта живёт в ОДНОЙ позиции — у процесса.

        Положи брокер сюда свой ``"ERROR"`` — и смена дефолта у процесса
        доехала бы одним путём из двух, а совпадение констант замаскировало бы
        расхождение до первого изменения.
        """
        t = _Transport()
        res = _broker(t).subscribe_all("gui")

        assert res["level"] is None
        _kind, _target, _command, data = t.sent[0]
        assert "level" not in data, "брокер подставил собственный дефолт — вторая позиция той же константы"

    def test_unsubscribe_never_carries_a_level(self):
        """Снятие порогом не параметризуется: общая схема — не повод слать лишнее."""
        t = _Transport()
        broker = _broker(t)
        broker.subscribe_all("gui", level="INFO")
        t.sent.clear()

        broker.unsubscribe_all("gui")

        _kind, _target, command, data = t.sent[0]
        assert command == UNSUBSCRIBE_COMMAND
        # Задача 5.6: снятие несёт маркер ОПТОВОСТИ (иначе `unsubscribe_all` снёс бы
        # прицельную подписку — находка Н2-2), но уровня по-прежнему не несёт: его
        # у снятия нет ни в сигнатуре процесса, ни в смысле.
        assert data == {"subscriber": "gui", "scope": "all"}
        assert "level" not in data

    def test_own_tail_gets_the_same_level_as_the_children(self):
        """Н-1: свой хвост оркестратора — такой же потребитель порога, как дети.

        До правки ``_own_tail`` звал ``subscribe_self(subscriber)`` одним
        аргументом, процесс подставлял свой дефолт ``ERROR`` — и подписка
        «хочу всё с INFO» давала ProcessManager'у ERROR-only хвост. Живой замер
        приёмки F1: 163 события от семи детей и **0 от ProcessManager** при 22
        его строках в сторе за то же окно.
        """
        t = _Transport()
        own = _OwnTailDouble()
        b = _broker(t, subscribe_self=own.subscribe, unsubscribe_self=own.unsubscribe)

        b.subscribe_all("gui", level="INFO")

        assert own.subscribes == [("gui", "INFO", True)], (
            f"свой хвост подписан не тем порогом, что дети: {own.subscribes}"
        )
        # Пара: конверт детям и свой хвост несут ОДИН И ТОТ ЖЕ порог — расхождение
        # этих двух и было дефектом (A1 положила уровень только в конверт).
        _kind, _target, _command, data = t.sent[0]
        assert data["level"] == own.subscribes[0][1]

    def test_replay_fan_out_re_subscribes_own_tail_with_the_intent_level(self):
        """Второй путь раздачи (шов инкарнации веером) — тот же порог.

        Раздачу делают ДВА пути; почини один — и свой хвост молча возвращался бы
        к дефолту на каждом веерном доигрывании.
        """
        t = _Transport()
        own = _OwnTailDouble()
        b = _broker(t, subscribe_self=own.subscribe, unsubscribe_self=own.unsubscribe)
        b.subscribe_all("gui", level="DEBUG")
        own.subscribes.clear()

        b.replay()  # без target → веер + свой хвост

        assert own.subscribes == [("gui", "DEBUG", True)], (
            f"веерное доигрывание вернуло свой хвост к дефолту: {own.subscribes}"
        )

    def test_absent_level_reaches_own_tail_as_none_not_as_error(self):
        """Константа дефолта живёт в ОДНОЙ позиции — у процесса.

        Подставь брокер здесь свой ``"ERROR"`` — и смена дефолта у процесса
        доехала бы одним путём из двух, а совпадение констант замаскировало бы
        расхождение до первого изменения (та же форма, что
        ``test_absent_level_puts_no_key_at_all`` для конверта детям).
        """
        t = _Transport()
        own = _OwnTailDouble()
        b = _broker(t, subscribe_self=own.subscribe, unsubscribe_self=own.unsubscribe)

        b.subscribe_all("gui")

        assert own.subscribes == [("gui", None, True)], (
            f"брокер подставил своему хвосту собственный дефолт: {own.subscribes}"
        )

    def test_changed_level_reaches_own_tail_too(self):
        """Смена порога — законная операция и для своего хвоста."""
        t = _Transport()
        own = _OwnTailDouble()
        b = _broker(t, subscribe_self=own.subscribe, unsubscribe_self=own.unsubscribe)
        b.subscribe_all("gui", level="ERROR")
        b.subscribe_all("gui", level="INFO")

        assert own.subscribes[-1] == ("gui", "INFO", True), f"свой хвост остался на прежнем пороге: {own.subscribes}"

    def test_own_tail_unsubscribe_is_called_with_one_argument(self):
        """Снятие порогом не параметризуется — у процесса его нет в сигнатуре.

        Общая схема «свой хвост» не повод слать лишний аргумент: production-форма
        ``unsubscribe_observability_tail(subscriber=None)`` приняла бы второй
        позиционный как ... ничто — она его не объявляет, и вызов упал бы
        TypeError'ом, который ``_own_tail`` глушит в мягкий ``success=False``.
        Поэтому арность проверяется счётом, а не сигнатурой дубля с дефолтом.
        """
        t = _Transport()
        own = _OwnTailDouble()
        b = _broker(t, subscribe_self=own.subscribe, unsubscribe_self=own.unsubscribe)
        b.subscribe_all("gui", level="INFO")

        b.unsubscribe_all("gui")

        assert own.unsubscribes == [(("gui",), {})], (
            f"снятие своего хвоста позвано не одним аргументом: {own.unsubscribes}"
        )

    def test_the_subscribe_self_double_matches_production(self):
        """Дубль обязан сверяться с оригиналом, иначе он проверяет сам себя.

        ``_own_tail`` глушит исключения (свой хвост не важнее чужих) — значит
        расхождение арности стало бы мягким ``success=False``, а не падением.
        Прецедент этого класса записан в правилах проекта: приватная копия
        фикстуры разошлась с conftest молча, и девять красных жили как «не наш» долг.
        """
        import inspect

        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        sub = inspect.signature(ProcessModule.subscribe_observability_tail)
        assert list(sub.parameters) == ["self", "subscriber", "level", "wholesale"]
        assert sub.parameters["level"].default is None, (
            "production-дефолт уровня переехал — дубль _OwnTailDouble устарел"
        )
        unsub = inspect.signature(ProcessModule.unsubscribe_observability_tail)
        assert list(unsub.parameters) == ["self", "subscriber", "wholesale"], (
            "сигнатура снятия разошлась с дублём — брокер обязан нести ровно то, что процесс принимает"
        )

    def test_pm_command_seam_hands_the_level_to_the_broker(self):
        """Живой PM (реальные объекты, не фейк-гарнесс): звено 3 цепочки A1.

        Именно здесь порог терялся: ``subscribe_all(str(args.get("subscriber")))``
        читал один ключ из двух. Тест на живом PM, а не на дубле брокера —
        иначе переименование продового атрибута оставило бы всё зелёным.
        """
        pm = make_pm({"camera_0": {"class": "x.Y"}})
        sent: list[dict] = []

        class _Comm:
            def broadcast(self, msg, exclude_self=True):
                sent.append({"kind": "broadcast", **msg})
                return 2

            def send_to_process(self, target, msg):
                sent.append({"kind": "addressed", "target": target, **msg})
                return True

        pm.communication = _Comm()

        res = pm._cmd_observability_tail_subscribe_all({"subscriber": "gui", "level": "INFO"})

        assert res["success"] is True
        assert sent[0]["data"] == {"subscriber": "gui", "level": "INFO", "scope": "all"}, (
            "порог не пережил шов команды ПМ — ровно корень Б-1"
        )
