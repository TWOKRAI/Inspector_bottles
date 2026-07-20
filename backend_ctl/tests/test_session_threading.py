# -*- coding: utf-8 -*-
"""Task 2.1 — потокобезопасность жизненного цикла DriverSession.

Системный диагноз ultra-ревью 2026-07-20: session-слой писался как однопоточный, а
SDK гоняет ``tools/call`` в ПАРАЛЛЕЛЬНЫХ потоках (``anyio.to_thread.run_sync`` +
``tg.start_soon``, без per-session очереди). Каждая пара «проверил — присвоил» здесь
была гонкой:

  * два ``ensure()`` создавали по driver'у — один утекал вместе с сокетом и reader-потоком;
  * ``reset()`` посреди чужого ``ensure()`` отдавал уже закрытый driver;
  * два ``capabilities_cache()`` дважды дёргали бэкенд, а сбой одного затирал удачный
    свод другого — валидация ``send_command`` слепла на всю сессию;
  * два ленивых ``_audit_log()`` создавали по журналу, и часть записей уходила в потерянный.

Тесты бьют по этим местам многопоточно. Гонки вероятностны: barrier синхронизирует старт
потоков (без него они просто не пересекаются во времени), а прогоны повторяются — один
удачный проход ничего не доказывает.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any, Dict, List

from backend_ctl.mcp_driver_session import DriverSession

_THREADS = 8
_ROUNDS = 30


class _CountingFakeDriver:
    """Fake-driver, считающий созданные экземпляры и закрытия."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.connection_lost = False
        self.closed = False

    def export_subscriptions(self) -> list:
        return []

    def import_subscriptions(self, intents: list) -> None:
        pass

    def replay_subscriptions(self) -> list:
        return []

    def capabilities(self) -> Dict[str, Any]:
        return {"ok": True, "driver": self.index}

    def close(self) -> None:
        self.closed = True


def _run_concurrently(fn: Any, threads: int = _THREADS) -> List[Any]:
    """Запустить fn в N потоках со стартом «по свистку» — иначе гонка не воспроизводится."""
    barrier = threading.Barrier(threads)
    results: List[Any] = [None] * threads
    errors: List[BaseException] = []

    def _worker(idx: int) -> None:
        try:
            barrier.wait()
            results[idx] = fn()
        except BaseException as exc:  # noqa: BLE001 — падение потока обязано валить тест
            errors.append(exc)

    workers = [threading.Thread(target=_worker, args=(i,)) for i in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=10.0)
    assert not [w for w in workers if w.is_alive()], "поток завис — вероятен дедлок на локе сессии"
    assert not errors, f"поток упал: {errors[0]!r}"
    return results


def _session_with_counter(*, connect_delay: float = 0.0) -> tuple[DriverSession, List[_CountingFakeDriver]]:
    """Сессия с фабрикой-счётчиком.

    ``connect_delay`` намеренно РАСТЯГИВАЕТ «коннект»: без этого гонка check-then-act
    почти не воспроизводится — GIL успевает провести поток от проверки до присвоения
    одним куском, и тест зеленел бы даже на не-потокобезопасном коде. Задержка делает
    окно шире планировщика, превращая вероятностный тест в детерминированный.
    """
    created: List[_CountingFakeDriver] = []
    lock = threading.Lock()

    def _factory() -> _CountingFakeDriver:
        if connect_delay:
            time.sleep(connect_delay)
        with lock:
            drv = _CountingFakeDriver(len(created))
            created.append(drv)
        return drv

    return DriverSession(driver_factory=_factory, log=lambda _m: None), created


def test_parallel_ensure_creates_exactly_one_driver() -> None:
    """N потоков × ensure() на пустой сессии → ровно ОДИН driver, ноль утечек."""
    for _ in range(_ROUNDS):
        session, created = _session_with_counter(connect_delay=0.01)
        drivers = _run_concurrently(session.ensure)
        assert len(created) == 1, f"создано {len(created)} driver'ов вместо одного — утечка сокета"
        assert all(d is drivers[0] for d in drivers), "потоки получили РАЗНЫЕ driver'ы"


