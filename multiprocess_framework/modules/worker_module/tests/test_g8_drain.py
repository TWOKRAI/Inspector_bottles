# -*- coding: utf-8 -*-
"""Ф7 G.8: drain→detach→stop воркера — дренаж дожидается завершения кадра (нет полукадра).

drain_worker: пауза (новых кадров нет) + ждать is_busy False (текущий кадр завершён).
Детерминированно через Event'ы: пока кадр «в работе» (release не взведён) drain НЕ
проскакивает (таймаут), после release кадр завершается целиком → drain проходит.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ThreadPriority,
    WorkerManager,
)


class _BusyWorker:
    """Воркер с управляемой busy-фазой (имитация кадра). Кадр висит на ``release``."""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._busy = False
        self._started = started
        self._release = release
        self.frames_done = 0

    @property
    def is_busy(self) -> bool:
        return self._busy

    def run(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        while not stop_event.is_set():
            if pause_event.is_set():
                stop_event.wait(0.01)
                continue
            self._busy = True
            try:
                self._started.set()
                # «Кадр» висит, пока тест не отпустит — имитирует работу над кадром.
                self._release.wait(2.0)
                self.frames_done += 1
            finally:
                self._busy = False
            # один управляемый кадр — дальше пауза (тест взводит) паркует петлю.


def _make(manager: WorkerManager, name: str, worker: _BusyWorker) -> None:
    cfg = ThreadConfig(priority=ThreadPriority.NORMAL)
    manager.create_worker(name, worker.run, cfg, auto_start=True)


class TestDrainWorker:
    def test_drain_missing_worker(self):
        m = WorkerManager("m")
        assert m.drain_worker("nope") is False

    def test_drain_waits_for_in_flight_frame(self):
        """Пока кадр в работе (busy) — drain НЕ проскакивает (таймаут). Кадр не рвётся."""
        m = WorkerManager("m")
        started, release = threading.Event(), threading.Event()
        worker = _BusyWorker(started, release)
        try:
            _make(m, "w", worker)
            assert started.wait(2.0)  # воркер вошёл в кадр (busy)

            # Кадр не отпущен → drain дожидается busy=False и упирается в таймаут.
            assert m.drain_worker("w", timeout=0.2) is False
            assert worker.is_busy is True  # кадр всё ещё выполняется — НЕ прерван

            # Отпускаем кадр → он завершается ЦЕЛИКОМ, затем воркер паркуется (pause взведён drain'ом).
            release.set()
            assert m.drain_worker("w", timeout=1.0) is True  # теперь idle
            assert worker.frames_done == 1  # кадр завершён полностью (нет полукадра)
        finally:
            m.stop_worker("w", timeout=1.0)

    def test_drain_and_remove(self):
        m = WorkerManager("m")
        started, release = threading.Event(), threading.Event()
        worker = _BusyWorker(started, release)
        _make(m, "w", worker)
        assert started.wait(2.0)
        release.set()  # даём кадру завершиться
        assert m.drain_and_remove("w", timeout=1.0) is True
        assert m.get_worker_status("w") is None or not m._worker_registry.has("w")

    def test_drain_grace_for_worker_without_is_busy(self):
        """Воркер без is_busy → grace-пауза, drain возвращает True (best-effort)."""
        m = WorkerManager("m")

        def plain_run(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    stop_event.wait(0.01)
                    continue
                stop_event.wait(0.01)

        cfg = ThreadConfig(priority=ThreadPriority.NORMAL)
        m.create_worker("plain", plain_run, cfg, auto_start=True)
        try:
            assert m.drain_worker("plain", timeout=0.5) is True
        finally:
            m.stop_worker("plain", timeout=1.0)
