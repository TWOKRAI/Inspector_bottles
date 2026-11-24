# -*- coding: utf-8 -*-
"""Потоковые hazard-тесты TimeRing (Tasks T9a и T9b): читатели, закрепление и экспорт под писателем.

Purpose: поймать гонки кольца: читатель без замка видит кадр, сдвинутый вытеснением, рваную пару
«число кадров / байты», рваный диапазон; пин/анпин и экспорт параллельно с append не портят кольцо.

Метод: каждый payload несёт свой capture_ns (первые 8 байт), читатель сверяет payload с метаданными
и проверяет инварианты снимка, которые верны при любом чередовании потоков. Потоки — daemon, join с
дедлайном, `sys.setswitchinterval(1e-6)` возвращается в `finally`.
"""

from __future__ import annotations

import struct
import sys
import threading
from collections.abc import Callable

import Services.frame_buffer.time_ring as time_ring_module
from Services.frame_buffer.segment import RECORD_SIZE, read_segment
from Services.frame_buffer.time_ring import TimeRing

__all__ = []

STEP = 1_000_000  # 1 мс между кадрами
PAYLOAD_SIZE = 64  # у всех кадров одинаковый размер: bytes_held == frames * PAYLOAD_SIZE
ITERATIONS = 20_000
JOIN_TIMEOUT = 5.0
BUFFER_S = 0.05  # окно 50 кадров: вытеснение идёт на каждом append
MAX_BYTES = 40 * PAYLOAD_SIZE  # потолок режет окно до 40 кадров: вытеснение по байтам тоже работает
PIN_MAX_BYTES = 10 * PAYLOAD_SIZE


def _payload(capture_ns: int) -> bytes:
    return struct.pack("<q", capture_ns) + b"\x00" * (PAYLOAD_SIZE - 8)


def _carried_ns(payload: bytes) -> int:
    return struct.unpack_from("<q", payload)[0]


def _ring() -> TimeRing:
    return TimeRing(buffer_seconds=BUFFER_S, max_bytes=MAX_BYTES, pin_max_bytes=PIN_MAX_BYTES)


class _Run:
    """Запуск набора daemon-потоков при минимальном интервале переключения GIL."""

    def __init__(self) -> None:
        self.errors: list[BaseException] = []
        self.writer_done = threading.Event()
        self.last_ns = 0  # прогресс писателя для потоков, которым нужно «сейчас»

    def guarded(self, fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - пробрасываем в основной поток
                self.errors.append(exc)

        return run

    def writer(self, ring: TimeRing, group_modulo: int | None = None) -> Callable[[], None]:
        def write() -> None:
            try:
                for i in range(ITERATIONS):
                    ns = i * STEP
                    ring.append(
                        capture_ns=ns,
                        capture_ts=float(i),
                        payload=_payload(ns),
                        seq=i + 1,
                        group_id=i % group_modulo if group_modulo else None,
                    )
                    self.last_ns = ns
            finally:
                self.writer_done.set()

        return write

    def go(self, *bodies: Callable[[], None]) -> None:
        """Запустить все тела в daemon-потоках, дождаться с дедлайном, пробросить первую ошибку."""
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=self.guarded(body), daemon=True) for body in bodies]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=JOIN_TIMEOUT)
            alive = [t for t in threads if t.is_alive()]
        finally:
            sys.setswitchinterval(old)
        assert not alive, "поток не завершился за дедлайн"
        if self.errors:
            raise self.errors[0]


def _check_stats_snapshot(stats: dict) -> None:
    """Инварианты одного снимка stats(): рваное чтение «число кадров / байты» их нарушает."""
    assert stats["bytes_held"] == stats["frames"] * PAYLOAD_SIZE
    assert stats["bytes_held"] <= MAX_BYTES
    assert stats["bytes_held_peak"] <= MAX_BYTES
    assert stats["bytes_held_peak"] >= stats["bytes_held"]


def _check_range_snapshot(rng: dict) -> None:
    """Кадры идут подряд с шагом STEP, разрывов seq нет: размах и число кадров связаны точно."""
    if rng["frames"] == 0:
        return
    assert rng["t_max_ns"] - rng["t_min_ns"] == (rng["frames"] - 1) * STEP
    assert rng["gaps"] == []


def _check_found(found: dict | None, t_ns: int, mode: str) -> None:
    if found is None:
        return
    assert _carried_ns(found["payload"]) == found["capture_ns"]  # payload принадлежит своей метаданной
    assert found["seq"] == found["capture_ns"] // STEP + 1
    if mode == "prev":
        assert found["capture_ns"] <= t_ns
    elif mode == "next":
        assert found["capture_ns"] >= t_ns


def _check_segment(blob: bytes, index: bytes) -> int:
    """Экспорт целиком согласован: записи подряд по `(capture_ns, seq)`, payload свой у каждой."""
    assert len(index) % RECORD_SIZE == 0
    records = read_segment(blob, index)
    assert len(records) == len(index) // RECORD_SIZE  # ни одна запись не вылезла за блок
    assert len(blob) == len(records) * PAYLOAD_SIZE
    previous = None
    for record in records:
        assert _carried_ns(record["payload"]) == record["capture_ns"]
        pair = (record["capture_ns"], record["seq"])
        assert previous is None or pair > previous
        previous = pair
    return len(records)


