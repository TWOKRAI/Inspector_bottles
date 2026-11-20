# -*- coding: utf-8 -*-
"""P3r: чтение УЗЛА из read-model, хранящей листья (acceptance, слепой tester, стадия RED).

После П3 ``TelemetryReadModel`` хранит ЛИСТЬЯ: dict-дельта по узлу раскладывается
на листья, ``snapshot("a.n")`` даёт плоские ``{"a.n.x": 3}``, ``get("a.n")`` -> None.
Потребители backend_ctl, спрашивающие путь УЗЛА, видят «пути нет».

Контракт (будет создан реализацией): ``backend_ctl._node_read.read_node(drv, path)
-> tuple[bool, Any]`` — сам берёт ``drv._telemetry_lock``, ровно один вызов
``drv._telemetry_model.snapshot(path)``. Правила:

  (R1) путь есть как лист -> ``(True, значение)`` (значение может быть None);
       лист-предок побеждает потомков и не бросает;
  (R2) иначе есть ключи с префиксом ``path + "."`` -> ``(True, вложенный dict)``
       относительно path, ключи режутся по ``.``; конфликт «лист и потомок» внутри
       поддерева — лист-предок побеждает;
  (R3) иначе ``(False, None)``; ``read_node(drv, "")`` -> ``(False, None)``.

Номера в именах/докстроках (1..10) — пункты REDS брифа.

Импорт ``read_node`` ЛЕНИВЫЙ (внутри тестов): иначе весь файл падал бы ImportError на
сборке, и поведенческие красные 4/5/6 были бы неотличимы от «модуля ещё нет».
Тесты, зовущие боевые пути (await_condition / state_get), идут в daemon-потоке с
join-дедлайном: двойной захват обычного ``drv._telemetry_lock`` даёт ЗАВИСАНИЕ, не исключение.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.recorder import Recorder, ReplayPlayer, load_recording
from backend_ctl.tests.conftest import wire_line as _line

#: Потолок на любой вызов боевого пути: на здоровом коде это миллисекунды.
_DEADLINE_SEC = 5.0


# --------------------------------------------------------------------------- #
#  Хелперы                                                                     #
# --------------------------------------------------------------------------- #


def _read_node() -> Callable[[Any, str], tuple]:
    """Ленивый импорт интерфейса (на базе: ImportError — ожидаемый красный)."""
    from backend_ctl._node_read import read_node

    return read_node


def _state_line(path: str, value: Any) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}})


def _state_push(path: str, value: Any) -> Dict[str, Any]:
    return {"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}


def _bounded(fn: Callable[[], Any], what: str) -> Any:
    """Выполнить ``fn`` в daemon-потоке с join-дедлайном; зависание -> pytest.fail.

    Исключение из ``fn`` пробрасывается как есть (чтобы RuntimeError не маскировался).
    """
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name=f"p3r-{what}")
    th.start()
    th.join(_DEADLINE_SEC)
    if th.is_alive():
        pytest.fail(f"зависание: {what} не вернулся за {_DEADLINE_SEC} с (вероятен двойной захват _telemetry_lock)")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _driver_with(path: str, value: Any) -> BackendDriver:
    """Настоящий driver; дельта попала в настоящую read-model под локом драйвера."""
    drv = BackendDriver()
    with drv._telemetry_lock:
        drv._telemetry_model.ingest(path, value)
    return drv


def _read(drv: BackendDriver, path: str) -> tuple:
    return _bounded(lambda: _read_node()(drv, path), f"read_node({path!r})")


# --------------------------------------------------------------------------- #
#  RED 1 — узел собирается из листьев во вложенный dict                         #
# --------------------------------------------------------------------------- #


def test_red1_flat_node_rebuilt_from_leaves() -> None:
    """1: ``ingest("a.n", {"x": 3})`` -> ``(True, {"x": 3})``."""
    drv = _driver_with("a.n", {"x": 3})
    assert _read(drv, "a.n") == (True, {"x": 3})


def test_red1_two_level_node_rebuilt_nested() -> None:
    """1: двухуровневый ``{"p": {"q": 1}, "r": 2}`` приходит тем же вложенным dict."""
    drv = _driver_with("a.n", {"p": {"q": 1}, "r": 2})
    assert _read(drv, "a.n") == (True, {"p": {"q": 1}, "r": 2})


# --------------------------------------------------------------------------- #
#  RED 2 — лист / None / отсутствие / пустой путь                               #
# --------------------------------------------------------------------------- #


def test_red2_leaf_returns_value() -> None:
    """2: лист ``a.n.x`` -> ``(True, 3)``."""
    drv = _driver_with("a.n", {"x": 3})
    assert _read(drv, "a.n.x") == (True, 3)


def test_red2_leaf_with_none_value_is_found() -> None:
    """2: лист со значением None — НАЙДЕН: ``(True, None)``, а не «пути нет»."""
    drv = _driver_with("a.n.x", None)
    assert _read(drv, "a.n.x") == (True, None)


def test_red2_missing_path_is_not_found() -> None:
    """2: отсутствующий ``a.zz`` (при живых соседях) -> ``(False, None)``."""
    drv = _driver_with("a.n", {"x": 3})
    assert _read(drv, "a.zz") == (False, None)


def test_red2_empty_path_is_not_found() -> None:
    """2: ``read_node(drv, "")`` -> ``(False, None)`` (пустой путь — не «весь снимок»)."""
    drv = _driver_with("a.n", {"x": 3})
    assert _read(drv, "") == (False, None)


def test_red2_partial_segment_is_not_a_prefix() -> None:
    """2: лист ``a.nn.x`` не делает ``a.n`` узлом — префикс считается по границе-точке, не по строке."""
    drv = _driver_with("a.nn", {"x": 3})
    assert _read(drv, "a.n") == (False, None)


# --------------------------------------------------------------------------- #
#  RED 3 — граница-точка между соседями с общим строковым префиксом             #
# --------------------------------------------------------------------------- #


def test_red3_neighbour_with_common_string_prefix_does_not_leak() -> None:
    """3: при ``a.n.x`` и ``a.n2.y`` чтение ``a.n`` — только ``{"x": ...}``; ``a.n2`` — только ``y``."""
    drv = BackendDriver()
    with drv._telemetry_lock:
        drv._telemetry_model.ingest("a.n", {"x": 1})
        drv._telemetry_model.ingest("a.n2", {"y": 2})
    assert _read(drv, "a.n") == (True, {"x": 1})
    assert _read(drv, "a.n2") == (True, {"y": 2})


# --------------------------------------------------------------------------- #
#  RED 4 — await_condition на пути узла (настоящий BackendDriver)               #
# --------------------------------------------------------------------------- #


def test_red4_await_state_path_matches_node_value_from_read_model() -> None:
    """4: дельта пришла ДО вызова; ожидание dict-значения узла -> success, source read-model."""
    drv = BackendDriver()
    drv.dispatch_raw(_state_line("a.n", {"x": 3}))
    res = _bounded(
        lambda: drv.await_condition("state_path", {"path": "a.n", "value": {"x": 3}}, timeout=2.0),
        "await_condition(state_path, узел)",
    )
    assert res["success"] is True, res
    assert res["matched"]["source"] == "read-model"


def test_red4_await_state_path_other_dict_times_out_with_nested_last_seen() -> None:
    """4: ожидание ДРУГОГО dict (``{"x": 9}``) -> короткий таймаут; ``last_seen.value`` — вложенный dict."""
    drv = BackendDriver()
    drv.dispatch_raw(_state_line("a.n", {"x": 3}))
    res = _bounded(
        lambda: drv.await_condition("state_path", {"path": "a.n", "value": {"x": 9}}, timeout=0.3),
        "await_condition(state_path, чужой dict)",
    )
    assert res["success"] is False and res["timed_out"] is True, res
    assert res["last_seen"] is not None, res
    assert res["last_seen"]["value"] == {"x": 3}, res["last_seen"]


# --------------------------------------------------------------------------- #
#  RED 5 — metric_threshold на пути узла                                        #
# --------------------------------------------------------------------------- #


def test_red5_metric_threshold_on_node_path_reports_nested_last_seen() -> None:
    """5: порог по узлу ``a.n``: не падает, ``last_seen`` = ``{"path": "a.n", "value": {"x": 3}}``,
    порог не пересечён, ключа ``unknown_metric`` в ответе НЕТ (узел известен, а не опечатка)."""
    drv = BackendDriver()
    drv.dispatch_raw(_state_line("a.n", {"x": 3}))
    res = _bounded(
        lambda: drv.await_condition("metric_threshold", {"path": "a.n", "op": ">=", "value": 10}, timeout=0.3),
        "await_condition(metric_threshold, узел)",
    )
    assert res["success"] is False and res["timed_out"] is True, res
    assert res["last_seen"] is not None, res
    assert res["last_seen"]["path"] == "a.n", res["last_seen"]
    assert res["last_seen"]["value"] == {"x": 3}, res["last_seen"]
    assert "unknown_metric" not in res, res


# --------------------------------------------------------------------------- #
#  RED 6 — реплей: оба пути попадания узла в read-model                         #
# --------------------------------------------------------------------------- #


def _header_only_recording(tmp_path: Path, snapshot: Dict[str, Any]) -> str:
    """Запись только с header-снимком (событий нет) — форма файла как у Recorder."""
    path = tmp_path / "hdr.jsonl"
    lines = [
        {"format": "bctl-record", "version": 1, "snapshot": snapshot},
        {"footer": True, "events_written": 0, "dropped": 0, "reason": "stopped"},
    ]
    path.write_text("\n".join(json.dumps(ln) for ln in lines) + "\n", encoding="utf-8")
    return str(path)


def _wait_written(rec: Recorder, n: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while rec._events_written < n and time.monotonic() < deadline:
        time.sleep(0.01)


def _events_recording(tmp_path: Path, path: str, value: Any) -> str:
    """Настоящий Recorder пишет событие ``state.changed`` (узел целиком) в файл."""
    drv = BackendDriver("127.0.0.1", 8765)
    out = str(tmp_path / "ev.jsonl")
    rec = Recorder(drv, out)
    rec.start()
    drv._emit_event(_state_push(path, value))
    _wait_written(rec, 1)
    rec.stop()
    return out


def _player_header_state(tmp_path: Path, value: Any) -> ReplayPlayer:
    """6а: узел приходит из снимка header — секция ``state`` (дерево) -> prime."""
    tree = {"a": {"n": value}}
    rec = load_recording(_header_only_recording(tmp_path, {"state": {"status": "ok", "value": tree}}))
    return ReplayPlayer(rec, position="end")


def _player_header_telemetry(tmp_path: Path, value: Any) -> ReplayPlayer:
    """6а': header несёт плоский ``telemetry.values`` (так пишет сам Recorder из read-model)."""
    flat: Dict[str, Any] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}", v)
        else:
            flat[prefix] = node

    walk("a.n", value)
    rec = load_recording(_header_only_recording(tmp_path, {"telemetry": {"values": flat, "history": {}}}))
    return ReplayPlayer(rec, position="end")


