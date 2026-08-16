# -*- coding: utf-8 -*-
"""Task 3.4: адресная runtime-дельта телеметрии — АВТОРСКИЕ hazard-тесты.

Роль этого файла (правило «три роли авторства»): здесь НЕ приёмка. Приёмку по
критериям написал независимый тестировщик, не видевший реализации, —
``test_telemetry_addressed_delta_persist.py``, и трогать её нельзя. Здесь то,
что видно только автору механизма:

* **порядок доигрывания — хронологический**, в том числе на ОТЛОЖЕННОМ пути, за
  гейтом готовности ребёнка. Ошибка здесь тихая: ребёнок применяет конверты в
  порядке приёма, и переставленный конверт даёт неверный gate без единой строки
  в журнале;
* **актуальность журнала на момент отправки**, а не на момент планирования —
  включая случай «оператор правит систему, пока срез стоит в очереди»;
* **свёртка журнала** (смежные merge одного адресата) и изоляция детей;
* **семантика сброса** (tombstone против забвения записи);
* **отсутствие лишнего трафика** и забвение процессов вне топологии.

Главное свойство — ЭКВИВАЛЕНТНОСТЬ с выжившим: пересозданный ребёнок обязан
прийти к тому же эффективному gate, что и ребёнок, переживший ту же
последовательность правок не умирая. Оно проверяется НАСТОЯЩИМ приёмником
(``ProcessHeartbeat.reconfigure_telemetry`` — боевой код ребёнка), а не моделью
автора: модель согласилась бы сама с собой.

Всё, что может заблокироваться, ждёт опросом с дедлайном — регресс обязан
ПАДАТЬ, а не вешать суиту.
"""

from __future__ import annotations

import threading
import time

import pytest

from ...process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from .conftest import make_pm


# ---------------------------------------------------------------------------
# Харнесс
# ---------------------------------------------------------------------------


class _Comm:
    """Единый хронологический журнал: веерные и адресные отправки в ОДНОМ списке.

    Раздельные списки стирают относительный порядок между веерным и адресным
    путём — а хронологический порядок конвертов и есть проверяемый контракт.
    """

    def __init__(self, reach: int) -> None:
        self.log: list[dict] = []
        self._reach = reach

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.log.append({"kind": "broadcast", **message})
        return self._reach

    def send_to_process(self, target: str, message) -> bool:
        self.log.append({"kind": "addressed", "target": target, **message})
        return True


def _pm(children: dict):
    pm = make_pm(children)
    pm.communication = _Comm(reach=len(children))
    for name in children:
        pm.shared_resources.register_process(name, {})
    return pm


def _envelopes_for(pm, name: str) -> list[dict]:
    """Конверты ``telemetry.reconfigure``, реально дошедшие бы до `name`, в порядке отправки."""
    return [
        row
        for row in pm.communication.log
        if row.get("command") == "telemetry.reconfigure" and (row["kind"] == "broadcast" or row.get("target") == name)
    ]


def _respawn(pm, *names: str) -> dict:
    return pm.apply_topology({"processes": [{"process_name": n, "process_class": f"m.{n.title()}"} for n in names]})


def _respawn_via_topology(pm, watch: str = "lines") -> None:
    """Call-site №1 доигрывания: hot-swap рецепта (``apply_topology``, фан-аут).

    Пересоздаёт ВСЕХ, поэтому `watch` ни на что не влияет — принимается ради общей
    сигнатуры с одноадресным путём.
    """
    assert _respawn(pm, "lines", "seg")["success"] is True


def _respawn_via_restart(pm, watch: str = "lines") -> None:
    """Call-site №2 доигрывания: одиночный краш-рестарт (``restart_process``, адресно).

    Это ТОТ путь, на котором нашли живое репро 2026-08-16. Зовётся боевой
    `restart_process`, а не сам replay: иначе тест сторожил бы механизм, оставив
    без присмотра его проводку в lifecycle.

    Перезапускается ИМЕННО наблюдаемый ребёнок: этот путь трогает одного, и сравнивать
    «пересозданного» с выжившим, перезапустив кого-то другого, значило бы сравнивать
    пустоту с чем угодно (тест был бы красным на верной реализации).
    """
    assert pm.restart_process(watch) is True


