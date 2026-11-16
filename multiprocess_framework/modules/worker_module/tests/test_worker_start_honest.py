# -*- coding: utf-8 -*-
"""C-91: контракт ``WorkerManager.start_worker`` — «True» не врёт.

Контракт (plans/worker-start-honest/plan.md, «Цель»):
  * ``start_worker`` -> True  значит «на момент возврата жив ровно один поток
    воркера, и он не остановлен»;
  * над живым прежним потоком новый не создаётся никогда (возврат False);
  * мёртвый поток -> всегда новый поток, даже при залипшем статусе RUNNING;
  * запрос остановки не теряется авто-рестартом (restart_on_failure):
    после ``stop_worker -> True`` потоков воркера нет;
  * два параллельных ``start_worker`` дают один живой поток;
  * если ``Thread.start()`` бросил — статус и ``restart_count`` возвращены.

Слепой набор: написан только по критериям R1–R10, без чтения реализации.

Соглашения набора:
  * любой вызов, способный зависнуть, идёт в daemon-потоке с дедлайном join;
  * ожидаемые значения — литералы;
  * живые потоки воркера считаются через ``threading.enumerate()`` по имени
    ``f"{manager_name}_{worker}"``;
  * «новый поток» проверяется по ОБЪЕКТУ ``Thread`` (``is not``), а не только по
    ``thread.ident``: идентификаторы мёртвых потоков ОС переиспользует
    (на macOS почти всегда), сравнение одних ident даёт ложные красные.
"""

import itertools
import sys
import threading
import warnings

import pytest

from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    WorkerManager,
    WorkerStatus,
)

_DEADLINE = 5.0  # потолок любого вызова, который теоретически может повиснуть
_MGR_COUNTER = itertools.count()


# ---------------------------------------------------------------------------
# Инфраструктура
# ---------------------------------------------------------------------------