def _player_events(tmp_path: Path, value: Any) -> ReplayPlayer:
    """6б: узел приходит из событий ``state.changed`` записи (header пуст)."""
    return ReplayPlayer(load_recording(_events_recording(tmp_path, "a.n", value)), position="end")


_NODE_SHAPES = {
    "flat": {"x": 3},
    "two-level": {"p": {"q": 1}, "r": 2},
}
_ROUTES = {
    "header-state-tree": _player_header_state,
    "header-telemetry-values": _player_header_telemetry,
    "events-state-changed": _player_events,
}


@pytest.mark.parametrize("shape", sorted(_NODE_SHAPES))
@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_red6_replay_state_get_node_returns_nested_dict(tmp_path: Path, route: str, shape: str) -> None:
    """6: ``ReplayPlayer.state_get("a.n")`` -> ``status: ok``, ``value`` — вложенный dict, ``recorded: True``."""
    value = _NODE_SHAPES[shape]
    player = _ROUTES[route](tmp_path, value)
    res = _bounded(lambda: player.state_get("a.n"), "ReplayPlayer.state_get(узел)")
    assert res["status"] == "ok", res
    assert res["value"] == value, res
    assert res["recorded"] is True, res


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_red6_replay_state_get_missing_path_keeps_error_text(tmp_path: Path, route: str) -> None:
    """6: отсутствующий путь — прежний ``status: error`` с текстом «Путь не существует: '<путь>'»."""
    player = _ROUTES[route](tmp_path, {"x": 3})
    res = _bounded(lambda: player.state_get("a.zz"), "ReplayPlayer.state_get(нет пути)")
    assert res["status"] == "error", res
    assert "Путь не существует: 'a.zz'" in res["error"], res


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_red6_replay_state_get_empty_path_stays_error(tmp_path: Path, route: str) -> None:
    """6: ``state_get("")`` — прежний ``status: error`` (пустой путь не «весь снимок»)."""
    player = _ROUTES[route](tmp_path, {"x": 3})
    res = _bounded(lambda: player.state_get(""), "ReplayPlayer.state_get('')")
    assert res["status"] == "error", res