def _last_for(pm, name: str) -> dict:
    """Последняя АДРЕСНАЯ запись журнала для `name` (журнал — истина, реестра уровней нет)."""
    records = [r for r in pm._telemetry_delta_log if r["target"] == name]
    assert records, f"в журнале нет записей для {name!r}: {pm._telemetry_delta_log}"
    return records[-1]


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _apply_to_child(heartbeat: ProcessHeartbeat, envelopes: list[dict]) -> None:
    """Применить конверты БОЕВЫМ приёмником ребёнка, в порядке доставки.

    Ровно то, что делает ``apply_telemetry_reconfigure`` на стороне процесса
    (``telemetry_reload.py``: ``heartbeat.reconfigure_telemetry(section["publish"], mode=mode)``).
    """
    for row in envelopes:
        data = row.get("data", {})
        heartbeat.reconfigure_telemetry(data["publish"], mode=data.get("telemetry_mode", "replace"))


# ---------------------------------------------------------------------------
# Главное свойство: эквивалентность пересозданного и выжившего
# ---------------------------------------------------------------------------


#: Обе последовательности одной пары правок. Порядок здесь — НЕ украшение параметризации:
#: приёмник ребёнка применяет конверты в порядке приёма, поэтому «адресная последней» и
#: «фан-аутная последней» дают РАЗНЫЙ верный ответ. Ревью поймало, что оба прежних теста
#: эквивалентности случайно стояли в первой форме, и вторая не проверялась вовсе.
_GLOBAL_EDIT = {
    "publish": {"metrics": {"fps": {"interval_sec": 3.0}, "latency_ms": {"interval_sec": 11.0}}},
    "telemetry_mode": "merge",
}
_ADDRESSED_EDIT = {
    "publish": {"metrics": {"fps": {"interval_sec": 7.0}, "shm": {"enabled": False}}},
    "telemetry_mode": "merge",
    "target": "lines",
}
_ADDRESSED_RESET = {"publish": None, "target": "lines"}

_RESPAWNS = {"apply_topology": _respawn_via_topology, "process.restart": _respawn_via_restart}


