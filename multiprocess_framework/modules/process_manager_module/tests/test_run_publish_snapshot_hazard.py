# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — дополнение лида к слепому набору: снимок состояния берётся ПОД замком публикации.

Слепой ``test_run_state_published_in_order`` не ловил инъекцию «снимок взят до захвата ``_run_publish_lock``»
(handoff 2026-11-09, п. «Не сделано»): у него медленный не снимок, а запись в стор. Здесь окно гонки открывает сам
снимок: обёртка ``_run_snapshot`` отдаёт значение и засыпает. Верный код: сон проходит внутри замка публикации,
второй издатель ждёт и снимает уже новое состояние. Инъекция (снимок до замка): сон вне замка, второй издатель
публикует новое состояние, первый затем пишет устаревшее — последняя запись в стор ≠ состоянию машины.

Тест не правит файл слепого tester; автор — лид полосы.
"""

from __future__ import annotations

import threading
import time

from .test_run_commands import _JOIN_S, _join, _Store, make_run_pm


def test_stale_snapshot_does_not_roll_back_published_state() -> None:
    pm = make_run_pm(True)
    store = _Store()
    pm._state_store_manager = store

    real_snapshot = pm._run_snapshot
    first_taken = threading.Event()
    calls = {"n": 0}
    calls_lock = threading.Lock()

    def slow_snapshot():
        result = real_snapshot()  # настоящий снимок под _run_lock; сон — уже после него
        with calls_lock:
            calls["n"] += 1
            first = calls["n"] == 1
        if first:
            first_taken.set()
            time.sleep(0.05)
        return result

    pm._run_snapshot = slow_snapshot  # type: ignore[method-assign]
    errors: list[BaseException] = []

    def guarded(fn):
        def go() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        return go

    a = threading.Thread(target=guarded(lambda: pm._run_apply("start")), daemon=True, name="snap-a")
    a.start()
    assert first_taken.wait(_JOIN_S), "первый издатель не снял снимок"
    b = threading.Thread(target=guarded(lambda: pm._run_apply("stop")), daemon=True, name="snap-b")
    b.start()
    _join(b)
    _join(a)
    assert not errors, errors

    assert pm._run_state == "stopping"
    assert store.values("system.run.state")[-1] == "stopping", store.writes
    assert store.values("system.run.since")[-1] == pm._run_since, store.writes


def test_tick_updates_ready_even_when_state_does_not_change() -> None:
    """``tick(ready=False)`` в ``stopping`` — no-op по состоянию, но обновляет ``_run_ready`` (DESIGN п.2).

    Следом ``settled`` без явного ``ready`` читает ``_run_ready`` и даёт ``not_ready``, а не ``ready``.
    Инъекция «tick не пишет _run_ready» оставляла набор зелёным (стадия 3, I16).
    """
    pm = make_run_pm(True)
    assert pm._run_apply("start")[0] == "running"
    assert pm._run_apply("stop")[0] == "stopping"

    new, code, prev = pm._run_apply("tick", ready=False)
    assert (new, code, prev) == ("stopping", None, "stopping")

    new, code, prev = pm._run_apply("settled")
    assert (new, code, prev) == ("not_ready", None, "stopping")
