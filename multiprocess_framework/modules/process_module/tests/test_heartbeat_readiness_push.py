# -*- coding: utf-8 -*-
"""Task 3.3 (lane F) — внеочередной heartbeat при смене ГОТОВНОСТИ, не только ``paused`` (слепые acceptance-тесты).

Контекст: процесс-ребёнок шлёт Process Manager'у регулярный heartbeat раз в ``heartbeat_interval`` и внеочередной —
при смене состояния. Готовность — снимок ``readiness`` в сообщении (``ready``, ``reasons`` [dict ``node``/``severity``/
``reason``], ``paused``, ``at``). Блокирующие severity — ``failure``, ``check_function``; неблокирующие —
``out_of_spec``, ``maintenance``. До задачи внеочередной уходит только при смене ``paused``; требуется — также при смене
``ready`` и набора блокирующих причин.

Критерии (нумерация брифа) и статус на ТЕКУЩЕМ коде (до реализации):

  КРАСНЫЕ (ожидаемо):
    1  ``test_blocking_failure_pushes_ready_false_heartbeat_with_long_interval``
    2b ``test_flapping_readiness_final_state_delivered_after_quiet``  (вторая половина критерия 2)
    3  ``test_boot_latch_ready_true_without_reasons_is_pushed``
    5  ``test_blocking_severity_change_is_pushed``, ``test_second_plugin_blocking_reason_is_pushed``
    + дополнительно от tester'а (в брифе нет, красные по той же причине):
      ``test_push_message_keys_match_regular[blocking_failure]`` (8b) и
      ``test_no_duplicate_after_regular_carried_same_snapshot[blocking_failure]`` (9b) — внеочередной по НОВОМУ
      триггеру устроен как регулярный и не дублируется.

  КОНТРОЛИ (зелёные на текущем коде, обязаны остаться зелёными):
    2a ``test_flapping_readiness_is_debounced_in_window``  (первая половина критерия 2)
    4  ``test_non_blocking_change_pushes_nothing``, ``test_non_blocking_added_next_to_blocking_pushes_nothing`` (4b)
    6  ``test_paused_change_still_pushes_*``, ``test_push_does_not_shift_regular_schedule``
    8  ``test_push_message_keys_match_regular[paused]``
    9  ``test_no_duplicate_after_regular_carried_same_snapshot[paused]``

Критерий 7 перенесён автору. Стенд — как у ``test_heartbeat_paused_push``: настоящий ``GenericProcess`` под
``run_process_function`` в daemon-потоке, настоящий ``ProcessHeartbeat``, подменён только ``send_message`` процесса
(кладёт heartbeat в очередь теста). Плагины с переключаемым ``readiness()`` — в этом файле (``SHARED["reasons"]``).
Все ожидания — циклы с дедлайном, выход процесса — join-дедлайн; тесты ничего не коммитят и не трогают код приложения.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

_THIS = "multiprocess_framework.modules.process_module.tests.test_heartbeat_readiness_push"
_JOIN_S = 30.0

#: Граница «не позже»: 0,5 с снимок + антидребезг + запас от мигания стенда (как в ``test_heartbeat_paused_push``).
_PUSH_DEADLINE_S = 1.5
#: Большой интервал: регулярный heartbeat за время теста не наступит, всё внеочередное наблюдаемо.
_LONG_INTERVAL_S = 30.0
#: Интервал сценариев про расписание регулярного heartbeat (сетка отметок ``A + k * T``).
_GRID_INTERVAL_S = 3.0
#: Допуск попадания сообщения в узел сетки регулярных heartbeat.
_GRID_TOL_S = 0.4

NODE_A = "pp_plugin"
NODE_B = "pp_plugin_b"

FAILURE = [{"severity": "failure", "reason": "тест: отказ"}]
CHECK_FUNCTION = [{"severity": "check_function", "reason": "тест: проверка функции"}]
OUT_OF_SPEC = [{"severity": "out_of_spec", "reason": "тест: вне спецификации"}]
MAINTENANCE = [{"severity": "maintenance", "reason": "тест: обслуживание"}]

SHARED: dict[str, Any] = {}


class _ToggleReadiness:
    """Хук ``readiness()`` отдаёт причины из ``SHARED["reasons"][<имя плагина>]`` (переключает тест)."""

    name: str

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [dict(item) for item in SHARED.get("reasons", {}).get(self.name, [])]


class PpPlugin(_ToggleReadiness, ProcessModulePlugin):
    name = NODE_A
    category = "processing"


class PpPluginB(_ToggleReadiness, ProcessModulePlugin):
    name = NODE_B
    category = "processing"


_PLUGIN_CLASS = {NODE_A: "PpPlugin", NODE_B: "PpPluginB"}


class _CaptureHeartbeats:
    """Подмена ``send_message``: heartbeat -> очередь теста, остальное — как у процесса."""

    def send_message(self, target: str, message: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(message, dict) and message.get("command") == "heartbeat":
            out = SHARED.get("queue")
            if out is not None:
                out.put(message)
            return True
        return super().send_message(target, message, *args, **kwargs)  # type: ignore[misc]


class PpPluginProcess(_CaptureHeartbeats, GenericProcess):
    """Настоящий ``GenericProcess`` с плагинами (есть оркестратор, воркеры ``run_watch`` и снимка)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


