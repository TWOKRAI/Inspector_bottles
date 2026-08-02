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
        # Считаем потоки ГЕЙТА по префиксу имени, а не общий active_count(): чужой
        # поток (ожидатель соседнего теста, таймер) сдвигал бы счётчик и ронял тест
        # на невиновном (замечание ревью Fable, находка 5).
        before = {t for t in threading.enumerate() if t.name.startswith("ready-gate-")}

        pm._broadcast_command("routing.refresh", {"epoch": 7})

        time.sleep(0.3)
        assert _addressed(sent) == [], f"досылка при выключенном гейте: {sent}"
        after = {t for t in threading.enumerate() if t.name.startswith("ready-gate-")}
        assert after - before == set(), "заведён поток ожидания при выключенном гейте"

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


class TestRedeliveryDoesNotDeliverThePast:
    """Ревью Fable, находка 1: досылка не смеет привезти конверт ПОЗЖЕ свежего.

    Репро ревьюера: switch A→B при не-готовом ребёнке планирует досылку конверта B
    на ``ready_event`` инкарнации-1. Switch B→C пересоздаёт ребёнка — в реестре
    НОВЫЙ event, старый умирает невзведённым. Свежий конверт C доставляется, а поток
    досылки-B ждёт на мёртвом объекте весь дедлайн и «действует вслепую» — порядок
    доставки получается ``['C', 'B']``. У ``routing.refresh`` есть страж по эпохе,
    у ``config.reload`` и ``telemetry.reconfigure`` — нет, поэтому ребёнок
    пересобирает слой ПОКИНУТОГО рецепта.

    Идемпотентность от этого не спасает и никогда не спасала: дубль безвреден,
    стейл-после-свежего — нет.
    """

    def test_stale_envelope_is_dropped_when_a_newer_broadcast_follows(self):
        pm, sent = _pm_with_children("camera_0")
        first_event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = first_event
        # Дедлайн КОРОТКИЙ и ждём мы ДОЛЬШЕ него. Первая версия теста ставила 3с и
        # проверяла через 1с — устаревшая досылка просто не успевала приехать, и
        # тест был зелёным даже без защиты. Поймано собственной слом-инъекцией RF1:
        # тест, переживший свой слом, не существует.
        pm.update_config("child_command_ready_timeout_s", 0.5)

        pm._broadcast_command("config.reload", {"recipe": "B"})

        # Пересоздание ребёнка: СВЕЖИЙ объект события, старый не взведут никогда —
        # ожидатель конверта B обречён досидеть до дедлайна и «действовать вслепую».
        second_event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = second_event
        pm._broadcast_command("config.reload", {"recipe": "C"})
        second_event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"свежая досылка не пришла: {sent}"
        time.sleep(1.5)  # ЗАВЕДОМО дольше дедлайна: устаревшая досылка приехала бы

        delivered = [row["data"]["recipe"] for row in _addressed(sent, "config.reload")]
        assert delivered == ["C"], f"устаревший конверт доставлен: порядок {delivered}"

    def test_stale_waiter_stops_early_instead_of_burning_the_deadline(self):
        """Снятый по поколению поток уходит СРАЗУ, а не досиживает дедлайн.

        Иначе каждый перекрытый switch оставляет по потоку на команду на ребёнка,
        и все они висят на мёртвых событиях до истечения дедлайна.
        """
        pm, _sent = _pm_with_children("camera_0")
        pm._process_registry._ready_events["camera_0"] = threading.Event()
        pm.update_config("child_command_ready_timeout_s", 30.0)

        # Считаем ТОЛЬКО потоки этого вызова: в suite живут ожидатели соседних
        # тестов с длинными дедлайнами, и `enumerate()` целиком дал бы чужой поток
        # (тест бы падал на невиновном — класс «глобальный патч часов = флейк»).
        before = set(threading.enumerate())
        pm._broadcast_command("config.reload", {"recipe": "B"})
        gate_threads = [t for t in set(threading.enumerate()) - before if t.name.startswith("ready-gate-")]
        assert gate_threads, "поток ожидания не заведён — тест не про то"

        pm._process_registry._ready_events["camera_0"] = threading.Event()
        pm._broadcast_command("config.reload", {"recipe": "C"})

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not gate_threads[0].is_alive():
                break
            time.sleep(0.05)
        assert not gate_threads[0].is_alive(), "устаревший ожидатель досиживает дедлайн (30с) вместо снятия"

    def test_a_fresher_broadcast_of_another_command_does_not_cancel_this_one(self):
        """Свежий refresh не отменяет досылку ещё актуального reload'а.

        **Тест переписан осознанно (ФР-1, находка B-4-1 сквозного ревью Ф5).** До
        фикса он назывался ``test_generations_are_per_command`` и закреплял
        гранулярность «поколение = имя команды» — то самое, что и было дефектом:
        под одним ``config.reload`` едут конверты разного содержания, и поздний
        пустой гасил содержательный. Дорожка поколений теперь — пара
        ``(команда, ключ содержимого)``, и имя команды осталось её ПЕРВОЙ
        половиной. Этот тест сторожит ровно её: рассылка другой команды не имеет
        права снимать чужую досылку. Вторую половину (содержимое) сторожат
        :class:`TestGenerationsFollowTheEnvelopeNotTheCommandName`.

        Проверка «refresh доставлен только последний» оставлена намеренно: она
        показывает, что разделение дорожек не превратилось в «ничего никогда не
        гасится» — внутри одной пары (команда, содержимое) стейл по-прежнему снят.
        """
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        pm.update_config("child_command_ready_timeout_s", 5.0)

        pm._broadcast_command("config.reload", {"recipe": "B"})
        pm._broadcast_command("routing.refresh", {"epoch": 9})
        pm._broadcast_command("routing.refresh", {"epoch": 10})
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) == 1), f"reload снят чужим поколением: {sent}"
        refresh = [row["data"]["epoch"] for row in _addressed(sent, "routing.refresh")]
        assert refresh == [10], f"досылка refresh должна быть только последней: {refresh}"