# --------------------------------------------------------------------------- #
#  RED 7 — гонка: запись узла против чтения (лок драйвера)                      #
# --------------------------------------------------------------------------- #

_RACE_SEC = 0.7  # бюджет на плечо
_WRITER_CAP = 6000  # потолок записей: писатель без паузы забивает EventHub


def _race_value(i: int) -> Dict[str, Any]:
    """Форма узла с инвариантом ``x == y`` и меняющимся числом листьев (0..4 лишних)."""
    node: Dict[str, Any] = {"x": i, "y": i}
    for j in range(i % 5):
        node[f"k{j}"] = j
    return node


def _race(reader: Callable[[BackendDriver, List[str]], None]) -> List[str]:
    """Общий каркас: узел записан ДО потоков; писатель — только ``dispatch_raw``;
    читатель крутится ``_RACE_SEC``. Возвращает список нарушений (пусто = чисто)."""
    drv = BackendDriver()
    drv.dispatch_raw(_state_line("a.n", _race_value(0)))  # узел существует до старта потоков
    problems: List[str] = []
    stop = threading.Event()

    def writer() -> None:
        try:
            for i in range(1, _WRITER_CAP):
                if stop.is_set():
                    break
                drv.dispatch_raw(_state_line("a.n", _race_value(i)))
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"писатель упал: {exc!r}")

    def read_loop() -> None:
        try:
            reader(drv, problems)
        except BaseException as exc:  # noqa: BLE001 — RuntimeError "dictionary changed size" и пр.
            problems.append(f"читатель упал: {exc!r}")

    w = threading.Thread(target=writer, daemon=True, name="p3r-race-writer")
    r = threading.Thread(target=read_loop, daemon=True, name="p3r-race-reader")
    w.start()
    r.start()
    r.join(_RACE_SEC + _DEADLINE_SEC)
    stop.set()
    w.join(_DEADLINE_SEC)
    if r.is_alive() or w.is_alive():
        problems.append("зависание потока гонки (читатель или писатель не завершился)")
    return problems