class _Collector:
    """Фоновый читатель очереди: складывает ``(момент прихода, сообщение)``."""

    def __init__(self, out: Any) -> None:
        self._out = out
        self._lock = threading.Lock()
        self._items: list[tuple[float, dict]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="rp-collector")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._out.get(timeout=0.05)
            except Exception:  # noqa: BLE001 — таймаут очереди
                continue
            with self._lock:
                self._items.append((time.monotonic(), msg))

    def items(self) -> list[tuple[float, dict]]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def wait_for(self, predicate: Any, deadline_s: float) -> tuple[bool, float]:
        """Ждать сообщения под ``predicate`` (уже пришедшие тоже считаются); вернуть (нашли, сколько ждали)."""
        started = time.monotonic()
        end = started + deadline_s
        while time.monotonic() < end:
            if any(predicate(msg) for _, msg in self.items()):
                return True, time.monotonic() - started
            time.sleep(0.02)
        return any(predicate(msg) for _, msg in self.items()), time.monotonic() - started

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5.0)


def _readiness(msg: dict) -> dict | None:
    readiness = msg.get("readiness")
    return readiness if isinstance(readiness, dict) else None


def _ready_of(msg: dict) -> Any:
    """``readiness.ready`` сообщения или ``None`` (нет снимка в сообщении)."""
    readiness = _readiness(msg)
    return None if readiness is None else readiness.get("ready")


def _paused_of(msg: dict) -> Any:
    readiness = _readiness(msg)
    return None if readiness is None else readiness.get("paused")


def _blocking_of(msg: dict) -> set[tuple[str, str]]:
    """Блокирующие причины сообщения как ``{(имя плагина без префикса процесса, severity)}``."""
    readiness = _readiness(msg)
    if readiness is None:
        return set()
    return {
        (str(r.get("node", "")).rsplit(".", 1)[-1], r.get("severity"))
        for r in readiness.get("reasons", [])
        if r.get("severity") in ("failure", "check_function")
    }


def _all_severities(snap: dict | None) -> set[tuple[str, str]]:
    if not snap:
        return set()
    return {(str(r.get("node", "")).rsplit(".", 1)[-1], r.get("severity")) for r in snap.get("reasons", [])}