#: Конверт switch'а — ровно тот, что собирает `_reset_observability_sessions`
#: (сброс L3 + слой L2 одним сообщением). Ключи, а не значения, и есть «род
#: содержимого», по которому теперь ведутся поколения.
_SWITCH_ENVELOPE = {
    "observability_session_clear": True,
    "observability_recipe": {"defaults": {"logger": {"default_level": "WARNING"}}},
    "observability_recipe_path": "recipes/new.yaml",
}


class TestGenerationsFollowTheEnvelopeNotTheCommandName:
    """ФР-1 (находка B-4-1): досылка не имеет права потерять СОДЕРЖИМОЕ.

    Класс дефекта — «связка двух порознь верных правок». Поколения досылки
    (правка 1) считались на имя команды; конверт switch'а и фан-аут watcher'а
    (правка 2) поехали под одним именем ``config.reload`` с разным содержимым.
    Порознь обе верны, вместе — поздний ПУСТОЙ конверт получал более свежее
    поколение и гасил досылку switch-конверта, содержимого которого сам не нёс.
    Следствие живьём: protected-процесс, рестартующий в момент switch, навсегда
    остаётся на слое и адресе ПОКИНУТОГО рецепта.

    Дорожка поколений теперь — пара ``(команда, ключ содержимого)``; конверт
    актуален, пока хоть одна его ручка не перекрыта (правило «any», см.
    ``_broadcast_envelope_relevant``).
    """

    def _pm(self):
        """Дедлайн КОРОТКИЙ, а проверяем ДОЛЬШЕ него.

        Урок собственной слом-инъекции RF1: при длинном дедлайне снятая досылка
        просто не успевает приехать, и тест зелен даже без защиты. Здесь наоборот
        — всё, что не снято, обязано приехать в пределах ожидания, а всё, что
        снято, имело полную возможность приехать и не приехало.
        """
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        pm.update_config("child_command_ready_timeout_s", 0.5)
        return pm, sent, event

    def test_a_later_empty_envelope_does_not_cancel_the_switch_envelope(self):
        """Репро ФР-1 целиком: пустой ``config.reload`` не гасит конверт switch'а.

        Ровно последовательность живого switch'а: ``_reset_observability_sessions``
        шлёт конверт со слоем L2, а следом (или почти следом) watcher'ский фан-аут
        L1 шлёт ту же команду с пустым payload'ом.
        """
        pm, sent, event = self._pm()

        pm._broadcast_command("config.reload", dict(_SWITCH_ENVELOPE))
        pm._broadcast_command("config.reload", {})
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"досылки нет вовсе: {sent}"
        time.sleep(1.0)  # заведомо дольше дедлайна: всё, что не снято, уже приехало
        payloads = [row["data"] for row in _addressed(sent, "config.reload")]
        assert any("observability_recipe" in p for p in payloads), (
            f"конверт switch со слоем L2 снят поздним пустым reload'ом: {payloads}"
        )
        # Пустой конверт — самостоятельное намерение «перечитай свой источник»,
        # и он тоже обязан доехать: разные роды содержимого друг друга не гасят.
        assert any(p == {} for p in payloads), f"пустой конверт пропал: {payloads}"

    def test_two_empty_envelopes_still_collapse_to_the_last_one(self):
        """Стейл-после-свежего для ОДИНАКОВОГО содержимого по-прежнему гасится.

        Пустой конверт — не «нет содержимого», а свой род со своей дорожкой
        (``_EMPTY_ENVELOPE_KEY``). Без него разделение дорожек означало бы
        «пустые не гасят даже друг друга», и каждый тик watcher'а копил бы по
        досылке на ребёнка.
        """
        pm, sent, event = self._pm()

        pm._broadcast_command("config.reload", {})
        pm._broadcast_command("config.reload", {})
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"досылки нет: {sent}"
        time.sleep(1.0)
        rows = _addressed(sent, "config.reload")
        assert len(rows) == 1, f"два пустых конверта дали две досылки: {rows}"

    def test_two_switch_envelopes_still_collapse_to_the_last_one(self):
        """Switch A→B, перекрытый switch'ем B→C: доезжает только C.

        Тот самый сценарий находки 1 предыдущего ревью — он обязан пережить
        разделение дорожек, иначе ФР-1 чинился бы ценой воскрешения находки 1.
        """
        pm, sent, event = self._pm()
        first = dict(_SWITCH_ENVELOPE, observability_recipe_path="recipes/B.yaml")
        second = dict(_SWITCH_ENVELOPE, observability_recipe_path="recipes/C.yaml")

        pm._broadcast_command("config.reload", first)
        pm._broadcast_command("config.reload", second)
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"досылки нет: {sent}"
        time.sleep(1.0)
        paths = [row["data"]["observability_recipe_path"] for row in _addressed(sent, "config.reload")]
        assert paths == ["recipes/C.yaml"], f"конверт покинутого рецепта доставлен: {paths}"

    def test_a_covering_envelope_cancels_the_bare_pending_one(self):
        """Свежий конверт, ВКЛЮЧАЮЩИЙ содержимое отложенного, снимает его.

        Отложен голый сброс сессии; следом уезжает конверт switch'а, который тот
        же сброс несёт в себе — везти его вторым сообщением уже не за чем. Это и
        есть смысл дорожек по ключам: перекрытие считается по содержимому, а не
        по совпадению payload'ов целиком.
        """
        pm, sent, event = self._pm()

        pm._broadcast_command("config.reload", {"observability_session_clear": True})
        pm._broadcast_command("config.reload", dict(_SWITCH_ENVELOPE))
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"досылки нет: {sent}"
        time.sleep(1.0)
        rows = _addressed(sent, "config.reload")
        assert len(rows) == 1, f"перекрытый голый конверт доставлен вторым сообщением: {[r['data'] for r in rows]}"
        assert "observability_recipe" in rows[0]["data"]

    def test_a_partial_envelope_does_not_cancel_the_richer_pending_one(self):
        """Обратный порядок: бедный конверт НЕ снимает богатый — он его не заменяет.

        Правило «any» вслух: перекрыт только ``observability_session_clear``, а
        слой рецепта бедный конверт не везёт. Снять богатый значило бы объявить
        частичное перекрытие полным — то же самое, чем ФР-1 и был. Цена —
        безвредный дубль сброса сессии (все команды этого пути идемпотентны).
        """
        pm, sent, event = self._pm()

        pm._broadcast_command("config.reload", dict(_SWITCH_ENVELOPE))
        pm._broadcast_command("config.reload", {"observability_session_clear": True})
        event.set()

        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 2, timeout=3.0), (
            f"богатый конверт снят бедным — слой L2 потерян: {[r['data'] for r in _addressed(sent, 'config.reload')]}"
        )
        payloads = [row["data"] for row in _addressed(sent, "config.reload")]
        assert any("observability_recipe" in p for p in payloads), f"слой L2 не доехал: {payloads}"

    def test_concurrent_broadcasts_of_the_same_content_collapse_to_one(self):
        """Дорожки поколений живут под локом: гонка рассылок не даёт лишних досылок.

        Hazard именно этой конструкции: раньше поколение было одним числом на
        команду, теперь это словарь отметок, который строится циклом. Инкремент
        без лока дал бы двум потокам одинаковый номер — и оба конверта считали бы
        себя последними. Проверяется наблюдаемо: 12 одинаковых по содержимому
        рассылок из 4 потоков → РОВНО одна досылка.
        """
        pm, sent, event = self._pm()
        pm.update_config("child_command_ready_timeout_s", 5.0)
        errors: list[BaseException] = []

        def _spam():
            try:
                for _ in range(3):
                    pm._broadcast_command("config.reload", dict(_SWITCH_ENVELOPE))
            except BaseException as exc:  # noqa: BLE001 — падение потока обязано стать красным тестом
                errors.append(exc)

        threads = [threading.Thread(target=_spam, daemon=True) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3.0)
            assert not thread.is_alive(), "рассылка заблокировалась под локом поколений"
        assert not errors, f"рассылка упала в потоке: {errors}"

        event.set()
        assert _wait_for(lambda: len(_addressed(sent, "config.reload")) >= 1), f"досылки нет: {sent}"
        time.sleep(1.0)
        rows = _addressed(sent, "config.reload")
        assert len(rows) == 1, f"гонка поколений дала {len(rows)} досылок вместо одной"