def test_red7_race_read_node_never_torn_nor_raises() -> None:
    """7 (плечо read_node): ни исключений, ни значений с ``x != y``, узел всегда найден."""
    read_node = _read_node()

    def reader(drv: BackendDriver, problems: List[str]) -> None:
        deadline = time.monotonic() + _RACE_SEC
        reads = 0
        while time.monotonic() < deadline and not problems:
            found, value = read_node(drv, "a.n")
            reads += 1
            if found is not True:
                problems.append(f"узел пропал посреди записи: {(found, value)!r}")
            elif not isinstance(value, dict) or value.get("x") != value.get("y"):
                problems.append(f"рваное чтение: {value!r}")
        if reads == 0:
            problems.append("читатель не сделал ни одного чтения")

    assert _race(reader) == []


def test_red7_race_await_condition_last_seen_never_torn() -> None:
    """7 (плечо await): ``await_condition(..., timeout=0)`` в цикле — ни исключений, ни зависания;
    ``last_seen`` обязан быть непустым и с ``x == y`` (узел существует до старта потоков)."""

    def reader(drv: BackendDriver, problems: List[str]) -> None:
        deadline = time.monotonic() + _RACE_SEC
        calls = 0
        while time.monotonic() < deadline and not problems:
            res = drv.await_condition("state_path", {"path": "a.n", "value": {"x": -1, "y": -2}}, timeout=0)
            calls += 1
            seen = res.get("last_seen")
            if not seen:
                problems.append(f"last_seen пуст при существующем узле: {res!r}")
                continue
            value = seen.get("value")
            if not isinstance(value, dict) or value.get("x") != value.get("y"):
                problems.append(f"рваный last_seen: {value!r}")
        if calls == 0:
            problems.append("ни одного вызова await_condition")

    assert _race(reader) == []