def _wait(predicate: Any, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _snap() -> dict | None:
    proc = SHARED.get("proc")
    return None if proc is None else proc._readiness_snapshot


def _set_reasons(node: str, reasons: list[dict]) -> None:
    SHARED["reasons"][node] = [dict(r) for r in reasons]


class _Stand:
    """Один настоящий процесс + очередь + сборщик (с момента создания, t=0)."""

    def __init__(self, nodes: tuple[str, ...], heartbeat_interval: float, preset: dict[str, list[dict]]) -> None:
        self.event = multiprocessing.Event()
        self.event.set()
        self.out = multiprocessing.get_context("spawn").Queue()
        SHARED.clear()
        SHARED.update(
            {
                "event": self.event,
                "proc": None,
                "queue": self.out,
                "reasons": {n: [dict(r) for r in preset.get(n, [])] for n in nodes},
            }
        )
        plugins = [{"plugin_class": f"{_THIS}.{_PLUGIN_CLASS[n]}", "plugin_name": n} for n in nodes]
        cfg: dict[str, Any] = {
            "config": {"plugins": plugins, "chain_targets": []},
            "heartbeat_interval": heartbeat_interval,
        }
        self.own_ready = multiprocessing.Event()
        bundle = {
            "queues": {"data": multiprocessing.Queue()},
            "config": cfg,
            "custom": {"process_config": cfg, "ready_event": self.own_ready},
        }
        self.stop_flag = threading.Event()
        self.collector = _Collector(self.out)
        self.thread = threading.Thread(
            target=run_process_function,
            args=(f"{_THIS}.PpPluginProcess", "pp_real", self.stop_flag, bundle, None),
            daemon=True,
            name="rp-real-process",
        )
        self.thread.start()

    def warm_up(self, snap_ok: Any = None, settle_s: float = 1.0) -> None:
        """Дождаться готовности процесса и нужного снимка, дать осесть стартовым сообщениям, очистить сборщик."""
        snap_ok = snap_ok or (lambda s: s.get("ready") is True)
        assert self.own_ready.wait(_JOIN_S), "процесс не объявил готовность"
        assert _wait(lambda: bool(_snap()) and snap_ok(_snap()), 5.0), _snap()
        time.sleep(settle_s)
        self.collector.clear()

    def close(self) -> None:
        self.stop_flag.set()
        self.thread.join(_JOIN_S)
        alive = self.thread.is_alive()
        self.collector.stop()
        self.out.close()
        self.out.cancel_join_thread()
        SHARED.clear()
        assert not alive, "run_process_function не вышел после stop"


@pytest.fixture
def stand_factory():
    """Фабрика стендов; все созданные останавливаются по выходу из теста."""
    made: list[_Stand] = []

    def make(
        nodes: tuple[str, ...] = (NODE_A,),
        heartbeat_interval: float = _LONG_INTERVAL_S,
        preset: dict[str, list[dict]] | None = None,
    ) -> _Stand:
        stand = _Stand(nodes, heartbeat_interval, preset or {})
        made.append(stand)
        return stand

    yield make
    for stand in made:
        stand.close()


# --------------------------------------------------------------------------- #
# Триггеры (для параметризованных тестов 8 и 9)
# --------------------------------------------------------------------------- #


def _fire(stand: _Stand, kind: str) -> None:
    if kind == "paused":
        stand.event.clear()
    else:
        _set_reasons(NODE_A, FAILURE)


def _is_push_of(kind: str, msg: dict) -> bool:
    """Сообщение несёт эффект триггера ``kind``."""
    if kind == "paused":
        return _paused_of(msg) is True
    return _ready_of(msg) is False and (NODE_A, "failure") in _blocking_of(msg)


_TRIGGERS = [
    pytest.param("paused", id="paused"),
    pytest.param("blocking_failure", id="blocking_failure"),
]


# --------------------------------------------------------------------------- #
# Критерий 1: смена готовности -> внеочередной heartbeat (интервал 30 с)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_blocking_failure_pushes_ready_false_heartbeat_with_long_interval(stand_factory) -> None:
    """Плагин -> блокирующий ``failure``: при интервале 30 с принято сообщение ``ready == False`` не позже 1,5 с."""
    stand = stand_factory()
    stand.warm_up()

    _set_reasons(NODE_A, FAILURE)
    # снимок процесса сам смену увидел (иначе красный был бы про стенд, а не про отправку)
    assert _wait(lambda: (_snap() or {}).get("ready") is False, 3.0), _snap()
    found, elapsed = stand.collector.wait_for(lambda m: _ready_of(m) is False, _PUSH_DEADLINE_S)

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert found, f"heartbeat с ready=False не пришёл за {_PUSH_DEADLINE_S} с после смены readiness(); пришло: {got}"
    assert elapsed <= _PUSH_DEADLINE_S, elapsed
    pushed = next(m for _, m in stand.collector.items() if _ready_of(m) is False)
    assert (NODE_A, "failure") in _blocking_of(pushed), pushed.get("readiness")


# --------------------------------------------------------------------------- #
# Критерий 2: серия смен готовности — антидребезг и итоговое значение
# --------------------------------------------------------------------------- #


def _flap_readiness(stand: _Stand) -> tuple[float, float]:
    """21 смена готовности за ~1,05 с (нечётное число: итог ``failure`` -> ``ready False`` отличается от стартового)."""
    started = time.monotonic()
    for i in range(21):
        _set_reasons(NODE_A, FAILURE if i % 2 == 0 else [])
        time.sleep(0.05)
    return started, time.monotonic()


@pytest.mark.timeout(120)
def test_flapping_readiness_is_debounced_in_window(stand_factory) -> None:
    """Контроль (2a): 21 смена за ~1,05 с дают не больше 3 сообщений за это окно."""
    stand = stand_factory()
    stand.warm_up()

    started, flaps_end = _flap_readiness(stand)
    in_window = [m for t, m in stand.collector.items() if started <= t <= flaps_end]

    assert len(in_window) <= 3, f"дребезг не подавлен: {len(in_window)} heartbeat за {flaps_end - started:.2f} с"


@pytest.mark.timeout(120)
def test_flapping_readiness_final_state_delivered_after_quiet(stand_factory) -> None:
    """(2b) После серии и тишины 2,5 с последнее принятое сообщение несёт итог: ``ready == False`` и ``failure``."""
    stand = stand_factory()
    stand.warm_up()

    _flap_readiness(stand)
    time.sleep(2.5)

    assert (_snap() or {}).get("ready") is False, f"снимок процесса не принял итог серии: {_snap()}"
    got = [m for _, m in stand.collector.items()]
    assert got, "после серии смен готовности ни одного heartbeat (итог не доставлен)"
    assert _ready_of(got[-1]) is False, (
        f"последний heartbeat не актуален: ready по порядку = {[_ready_of(m) for m in got]}"
    )
    assert (NODE_A, "failure") in _blocking_of(got[-1]), got[-1].get("readiness")


# --------------------------------------------------------------------------- #
# Критерий 3: боот-защёлка ready False -> True без причин
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_boot_latch_ready_true_without_reasons_is_pushed(stand_factory) -> None:
    """Процесс стартует не готовым и становится готовым без причин: приходит сообщение ``ready == True``.

    Без ``warm_up``: сборщик с t=0. Предусловие — получено хотя бы одно сообщение с ``readiness``, и оно ещё
    ``ready == False`` (иначе боот-защёлка в этом прогоне не наблюдена и тест ничего не проверял бы).
    """
    stand = stand_factory()

    has_snapshot, _ = stand.collector.wait_for(lambda m: _readiness(m) is not None, 15.0)
    assert has_snapshot, "предусловие: ни одного сообщения с readiness за 15 с"
    first = next(m for _, m in stand.collector.items() if _readiness(m) is not None)
    assert _ready_of(first) is False, (
        f"предусловие: первое сообщение с readiness уже ready={_ready_of(first)} — боот-защёлка не наблюдена"
    )
    assert stand.own_ready.wait(_JOIN_S), "процесс не объявил готовность"
    assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()

    found, elapsed = stand.collector.wait_for(lambda m: _ready_of(m) is True, _PUSH_DEADLINE_S)

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert found, f"heartbeat с ready=True не пришёл за {_PUSH_DEADLINE_S} с после готовности без причин; пришло: {got}"
    pushed = next(m for _, m in stand.collector.items() if _ready_of(m) is True)
    assert _readiness(pushed)["reasons"] == [], pushed["readiness"]


# --------------------------------------------------------------------------- #
# Критерий 4: смена только неблокирующего — тишина
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_non_blocking_change_pushes_nothing(stand_factory) -> None:
    """Контроль: ``out_of_spec`` и ``maintenance`` появляются в снимке, но внеочередных сообщений 0."""
    stand = stand_factory()
    stand.warm_up()

    _set_reasons(NODE_A, OUT_OF_SPEC)
    assert _wait(lambda: (NODE_A, "out_of_spec") in _all_severities(_snap()), 3.0), _snap()
    _set_reasons(NODE_A, MAINTENANCE)
    assert _wait(lambda: (NODE_A, "maintenance") in _all_severities(_snap()), 3.0), _snap()
    time.sleep(2.0)

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert got == [], f"смена только неблокирующих причин дала внеочередные сообщения: {got}"


@pytest.mark.timeout(120)
def test_non_blocking_added_next_to_blocking_pushes_nothing(stand_factory) -> None:
    """Контроль (4b): при уже стоящем ``failure`` второй плагин получает ``out_of_spec`` — сообщений 0."""
    stand = stand_factory(nodes=(NODE_A, NODE_B), preset={NODE_A: FAILURE})
    stand.warm_up(snap_ok=lambda s: (NODE_A, "failure") in _all_severities(s))

    _set_reasons(NODE_B, OUT_OF_SPEC)
    assert _wait(lambda: (NODE_B, "out_of_spec") in _all_severities(_snap()), 3.0), _snap()
    time.sleep(2.0)

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert got == [], f"неблокирующая причина рядом с блокирующей дала внеочередные сообщения: {got}"


# --------------------------------------------------------------------------- #
# Критерий 5: набор блокирующих причин (ready не меняется)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_blocking_severity_change_is_pushed(stand_factory) -> None:
    """``failure`` -> ``check_function`` (``ready`` остаётся False): сообщение с ``check_function`` не позже 1,5 с."""
    stand = stand_factory(preset={NODE_A: FAILURE})
    stand.warm_up(snap_ok=lambda s: (NODE_A, "failure") in _all_severities(s))

    _set_reasons(NODE_A, CHECK_FUNCTION)
    assert _wait(lambda: (NODE_A, "check_function") in _all_severities(_snap()), 3.0), _snap()
    found, _ = stand.collector.wait_for(lambda m: (NODE_A, "check_function") in _blocking_of(m), _PUSH_DEADLINE_S)

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert found, f"смена severity failure -> check_function не дошла за {_PUSH_DEADLINE_S} с; пришло: {got}"


@pytest.mark.timeout(120)
def test_second_plugin_blocking_reason_is_pushed(stand_factory) -> None:
    """У первого ``failure``; второй плагин тоже получает ``failure`` (``ready`` остаётся False): сообщение с обоими."""
    stand = stand_factory(nodes=(NODE_A, NODE_B), preset={NODE_A: FAILURE})
    stand.warm_up(snap_ok=lambda s: (NODE_A, "failure") in _all_severities(s))

    _set_reasons(NODE_B, FAILURE)
    assert _wait(lambda: (NODE_B, "failure") in _all_severities(_snap()), 3.0), _snap()
    found, _ = stand.collector.wait_for(
        lambda m: {(NODE_A, "failure"), (NODE_B, "failure")} <= _blocking_of(m), _PUSH_DEADLINE_S
    )

    got = [(_ready_of(m), sorted(_blocking_of(m))) for _, m in stand.collector.items()]
    assert found, f"второй плагин в блокирующих причинах не дошёл за {_PUSH_DEADLINE_S} с; пришло: {got}"


# --------------------------------------------------------------------------- #
# Критерий 6: paused как прежде
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_paused_change_still_pushes_true(stand_factory) -> None:
    """Контроль: ``run_event.clear()`` при интервале 30 с -> сообщение с ``paused == True`` не позже 1,5 с."""
    stand = stand_factory()
    stand.warm_up()

    stand.event.clear()
    found, _ = stand.collector.wait_for(lambda m: _paused_of(m) is True, _PUSH_DEADLINE_S)

    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"heartbeat с paused=True не пришёл за {_PUSH_DEADLINE_S} с; пришло: {got}"


@pytest.mark.timeout(120)
def test_paused_change_still_pushes_false(stand_factory) -> None:
    """Контроль: ``run_event.set()`` после паузы -> сообщение с ``paused == False`` не позже 1,5 с."""
    stand = stand_factory()
    stand.warm_up()
    stand.event.clear()
    assert _wait(lambda: (_snap() or {}).get("paused") is True, 5.0), "после clear() paused снимка не стал True"
    time.sleep(2.0)
    stand.collector.clear()

    stand.event.set()
    found, _ = stand.collector.wait_for(lambda m: _paused_of(m) is False, _PUSH_DEADLINE_S)

    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"heartbeat с paused=False не пришёл за {_PUSH_DEADLINE_S} с; пришло: {got}"


class _GridRun:
    """Итог сценария на сетке регулярных heartbeat (интервал ``_GRID_INTERVAL_S``)."""

    def __init__(self, a: float, grid_point: float, trigger_at: float, after: list[tuple[float, dict]]) -> None:
        self.a = a  # приход первого (стартового, регулярного) сообщения
        self.grid_point = grid_point  # g = A + k*T: последний регулярный перед триггером
        self.trigger_at = trigger_at
        self.after = after  # сообщения после триггера до g + 1,9*T


def _run_on_grid(stand_factory, kind: str) -> _GridRun:
    """Сетка регулярных heartbeat ``A + k*T``; триггер через 0,3 с после узла ``g``; сбор до ``g + 1,9*T``.

    Стартовое сообщение ``A`` — регулярное (внеочередному нужно, чтобы в PM уже уходила готовность). Триггер ставится
    сразу после узла сетки: внеочередное сообщение (<= 1,5 с) обязано прийти до следующего регулярного (``g + T``).
    """
    stand = stand_factory(heartbeat_interval=_GRID_INTERVAL_S)
    ok, _ = stand.collector.wait_for(lambda m: True, 15.0)
    assert ok, "ни одного heartbeat за 15 с"
    a = stand.collector.items()[0][0]
    assert stand.own_ready.wait(_JOIN_S), "процесс не объявил готовность"
    assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()
    ready_at = time.monotonic()
    assert (
        any(_readiness(m) is not None for _, m in stand.collector.items())
        or stand.collector.wait_for(lambda m: _readiness(m) is not None, _GRID_INTERVAL_S + 1.0)[0]
    ), "предусловие: в PM не ушла ни одна готовность (нет регулярного сообщения с readiness)"

    k = 1
    while a + k * _GRID_INTERVAL_S + 0.3 < ready_at + 1.0:
        k += 1
    g = a + k * _GRID_INTERVAL_S
    trigger_at = g + 0.3
    time.sleep(max(0.0, trigger_at - time.monotonic()))
    _fire(stand, kind)
    end = g + 1.9 * _GRID_INTERVAL_S
    time.sleep(max(0.0, end - time.monotonic()))
    after = [(t, m) for t, m in stand.collector.items() if t >= trigger_at]
    return _GridRun(a, g, trigger_at, after)


@pytest.mark.timeout(120)
def test_push_does_not_shift_regular_schedule(stand_factory) -> None:
    """Контроль: после внеочередного (смена ``paused``) регулярный heartbeat остаётся в узле сетки ``g + T``."""
    run = _run_on_grid(stand_factory, "paused")

    pushes = [t for t, m in run.after if _paused_of(m) is True and t < run.grid_point + _GRID_INTERVAL_S - _GRID_TOL_S]
    seen = [(round(t - run.trigger_at, 2), _paused_of(m)) for t, m in run.after]
    assert pushes, f"внеочередное сообщение с paused=True не пришло до следующего узла; после триггера: {seen}"
    next_node = run.grid_point + _GRID_INTERVAL_S
    near = [t for t, _ in run.after if abs(t - next_node) <= _GRID_TOL_S]
    assert near, (
        f"регулярный heartbeat не пришёл в узел сетки g+T ({_GRID_TOL_S} с допуска): расписание сдвинуто; "
        f"приходы относительно узла: {[round(t - next_node, 2) for t, _ in run.after]}"
    )


# --------------------------------------------------------------------------- #
# Критерий 8: ключи внеочередного = ключи регулярного
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
@pytest.mark.parametrize("kind", _TRIGGERS)
def test_push_message_keys_match_regular(stand_factory, kind: str) -> None:
    """Контроль для ``paused`` (8), красный для ``blocking_failure`` (8b): те же ключи, что у регулярного, и ``pid``."""
    stand = stand_factory()
    ok, _ = stand.collector.wait_for(lambda m: _readiness(m) is not None, 15.0)
    assert ok, "предусловие: регулярного сообщения с readiness нет"
    regular = next(m for _, m in stand.collector.items() if _readiness(m) is not None)
    stand.warm_up()

    _fire(stand, kind)
    found, _ = stand.collector.wait_for(lambda m: _is_push_of(kind, m), _PUSH_DEADLINE_S)
    assert found, f"внеочередное сообщение ({kind}) не пришло за {_PUSH_DEADLINE_S} с"
    pushed = next(m for _, m in stand.collector.items() if _is_push_of(kind, m))

    assert set(pushed) == set(regular), (
        f"ключи расходятся: внеочередной {sorted(pushed)} vs регулярный {sorted(regular)}"
    )
    assert isinstance(pushed.get("pid"), int) and pushed["pid"] == regular["pid"], (
        pushed.get("pid"),
        regular.get("pid"),
    )


# --------------------------------------------------------------------------- #
# Критерий 9: дубля нет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
@pytest.mark.parametrize("kind", _TRIGGERS)
def test_no_duplicate_after_regular_carried_same_snapshot(stand_factory, kind: str) -> None:
    """Контроль для ``paused`` (9), красный для ``blocking_failure`` (9b).

    Смена -> внеочередное сообщение -> регулярный heartbeat узла ``g+T`` несёт тот же снимок -> до ``g+1,9T`` других
    сообщений нет: после регулярного с тем же снимком внеочередное не шлётся.
    """
    run = _run_on_grid(stand_factory, kind)
    next_node = run.grid_point + _GRID_INTERVAL_S

    got = [(round(t - run.trigger_at, 2), _is_push_of(kind, m)) for t, m in run.after]
    off_grid = [t for t, _ in run.after if abs(t - next_node) > _GRID_TOL_S]
    on_grid = [m for t, m in run.after if abs(t - next_node) <= _GRID_TOL_S]
    assert off_grid, f"внеочередное сообщение ({kind}) не пришло: после триггера {got}"
    assert len(off_grid) == 1, f"кроме внеочередного есть ещё внесеточные сообщения (дубль): после триггера {got}"
    assert off_grid[0] < next_node - _GRID_TOL_S, got
    assert len(on_grid) == 1 and _is_push_of(kind, on_grid[0]), (
        f"регулярный heartbeat узла g+T должен нести тот же снимок; после триггера {got}"
    )