def run_with_deadline(fn, deadline: float = _DEADLINE):
    """Выполнить ``fn`` в daemon-потоке; зависание -> AssertionError, не повисший pytest."""
    box: dict = {}

    def runner():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в вызывающий поток
            box["error"] = exc

    t = threading.Thread(target=runner, name="c91-call", daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с (daemon-поток брошен)"
    if "error" in box:
        raise box["error"]
    return box["value"]


def wait_until(predicate, timeout: float = _DEADLINE) -> bool:
    """Дождаться условия без сна «на удачу»: шаги по Event.wait с общим дедлайном."""
    tick = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        tick.wait(0.005)
        waited += 0.005
    return bool(predicate())


class Env:
    """Менеджер + перехват логов + события освобождения целей."""

    def __init__(self):
        self.name = f"c91m{next(_MGR_COUNTER)}"
        self.mgr = WorkerManager(self.name)
        assert self.mgr.initialize() is True
        self.logs: list[str] = []
        self.release = threading.Event()  # отпускает ВСЕ кооперативные цели (уборка)
        self.gate = threading.Event()  # отпускает «упрямые» цели (игнорируют stop_event)
        self._hook_logs()

    def _hook_logs(self):
        def rec(msg, *a, **kw):
            self.logs.append(msg() if callable(msg) else str(msg))
            return True

        for level in ("debug", "info", "warning", "error"):
            setattr(self.mgr, f"_log_{level}", rec)

    # --- наблюдения ---

    def thread_name(self, worker: str) -> str:
        return f"{self.name}_{worker}"

    def live(self, worker: str) -> list[threading.Thread]:
        name = self.thread_name(worker)
        return [t for t in threading.enumerate() if t.name == name and t.is_alive()]

    def info(self, worker: str) -> dict:
        return self.mgr._worker_registry.get(worker)

    def status(self, worker: str) -> WorkerStatus:
        return self.mgr._worker_registry.get_status(worker)

    def restart_count(self, worker: str) -> int:
        return self.info(worker)["restart_count"]

    def make_target(self, behaviors: list[str]):
        """Цель с поведением по номеру вызова (последнее повторяется).

        exit     — сразу вернуться;
        raise    — бросить исключение;
        stubborn — игнорировать stop_event до ``env.gate``;
        coop     — жить, пока не взведён stop_event (или общий ``env.release``).
        """
        calls: list[int] = []
        names: list[str] = []
        lock = threading.Lock()
        env = self

        def target(stop_event, pause_event):
            with lock:
                n = len(calls)
                calls.append(threading.get_ident())
                names.append(threading.current_thread().name)
            mode = behaviors[min(n, len(behaviors) - 1)]
            if mode == "exit":
                return
            if mode == "raise":
                raise RuntimeError("c91: преднамеренная ошибка цели")
            if mode == "stubborn":
                env.gate.wait(10.0)
                return
            while not (stop_event.is_set() or env.release.is_set()):
                stop_event.wait(0.01)

        target.calls = calls
        target.names = names
        return target

    def create(self, worker: str, behaviors: list[str], **cfg):
        target = self.make_target(behaviors)
        assert self.mgr.create_worker(worker, target, ThreadConfig(**cfg)) is True
        return target

    def start(self, worker: str):
        return run_with_deadline(lambda: self.mgr.start_worker(worker))

    def stop(self, worker: str, timeout: float = 2.0):
        return run_with_deadline(lambda: self.mgr.stop_worker(worker, timeout=timeout))

    def cleanup(self):
        self.release.set()
        self.gate.set()
        for t in list(threading.enumerate()):
            if t.name.startswith(self.name + "_"):
                t.join(timeout=2.0)


@pytest.fixture
def env():
    e = Env()
    try:
        yield e
    finally:
        e.cleanup()


def _stubborn_state_b(env: Env, worker: str):
    """Состояние B: поток жив, stop_event взведён, но цель его игнорирует.

    Возвращает (target, прежний_Thread).
    """
    target = env.create(worker, ["stubborn", "coop"])
    assert env.start(worker) is True
    live = env.live(worker)
    assert len(live) == 1, "предусловие: после первого старта ровно один живой поток"
    old = live[0]
    # stop_worker не дожидается упрямой цели -> обязан честно вернуть False
    assert env.stop(worker, timeout=0.05) is False, "предусловие B: stop_worker(0.05) обязан вернуть False"
    assert old.is_alive(), "предусловие B: прежний поток ещё жив"
    return target, old


# ---------------------------------------------------------------------------
# R1 — охрана: два цикла start/stop дают два разных потока
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r1_two_start_stop_cycles_give_two_distinct_threads(env):
    env.create("w", ["coop"])

    assert env.start("w") is True
    first = env.live("w")
    assert len(first) == 1
    assert env.stop("w") is True
    assert env.live("w") == []

    assert env.start("w") is True
    second = env.live("w")
    assert len(second) == 1
    assert env.stop("w") is True

    assert second[0] is not first[0]
    assert env.live("w") == []


# ---------------------------------------------------------------------------
# R2 — состояние B: над живым (умирающим) потоком новый не создаём
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r2_start_over_alive_stopping_thread_is_rejected(env):
    target, old = _stubborn_state_b(env, "w")
    rc_before = env.restart_count("w")

    result = env.start("w")

    assert result is False
    live = env.live("w")
    assert len(live) == 1
    assert live[0] is old
    assert env.restart_count("w") == rc_before
    assert len(target.calls) == 1, "новый вызов цели означает второй поток над старым"


@pytest.mark.timeout(30)
def test_r2_rejected_start_is_logged_as_rejected(env):
    _stubborn_state_b(env, "w")

    env.start("w")

    assert any("отклонён" in line for line in env.logs), f"в логе нет «отклонён»: {env.logs}"


# ---------------------------------------------------------------------------
# R3 — охрана: после выхода прежнего потока старт проходит
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r3_start_succeeds_after_previous_thread_exited(env):
    """Состояние B построено заново; отказ из R2 здесь не проверяется (R3 — охрана)."""
    target = env.create("w", ["stubborn", "coop"])
    assert env.start("w") is True
    old = env.live("w")[0]
    assert env.stop("w", timeout=0.05) is False
    env.gate.set()
    old.join(_DEADLINE)
    assert not old.is_alive()
    rc_before = env.restart_count("w")

    result = env.start("w")

    assert result is True
    live = env.live("w")
    assert len(live) == 1
    assert live[0] is not old
    assert env.restart_count("w") == rc_before + 1
    assert len(target.calls) == 2


# ---------------------------------------------------------------------------
# R4 — залипший RUNNING при мёртвом потоке: всегда новый поток
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r4_stale_running_with_dead_thread_gets_new_thread(env):
    target = env.create("w", ["exit", "coop"])
    assert env.start("w") is True
    old = env.info("w")["thread"]
    old.join(_DEADLINE)
    assert not old.is_alive(), "предусловие: поток отработал и вышел"
    assert env.live("w") == []
    env.mgr._worker_registry.update_status("w", WorkerStatus.RUNNING)  # залипание вручную
    assert env.status("w") == WorkerStatus.RUNNING

    result = env.start("w")

    assert result is True
    live = env.live("w")
    assert len(live) == 1, "True без живого потока — ровно дефект C-91"
    assert live[0] is not old
    assert len(target.calls) == 2


# ---------------------------------------------------------------------------
# R5 — охрана: идемпотентный старт запущенного воркера
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r5_repeat_start_of_running_worker_is_idempotent_true(env):
    target = env.create("w", ["coop"])
    assert env.start("w") is True
    first = env.live("w")
    assert len(first) == 1
    assert wait_until(lambda: env.status("w") == WorkerStatus.RUNNING)

    result = env.start("w")

    assert result is True
    live = env.live("w")
    assert len(live) == 1
    assert live[0] is first[0]
    assert len(target.calls) == 1


# ---------------------------------------------------------------------------
# R6 — двойной старт: один живой поток
# ---------------------------------------------------------------------------


class _AlivenessProxy:
    """Подмена потока в реестре: точка встречи двух стартующих внутри проверки жизни.

    Барьер на входе в метод гонку не воспроизводит (GIL отдаёт первому потоку весь
    короткий проход), поэтому встречаемся ВНУТРИ спорной операции — проверки
    ``is_alive`` перед созданием нового потока. Barrier с timeout: если замок
    разводит стартующих, второй не придёт, и первый не должен повиснуть.
    """

    def __init__(self, real, barrier: threading.Barrier):
        self._real = real
        self._barrier = barrier
        self._seen: set[int] = set()
        self.hits = 0
        self._lock = threading.Lock()

    def is_alive(self):
        me = threading.current_thread()
        if me.name.startswith("c91-starter"):
            with self._lock:
                first_time = me.ident not in self._seen
                self._seen.add(me.ident)
                if first_time:
                    self.hits += 1
            if first_time:
                try:
                    self._barrier.wait()
                except threading.BrokenBarrierError:
                    pass
        return self._real.is_alive()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.mark.timeout(30)
def test_r6_two_parallel_starts_give_exactly_one_live_thread(env):
    target = env.create("w", ["exit", "coop"])
    assert env.start("w") is True
    old = env.info("w")["thread"]
    old.join(_DEADLINE)
    assert not old.is_alive(), "предусловие: прежний поток мёртв"
    assert wait_until(lambda: env.status("w") == WorkerStatus.STOPPED)

    barrier = threading.Barrier(2, timeout=0.3)
    proxy = _AlivenessProxy(old, barrier)
    env.info("w")["thread"] = proxy

    results: list = []
    errors: list = []
    go = threading.Event()

    def starter():
        go.wait(_DEADLINE)
        try:
            results.append(env.mgr.start_worker("w"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    starters = [threading.Thread(target=starter, name=f"c91-starter-{i}", daemon=True) for i in range(2)]
    for s in starters:
        s.start()
    go.set()
    for s in starters:
        s.join(_DEADLINE)
        assert not s.is_alive(), "start_worker завис (взаимная блокировка?)"

    assert errors == []
    assert proxy.hits >= 1, "сценарий недействителен: start_worker не проверял is_alive у потока из реестра"
    assert len(results) == 2
    assert any(r is True for r in results), "хотя бы один из двух стартов обязан быть успешным"
    live = env.live("w")
    assert len(live) == 1, f"ожидался ровно один живой поток, найдено {len(live)}; цель вызвана {len(target.calls)} раз"


# ---------------------------------------------------------------------------
# R7 — H2: stop_worker в окне авто-рестарта не теряется
# ---------------------------------------------------------------------------


def _frame_in_thread_join(ident: int) -> bool:
    frame = sys._current_frames().get(ident)
    while frame is not None:
        code = frame.f_code
        if code.co_name == "join" and code.co_filename.endswith("threading.py"):
            return True
        frame = frame.f_back
    return False


@pytest.mark.timeout(30)
def test_r7_stop_in_auto_restart_window_leaves_no_threads(env):
    env.create("w", ["raise", "coop"], restart_on_failure=True, max_restarts=3)
    lc = env.mgr._lifecycle
    original = lc._restart_worker_internal
    in_window = threading.Event()
    release_window = threading.Event()

    def wrapper(name, *a, **kw):
        in_window.set()
        release_window.wait(_DEADLINE)
        return original(name, *a, **kw)

    lc._restart_worker_internal = wrapper

    assert env.start("w") is True
    e1 = env.info("w")["stop_event"]
    assert in_window.wait(_DEADLINE), "предусловие: поток воркера вошёл в окно авто-рестарта"

    box: dict = {}

    def stopper():
        box["result"] = env.mgr.stop_worker("w", timeout=2.0)

    st = threading.Thread(target=stopper, name="c91-stopper", daemon=True)
    st.start()

    in_join = wait_until(lambda: st.ident is not None and _frame_in_thread_join(st.ident), 2.0)
    if not in_join:
        warnings.warn("R7: stop_worker не замечен в Thread.join; запасное подтверждение по E1.is_set() (слабое)")
        assert wait_until(e1.is_set, 2.0), "stop_worker не взвёл stop_event первого потока"

    release_window.set()
    st.join(_DEADLINE)
    assert not st.is_alive(), "stop_worker завис после выхода из окна"

    assert box["result"] is True
    assert env.live("w") == [], "авто-рестарт породил поток поверх уже обработанного запроса остановки (H2)"
    assert env.status("w") == WorkerStatus.STOPPED


# ---------------------------------------------------------------------------
# R8 — живой поток, RUNNING, stop_event взведён: старт отклонён
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r8_alive_running_with_stop_event_set_is_rejected(env):
    target = env.create("w", ["stubborn"])
    assert env.start("w") is True
    old = env.live("w")[0]
    assert wait_until(lambda: env.status("w") == WorkerStatus.RUNNING)
    env.info("w")["stop_event"].set()
    assert env.status("w") == WorkerStatus.RUNNING
    assert old.is_alive()

    result = env.start("w")

    assert result is False
    live = env.live("w")
    assert len(live) == 1
    assert live[0] is old
    assert len(target.calls) == 1


# ---------------------------------------------------------------------------
# R9 — охрана: имя потока сохранено (старт C и авто-рестарт)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r9_thread_name_on_fresh_start(env):
    target = env.create("w", ["coop"])
    assert env.start("w") is True

    assert wait_until(lambda: len(target.names) == 1)
    assert target.names == [f"{env.name}_w"]
    assert [t.name for t in env.live("w")] == [f"{env.name}_w"]


@pytest.mark.timeout(30)
def test_r9_thread_name_after_auto_restart(env):
    target = env.create("w", ["raise", "coop"], restart_on_failure=True, max_restarts=3)
    assert env.start("w") is True

    assert wait_until(lambda: len(target.names) == 2), "авто-рестарт не произошёл"
    assert target.names == [f"{env.name}_w", f"{env.name}_w"]
    assert [t.name for t in env.live("w")] == [f"{env.name}_w"]


# ---------------------------------------------------------------------------
# R10 — Thread.start() бросил: статус и restart_count возвращены
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r10_thread_start_failure_restores_status_and_restart_count(env, monkeypatch):
    target = env.create("w", ["exit", "coop"])
    assert env.start("w") is True
    old = env.info("w")["thread"]
    old.join(_DEADLINE)
    assert not old.is_alive()
    assert wait_until(lambda: env.status("w") == WorkerStatus.STOPPED)
    rc_before = env.restart_count("w")
    worker_thread_name = env.thread_name("w")

    real_start = threading.Thread.start

    def failing_start(self):
        if self.name == worker_thread_name:
            raise RuntimeError("can't start new thread")
        return real_start(self)

    monkeypatch.setattr(threading.Thread, "start", failing_start)
    try:
        outcome = run_with_deadline(lambda: _call_start_capture(env.mgr, "w"))
    finally:
        monkeypatch.undo()

    # Исход вызова: False или исключение — оба честны; True — ложь (потока нет).
    assert outcome != ("ok", True), "start_worker вернул True, хотя поток не стартовал"
    assert env.status("w") == WorkerStatus.STOPPED, "статус RUNNING залип при непущенном потоке"
    assert env.restart_count("w") == rc_before
    assert env.live("w") == []
    assert len(target.calls) == 1


def _call_start_capture(mgr, worker: str):
    try:
        return ("ok", mgr.start_worker(worker))
    except Exception as exc:  # noqa: BLE001
        return ("raised", type(exc).__name__)
