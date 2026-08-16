"""Независимые приёмочные тесты TelemetryPoller (задача 3.3, ветка feat/telemetry-stage6).

Написаны ДО реализации, по контракту из ТЗ, без чтения `telemetry_poller.py` и
без чтения авторских тестов (`test_telemetry_poller_hazards*.py`). Источник
истины — сигнатура класса и восемь критериев приёмки, продиктованные постановщиком
задачи; сам план (раздел Task 3.3) не читался.

Что проверяет какой тест (критерии из ТЗ):
    AC1 — test_active_true_polls_grow_over_window,
          test_active_false_polls_exactly_zero_in_next_window
    AC2 — test_interval_sec_is_public_and_bounds_poll_count
    AC3 — test_one_call_per_started_poll_with_many_metrics_in_response
    AC4 — test_stop_yields_zero_polls_in_next_window,
          test_set_active_true_after_stop_does_not_silently_resume
    AC5 — test_poll_fn_called_only_through_submit_not_directly,
          test_poll_fn_executes_off_main_thread
    AC6 — test_poller_constructor_has_no_router_access
    AC7 — test_set_targets_polls_each_target_once_per_tick,
          test_set_targets_empty_yields_zero_polls_while_active
    AC8 — test_failed_response_does_not_crash_and_next_tick_still_happens,
          test_missing_levels_key_does_not_write_garbage_to_view_model
    Доп. (текст контракта, не пронумерован) —
          test_poll_result_lands_in_view_model_get

Общее правило: НИ ОДИН тест не ждёт голым sleep без дедлайна. Ожидание —
либо фиксированное окно через `qtbot.wait(ms)` (обрабатывает event loop),
либо цикл с дедлайном по `time.monotonic()`, который гарантированно
завершается (падением ассерта), а не висит.
"""

from __future__ import annotations

import inspect
import math
import threading
import time

import pytest

from multiprocess_framework.modules.frontend_module.state import (
    TelemetryPoller,
    TelemetryViewModel,
)


# --------------------------------------------------------------------------- #
#  Двойники submit/poll_fn                                                     #
# --------------------------------------------------------------------------- #