# --------------------------------------------------------------------------- #
#  RED 8 — расхождения с живым state.get зафиксированы литералами               #
# --------------------------------------------------------------------------- #


def test_red8_empty_dict_node_is_not_found() -> None:
    """8: ``ingest("a.n", {})`` -> ``(False, None)`` (листьев нет — узла в снимке нет)."""
    drv = _driver_with("a.n", {})
    assert _read(drv, "a.n") == (False, None)


def test_red8_nested_empty_dict_is_dropped() -> None:
    """8: ``{"x": 3, "e": {}}`` -> ``(True, {"x": 3})`` (пустой вложенный dict не восстанавливается)."""
    drv = _driver_with("a.n", {"x": 3, "e": {}})
    assert _read(drv, "a.n") == (True, {"x": 3})


def test_red8_dotted_key_is_split_into_nesting() -> None:
    """8: ``{"k.dot": 1}`` -> ``(True, {"k": {"dot": 1}})`` (ключи режутся по ``.``)."""
    drv = _driver_with("a.n", {"k.dot": 1})
    assert _read(drv, "a.n") == (True, {"k": {"dot": 1}})


# --------------------------------------------------------------------------- #
#  RED 9 — смесь «лист и потомок» (push против ответа опроса)                   #
# --------------------------------------------------------------------------- #


def _poll(drv: BackendDriver, values: Dict[str, Any]) -> None:
    """Влить ответ опроса так, как это делает опрашивающий: номер снят под локом драйвера."""
    with drv._telemetry_lock:
        m = drv._telemetry_model
        m.ingest_poll_snapshot(values, requested_at_seq=m.write_seq)


def _mixed_push_then_poll() -> BackendDriver:
    drv = BackendDriver()
    with drv._telemetry_lock:
        drv._telemetry_model.ingest("a.n.p", 5)
    _poll(drv, {"a.n.p.q": 1})
    return drv


def _mixed_poll_after_leaf_below() -> BackendDriver:
    """Обратный порядок записи: сначала потомок ``a.n.p.q``, затем poll кладёт лист ``a.n.p = 5``."""
    drv = BackendDriver()
    with drv._telemetry_lock:
        drv._telemetry_model.ingest("a.n.p.q", 1)
    _poll(drv, {"a.n.p": 5})
    return drv


