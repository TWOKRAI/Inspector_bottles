"""
Приёмочные тесты (слепые, RED до кода) задачи 1.1 плана lifecycle-owner-scope.

Контракт:
  * ``core.stop_budget``: функция ``stop_budget(shutdown_timeout)`` и константы окон;
  * ``core.child_process_stop.ChildProcessStop``: остановка группы детей с метками
    «подтверждённо мёртв» (request_stop / join_until / kill / survivors / close);
  * ``ProcessRegistry(child_stop_budget=...)``: ключ ``stop_budget`` в конфиге ребёнка.

Тесты строятся на дублёрах процессов и событий (настоящие процессы не запускаются).
Модули контракта импортируются ВНУТРИ тестов: пока модуля нет, каждый тест красный по
отдельности (ModuleNotFoundError), а не весь файл — ошибкой сбора.

Ожидаемые значения — литералы. Сравнения времени — с допуском не меньше 0.1 с:
дискретность ``time.monotonic()`` на Windows 15,6 мс. Всё, что может зависнуть,
гоняется в daemon-потоке со сроком ``join``.
"""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any, Callable

import pytest

from ..core.process_registry import ProcessRegistry

_CORE = "multiprocess_framework.modules.process_manager_module.core"

_KEYS = ["work_s", "infra_s", "pm_graceful_s", "pm_total_s", "outer_s"]


def _budget_mod() -> Any:
    return importlib.import_module(f"{_CORE}.stop_budget")


def _stop_cls() -> Any:
    return importlib.import_module(f"{_CORE}.child_process_stop").ChildProcessStop


# ---------------------------------------------------------------------------
# Дублёры и помощники
# ---------------------------------------------------------------------------


class FakeProc:
    """Дублёр процесса: ``is_alive/terminate/kill`` с записью момента каждого вызова.

    ``die_at`` — абсолютный ``time.monotonic()``, с которого процесс мёртв;
    ``die_when`` — предикат, при истинности которого процесс мёртв;
    ``dies_on_terminate`` / ``dies_on_kill`` — смерть от соответствующего сигнала.
    """

    def __init__(
        self,
        name: str,
        *,
        die_at: float | None = None,
        die_when: Callable[[], bool] | None = None,
        dies_on_terminate: bool = False,
        dies_on_kill: bool = False,
        terminate_raises: bool = False,
        kill_raises: bool = False,
        dead: bool = False,
    ) -> None:
        self.name = name
        self._die_at = die_at
        self._die_when = die_when
        self._dies_on_terminate = dies_on_terminate
        self._dies_on_kill = dies_on_kill
        self._terminate_raises = terminate_raises
        self._kill_raises = kill_raises
        self._dead = dead
        self.death_t: float | None = time.monotonic() if dead else None
        self.terminate_t: list[float] = []
        self.kill_t: list[float] = []
        self.alive_calls = 0

    def _die(self, when: float | None = None) -> None:
        if not self._dead:
            self._dead = True
            self.death_t = time.monotonic() if when is None else when

    def is_alive(self) -> bool:
        self.alive_calls += 1
        if not self._dead:
            if self._die_at is not None and time.monotonic() >= self._die_at:
                self._die(self._die_at)
            elif self._die_when is not None and self._die_when():
                self._die()
        return not self._dead

    def terminate(self) -> None:
        self.terminate_t.append(time.monotonic())
        if self._terminate_raises:
            raise RuntimeError("terminate boom")
        if self._dies_on_terminate:
            self._die()

    def kill(self) -> None:
        self.kill_t.append(time.monotonic())
        if self._kill_raises:
            raise RuntimeError("kill boom")
        if self._dies_on_kill:
            self._die()


class FakeEvent:
    """Дублёр stop_event: запись вызовов ``set()``."""

    def __init__(self) -> None:
        self.set_calls: list[float] = []

    def set(self) -> None:
        self.set_calls.append(time.monotonic())