def test_reset_during_ensure_stays_consistent() -> None:
    """reset() параллельно с ensure() не роняет поток и не отдаёт ``None``.

    Инвариант именно такой, а не «выданный driver жив»: сосед вправе сбросить сессию
    сразу после выдачи — ссылка на закрытый driver в чужих руках здесь законна. Ловим
    другое: до Task 2.1 ``ensure()`` мог наткнуться на полу-сброшенное состояние
    (driver уже закрыт, поле ещё не обнулено) и упасть AttributeError'ом внутри
    replay-ветки, а два потока — создать по driver'у, из которых один утекал.
    """
    for _ in range(_ROUNDS):
        session, created = _session_with_counter()
        session.ensure()
        counter = itertools.count()

        def _mixed() -> Any:
            if next(counter) % 2:
                session.reset()
                return None
            return session.ensure()

        results = _run_concurrently(_mixed)

        assert any(r is not None for r in results), "ни один ensure() не отдал driver"
        # Каждый созданный driver либо активен, либо закрыт штатным reset'ом — «повисших»
        # (созданных, но потерянных без close) быть не должно: это утечка сокета и потока.
        leaked = [d for d in created if not d.closed and d is not session._driver]
        assert not leaked, f"{len(leaked)} driver'ов создано и потеряно без close()"


def test_parallel_capabilities_cache_fetches_once() -> None:
    """N потоков × capabilities_cache() → свод собирается один раз, результат общий."""
    calls: List[int] = []
    calls_lock = threading.Lock()

    class _CapsDriver(_CountingFakeDriver):
        def capabilities(self) -> Dict[str, Any]:
            time.sleep(0.01)  # расширяем окно check-then-act (см. _session_with_counter)
            with calls_lock:
                calls.append(1)
            return {"ok": True}

    session = DriverSession(driver_factory=lambda: _CapsDriver(0), log=lambda _m: None)
    results = _run_concurrently(session.capabilities_cache)

    assert len(calls) == 1, f"свод собран {len(calls)} раз — лишние обращения к бэкенду"
    assert all(r == {"ok": True} for r in results)


def test_failed_capabilities_fetch_does_not_clobber_good_cache() -> None:
    """Сбой сбора НЕ затирает уже собранный свод — иначе валидация слепнет на всю сессию."""

    class _FlakyDriver(_CountingFakeDriver):
        fail = False

        def capabilities(self) -> Dict[str, Any]:
            if _FlakyDriver.fail:
                raise RuntimeError("бэкенд не отдал свод")
            return {"ok": True}

    session = DriverSession(driver_factory=lambda: _FlakyDriver(0), log=lambda _m: None)
    assert session.capabilities_cache() == {"ok": True}

    _FlakyDriver.fail = True
    try:
        # refresh со сбоем: прежний удачный свод обязан уцелеть.
        assert session.capabilities_cache(refresh=True) == {"ok": True}
    finally:
        _FlakyDriver.fail = False


def test_parallel_audit_log_init_creates_single_journal(tmp_path, monkeypatch) -> None:
    """Ленивый аудит-журнал инициализируется один раз даже под конкуренцией."""
    monkeypatch.setenv("BACKEND_CTL_AUDIT_DIR", str(tmp_path))
    session = DriverSession(driver_factory=lambda: _CountingFakeDriver(0), log=lambda _m: None)

    journals = _run_concurrently(session._audit_log)
    assert all(j is journals[0] for j in journals), "созданы РАЗНЫЕ журналы — часть записей потеряна"


class _StubRecording:
    """Минимальная запись для ReplayPlayer — только то, что читает конструктор."""

    truncated = False
    header: Dict[str, Any] = {}
    events: List[Dict[str, Any]] = []


def test_load_replay_closes_live_driver_end_to_end(monkeypatch) -> None:
    """Сквозной путь load_replay(): загрузка записи закрывает живое соединение."""
    session, _created = _session_with_counter()
    live = session.ensure()

    monkeypatch.setattr("backend_ctl.mcp_driver_session.load_recording", lambda _p: _StubRecording())

    class _StubPlayer:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            self.driver = object()

        def status(self) -> Dict[str, Any]:
            return {"success": True}

    monkeypatch.setattr("backend_ctl.mcp_driver_session.ReplayPlayer", _StubPlayer)

    out = session.load_replay("не-важно.jsonl")
    assert out["success"] is True
    assert live.closed is True, "load_replay обязан квиесцировать live-driver (C-3)"

    # Возврат в live честно переподключается — «следующий ensure() переподключится»
    # в докстроке unload_replay() до Task 2.1 было неправдой: driver оставался прежним.
    session.unload_replay()
    revived = session.ensure()
    assert revived is not live, "после реплея обязан подняться НОВЫЙ live-driver"