class TestEquivalenceWithASurvivingSibling:
    """Контракт — не «конверт доехал», а «gate тот же, что у не умиравшего».

    Проверяется на ОБОИХ call-site'ах доигрывания и в ОБЕИХ последовательностях правок.
    Значения расходятся по конвертам (3.0 против 7.0 на общей метрике ``fps``, плюс
    ``latency_ms`` только в фан-аутной и ``shm`` только в адресной), чтобы совпадение
    констант не спрятало неверную реализацию.
    """

    def _live_and_respawned(self, pm, sequence, respawn=None, watch: str = "lines") -> tuple[dict | None, dict | None]:
        """Прогнать `sequence` и вернуть gate ребёнка `watch`: у выжившего и у пересозданного.

        Оба стартуют из ОДНОГО boot-состояния (gate выключен — так выглядел `lines` в живом
        репро: ``publish=null``), поэтому разойтись они могут только доигрыванием.

        `watch` — кого именно сравниваем. Правленый ребёнок и его СОСЕД — разные утверждения:
        у соседа своя доля журнала (только фан-аутные записи), и потерять её он может там,
        где правленый ничего не замечает.
        """
        live = ProcessHeartbeat(None)
        for command in sequence:
            pm.communication.log.clear()
            pm._cmd_telemetry_broadcast(command)
            _apply_to_child(live, _envelopes_for(pm, watch))

        respawned = ProcessHeartbeat(None)
        pm.communication.log.clear()
        (respawn or _respawn_via_topology)(pm, watch)
        _apply_to_child(respawned, _envelopes_for(pm, watch))
        return live.current_telemetry_publish(), respawned.current_telemetry_publish()

    @pytest.mark.parametrize("call_site", sorted(_RESPAWNS))
    @pytest.mark.parametrize(
        "order,expected_fps",
        [
            # Адресная позже → её 7.0 и остаётся эффективным.
            ("addressed_last", 7.0),
            # Фан-аутная позже → общий проход оператора ПЕРЕКРЫВАЕТ точечную правку, и 3.0
            # — правильный ответ. Приоритет «узкий уровень поверх широкого» дал бы здесь 7.0
            # у пересозданного при 3.0 у выжившего (блокер ревью).
            ("fanout_last", 3.0),
        ],
    )
    def test_respawned_gate_equals_the_live_gate(self, call_site: str, order: str, expected_fps: float) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        sequence = [_GLOBAL_EDIT, _ADDRESSED_EDIT] if order == "addressed_last" else [_ADDRESSED_EDIT, _GLOBAL_EDIT]
        live, respawned = self._live_and_respawned(pm, sequence, respawn=_RESPAWNS[call_site])

        assert respawned == live, (
            f"[{call_site}, {order}] gate пересозданного ребёнка разошёлся с gate выжившего: "
            f"выживший={live} пересозданный={respawned}"
        )
        # Контроль вырождения: сравнивались не два None/дефолта, и победил тот конверт,
        # который оператор отдал ПОСЛЕДНИМ, а не тот, что «уже» по адресации.
        assert live is not None
        assert live["metrics"]["fps"]["interval_sec"] == expected_fps, (
            f"[{order}] эффективным обязан быть fps={expected_fps} (последняя по времени правка)"
        )
        assert live["metrics"]["latency_ms"]["interval_sec"] == 11.0
        assert live["metrics"]["shm"]["enabled"] is False

    @pytest.mark.parametrize("call_site", sorted(_RESPAWNS))
    @pytest.mark.parametrize("order", ["addressed_last", "fanout_last"])
    def test_neighbour_gate_equals_its_live_self(self, call_site: str, order: str) -> None:
        """Эквивалентность у СОСЕДА: ему правку не адресовали, но свою долю он терять не вправе.

        Найдено сломом ревьюера: снятие сверки получателя в свёртке журнала (фан-аутная
        запись складывается со следующей адресной в ОДНУ запись с адресным получателем)
        оставляло 813 тестов зелёными, а `seg` после respawn — вообще без своей фан-аутной
        правки. Эквивалентность проверялась только у правленого ребёнка.

        Соседний тест ``test_addressed_edit_does_not_leak_to_a_neighbour_on_respawn`` сторожит
        обратное утверждение — «соседу не досталось ЛИШНЕГО». Здесь — «у соседа не отняли
        СВОЕГО»; из первого второе не следует.
        """
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        sequence = [_GLOBAL_EDIT, _ADDRESSED_EDIT] if order == "addressed_last" else [_ADDRESSED_EDIT, _GLOBAL_EDIT]
        live, respawned = self._live_and_respawned(pm, sequence, respawn=_RESPAWNS[call_site], watch="seg")

        assert respawned == live, (
            f"[{call_site}, {order}] gate соседа 'seg' после respawn разошёлся с его же живым: "
            f"выживший={live} пересозданный={respawned}"
        )
        # Контроль вырождения: у соседа ЕСТЬ что терять, и это ровно фан-аутная правка —
        # ни значения адресной правки соседа, ни её ключей у него быть не должно.
        assert live is not None, "предпосылка: сосед получил фан-аутную правку и его gate включён"
        assert live["metrics"]["fps"]["interval_sec"] == 3.0, "у соседа обязано остаться ФАН-АУТНОЕ значение"
        assert live["metrics"]["latency_ms"]["interval_sec"] == 11.0
        assert "shm" not in live["metrics"], (
            f"соседу протекла адресная правка 'lines' (ключ shm, которого он не просил): {live}"
        )
        assert live["metrics"]["fps"]["interval_sec"] != 7.0, "соседу протекло АДРЕСНОЕ значение fps"

    @pytest.mark.parametrize("call_site", sorted(_RESPAWNS))
    @pytest.mark.parametrize(
        "order,gate_off",
        [
            # Сброс последним → оператор выключил gate ИМЕННО этому ребёнку.
            ("addressed_last", True),
            # Сброс, а ПОСЛЕ него общий проход → gate снова включён. Худший случай блокера:
            # приоритет уровней доиграл бы tombstone последним и оставил бы пересозданного
            # ребёнка вообще без телеметрии при живом соседе с включённой.
            ("fanout_last", False),
        ],
    )
    def test_addressed_reset_keeps_equivalence(self, call_site: str, order: str, gate_off: bool) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        sequence = [_GLOBAL_EDIT, _ADDRESSED_RESET] if order == "addressed_last" else [_ADDRESSED_RESET, _GLOBAL_EDIT]
        live, respawned = self._live_and_respawned(pm, sequence, respawn=_RESPAWNS[call_site])

        assert (live is None) is gate_off, f"предпосылка теста не выполнена: выживший = {live}"
        assert respawned == live, (
            f"[{call_site}, {order}] сброс доигран не в свою хронологическую позицию: "
            f"выживший={live} пересозданный={respawned}"
        )