class ImmediateSubmit:
    """Двойник submit: исполняет fn СИНХРОННО в момент вызова, в том же потоке.

    Годится для тестов, где важен только факт/число вызовов poll_fn и данные,
    дошедшие в read-model — без реальной потоковой модели доставки.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, fn, on_result) -> None:
        self.calls += 1
        on_result(fn())


class SwallowingSubmit:
    """Двойник submit, который НИКОГДА не исполняет fn (работа "теряется").

    Нужен для AC5: доказывает, что poll_fn вызывается ТОЛЬКО через submit,
    а не напрямую поллером в обход очереди.
    """

    def __init__(self) -> None:
        self.submit_calls = 0

    def __call__(self, fn, on_result) -> None:
        self.submit_calls += 1
        # fn сознательно НЕ вызываем.


class ThreadedSubmit:
    """Двойник submit, реально уводящий fn в отдельный daemon-поток.

    on_result вызывается в ТОМ ЖЕ фоновом потоке — тесту важен только поток
    исполнения fn (инвариант ADR-136: не блокировать main thread), а не
    потоковая модель доставки результата обратно. join с дедлайном — если fn
    зависнет, тест ОБЯЗАН упасть, а не повиснуть вместе с ним.
    """

    def __init__(self, join_timeout: float = 2.0) -> None:
        self.join_timeout = join_timeout
        self.timed_out = False

    def __call__(self, fn, on_result) -> None:
        def _run() -> None:
            result = fn()
            on_result(result)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=self.join_timeout)
        if t.is_alive():
            self.timed_out = True


class IdentityRecordingPollFn:
    """poll_fn-двойник: запоминает id потока каждого вызова."""

    def __init__(self) -> None:
        self.thread_ids: list[int] = []

    def __call__(self, name: str) -> dict:
        self.thread_ids.append(threading.get_ident())
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}


def _wait_until(qtbot, predicate, deadline_sec: float = 3.0, step_ms: int = 50) -> None:
    """Крутить Qt event loop короткими шагами, пока predicate() не станет True.

    Дедлайн жёсткий: если predicate не выполнился за deadline_sec — тест
    ОБЯЗАН упасть по ассерту вызывающего кода (сам по себе _wait_until не
    падает, только перестаёт ждать), а не повиснуть.
    """
    deadline = time.monotonic() + deadline_sec
    while not predicate() and time.monotonic() < deadline:
        qtbot.wait(step_ms)


# --------------------------------------------------------------------------- #
#  AC1 — видима опрашивает, скрыта молчит (число, не факт)                     #
# --------------------------------------------------------------------------- #


def test_active_true_polls_grow_over_window(qtbot) -> None:
    """AC1: активный поллер опрашивает >0 раз за окно, и счёт растёт со временем."""

    def poll_fn(name: str) -> dict:
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {"state.fps": 1.0}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    qtbot.wait(400)
    started_after_first_window = poller.polls_started
    assert started_after_first_window > 0, "видимая вкладка не опросила ни разу за 400мс при interval_sec=0.05"

    qtbot.wait(400)
    poller.stop()
    assert poller.polls_started > started_after_first_window, (
        "число опросов не растёт со временем при активном поллере "
        f"(было {started_after_first_window}, стало {poller.polls_started})"
    )


def test_active_false_polls_exactly_zero_in_next_window(qtbot) -> None:
    """AC1: set_active(False) → РОВНО 0 опросов за следующее окно (не "меньше")."""

    def poll_fn(name: str) -> dict:
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)
    qtbot.wait(200)
    assert poller.polls_started > 0, "не набралось ни одного опроса за первые 200мс"

    poller.set_active(False)
    baseline = poller.polls_started
    qtbot.wait(400)
    poller.stop()
    assert poller.polls_started == baseline, (
        f"скрытая вкладка продолжила опрашивать: было {baseline}, стало {poller.polls_started}"
    )


# --------------------------------------------------------------------------- #
#  AC2 — частота названа и ограничивает опрос сверху                           #
# --------------------------------------------------------------------------- #


def test_interval_sec_is_public_and_bounds_poll_count(qtbot) -> None:
    """AC2: interval_sec публичен; число опросов не превышает потолок из формулы.

    Потолок ceil(T / interval_sec) * N с запасом на +1 полный цикл — гасит
    джиттер таймера Qt, но всё ещё ловит баг "опрос на каждый оборот event
    loop" (тот дал бы на порядки больше вызовов).
    """
    interval = 0.1
    targets = ("proc_a", "proc_b")
    wait_ms = 550

    def poll_fn(name: str) -> dict:
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=interval, targets=targets)
    assert poller.interval_sec == interval

    poller.set_active(True)
    qtbot.wait(wait_ms)
    poller.stop()

    t_sec = wait_ms / 1000.0
    max_allowed = (math.ceil(t_sec / interval) + 1) * len(targets)
    assert 0 < poller.polls_started <= max_allowed, (
        f"опросов {poller.polls_started}, потолок {max_allowed} "
        f"(ceil({t_sec}/{interval})+1)*{len(targets)} — похоже, поллер тикает "
        "на каждый оборот event loop, а не раз в interval_sec"
    )


# --------------------------------------------------------------------------- #
#  AC3 — пакетность: один опрос цели = один вызов poll_fn                      #
# --------------------------------------------------------------------------- #


def test_one_call_per_started_poll_with_many_metrics_in_response(qtbot) -> None:
    """AC3: ответ с 20 метриками даёт ровно ОДИН вызов poll_fn на опрос — не 20."""
    calls: list[str] = []
    many_levels = {f"state.metric_{i}": float(i) for i in range(20)}

    def poll_fn(name: str) -> dict:
        calls.append(name)
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": many_levels}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    _wait_until(qtbot, lambda: poller.polls_started >= 3)
    poller.stop()

    assert poller.polls_started >= 3, "не набралось 3 опросов за 3с ожидания"
    assert len(calls) == poller.polls_started, (
        f"вызовов poll_fn ({len(calls)}) не совпадает со счётчиком polls_started "
        f"({poller.polls_started}) при ответе с 20 метриками — подозрение на "
        "фан-аут вызова по метрикам, а не по целям"
    )


# --------------------------------------------------------------------------- #
#  AC4 — stop() = ноль трафика, повторный set_active(True) не воскрешает       #
# --------------------------------------------------------------------------- #


def test_stop_yields_zero_polls_in_next_window(qtbot) -> None:
    """AC4: после stop() — 0 опросов за следующее окно."""
    calls: list[str] = []

    def poll_fn(name: str) -> dict:
        calls.append(name)
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)
    qtbot.wait(200)
    assert poller.polls_started > 0

    poller.stop()
    baseline = poller.polls_started
    qtbot.wait(400)
    assert poller.polls_started == baseline, "после stop() опросы продолжились"
    assert len(calls) == baseline


def test_set_active_true_after_stop_does_not_silently_resume(qtbot) -> None:
    """AC4: повторный set_active(True) ПОСЛЕ stop() не воскрешает опрос молча.

    Выбранное прочтение контракта (двусмысленность явно есть, см. отчёт
    tester'а): stop() — терминальное состояние поллера, аналог close()/
    dispose(). Если задуманное поведение другое ("stop как временная пауза,
    set_active(True) снова включает"), этот тест переписывается ПОСЛЕ явного
    согласования семантики stop() с автором реализации — молчаливо не
    подгоняется.
    """

    def poll_fn(name: str) -> dict:
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)
    qtbot.wait(150)
    poller.stop()
    baseline = poller.polls_started

    poller.set_active(True)
    qtbot.wait(400)
    poller.stop()
    assert poller.polls_started == baseline, (
        f"опрос молча воскрес после stop()+set_active(True): было {baseline}, стало {poller.polls_started}"
    )


# --------------------------------------------------------------------------- #
#  AC5 — не блокирующий IPC из main thread (ADR-136)                           #
# --------------------------------------------------------------------------- #


def test_poll_fn_called_only_through_submit_not_directly(qtbot) -> None:
    """AC5: если submit не исполняет fn — poll_fn не вызван НИ РАЗУ."""
    poll_calls: list[str] = []

    def poll_fn(name: str) -> dict:
        poll_calls.append(name)
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = SwallowingSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)
    qtbot.wait(300)
    poller.stop()

    assert submit.submit_calls > 0, "submit ни разу не вызван — поллер вообще не тикнул"
    assert poll_calls == [], f"poll_fn вызван напрямую, минуя submit: {poll_calls}"


def test_poll_fn_executes_off_main_thread(qtbot) -> None:
    """AC5: реальное исполнение poll_fn идёт НЕ в main thread.

    Тест обязан падать по дедлайну, а не висеть: submit-двойник сам держит
    join с таймаутом на фоновый поток и выставляет флаг timed_out вместо
    попытки поднять исключение из чужого потока.
    """
    main_thread_id = threading.get_ident()
    poll_fn = IdentityRecordingPollFn()
    submit = ThreadedSubmit(join_timeout=2.0)
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    _wait_until(qtbot, lambda: bool(poll_fn.thread_ids))
    poller.stop()

    assert not submit.timed_out, "poll_fn завис дольше 2с в фоновом потоке — похоже на дедлок"
    assert poll_fn.thread_ids, "poll_fn ни разу не был вызван за 3с ожидания"
    assert main_thread_id not in poll_fn.thread_ids, (
        f"poll_fn вызван в main thread ({main_thread_id}): {poll_fn.thread_ids}"
    )


# --------------------------------------------------------------------------- #
#  AC6 — 0 серверных подписок (у поллера нет доступа к router)                 #
# --------------------------------------------------------------------------- #


def test_poller_constructor_has_no_router_access() -> None:
    """AC6: конструктор не принимает router/state-proxy — только poll_fn/submit.

    Инвариант ADR-136 (0 серверных подписок) проверяется на уровне сигнатуры:
    если бы поллер сам делал state.subscribe, ему было бы НЕЧЕМ это делать —
    у него просто нет параметра, через который можно получить router/proxy.
    """
    sig = inspect.signature(TelemetryPoller.__init__)
    forbidden_substrings = ("router", "subscribe", "state_proxy", "proxy")
    for name in sig.parameters:
        lname = name.lower()
        assert not any(bad in lname for bad in forbidden_substrings), (
            f"параметр конструктора '{name}' намекает на доступ к router/state-proxy — "
            "нарушение инварианта ADR-136 (0 серверных подписок)"
        )


# --------------------------------------------------------------------------- #
#  AC7 — несколько целей                                                       #
# --------------------------------------------------------------------------- #


def test_set_targets_polls_each_target_once_per_tick(qtbot) -> None:
    """AC7: set_targets(["a","b"]) → на тик опрошены ОБЕ, по одному вызову каждая."""
    calls: list[str] = []

    def poll_fn(name: str) -> dict:
        calls.append(name)
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=())
    poller.set_targets(["proc_a", "proc_b"])
    poller.set_active(True)

    _wait_until(qtbot, lambda: poller.polls_started >= 4)
    poller.stop()

    assert poller.polls_started >= 4, "не набралось хотя бы 2 тиков по 2 цели за 3с"
    assert len(calls) == poller.polls_started
    count_a = calls.count("proc_a")
    count_b = calls.count("proc_b")
    assert count_a > 0 and count_b > 0, f"не обе цели опрошены: {calls}"
    assert abs(count_a - count_b) <= 1, f"цели опрашиваются не поровну за тик: proc_a={count_a}, proc_b={count_b}"


def test_set_targets_empty_yields_zero_polls_while_active(qtbot) -> None:
    """AC7: set_targets([]) → 0 опросов при активном поллере."""
    calls: list[str] = []

    def poll_fn(name: str) -> dict:
        calls.append(name)
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {}}}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)
    qtbot.wait(150)
    assert poller.polls_started > 0

    poller.set_targets([])
    baseline = poller.polls_started
    qtbot.wait(400)
    poller.stop()
    assert poller.polls_started == baseline, (
        f"опрос продолжился при пустом списке целей: было {baseline}, стало {poller.polls_started}"
    )
    assert len(calls) == baseline


# --------------------------------------------------------------------------- #
#  AC8 — ответ success=False / без levels не роняет поллер                     #
# --------------------------------------------------------------------------- #


def test_failed_response_does_not_crash_and_next_tick_still_happens(qtbot) -> None:
    """AC8: ответ success=False не роняет поллер — следующий тик всё равно наступает."""

    def poll_fn(name: str) -> dict:
        return {"success": False, "error": "boom"}

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    _wait_until(qtbot, lambda: poller.polls_started >= 3)
    poller.stop()

    assert poller.polls_started >= 3, (
        "поллер не пережил success=False — опрос остановился после первой ошибки "
        "(исключение внутри обработчика результата рвёт цепочку тиков?)"
    )


def test_missing_levels_key_does_not_write_garbage_to_view_model(qtbot) -> None:
    """AC8: ответ БЕЗ 'levels' не пишет мусор в read-model и не роняет поллер."""

    def poll_fn(name: str) -> dict:
        return {"success": True, "result": {"snapshot_ts": 0.0}}  # нет 'levels'

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    _wait_until(qtbot, lambda: poller.polls_started >= 2)
    poller.stop()

    assert poller.polls_started >= 2, "поллер остановился после ответа без 'levels'"
    assert vm.snapshot("processes.proc_a") == {}, "мусор из ответа без 'levels' материализовался в read-model"


# --------------------------------------------------------------------------- #
#  Доп.: результат доезжает до read-model (текст контракта, не пронумерован)   #
# --------------------------------------------------------------------------- #


def test_poll_result_lands_in_view_model_get(qtbot) -> None:
    """Опрошенное значение читается через view_model.get('processes.<name>.<путь>')."""

    def poll_fn(name: str) -> dict:
        return {
            "success": True,
            "result": {
                "snapshot_ts": 1755300000.5,
                "levels": {"state.fps": 21.3, "state.latency_ms": 4.1},
            },
        }

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.05, targets=("proc_a",))
    poller.set_active(True)

    _wait_until(qtbot, lambda: vm.get("processes.proc_a.state.fps") is not None)
    poller.stop()

    assert vm.get("processes.proc_a.state.fps") == pytest.approx(21.3)
    assert vm.get("processes.proc_a.state.latency_ms") == pytest.approx(4.1)