class TestAddressedRestartPathIsGated:
    """Ревью Fable, находка 2: адресные отправки restart-потока шли МИМО гейта.

    Это тот самый процесс, которого только что перезапустили, — то есть ровно
    сценарий из Why задачи R4. Компенсирующей рассылки за адресной telemetry-дельтой
    нет: потеря тихая и постоянная, ребёнок остаётся на boot-конфиге.
    """

    def test_addressed_telemetry_replay_waits_for_readiness(self):
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        pm.update_config("child_command_ready_timeout_s", 10.0)
        pm._telemetry_runtime_delta = {"publish": {"logs": False}, "mode": "replace"}

        pm._replay_telemetry_runtime_delta("process.restart", target="camera_0")

        assert _addressed(sent, "telemetry.reconfigure") == [], "адресная дельта ушла не-готовому немедленно"
        event.set()
        assert _wait_for(lambda: len(_addressed(sent, "telemetry.reconfigure")) == 1), f"дельта не пришла: {sent}"

    def test_wire_reissue_waits_and_marks_active_only_after_send(self):
        """Провод не объявляется активным по несостоявшемуся применению."""
        pm, sent = _pm_with_children("camera_0")
        event = threading.Event()
        pm._process_registry._ready_events["camera_0"] = event
        pm.update_config("child_command_ready_timeout_s", 10.0)
        pm._active_wires = {
            "cam->proc": {
                "source_process": "camera_0",
                "target_process": "proc",
                "status": "broken",
                "shm_config": {"shm_name": "frames", "owner_process": "camera_0", "buffer_slots": 4},
            }
        }
        pm.send_message = lambda target, msg: sent.append({"kind": "addressed", "target": target, **msg})

        reissued = pm._reissue_wires_for("camera_0")

        assert reissued == 0, "отложенный провод не должен считаться переигранным"
        assert pm._active_wires["cam->proc"]["status"] == "broken", "статус active по неотправленной команде"
        event.set()
        assert _wait_for(lambda: pm._active_wires["cam->proc"]["status"] == "active"), "провод не переигран"