# ---------------------------------------------------------------------------
# Порядок доставки лестницы — неинвертируемость
# ---------------------------------------------------------------------------


class TestReplayFollowsWriteOrder:
    """Срез ребёнка уезжает в порядке ЗАПИСИ и не рвётся ничем посередине.

    Опасен отложенный путь: конверты не-готовому ребёнку копятся за гейтом готовности,
    и всё, что уходит мимо очереди адресата, обгоняет их молча — ошибочный gate без
    единой строки в журнале.
    """

    def _pm_with_unready_child(self):
        """PM с журналом из двух правок и ребёнком, который ЕЩЁ не объявил готовность.

        Правки делаются при взведённом событии (иначе досылка примешалась бы к самим
        правкам), затем событие подменяется свежим невзведённым — ровно то, что делает
        respawn: пересозданный ребёнок приходит с НОВЫМ ready_event.
        """
        pm = _pm({"lines": {"class": "m.Lines"}})
        ready = threading.Event()
        ready.set()
        pm._process_registry._ready_events["lines"] = ready
        # 10с заведомо больше окна ожидания тестов (3с): конверт внутри окна может
        # прийти ТОЛЬКО по объявленной готовности, а не по истечению дедлайна.
        pm.update_config("child_command_ready_timeout_s", 10.0)

        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 3.0}}}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})

        fresh = threading.Event()
        pm._process_registry._ready_events["lines"] = fresh
        pm.communication.log.clear()
        return pm, fresh

    def _addressed_fps(self, pm) -> list[float]:
        return [
            row["data"]["publish"]["metrics"]["fps"]["interval_sec"]
            for row in pm.communication.log
            if row["kind"] == "addressed" and row.get("command") == "telemetry.reconfigure"
        ]

    def test_fanout_replay_keeps_the_slice_in_write_order(self) -> None:
        pm, ready = self._pm_with_unready_child()

        pm._replay_telemetry_runtime_delta("topology.apply")

        time.sleep(0.3)
        assert self._addressed_fps(pm) == [], (
            f"конверт ушёл не-готовому ребёнку немедленно, обогнав отложенный глобальный: {pm.communication.log}"
        )

        ready.set()
        assert _wait_for(lambda: len(self._addressed_fps(pm)) == 2), (
            f"срез не доехал после объявления готовности: {pm.communication.log}"
        )
        assert self._addressed_fps(pm) == [3.0, 7.0], (
            f"срез уехал не в порядке записи оператором, фактически {self._addressed_fps(pm)}"
        )

    def test_restart_replay_sends_the_whole_slice_in_one_gated_action(self) -> None:
        """Одноадресный путь: ОДИН колбэк шлёт весь срез — точки перестановки между конвертами нет."""
        pm, ready = self._pm_with_unready_child()

        pm._replay_telemetry_runtime_delta("process.restart", target="lines")

        time.sleep(0.3)
        assert self._addressed_fps(pm) == [], f"конверт ушёл не-готовому ребёнку: {pm.communication.log}"

        ready.set()
        assert _wait_for(lambda: len(self._addressed_fps(pm)) == 2), (
            f"срез не доехал после готовности: {pm.communication.log}"
        )
        assert self._addressed_fps(pm) == [3.0, 7.0]

    def test_deferred_replay_carries_the_delta_as_of_send_time(self) -> None:
        """Между планированием досылки и готовностью ребёнка оператор успел правку.

        Захвати колбэк снимок дельты при планировании — уехало бы прошлое, и хранилище
        PM разошлось бы с тем, что реально применил ребёнок (стейл-после-свежего).
        """
        pm, ready = self._pm_with_unready_child()
        pm._replay_telemetry_runtime_delta("process.restart", target="lines")

        pm._record_telemetry_delta("lines", {"metrics": {"fps": {"interval_sec": 9.0}}}, "replace")

        ready.set()
        assert _wait_for(lambda: len(self._addressed_fps(pm)) == 2), f"срез не доехал: {pm.communication.log}"
        # Судим СОСТАВ отправленного, не его последовательность: за порядок отвечают
        # тесты выше, и цеплять за него ещё и этот ассерт значило бы дать тесту две
        # причины смерти (слом ревьюера убил его инверсией порядка — не тем свойством,
        # которое он сторожит).
        fps = self._addressed_fps(pm)
        assert 9.0 in fps, f"уехала дельта на момент ПЛАНИРОВАНИЯ, а не на момент отправки: {fps}"
        assert 7.0 not in fps, f"уехала УСТАРЕВШАЯ адресная дельта вместе со свежей: {fps}"

    def test_operator_edit_during_a_queued_fanout_replay_still_wins(self) -> None:
        """Стейл-после-свежего на ФАН-АУТНОМ пути: пока срез стоит в очереди, оператор правит.

        Ревью воспроизвело на прежней редакции: последним ребёнку приходило старое значение.
        Generation-guard (``still_relevant``), какой стоит у досылки
        ``_redeliver_to_unready_children``, здесь НЕ ставится намеренно — он снял бы досылку
        целиком и оставил пересозданного ребёнка на boot-конфиге, то есть вернул бы дефект
        самой задачи. Свежесть держится тем, что срез берётся на момент ОТПРАВКИ.

        Правка оператора здесь АДРЕСНАЯ, и это не произвол. Фан-аутная форма этого сценария
        недоказуема на этом шве: за фан-аутной правкой сама рассылка планирует свою досылку
        не-готовому ребёнку, и она приходит последней независимо от того, что сделал срез —
        тест был бы зелёным и на заведомо сломанной реализации (проверено инъекцией
        «срез заморожен при планировании»: 0 красных). У адресной правки такого
        компенсатора нет — доставить свежее значение может только сам срез.
        """
        pm = _pm({"lines": {"class": "m.Lines"}})
        ready = threading.Event()
        ready.set()
        pm._process_registry._ready_events["lines"] = ready
        pm.update_config("child_command_ready_timeout_s", 10.0)
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "telemetry_mode": "merge", "target": "lines"}
        )

        # respawn: ребёнок пришёл с новым (невзведённым) сигналом готовности, срез встал в очередь
        pm._process_registry._ready_events["lines"] = threading.Event()
        pm.communication.log.clear()
        pm._replay_telemetry_runtime_delta("topology.apply")

        # ...и ровно в этот момент оператор правит того же ребёнка ещё раз
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 20.0}}}, "telemetry_mode": "merge", "target": "lines"}
        )

        pm._process_registry._ready_events["lines"].set()
        assert _wait_for(lambda: len(self._addressed_fps(pm)) >= 2), f"срез не доехал: {pm.communication.log}"
        fps = self._addressed_fps(pm)
        assert fps[-1] == 20.0, f"последним ребёнку пришла УСТАРЕВШАЯ правка вместо той, что оператор дал позже: {fps}"


