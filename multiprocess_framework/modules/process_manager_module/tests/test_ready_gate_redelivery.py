# -*- coding: utf-8 -*-
"""Readiness-гейт рассылки (резидуал 5.11-R4) — команда ждёт, пока её смогут принять.

**Откуда взялось.** Живой прогон 5.11 (2026-07-29) показал в логе свежесозданного
ребёнка ``No handler for key 'observability.tail.subscribe'``: message-loop
поднимается на шаге 7 ``initialize()``, а команды регистрируются позже, в ``run()``.
Попавшее в это окно сообщение читается и выбрасывается, а отправитель
fire-and-forget не узнаёт об этом никогда. Task 5.11 закрыла так раздачу подписок;
тот же лог показывал ``No handler`` ещё для ``routing.refresh`` и ``config.reload`` —
у них есть компенсация (epoch-сверка / чтение рецепта на boot), поэтому симптома не
видно, но механизм тот же. Резидуал R4 — про них.

Тесты авторские (hazard-класс: гонка, зазор, поток обслуживания). Независимый
``tester`` НЕ вызывался — заявляю вслух, как требует правило: контракт здесь
внутренний (шов рассылки), снаружи наблюдаем только косвенно, и tester, не видя
кода, зафиксировал бы выдуманную модель как контракт.

Всё, что может заблокироваться, гоняется в daemon-потоке с дедлайном ``join``:
регресс обязан ПАДАТЬ, а не вешать суиту.
"""

from __future__ import annotations

import threading
import time

from .conftest import MockProcess, make_pm


def _pm_with_children(*names: str):
    """PM с mock-коммуникацией и зарегистрированными детьми.

    Возвращает ``(pm, sent)``, где ``sent`` — журнал реальных отправок:
    ``kind='broadcast'`` (веерная) и ``kind='addressed'`` (адресная досылка).
    """
    pm = make_pm({name: {"class": "x.Y"} for name in names})
    sent: list[dict] = []

    class _Comm:
        def broadcast(self, msg, exclude_self=True):
            sent.append({"kind": "broadcast", **msg})
            return len(names)

        def send_to_process(self, target, msg):
            sent.append({"kind": "addressed", "target": target, **msg})
            return True

    pm.communication = _Comm()
    for name in names:
        pm._process_registry._processes[name] = MockProcess(name, alive=True)
    return pm, sent


def _addressed(sent: list[dict], command: str | None = None) -> list[dict]:
    rows = [row for row in sent if row["kind"] == "addressed"]
    return [row for row in rows if command is None or row.get("command") == command]


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _run_with_deadline(fn, deadline: float = 3.0) -> bool:
    """Прогнать вызов в daemon-потоке; ``False`` — не уложился (значит заблокировался)."""
    done = threading.Event()

    def _body():
        fn()
        done.set()

    threading.Thread(target=_body, daemon=True).start()
    return done.wait(deadline)


