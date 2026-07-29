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
        assert data == {"subscriber": "gui"}

    def test_subscribe_all_also_wires_orchestrator_own_tail(self):
        """«Хочу всё» включает оркестратор — он такой же источник записей."""
        t = _Transport()
        own: list[str] = []
        b = _broker(t, subscribe_self=lambda s: own.append(s) or {"success": True, "process": "ProcessManager"})

        res = b.subscribe_all("gui")

        assert own == ["gui"]
        assert res["orchestrator"] == {"success": True, "process": "ProcessManager"}

    def test_orchestrator_without_hub_answers_honestly_and_does_not_break_fan_out(self):
        """Процесс без hub'а отказывает — раздача детям от этого не страдает."""
        t = _Transport(reached=4)
        b = _broker(t, subscribe_self=lambda s: {"success": False, "reason": "observability hub не активен"})

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
        assert sent[0]["data"] == {"subscriber": "gui"}
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
        assert sent[0]["data"] == {"subscriber": "gui"}

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
        assert resubs[0]["target"] == "camera_0" and resubs[0]["data"] == {"subscriber": "gui"}

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