@pytest.mark.parametrize("build", [_mixed_push_then_poll, _mixed_poll_after_leaf_below], ids=["p-then-q", "q-then-p"])
def test_red9_leaf_ancestor_wins_inside_subtree(build: Callable[[], BackendDriver]) -> None:
    """9: в снимке и ``a.n.p``, и ``a.n.p.q``; ``read_node("a.n")`` не бросает и равен ``(True, {"p": 5})``."""
    drv = build()
    snap = drv._telemetry_model.snapshot("a.n")
    assert snap == {"a.n.p": 5, "a.n.p.q": 1}, f"предпосылка теста нарушена, снимок: {snap!r}"
    assert _read(drv, "a.n") == (True, {"p": 5})


@pytest.mark.parametrize("build", [_mixed_push_then_poll, _mixed_poll_after_leaf_below], ids=["p-then-q", "q-then-p"])
def test_red9_leaf_ancestor_read_directly_returns_leaf(build: Callable[[], BackendDriver]) -> None:
    """9: ``read_node("a.n.p")`` -> ``(True, 5)`` — лист-предок побеждает потомка ``a.n.p.q``."""
    assert _read(build(), "a.n.p") == (True, 5)


def test_red9_leaf_at_node_path_wins_over_descendant_leaf() -> None:
    """9: ``ingest("a.n.x", 1)``, затем poll ``a.n = 5`` -> ``read_node("a.n")`` = ``(True, 5)``."""
    drv = BackendDriver()
    with drv._telemetry_lock:
        drv._telemetry_model.ingest("a.n.x", 1)
    _poll(drv, {"a.n": 5})
    snap = drv._telemetry_model.snapshot("a.n")
    assert snap == {"a.n.x": 1, "a.n": 5}, f"предпосылка теста нарушена, снимок: {snap!r}"
    assert _read(drv, "a.n") == (True, 5)


# --------------------------------------------------------------------------- #
#  RED 10 — инвариант одного чтения: у модели достаточно ОДНОГО snapshot        #
# --------------------------------------------------------------------------- #


class _SnapshotOnlyModel:
    """Модель с единственным методом ``snapshot(prefix)`` (граница — точка, как у настоящей).

    Нет ``get`` — по построению: код, зовущий ``model.get(...)``, упадёт AttributeError.
    Фиксирует, ПОД ЛОКОМ ли шло чтение, и сколько раз его позвали.
    """

    def __init__(self, flat: Dict[str, Any], lock: Any) -> None:
        self._flat = flat
        self._lock = lock
        self.calls: List[str] = []
        self.lock_held_during_call: List[bool] = []

    def snapshot(self, prefix: str) -> Dict[str, Any]:
        self.calls.append(prefix)
        self.lock_held_during_call.append(self._lock.locked())
        dotted = prefix + "."
        return {p: v for p, v in self._flat.items() if p == prefix or p.startswith(dotted)}


class _DriverShell:
    """Обёртка-драйвер: только то, что читает ``read_node`` (лок и модель)."""

    def __init__(self, flat: Dict[str, Any]) -> None:
        self._telemetry_lock = threading.Lock()
        self._telemetry_model = _SnapshotOnlyModel(flat, self._telemetry_lock)


@pytest.mark.parametrize(
    ("flat", "path", "expected"),
    [
        ({"a.n.x": 3}, "a.n", (True, {"x": 3})),
        ({"a.n.x": 3}, "a.n.x", (True, 3)),
        ({"a.n.x": 3}, "a.zz", (False, None)),
    ],
    ids=["node", "leaf", "missing"],
)
def test_red10_one_snapshot_call_under_lock_no_get(flat: Dict[str, Any], path: str, expected: tuple) -> None:
    """10: стаб без ``get`` проходит ``read_node``; ровно один ``snapshot(path)``, и он под локом драйвера."""
    shell = _DriverShell(flat)
    assert not hasattr(shell._telemetry_model, "get")
    result = _bounded(lambda: _read_node()(shell, path), f"read_node(стаб, {path!r})")
    assert result == expected
    assert shell._telemetry_model.calls == [path]
    assert shell._telemetry_model.lock_held_during_call == [True]
    assert not shell._telemetry_lock.locked(), "лок обязан быть отпущен после чтения"