# ---------------------------------------------------------------------------
# Свёртка журнала
# ---------------------------------------------------------------------------


class TestAddressedAccumulation:
    """Свёртка журнала: смежные merge одного адресата складываются, чужие записи — барьер."""

    def test_consecutive_addressed_merges_accumulate(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "telemetry_mode": "merge", "target": "lines"}
        )
        pm._cmd_telemetry_broadcast(
            {
                "publish": {"metrics": {"latency_ms": {"interval_sec": 2.0}}},
                "telemetry_mode": "merge",
                "target": "lines",
            }
        )
        assert len(pm._telemetry_delta_log) == 1, "смежные merge одного адресата обязаны свернуться в одну запись"
        record = pm._telemetry_delta_log[0]
        assert record["target"] == "lines" and record["mode"] == "merge"
        metrics = record["publish"]["metrics"]
        assert metrics["fps"] == {"interval_sec": 7.0}, "первая адресная правка потеряна накоплением"
        assert metrics["latency_ms"] == {"interval_sec": 2.0}

    def test_addressed_replace_resets_the_accumulated_addressed_delta(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "telemetry_mode": "merge", "target": "lines"}
        )
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"shm": {"enabled": False}}}, "target": "lines"})
        assert len(pm._telemetry_delta_log) == 1, "replace обязан выбросить предысторию СВОЕГО адресата"
        metrics = pm._telemetry_delta_log[0]["publish"]["metrics"]
        assert "fps" not in metrics
        assert metrics["shm"] == {"enabled": False}

    def test_addressed_edit_does_not_touch_the_neighbour_entry(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 5.0}}}, "target": "seg"})
        assert _last_for(pm, "lines")["publish"]["metrics"]["fps"]["interval_sec"] == 7.0
        assert _last_for(pm, "seg")["publish"]["metrics"]["fps"]["interval_sec"] == 5.0

    def test_addressed_edit_does_not_touch_the_global_level(self) -> None:
        """Разворот Task 3.4 не должен превратить адресную правку в системную."""
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        assert getattr(pm, "_telemetry_runtime_delta", None) is None


