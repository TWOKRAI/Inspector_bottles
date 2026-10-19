"""Тест автора T5.3c c2: гонка первых записей в несуществующий каталог устройства (``RobotDataStore``).

Purpose:
    Восемь потоков одновременно пишут первый документ устройства на свежем корне; ключи валидны, поэтому
    ``InvalidStoreKey`` не допустим ни разу: допустимы ``ok`` и ``RevisionConflict`` (один победитель).

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from Services.robot_comm.store import RobotDataStore

_THREADS = 8
_ROUNDS = 20
_JOIN_S = 15.0


def _write_program(store: RobotDataStore) -> None:
    store.write_program("r1", "p1", {"version": 1, "name": "p1", "steps": []}, base_rev=None)


def _write_points(store: RobotDataStore) -> None:
    store.write("r1", "points", {"version": 1, "points": []}, base_rev=None)


def _race(root: Path, op: Callable[[RobotDataStore], None]) -> Counter[str]:
    store = RobotDataStore(root)
    outcome: Counter[str] = Counter()
    guard = threading.Lock()
    start = threading.Event()

    def body() -> None:
        start.wait(_JOIN_S)
        try:
            op(store)
            name = "ok"
        except Exception as exc:  # noqa: BLE001 - исход потока считается по имени класса
            name = type(exc).__name__
        with guard:
            outcome[name] += 1

    threads = [threading.Thread(target=body, daemon=True) for _ in range(_THREADS)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(_JOIN_S)
    assert not any(t.is_alive() for t in threads), "поток записи завис"
    return outcome


@pytest.mark.parametrize("op", [_write_program, _write_points], ids=["program", "points"])
def test_first_writes_into_fresh_root_never_invalid_key(tmp_path: Path, op: Callable[[RobotDataStore], None]) -> None:
    total: Counter[str] = Counter()
    for round_no in range(_ROUNDS):
        outcome = _race(tmp_path / f"round{round_no}", op)
        assert outcome["ok"] == 1, (round_no, dict(outcome))
        total.update(outcome)
    assert set(total) <= {"ok", "RevisionConflict"}, dict(total)