class TestRedeliveryToUnreadyChildren:
    """Пара «до готовности — тишина, после — конверт»."""

    def test_unready_child_gets_the_envelope_after_it_declares_readiness(self):
        """Не готов на момент рассылки → досылка адресно, когда объявится.

        Веерная рассылка уезжает как прежде (её ребёнок прочитает и выбросит) —
        проверяется именно ВТОРОЙ, адресный конверт: он и есть та доставка,
        которую ребёнок реально способен обработать.
        """
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        time.sleep(0.3)
        assert _addressed(sent) == [], f"досылка ушла до объявления готовности: {sent}"

        event.set()

        assert _wait_for(lambda: len(_addressed(sent)) == 1), f"досылка не пришла после готовности: {sent}"
        row = _addressed(sent)[0]
        assert row["target"] == "camera_0"
        assert row["command"] == "routing.refresh"
        assert row["data"] == {"epoch": 7}

    def test_ready_child_gets_exactly_one_envelope(self):
        """Готов → только веерная рассылка. Досылка готовому — лишний конверт на ровном месте."""
        pm, sent = _pm_with_children("camera_0")
        ready = threading.Event()
        ready.set()
        pm._process_registry._ready_events["camera_0"] = ready

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        time.sleep(0.3)
        assert _addressed(sent) == [], f"досылка ушла готовому ребёнку: {sent}"
        assert len([r for r in sent if r["kind"] == "broadcast"]) == 1

    def test_registry_without_ready_signal_keeps_the_old_behaviour(self):
        """Сигнала нет (mock-реестр, не-ProcessModule) → досылки нет.

        ``None`` значит «спросить не у кого», а не «не готов»: гадать «наверное,
        не готов» значило бы слать вторую копию всем и всегда.
        """
        pm, sent = _pm_with_children("camera_0")  # _ready_events пуст

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        time.sleep(0.3)
        assert _addressed(sent) == [], f"досылка при отсутствии сигнала: {sent}"

    def test_only_unready_children_are_redelivered(self):
        """Из троих досылку получает РОВНО не-готовый — не «все на всякий случай»."""
        pm, sent = _pm_with_children("camera_0", "camera_1", "consumer")
        ready = threading.Event()
        ready.set()
        pm._process_registry._ready_events["camera_0"] = ready
        late = threading.Event()
        pm._process_registry._ready_events["camera_1"] = late
        # consumer — без сигнала вовсе

        pm._broadcast_command("config.reload", {"observability_session_clear": True})
        late.set()

        assert _wait_for(lambda: len(_addressed(sent)) == 1), f"досылка не состоялась: {sent}"
        assert {row["target"] for row in _addressed(sent)} == {"camera_1"}


class TestRedeliveryPolicy:
    """Дедлайн, выключатель и снимок payload'а."""

    def test_zero_timeout_disables_redelivery(self):
        """``child_command_ready_timeout_s=0`` → аварийный откат к поведению до R4.

        Проверяется и отсутствие отправки, и отсутствие потока: «выключено» должно
        означать «не платим», а не «платим молча».
        """
        pm, sent = _pm_with_children("camera_0")
        pm._process_registry._ready_events["camera_0"] = threading.Event()  # НЕ взводим
        pm.update_config("child_command_ready_timeout_s", 0)
        before = threading.active_count()

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        time.sleep(0.3)
        assert _addressed(sent) == [], f"досылка при выключенном гейте: {sent}"
        assert threading.active_count() == before, "заведён поток ожидания при выключенном гейте"

    def test_deadline_expiry_redelivers_anyway_and_says_so(self):
        """Не объявился за дедлайн → досылаем ВСЁ РАВНО, но громко.

        Молчаливый отказ здесь неотличим от «команды и не было» — а именно так
        и выглядел исходный дефект.
        """
        pm, sent = _pm_with_children("camera_0")
        pm._process_registry._ready_events["camera_0"] = threading.Event()  # НЕ взводим
        pm.update_config("child_command_ready_timeout_s", 0.2)
        warnings: list[str] = []
        pm._log_warning = lambda msg, *a, **k: warnings.append(str(msg))

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        assert _wait_for(lambda: len(_addressed(sent)) == 1, timeout=3.0), f"по дедлайну досылки нет: {sent}"
        assert any("не объявил готовность" in w for w in warnings), f"дедлайн прошёл молча: {warnings}"

    def test_redelivered_payload_is_a_snapshot_of_what_was_broadcast(self):
        """Досылается ТО, что уехало в рассылке, а не то, во что payload превратился потом.

        Досылка уходит секундами позже, а вызывающий волен переиспользовать свой
        dict (так делает fan-out телеметрии). Без снимка ребёнок получил бы
        конверт от чужого события — и это был бы не «потерянный», а «подменённый».
        """
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        payload = {"epoch": 7, "processes": {"camera_0": {"incarnation": 1}}}

        pm._broadcast_command("routing.refresh", payload)
        payload["epoch"] = 999
        payload["processes"]["camera_0"]["incarnation"] = 999
        event.set()

        assert _wait_for(lambda: len(_addressed(sent)) == 1), f"досылка не пришла: {sent}"
        data = _addressed(sent)[0]["data"]
        assert data["epoch"] == 7, f"досылка уехала с мутированным payload: {data}"
        assert data["processes"]["camera_0"]["incarnation"] == 1