# ---------------------------------------------------------------------------
# Семантика сброса
# ---------------------------------------------------------------------------


class TestResetSemantics:
    def test_fanout_publish_none_clears_both_levels(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        pm._cmd_telemetry_broadcast({"publish": None})
        assert pm._telemetry_runtime_delta is None
        assert pm._telemetry_delta_log == [], (
            "адресные записи пережили фан-аут сброс и воскресили бы gate у своих детей при respawn"
        )

    def test_addressed_publish_none_stores_a_tombstone_not_a_forget(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        pm._cmd_telemetry_broadcast({"publish": None, "target": "lines"})
        assert pm._telemetry_delta_log, "адресный сброс забыл запись вместо tombstone"
        assert pm._telemetry_delta_log[-1] == {"target": "lines", "publish": None, "mode": "replace"}

    def test_addressed_reset_does_not_clear_the_global_level(self) -> None:
        """Сброс ОДНОМУ ребёнку — не сброс системе: соседи обязаны остаться при своём."""
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}})
        pm._cmd_telemetry_broadcast({"publish": None, "target": "lines"})
        assert pm._telemetry_runtime_delta is not None
        pm.communication.log.clear()
        _respawn(pm, "lines", "seg")
        seg = _envelopes_for(pm, "seg")
        assert seg and seg[-1]["data"]["publish"] is not None, (
            f"адресный сброс 'lines' погасил gate соседа 'seg': {seg}"
        )

    def test_addressed_edit_after_a_tombstone_starts_from_scratch(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast({"publish": None, "target": "lines"})
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "telemetry_mode": "merge", "target": "lines"}
        )
        assert _last_for(pm, "lines")["publish"] == {"metrics": {"fps": {"interval_sec": 7.0}}}


# ---------------------------------------------------------------------------
# Отсутствие лишнего трафика
# ---------------------------------------------------------------------------


class TestNoExtraTraffic:
    def test_child_without_an_addressed_entry_gets_no_second_message(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        pm.communication.log.clear()
        _respawn(pm, "lines", "seg")

        seg = _envelopes_for(pm, "seg")
        assert len(seg) == 1, f"'seg' без собственной правки получил лишний конверт: {seg}"
        assert seg[0]["data"]["publish"]["metrics"]["latency_ms"]["interval_sec"] == 11.0

    def test_replay_without_any_delta_sends_nothing(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        assert pm._replay_telemetry_runtime_delta("test") == 0
        assert pm._replay_telemetry_runtime_delta("test", target="lines") == 0
        assert pm.communication.log == []

    def test_addressed_entry_of_a_child_outside_the_topology_is_not_sent(self) -> None:
        """Ребёнок снят с топологии → его адресная запись никому не адресована."""
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "seg"})
        pm.communication.log.clear()
        _respawn(pm, "lines")  # 'seg' в новой топологии нет

        addressed = [row for row in pm.communication.log if row["kind"] == "addressed"]
        assert addressed == [], f"адресный конверт ушёл процессу вне топологии: {addressed}"

    def test_a_new_process_does_not_inherit_the_edit_of_its_namesake(self) -> None:
        """Имя переиспользуемо, правка — нет (MAJOR 4 ревью).

        Записи журнала живут по ИМЕНИ. Не забудь PM правку выбывшего процесса — новый
        процесс с тем же именем и ДРУГИМ классом унаследовал бы чужую операторскую
        настройку: молча, и тем вернее, чем реже такой рецепт пересобирают.
        Пропуск при отправке («не живой — не шлём») этого не закрывает: он молчит ровно
        до того момента, когда имя снова станет живым.
        """
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "seg"})
        _respawn(pm, "lines")  # 'seg' выбыл из топологии
        assert all(record["target"] != "seg" for record in pm._telemetry_delta_log), (
            f"правка выбывшего процесса осталась в журнале: {pm._telemetry_delta_log}"
        )

        pm.communication.log.clear()
        pm.apply_topology(  # имя вернулось, но это ДРУГОЙ процесс
            {
                "processes": [
                    {"process_name": "lines", "process_class": "m.Lines"},
                    {"process_name": "seg", "process_class": "m.SegV2"},
                ]
            }
        )
        seg = _envelopes_for(pm, "seg")
        assert seg == [], f"новый процесс с прежним именем унаследовал чужую правку: {seg}"