class Marks:
    """Журнал меток ``on_confirmed_dead(name, process)``; ``delay_s`` — медленный колбэк."""

    def __init__(self, delay_s: float = 0.0, raise_for: tuple[str, ...] = ()) -> None:
        self.names: list[str] = []
        self.times: dict[str, float] = {}
        self.procs: dict[str, Any] = {}
        self._delay_s = delay_s
        self._raise_for = raise_for

    def __call__(self, name: str, process: Any) -> None:
        self.names.append(name)
        self.times.setdefault(name, time.monotonic())
        self.procs.setdefault(name, process)
        if self._delay_s:
            time.sleep(self._delay_s)
        if name in self._raise_for:
            raise RuntimeError("mark boom")


def _run_bounded(fn: Callable[[], Any], limit_s: float = 10.0) -> Any:
    """Вызвать ``fn`` в daemon-потоке; зависание — провал теста, а не зависший прогон."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(limit_s)
    if th.is_alive():
        pytest.fail(f"вызов завис дольше {limit_s} с")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _make(
    procs: list[FakeProc],
    *,
    marks: Marks | None = None,
    grace: float = 0.3,
    confirm: float = 1.0,
    poll: float = 0.01,
) -> tuple[Any, dict[str, FakeProc], dict[str, FakeEvent]]:
    processes = {p.name: p for p in procs}
    events = {p.name: FakeEvent() for p in procs}
    cs = _stop_cls()(
        processes,
        events,
        on_confirmed_dead=marks,
        terminate_grace_s=grace,
        kill_confirm_s=confirm,
        poll_s=poll,
    )
    return cs, processes, events


# ---------------------------------------------------------------------------
# stop_budget
# ---------------------------------------------------------------------------


def test_stop_budget_literals() -> None:
    """Окна для 5.0 и 1.0: значения и порядок ключей."""
    sb = _budget_mod().stop_budget

    r5 = sb(5.0)
    assert isinstance(r5, dict)
    assert list(r5) == _KEYS
    assert r5["work_s"] == pytest.approx(3.0)
    assert r5["infra_s"] == pytest.approx(1.0)
    assert r5["pm_graceful_s"] == pytest.approx(5.0)
    assert r5["pm_total_s"] == pytest.approx(7.0)
    assert r5["outer_s"] == pytest.approx(8.5)

    r1 = sb(1.0)
    assert list(r1) == _KEYS
    assert r1["work_s"] == pytest.approx(0.6)
    assert r1["infra_s"] == pytest.approx(0.2)
    assert r1["pm_graceful_s"] == pytest.approx(1.0)
    assert r1["pm_total_s"] == pytest.approx(3.0)
    assert r1["outer_s"] == pytest.approx(4.5)


@pytest.mark.parametrize("value", [None, 0, 0.0])
def test_stop_budget_default_for_none_and_zero(value: Any) -> None:
    """``None``, ``0``, ``0.0`` — как для 5.0."""
    r = _budget_mod().stop_budget(value)
    assert list(r) == _KEYS
    assert r["work_s"] == pytest.approx(3.0)
    assert r["infra_s"] == pytest.approx(1.0)
    assert r["pm_graceful_s"] == pytest.approx(5.0)
    assert r["pm_total_s"] == pytest.approx(7.0)
    assert r["outer_s"] == pytest.approx(8.5)


def test_stop_budget_constants() -> None:
    """Константы окон — литералы контракта."""
    m = _budget_mod()
    assert m.STOP_POLL_S == pytest.approx(0.05)
    assert m.TERMINATE_GRACE_S == pytest.approx(1.0)
    assert m.KILL_CONFIRM_S == pytest.approx(1.0)
    assert m.PM_TEARDOWN_MARGIN_S == pytest.approx(1.5)
    assert m.DEFAULT_SHUTDOWN_TIMEOUT_S == pytest.approx(5.0)
    assert m.KILL_RESERVE_S == pytest.approx(2.0)
    assert m.SHUTDOWN_TIMEOUT_KEY == "shutdown_timeout"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0, -0.001])
def test_stop_budget_rejects_bad_numbers(value: float) -> None:
    """NaN, бесконечность и отрицательное — ``ValueError``."""
    with pytest.raises(ValueError):
        _budget_mod().stop_budget(value)


@pytest.mark.parametrize("value", [True, "secret-xyz-77"])
def test_stop_budget_rejects_bad_types(value: Any) -> None:
    """``True`` и строка — ``TypeError``."""
    with pytest.raises(TypeError):
        _budget_mod().stop_budget(value)


def test_stop_budget_error_text_does_not_echo_value() -> None:
    """Текст ошибки не содержит само значение (ни числа, ни строки)."""
    sb = _budget_mod().stop_budget
    with pytest.raises(ValueError) as ei_num:
        sb(-123.456)
    assert "123.456" not in str(ei_num.value)
    with pytest.raises(TypeError) as ei_str:
        sb("secret-xyz-77")
    assert "secret-xyz-77" not in str(ei_str.value)


# ---------------------------------------------------------------------------
# ChildProcessStop: request_stop / сигналы
# ---------------------------------------------------------------------------


def test_request_stop_sets_events_of_live_only_and_does_not_block() -> None:
    """``request_stop`` зовёт ``set()`` у событий живых; у мёртвых — нет; повтор безвреден."""
    live_a = FakeProc("A")
    live_b = FakeProc("B")
    dead_c = FakeProc("C", dead=True)
    cs, _procs, events = _make([live_a, live_b, dead_c], grace=0.6)

    t0 = time.monotonic()
    _run_bounded(cs.request_stop, 5.0)
    _run_bounded(cs.request_stop, 5.0)  # повтор безвреден
    assert time.monotonic() - t0 < 0.5

    assert len(events["A"].set_calls) >= 1
    assert len(events["B"].set_calls) >= 1
    assert events["C"].set_calls == []
    # request_stop — только событие: никаких сигналов процессам
    for p in (live_a, live_b, dead_c):
        assert p.terminate_t == []
        assert p.kill_t == []


def test_no_signal_before_kill() -> None:
    """Пока ``kill()`` не вызван, ``join_until`` не шлёт ни ``terminate``, ни ``kill``."""
    a = FakeProc("A", dies_on_terminate=True, dies_on_kill=True)
    b = FakeProc("B", dies_on_terminate=True, dies_on_kill=True)
    cs, _procs, _events = _make([a, b], grace=0.1, confirm=0.1)

    cs.request_stop()
    deadline = time.monotonic() + 0.6
    result = _run_bounded(lambda: cs.join_until(deadline), 5.0)

    assert result is False
    for p in (a, b):
        assert p.terminate_t == []
        assert p.kill_t == []


# ---------------------------------------------------------------------------
# ChildProcessStop: kill() и эскалация
# ---------------------------------------------------------------------------


def test_kill_does_not_block() -> None:
    """``kill()`` шлёт ``terminate`` каждому живому сразу и возвращается без ожидания grace."""
    a = FakeProc("A")
    b = FakeProc("B")
    dead_c = FakeProc("C", dead=True)
    cs, _procs, _events = _make([a, b, dead_c], grace=0.6, confirm=0.6)

    t0 = time.monotonic()
    _run_bounded(cs.kill, 5.0)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.3  # grace = 0.6: ожидания нет
    for p in (a, b):
        assert len(p.terminate_t) == 1
        assert t0 <= p.terminate_t[0] <= t0 + 0.3
        assert p.kill_t == []  # настоящий kill — только из join_until
    assert dead_c.terminate_t == []


def test_repeat_kill_is_noop() -> None:
    """Повторный ``kill()`` ничего не делает: новых ``terminate`` нет."""
    a = FakeProc("A")
    b = FakeProc("B")
    cs, _procs, _events = _make([a, b], grace=0.6, confirm=0.6)

    cs.kill()
    cs.kill()

    assert len(a.terminate_t) == 1
    assert len(b.terminate_t) == 1
    assert a.kill_t == []
    assert b.kill_t == []


def test_escalation_waits_terminate_grace() -> None:
    """Настоящий ``kill()`` уходит не раньше ``terminate_grace_s`` после ``kill()`` и ровно один раз."""
    a = FakeProc("A", dies_on_kill=True)
    b = FakeProc("B", dies_on_kill=True)
    cs, _procs, _events = _make([a, b], grace=0.3, confirm=1.0)

    t0 = time.monotonic()
    cs.kill()
    # срок не меньше начало + grace + confirm: граница deadline - confirm не раньше grace
    result = _run_bounded(lambda: cs.join_until(t0 + 2.0), 8.0)

    assert result is True
    for p in (a, b):
        assert len(p.terminate_t) == 1
        assert len(p.kill_t) == 1
        assert p.terminate_t[0] < p.kill_t[0]
        assert p.kill_t[0] >= t0 + 0.3 - 0.1  # не раньше grace (допуск 0.1 с)
        assert p.kill_t[0] <= t0 + 0.3 + 0.3  # и не позже граничного опроса


def test_kill_goes_at_deadline_minus_confirm_when_deadline_is_short() -> None:
    """Срок короче grace + confirm: kill уходит на ``deadline - kill_confirm_s``, а не на grace."""
    a = FakeProc("A", dies_on_kill=True)
    cs, _procs, _events = _make([a], grace=1.0, confirm=0.5)

    t0 = time.monotonic()
    cs.kill()
    result = _run_bounded(lambda: cs.join_until(t0 + 0.9), 8.0)

    assert result is True
    assert len(a.kill_t) == 1
    assert a.kill_t[0] >= t0 + 0.4 - 0.1  # граница deadline - confirm = t0 + 0.4
    assert a.kill_t[0] <= t0 + 0.4 + 0.3  # заметно раньше grace (t0 + 1.0)


def test_exceptions_from_signals_and_mark_do_not_escape() -> None:
    """Исключения ``terminate``/``kill``/``on_confirmed_dead`` не прерывают цикл и не вылетают."""
    a = FakeProc("A", terminate_raises=True, kill_raises=True)  # упрямый, сигналы падают
    b = FakeProc("B", dies_on_terminate=True)  # умирает; колбэк метки на нём падает
    c = FakeProc("C", dies_on_kill=True)  # игнорирует terminate, умирает от kill
    marks = Marks(raise_for=("B",))
    cs, _procs, _events = _make([a, b, c], marks=marks, grace=0.1, confirm=0.3)

    t0 = time.monotonic()
    _run_bounded(cs.kill, 5.0)
    result = _run_bounded(lambda: cs.join_until(t0 + 1.0), 8.0)

    assert result is False  # A жив до срока
    assert len(c.kill_t) == 1  # цикл дошёл до C несмотря на сбои A и колбэка B
    assert len(a.kill_t) >= 1  # kill для A пытались
    assert "C" in marks.names
    assert _run_bounded(cs.survivors, 5.0) == ("A",)
    _run_bounded(cs.close, 5.0)


# ---------------------------------------------------------------------------
# ChildProcessStop: join_until
# ---------------------------------------------------------------------------


def test_join_until_empty_group_is_true() -> None:
    """Пустая группа — ``True`` сразу."""
    cs = _stop_cls()({}, {}, poll_s=0.01)
    t0 = time.monotonic()
    assert _run_bounded(lambda: cs.join_until(t0 + 5.0), 8.0) is True
    assert time.monotonic() - t0 < 1.0


def test_join_until_true_when_all_dead_and_each_marked_once() -> None:
    """Все умерли до срока — ``True``; каждый помечен один раз, колбэк получил объект процесса."""
    t0 = time.monotonic()
    a = FakeProc("A", die_at=t0 + 0.1)
    b = FakeProc("B", die_at=t0 + 0.2)
    marks = Marks()
    cs, procs, _events = _make([a, b], marks=marks)

    result = _run_bounded(lambda: cs.join_until(t0 + 3.0), 8.0)

    assert result is True
    assert sorted(marks.names) == ["A", "B"]
    assert marks.procs["A"] is procs["A"]
    assert marks.procs["B"] is procs["B"]


def test_join_until_returns_false_on_deadline_and_does_not_raise() -> None:
    """Живой до срока — ``False``, без исключения, около срока."""
    a = FakeProc("A")
    cs, _procs, _events = _make([a])

    t0 = time.monotonic()
    result = _run_bounded(lambda: cs.join_until(t0 + 0.4), 5.0)
    elapsed = time.monotonic() - t0

    assert result is False
    assert 0.3 <= elapsed <= 0.4 + 0.5


def test_past_deadline_is_one_pass() -> None:
    """Срок в прошлом — ровно один проход: умершего метит, живого опрашивает, возвращает ``False``."""
    dead_a = FakeProc("A", dead=True)
    live_b = FakeProc("B")
    marks = Marks()
    cs, _procs, _events = _make([dead_a, live_b], marks=marks)

    t0 = time.monotonic()
    result = _run_bounded(lambda: cs.join_until(t0 - 5.0), 5.0)

    assert result is False
    assert time.monotonic() - t0 < 0.5
    assert marks.names == ["A"]
    assert live_b.alive_calls >= 1


def test_past_deadline_all_dead_is_true() -> None:
    """Срок в прошлом, но живых нет — ``True``."""
    marks = Marks()
    cs, _procs, _events = _make([FakeProc("A", dead=True)], marks=marks)

    assert _run_bounded(lambda: cs.join_until(time.monotonic() - 5.0), 5.0) is True
    assert marks.names == ["A"]


# ---------------------------------------------------------------------------
# ChildProcessStop: метки
# ---------------------------------------------------------------------------


def test_mark_at_moment_of_death() -> None:
    """Умершего метят в момент, когда смерть увидена, а не по очереди после живого соседа.

    Б умирает рано; А «умирает» только после того, как метка Б поставлена. Без опроса
    всей группы за проход ``join_until`` ждёт А и до срока не доходит до Б.
    """
    marks = Marks()
    t0 = time.monotonic()
    b = FakeProc("B", die_at=t0 + 0.1)
    a = FakeProc("A", die_when=lambda: "B" in marks.names)
    # порядок в группе: А первым — тот, кто ждёт метку Б
    cs, _procs, _events = _make([a, b], marks=marks, poll=0.01)

    result = _run_bounded(lambda: cs.join_until(t0 + 2.0), 8.0)

    assert result is True
    assert marks.names == ["B", "A"]
    assert b.death_t is not None and a.death_t is not None
    assert b.death_t <= marks.times["B"] <= b.death_t + 0.3  # метка Б — сразу за смертью Б
    assert marks.times["B"] <= a.death_t  # А умер уже после метки Б
    assert time.monotonic() - t0 < 1.5


def test_survivor_is_not_marked() -> None:
    """Выживший не метится ни ``join_until``, ни ``survivors``, ни ``close``; в ``survivors`` — по порядку."""
    marks = Marks()
    a = FakeProc("A")  # упрямый: не умирает ни от чего
    b = FakeProc("B", dies_on_terminate=True)
    c = FakeProc("C")  # упрямый
    cs, _procs, _events = _make([a, b, c], marks=marks, grace=0.1, confirm=0.2)

    t0 = time.monotonic()
    cs.request_stop()
    cs.kill()
    result = _run_bounded(lambda: cs.join_until(t0 + 1.0), 8.0)

    assert result is False
    assert len(a.kill_t) == 1 and len(c.kill_t) == 1  # настоящий kill дошёл до упрямых
    assert b.kill_t == []  # умерший от terminate kill не получает
    assert _run_bounded(cs.survivors, 5.0) == ("A", "C")
    _run_bounded(cs.close, 5.0)
    _run_bounded(cs.close, 5.0)  # идемпотентно
    assert marks.names == ["B"]


def test_survivors_is_a_tuple_of_names() -> None:
    """``survivors()`` — ``tuple`` имён; пусто, когда все мертвы."""
    cs, _procs, _events = _make([FakeProc("A", dead=True), FakeProc("B", dead=True)])
    assert _run_bounded(cs.survivors, 5.0) == ()
    cs2, _p2, _e2 = _make([FakeProc("X"), FakeProc("Y", dead=True)])
    result = _run_bounded(cs2.survivors, 5.0)
    assert isinstance(result, tuple)
    assert result == ("X",)


def test_one_mark_per_name() -> None:
    """Метка на имя — не более одной за жизнь объекта, всеми путями вместе."""
    t0 = time.monotonic()
    marks = Marks()
    a = FakeProc("A", die_at=t0 + 0.1)  # увидит join_until
    b = FakeProc("B", die_at=t0 + 0.5)  # умрёт после срока: увидит survivors
    c = FakeProc("C", die_at=t0 + 0.9)  # умрёт после срока: увидит close
    cs, _procs, _events = _make([a, b, c], marks=marks)

    assert _run_bounded(lambda: cs.join_until(t0 + 0.3), 5.0) is False
    assert marks.names == ["A"]

    time.sleep(max(0.0, t0 + 0.6 - time.monotonic()))  # B умер, C ещё жив
    assert _run_bounded(cs.survivors, 5.0) == ("C",)
    assert sorted(marks.names) == ["A", "B"]

    time.sleep(max(0.0, t0 + 1.0 - time.monotonic()))  # умер и C
    _run_bounded(cs.close, 5.0)
    assert _run_bounded(cs.survivors, 5.0) == ()
    _run_bounded(cs.close, 5.0)
    assert _run_bounded(lambda: cs.join_until(time.monotonic() + 0.2), 5.0) is True

    assert sorted(marks.names) == ["A", "B", "C"]
    assert len(marks.names) == 3  # ни одного повтора


def test_close_never_marks_survivors_and_is_idempotent() -> None:
    """``close()`` выжившему метку не ставит; мёртвым после ``join_until`` — повторных меток нет; повтор безвреден."""
    marks = Marks()
    cs, _procs, _events = _make([FakeProc("A", dead=True), FakeProc("B"), FakeProc("C", dead=True)], marks=marks)

    assert _run_bounded(lambda: cs.join_until(time.monotonic() - 1.0), 5.0) is False  # один проход: A и C помечены
    _run_bounded(cs.close, 5.0)
    assert sorted(marks.names) == ["A", "C"]

    _run_bounded(cs.close, 5.0)
    assert sorted(marks.names) == ["A", "C"]  # B не помечен, повторов нет


def test_late_death_after_deadline_is_marked() -> None:
    """Умер после срока ``join_until``, но до ``survivors()``: не в выживших, ровно одна метка."""
    marks = Marks()
    t0 = time.monotonic()
    a = FakeProc("A", die_at=t0 + 0.4)
    cs, _procs, _events = _make([a], marks=marks)

    assert _run_bounded(lambda: cs.join_until(t0 + 0.2), 5.0) is False
    assert marks.names == []

    time.sleep(max(0.0, t0 + 0.5 - time.monotonic()))  # A уже мёртв, срок давно вышел

    assert _run_bounded(cs.survivors, 5.0) == ()
    assert marks.names == ["A"]
    assert _run_bounded(cs.survivors, 5.0) == ()
    _run_bounded(cs.close, 5.0)
    assert marks.names == ["A"]


def test_kill_not_lost_when_mark_is_slow() -> None:
    """Медленный колбэк метки не съедает настоящий ``kill()``: срок короче grace + confirm, kill уходит."""
    marks = Marks(delay_s=0.8)
    b = FakeProc("B", dies_on_kill=True)  # игнорирует terminate; первым в группе
    a = FakeProc("A", dies_on_terminate=True)  # умирает сразу; его метка медленная
    cs, _procs, _events = _make([b, a], marks=marks, grace=0.5, confirm=0.8)

    t0 = time.monotonic()
    cs.kill()
    # grace + confirm = 1.3 > 1.2; граница kill: min(0.5, 1.2 - 0.8) = 0.4 — до конца метки (0.8)
    result = _run_bounded(lambda: cs.join_until(t0 + 1.2), 8.0)

    assert result is True
    assert len(b.kill_t) == 1  # kill не потерян
    assert b.kill_t[0] >= t0 + 0.4 - 0.1
    assert sorted(marks.names) == ["A", "B"]


def test_kill_not_lost_when_slow_mark_precedes_target() -> None:
    """То же, но медленная метка стоит в группе ПЕРЕД упрямым процессом."""
    marks = Marks(delay_s=0.8)
    a = FakeProc("A", dies_on_terminate=True)
    b = FakeProc("B", dies_on_kill=True)
    cs, _procs, _events = _make([a, b], marks=marks, grace=0.5, confirm=0.8)

    t0 = time.monotonic()
    cs.kill()
    result = _run_bounded(lambda: cs.join_until(t0 + 1.2), 8.0)

    assert result is True
    assert len(b.kill_t) == 1
    assert b.kill_t[0] >= t0 + 0.4 - 0.1
    assert sorted(marks.names) == ["A", "B"]


# ---------------------------------------------------------------------------
# ProcessRegistry: child_stop_budget -> config ребёнка
# ---------------------------------------------------------------------------

_BUDGET_5 = {"work_s": 3.0, "infra_s": 1.0, "pm_graceful_s": 5.0, "pm_total_s": 7.0, "outer_s": 8.5}


def _child_config(registry: ProcessRegistry, name: str, config: dict | None = None) -> dict:
    proc = registry.create_and_register(name, "os.getpid", {} if config is None else config, "normal")
    assert proc is not None
    return proc._args[3]["config"]


def test_child_config_gets_stop_budget() -> None:
    """При заданном ``child_stop_budget`` ребёнок получает в конфиге ключ ``stop_budget`` — копию словаря."""
    budget = dict(_BUDGET_5)
    registry = ProcessRegistry(logger=None, child_stop_budget=budget)

    cfg_r = _child_config(registry, "R")
    assert cfg_r["stop_budget"] == _BUDGET_5
    assert cfg_r["stop_budget"] is not budget  # копия, не тот же объект

    cfg_s = _child_config(registry, "S")
    assert cfg_s["stop_budget"] == _BUDGET_5
    assert cfg_s["stop_budget"] is not cfg_r["stop_budget"]  # у каждого ребёнка своя копия

    cfg_r["stop_budget"]["work_s"] = 99.0  # правка в конфиге ребёнка не течёт назад
    assert budget == _BUDGET_5
    assert cfg_s["stop_budget"] == _BUDGET_5


def test_child_config_explicit_stop_budget_wins() -> None:
    """Ключ ``stop_budget``, заданный в конфиге процесса явно, сильнее реестрового."""
    registry = ProcessRegistry(logger=None, child_stop_budget=dict(_BUDGET_5))

    explicit = {"work_s": 9.0}
    cfg = _child_config(registry, "R", {"stop_budget": explicit})

    assert cfg["stop_budget"] == {"work_s": 9.0}


def test_child_config_without_budget_has_no_key() -> None:
    """Без ``child_stop_budget`` ключа ``stop_budget`` в конфиге ребёнка нет (guard: зелёный и до кода)."""
    registry = ProcessRegistry(logger=None)

    assert "stop_budget" not in _child_config(registry, "R")