def test_concurrent_append_and_at() -> None:
    """Писатель 20000 кадров против читателя at/range/stats: ни ошибок, ни рваных снимков."""
    ring = _ring()
    run = _Run()

    def reader() -> None:
        modes = ("nearest", "prev", "next")
        n = 0
        while not run.writer_done.is_set():
            n += 1
            t_ns = max(run.last_ns - (n % 60) * STEP, 0)
            mode = modes[n % 3]
            _check_found(ring.at(t_ns, mode), t_ns, mode)
            _check_stats_snapshot(ring.stats())
            _check_range_snapshot(ring.range())

    run.go(run.writer(ring), reader)

    stats = ring.stats()
    _check_stats_snapshot(stats)
    assert stats["frames"] == 40  # потолок байтов режет окно в 50 кадров до 40
    assert ring.range()["t_max_ns"] == (ITERATIONS - 1) * STEP


def test_concurrent_pin_unpin_under_writer() -> None:
    """pin/unpin из отдельного потока под писателем: потолок и счётчики держатся, итог согласован."""
    ring = _ring()
    run = _Run()

    def pinner() -> None:
        n = 0
        while not run.writer_done.is_set():
            n += 1
            now = run.last_ns
            ring.pin(max(now - 5 * STEP, 0), now + 20 * STEP, f"t{n % 3}")  # прошлое и будущее
            if n % 2:
                ring.unpin(f"t{(n + 1) % 3}")
            stats = ring.stats()
            _check_stats_snapshot(stats)
            assert stats["pins_released"] >= 0

    def reader() -> None:
        released = 0
        n = 0
        while not run.writer_done.is_set():
            n += 1
            t_ns = max(run.last_ns - (n % 60) * STEP, 0)
            _check_found(ring.at(t_ns, "nearest"), t_ns, "nearest")
            stats = ring.stats()
            _check_stats_snapshot(stats)
            assert stats["pins_released"] >= released  # счётчик не убывает
            released = stats["pins_released"]
            assert ring.range()["frames"] > 0 or run.last_ns == 0

    run.go(run.writer(ring), pinner, reader)

    _check_stats_snapshot(ring.stats())
    exported = ring.export(0, ITERATIONS * STEP)
    assert _check_segment(exported["blob"], exported["index"]) == ring.stats()["frames"]


def test_concurrent_export_under_writer() -> None:
    """export параллельно с append: каждый экспорт — согласованный сегмент, кольцо не портится."""
    ring = _ring()
    run = _Run()
    exports = []

    def exporter() -> None:
        while not run.writer_done.is_set():
            lo = max(run.last_ns - 30 * STEP, 0)
            exported = ring.export(lo, lo + 60 * STEP)
            count = _check_segment(exported["blob"], exported["index"])
            assert count <= 40
            exports.append(count)
            _check_stats_snapshot(ring.stats())

    run.go(run.writer(ring), exporter)

    assert exports, "экспортёр не успел сделать ни одного прохода"
    stats = ring.stats()
    _check_stats_snapshot(stats)
    assert stats["frames"] == 40
    final = ring.export(0, ITERATIONS * STEP)
    assert _check_segment(final["blob"], final["index"]) == 40


def test_concurrent_find_group_under_writer() -> None:
    """find_group под писателем: без замка обход deque падает «deque mutated during iteration»."""
    ring = _ring()
    run = _Run()

    def reader() -> None:
        while not run.writer_done.is_set():
            found = ring.find_group(1)
            previous = None
            for frame in found:
                assert frame["group_id"] == 1
                assert _carried_ns(frame["payload"]) == frame["capture_ns"]
                pair = (frame["capture_ns"], frame["seq"])
                assert previous is None or pair > previous
                previous = pair
            assert len(found) <= 40

    run.go(run.writer(ring, group_modulo=3), reader)

    assert [f["group_id"] for f in ring.find_group(1)] == [1] * len(ring.find_group(1))
    _check_stats_snapshot(ring.stats())


def test_export_does_not_block_writer_while_blob_is_built(monkeypatch) -> None:
    """Склейка блока идёт вне замка: пока `build_segment` занят, append/at/stats проходят."""
    ring = TimeRing(buffer_seconds=100.0, max_bytes=10_000, pin_max_bytes=5_000)
    for i in range(3):
        ring.append(i * STEP, 0.0, bytes([i + 1]) * 100, i + 1)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    real_build = time_ring_module.build_segment

    def slow_build(frames):
        entered.set()
        assert release.wait(10)
        return real_build(frames)

    monkeypatch.setattr(time_ring_module, "build_segment", slow_build)
    box: dict = {}
    exporter = threading.Thread(target=lambda: box.update(ring.export(0, 10**12)), daemon=True)
    exporter.start()
    try:
        assert entered.wait(5), "export не дошёл до сборки блока"

        def writer() -> None:
            ring.append(3 * STEP, 0.0, b"" * 100, 4)
            ring.at(STEP, "nearest")
            ring.stats()
            done.set()

        threading.Thread(target=writer, daemon=True).start()
        assert done.wait(2), "append/at/stats заблокированы, пока export собирает блок"
    finally:
        release.set()
    exporter.join(5)
    assert not exporter.is_alive()
    assert len(box["blob"]) == 300  # export снял срез из 3 кадров, бывших на момент взятия замка
    assert len(box["index"]) == 3 * RECORD_SIZE
