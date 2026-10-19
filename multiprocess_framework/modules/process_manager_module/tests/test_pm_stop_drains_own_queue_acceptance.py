# -*- coding: utf-8 -*-
"""Task 1.8 (L-9, `plans/lifecycle-stop-ownership.md`) — слепая приёмка живой проводки «стоп вычерпывает свои каналы».

Дефект L-9: одиночный ``process.stop`` — PM ждёт выхода ребёнка в потоке, который единственный читает его
каналы, а ребёнок на выходе (``release_feeders_at_exit``, ``system_stop=False``) ждёт, пока читатель
вычерпает его хвост из pipe (~8 КБ на Windows). Взаимная блокировка кончается ``terminate`` через 5 с.

Контракт (стадия 0, `docs/reviews/2026-10-19_lifecycle-1.8-stage0.md` §4 D4, REDS R10-R11):
  * R10 — живая проводка: настоящий ``RouterManager`` «PM», настоящий ``ReaderGoneQueue`` как канал
    ``PM_system``, настоящий spawn-ребёнок. Ожидание стопа вычерпывает канал, пока ждёт: ответ ≤ 3,0 с
    (до фикса ≥ 5,0 с), ``exitcode`` 0 (до фикса -15), флаг отчёта ребёнка 1 (до фикса 0), все сообщения
    хвоста приходят следующим ``receive`` по порядку, очередь PM не помечена «читатель ушёл».
    K = 15 сообщений (4,8 КБ, влезает в pipe) — контроль: проходит и до, и после фикса.
  * R11 — склейка PM: ``ProcessManagerProcess._stop_wait_idle(pause_s)`` зовёт ``pump_inbound`` роутера
    один раз и спит остаток паузы; без роутера только спит; сбой pump — без исключения и ровно один лог.

Слепо: реализация не читалась. Ожидаемые числа — литералы REDS. Всё, что может зависнуть, идёт в daemon-потоке
с дедлайном join 12 с; зависание = упавший ассерт с цифрами, а не зависший прогон.

ОТКЛОНЕНИЕ ОТ ТЕКСТА R10 (см. отчёт): до фикса у ``ChildProcessStop`` нет kwarg ``idle``, а у роутера нет
``pump_inbound``. Чтобы R10 до фикса давал измеренные числа (≥ 5,0 с, -15, 0), а не ``TypeError`` в обработчике,
обработчик стопа строит ``ChildProcessStop`` с ``idle=``, а при ``TypeError`` — без него, и PM-подобная функция
зовёт ``pump_inbound`` только если он есть. Само существование API закрепляют R1-R9, R11.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from ...shared_resources_module.queues.core.reader_gone import ReaderGoneQueue, release_feeders_at_exit

DEADLINE_S = 12.0
SPAWN_READY_S = 40.0  # импорты ребёнка при spawn; до этого срока часы стопа не запущены
PM_BUDGET_S = 5.0  # graceful-срок стопа одного ребёнка (stop_process_timeout)
# Стенд 2026-10-19 16:43-16:52: ребёнок (devices) входит в хук выхода через 0,58...0,74 с ПОСЛЕ стопа
# (сначала гасятся плагины), а непрочитанное в PM.system растёт ~6 КБ за 0,25 с (≈ 24-32 КБ/с от всех писателей).
# За эту задержку pipe заполняется, и хвост даже в 12 сообщений (3838 Б < 8 КБ) в него уже не влезает.
STAND_HOOK_DELAY_S = 0.7
STAND_NEIGHBOUR = (1, 0.01)  # (сообщений за такт, пауза такта): 1 × ~321 Б каждые ~10 мс ≈ 32 КБ/с, без пачек
TAIL_MESSAGE_PAD = 258  # pickle одного сообщения хвоста = 321 байт (замер: len(pickle.dumps(msg)))


# --------------------------------------------------------------------------- #
# Ребёнок (top-level: spawn пиклит цель по dotted-пути)
# --------------------------------------------------------------------------- #


def _child_tail_then_exit(queue: Any, stop_event: Any, ready: Any, flag: Any, count: int, delay_s: float = 0.0) -> None:
    """Ждёт stop_event, пишет ``count`` сообщений по 321 Б в канал PM, зовёт хук выхода, ставит флаг.

    Флаг — аналог слота ``exit_report``: его ставит ребёнок ПОСЛЕ хука, значит 0 после выхода — «хук не дошёл».
    ``delay_s`` — пауза между стопом и записью хвоста (на стенде — остановка плагинов до хука выхода).
    """
    ready.set()
    stop_event.wait()
    time.sleep(delay_s)
    for i in range(count):
        queue.put({"type": "command", "command": "probe.tail", "i": i, "pad": "x" * TAIL_MESSAGE_PAD})
    release_feeders_at_exit([], [queue], system_stop=False)
    flag.value = 1


def _child_neighbour_writer(queue: Any, ready: Any, quit_event: Any, burst: int, period_s: float) -> None:
    """Сосед: НЕ останавливается PM, пока живёт, пишет в тот же канал PM сообщениями по ~321 Б.

    Так на стенде делают остальные процессы: pipe общий, и пока читатель PM занят ожиданием, его заполняют они.
    Темп задан парой ``(burst, period_s)``; ``STAND_NEIGHBOUR`` — как на стенде.
    """
    ready.set()
    n = 0
    while not quit_event.is_set():
        for _ in range(burst):
            queue.put({"type": "command", "command": "probe.noise", "n": n, "pad": "x" * TAIL_MESSAGE_PAD})
            n += 1
        time.sleep(period_s)


# --------------------------------------------------------------------------- #
# R10. Живая проводка
# --------------------------------------------------------------------------- #


def _pm_like_idle(router: Any) -> Callable[[float], None]:
    """Ожидание PM: перенести входящее из каналов в буфер роутера, затем доспать остаток паузы."""

    def _idle(pause_s: float) -> None:
        end = time.monotonic() + pause_s
        pump = getattr(router, "pump_inbound", None)
        if pump is not None:
            pump()
        rest = end - time.monotonic()
        if rest > 0:
            time.sleep(rest)

    return _idle


def _build_child_stop(proc: Any, stop_event: Any, router: Any, state: dict[str, Any]) -> Any:
    from ..core.child_process_stop import ChildProcessStop

    processes, events = {"child": proc}, {"child": stop_event}
    try:
        stop = ChildProcessStop(processes, events, idle=_pm_like_idle(router))
        state["idle_supported"] = True
    except TypeError:
        stop = ChildProcessStop(processes, events)
        state["idle_supported"] = False
    return stop


def _measure_single_stop(
    count: int, neighbour_rate: tuple[int, float] | None = None, tail_delay_s: float = 0.0
) -> dict[str, Any]:
    """Один стоп ребёнка с хвостом ``count`` сообщений; возвращает измерения (без ассертов).

    ``neighbour_rate`` ``(burst, period_s)`` — второй живой spawn-процесс пишет в тот же канал PM всё время стопа
    (R10b); ``tail_delay_s`` — через сколько после стопа остановленный ребёнок пишет хвост.
    """
    from ...router_module.channels.queue_channel import QueueChannel
    from ...router_module.core.router_manager import RouterManager

    ctx = multiprocessing.get_context("spawn")
    queue = ReaderGoneQueue(ctx=ctx)
    stop_event, ready, flag = ctx.Event(), ctx.Event(), ctx.Value("i", 0)
    proc = ctx.Process(
        target=_child_tail_then_exit,
        args=(queue, stop_event, ready, flag, count, tail_delay_s),
        name="tail-child",
        daemon=True,
    )

    neighbour_quit = ctx.Event()
    neighbour_ready = ctx.Event()
    neighbour = ctx.Process(
        target=_child_neighbour_writer,
        args=(queue, neighbour_ready, neighbour_quit, *(neighbour_rate or (0, 0.01))),
        name="noisy-neighbour",
        daemon=True,
    )

    router = RouterManager(manager_name="PM", process=SimpleNamespace(name="PM"))
    router.register_channel(QueueChannel("PM_system", queue))
    assert router.initialize() is True

    state: dict[str, Any] = {"errors": []}
    tail: list[int] = []

    def _on_stop(_msg: dict) -> None:
        try:
            stop = _build_child_stop(proc, stop_event, router, state)
            stop.request_stop()
            confirmed = stop.join_until(time.monotonic() + PM_BUDGET_S)
            if not confirmed:  # как PM: эскалация после graceful-срока
                stop.kill()
                stop.join_until(time.monotonic() + 2.0)
        except BaseException as exc:  # noqa: BLE001 — сбой обработчика виден в измерениях, а не глотается
            state["errors"].append(repr(exc))
        finally:
            state["reply_at"] = time.monotonic()

    router.register_message_handler("probe.stop", _on_stop)
    router.register_message_handler("probe.tail", lambda _m: None)
    router.register_message_handler("probe.noise", lambda _m: None)

    def _pm_loop() -> None:
        quiet_until: float | None = None
        while True:
            batch = router.receive(timeout=0.0, return_messages=False, channel_types=["system"])
            tail.extend(m["i"] for m in batch if m.get("command") == "probe.tail")
            if "reply_at" in state:
                now = time.monotonic()
                quiet_until = quiet_until if quiet_until is not None else now + 2.0
                if len(tail) >= count or now > quiet_until:
                    return
            time.sleep(0.01)

    measured: dict[str, Any] = {"count": count, "state": state}
    try:
        if neighbour_rate is not None:
            neighbour.start()
            assert neighbour_ready.wait(SPAWN_READY_S), "сосед не стартовал — стенд неисправен"
        proc.start()
        assert ready.wait(SPAWN_READY_S), f"ребёнок не стартовал за {SPAWN_READY_S} с — стенд неисправен"

        t_put = time.monotonic()
        queue.put({"type": "command", "command": "probe.stop"})
        loop = threading.Thread(target=_pm_loop, name="pm-receive-loop", daemon=True)
        loop.start()
        loop.join(DEADLINE_S)

        measured["loop_hung"] = loop.is_alive()
        measured["reply_s"] = (state["reply_at"] - t_put) if "reply_at" in state else None
        proc.join(5.0)
        measured["exitcode"] = proc.exitcode
        measured["flag"] = flag.value
        measured["tail"] = list(tail)
        measured["reader_gone"] = queue.is_reader_gone()
        return measured
    finally:
        neighbour_quit.set()
        for child in (proc, neighbour):
            if child.pid is None:
                continue
            child.join(3.0)  # сосед может застрять на выходе в feeder (pipe никто не читает) — тогда kill
            if child.is_alive():
                child.kill()
            child.join(5.0)
        queue.cancel_join_thread()
        queue.close()
        router.shutdown()


def _assert_stop_effect(m: dict[str, Any], count: int, label: str) -> None:
    print(  # видно при красном и с ``-s``: цифры до/после фикса берутся отсюда
        f"{label}: reply_s={m['reply_s']} exitcode={m['exitcode']} flag={m['flag']} "
        f"tail={len(m['tail'])}/{count} reader_gone={m['reader_gone']} loop_hung={m['loop_hung']} "
        f"idle_supported={m['state'].get('idle_supported')} errors={m['state']['errors']}"
    )

    assert not m["state"]["errors"], f"обработчик стопа упал: {m['state']['errors']}"
    assert m["reply_s"] is not None, "ответ на стоп не получен за дедлайн"
    assert m["reply_s"] <= 3.0, f"ответ на стоп за {m['reply_s']:.2f} с, ожидалось ≤ 3,0 (до фикса ≥ 5,0)"
    assert m["exitcode"] == 0, f"exitcode ребёнка {m['exitcode']}, ожидалось 0 (до фикса -15: terminate)"
    assert m["flag"] == 1, f"флаг отчёта ребёнка {m['flag']}, ожидалось 1 (хук выхода дошёл до конца)"
    assert not m["loop_hung"], "приёмный цикл PM завис на чтении хвоста"
    assert m["tail"] == list(range(count)), (
        f"хвост пришёл не целиком или не по порядку: {len(m['tail'])} из {count}, начало {m['tail'][:5]}"
    )
    assert m["reader_gone"] is False, "очередь PM помечена «читатель ушёл», а PM жив"


@pytest.mark.parametrize("count", [120, 15], ids=["K=120_tail_over_pipe", "K=15_control_fits_pipe"])
def test_r10_single_stop_with_tail_replies_fast_and_child_exits_by_itself(count: int) -> None:
    _assert_stop_effect(_measure_single_stop(count), count, f"R10 K={count}")


@pytest.mark.parametrize(
    ("label", "neighbour_rate", "tail_delay_s"),
    [
        ("R10b", STAND_NEIGHBOUR, STAND_HOOK_DELAY_S),
        ("R10b-ctl", None, STAND_HOOK_DELAY_S),
    ],
    ids=["R10b_stand_like", "R10b-ctl_no_neighbour"],
)
def test_r10b_shared_pipe_small_tail_still_exits_while_neighbour_keeps_writing(
    label: str, neighbour_rate: tuple[int, float] | None, tail_delay_s: float
) -> None:
    """Стенд: хвост остановленного ребёнка 12 сообщений / 3838 Б (меньше pipe 8 КБ), но pipe общий — пока PM ждёт,
    его заполняют живые соседи. Контроль без соседа (та же задержка 0,7 с): 3,8 КБ влезает, проходит до и после."""
    _assert_stop_effect(_measure_single_stop(12, neighbour_rate, tail_delay_s), 12, label)


# --------------------------------------------------------------------------- #
# R11. Склейка PM: _stop_wait_idle
# --------------------------------------------------------------------------- #


class _RouterDouble:
    def __init__(self, raises: bool = False) -> None:
        self.pump_calls = 0
        self._raises = raises

    def pump_inbound(self) -> int:
        self.pump_calls += 1
        if self._raises:
            raise RuntimeError("pump exploded")
        return 0


def _pm_with_router(router: Any) -> tuple[Any, list[tuple[str, str]]]:
    from ..process.process_manager_process import ProcessManagerProcess

    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    records: list[tuple[str, str]] = []

    def _recorder(level: str) -> Callable[..., bool]:
        def _log(message: Any, *_a: Any, **_k: Any) -> bool:
            records.append((level, str(message)))
            return True

        return _log

    pm._log_warning = _recorder("warning")  # type: ignore[method-assign]
    pm._log_error = _recorder("error")  # type: ignore[method-assign]
    pm.router_manager = router
    return pm, records


def _timed(fn: Callable[[], Any]) -> float:
    box: dict[str, Any] = {}

    def _run() -> None:
        t0 = time.monotonic()
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=_run, name="timed-call", daemon=True)
    th.start()
    th.join(DEADLINE_S)
    assert not th.is_alive(), f"вызов не вернулся за {DEADLINE_S} с — завис"
    if "error" in box:
        raise box["error"]
    return box["elapsed"]


def test_r11_stop_wait_idle_pumps_once_and_sleeps_the_rest_of_the_pause() -> None:
    router = _RouterDouble()
    pm, records = _pm_with_router(router)

    elapsed = _timed(lambda: pm._stop_wait_idle(0.05))

    assert router.pump_calls == 1, f"pump_inbound вызван {router.pump_calls} раз, ожидалось 1"
    assert 0.04 <= elapsed <= 0.2, f"_stop_wait_idle(0.05) длился {elapsed:.3f} с, ожидалось [0,04; 0,2]"
    assert records == [], f"штатный проход написал в лог: {records}"


def test_r11_without_router_it_only_sleeps() -> None:
    pm, records = _pm_with_router(None)

    elapsed = _timed(lambda: pm._stop_wait_idle(0.05))

    assert 0.04 <= elapsed <= 0.2, f"_stop_wait_idle(0.05) без роутера длился {elapsed:.3f} с, ожидалось [0,04; 0,2]"
    assert records == [], f"проход без роутера написал в лог: {records}"


def test_r11_pump_failure_does_not_raise_and_logs_exactly_once() -> None:
    router = _RouterDouble(raises=True)
    pm, records = _pm_with_router(router)

    _timed(lambda: pm._stop_wait_idle(0.05))

    assert router.pump_calls == 1
    assert len(records) == 1, f"сбой pump дал {len(records)} записей лога, ожидалась ровно 1: {records}"