class TestGateDoesNotBlockTheMessageLoop:
    """Рассылку зовут из message_processor — ждать готовности синхронно нельзя.

    Синхронное ожидание здесь не «медленно», а смертельно: heartbeat и
    ``topology.apply`` обслуживает ОДИН поток, и он же ждал бы ребёнка, который
    без heartbeat'ов будет объявлен мёртвым.
    """

    def test_broadcast_returns_immediately_when_a_child_is_not_ready(self):
        pm, _sent = _pm_with_children("camera_0")
        pm._process_registry._ready_events["camera_0"] = threading.Event()  # НЕ взводим
        pm.update_config("child_command_ready_timeout_s", 30.0)

        assert _run_with_deadline(lambda: pm._broadcast_command("routing.refresh", {"epoch": 7})), (
            "рассылка заблокировалась в ожидании готовности ребёнка"
        )

    def test_broadcast_returns_the_broadcast_reach_not_the_redelivery_count(self):
        """Возврат — охват веерной рассылки. Складывать с досылками значило бы
        отвечать за «применилось», измерив «положено в очередь»."""
        pm, _sent = _pm_with_children("camera_0", "camera_1")
        pm._process_registry._ready_events["camera_0"] = threading.Event()

        assert pm._broadcast_command("routing.refresh", {"epoch": 7}) == 2


class TestAllSwitchBroadcastsAreCovered:
    """Три рассылки switch'а — не одна из трёх.

    Прямой урок прошлых заходов: дефект, починенный на одном пути из нескольких,
    воскресает на соседней развилке. Гейт живёт в общем примитиве рассылки, и
    этот тест — про то, что каждая из трёх реально через него проходит.
    """

    def _pm(self):
        """Дедлайн намеренно ДЛИННЫЙ, событие взводится вручную после вызова.

        Слом-инъекция RG5 («по дедлайну молчать») показала, что при коротком
        дедлайне эти три теста доезжали через аварийный путь — то есть проверяли
        фолбэк, выдавая это за проверку механизма. Теперь дедлайн заведомо не
        успевает, и досылка может прийти ТОЛЬКО по объявленной готовности.
        """
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        # 10с заведомо больше, чем ждёт `_wait_for` (3с): досылка внутри окна
        # ожидания может прийти ТОЛЬКО от взведённого события, не от дедлайна.
        pm.update_config("child_command_ready_timeout_s", 10.0)
        return pm, sent, event

    def test_routing_refresh_is_redelivered(self):
        pm, sent, event = self._pm()
        pm.shared_resources.get_process_names = lambda: ["camera_0"]

        pm._broadcast_routing_refresh("topology.apply")
        assert _addressed(sent, "routing.refresh") == [], "досылка ушла до готовности"
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "routing.refresh")) == 1), f"нет досылки: {sent}"

    def test_telemetry_reconfigure_is_redelivered(self):
        pm, sent, event = self._pm()
        pm._telemetry_runtime_delta = {"publish": {"logs": False}, "mode": "replace"}

        pm._replay_telemetry_runtime_delta("topology.apply")
        assert _addressed(sent, "telemetry.reconfigure") == [], "досылка ушла до готовности"
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "telemetry.reconfigure")) == 1), f"нет досылки: {sent}"

    def test_config_reload_is_redelivered(self):
        pm, sent, event = self._pm()

        pm._reset_observability_sessions("topology.apply")
        assert _addressed(sent, "config.reload") == [], "досылка ушла до готовности"
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) == 1), f"нет досылки: {sent}"


class TestObservabilityReplayStillUsesTheSameGate:
    """Регресс 5.11: раздача подписок осталась за гейтом после выноса примитива.

    Ожидание переехало в общий ``_run_when_child_ready``; если при выносе
    потерялась проводка, живой дефект 5.11 воскреснет молча.
    """

    def test_replay_still_waits_for_readiness(self):
        pm, sent = _pm_with_children("camera_0")
        pm._cmd_observability_tail_subscribe_all({"subscriber": "gui"})
        sent.clear()
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event

        pm._mark_instance_started("camera_0")

        time.sleep(0.3)
        assert _addressed(sent) == [], f"раздача ушла до объявления готовности: {sent}"

        event.set()

        assert _wait_for(lambda: len(_addressed(sent)) >= 1), f"раздача не пришла после готовности: {sent}"
