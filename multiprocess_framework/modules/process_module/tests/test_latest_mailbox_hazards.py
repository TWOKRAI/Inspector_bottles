"""Потоковые hazard-тесты LatestMailbox (T1, plan gui-frame-path; файл автора реализации).

Purpose: поймать гонку счётчиков ``put == taken + superseded + pending`` при одновременных
``put`` / ``take`` из нескольких потоков. На стандартном интервале переключения потоков
(5 мс) версия без замка не краснеет: операции слишком коротки. Поэтому тест ставит
``sys.setswitchinterval(1e-6)`` и восстанавливает прежнее значение в ``finally``.

Приёмка и контракт — в ``test_latest_mailbox.py`` (файл слепого tester-а); здесь только
потоки. Все потоки daemon, ``join`` с дедлайном: зависание даёт красный тест, не повисший
прогон.
"""

import sys
import threading

import pytest

from multiprocess_framework.modules.process_module.generic.latest_mailbox import (
    LatestMailbox,
)

__all__: list[str] = []

_KEYS = ["k0", "k1", "k2"]  # общие для всех потоков
_MAX_KEYS = 2  # меньше числа ключей: отказы по max_keys тоже идут в гонке
_NBYTES = 10
_WRITERS = 3
_ITERATIONS = 4000
_JOIN_DEADLINE_S = 60.0


def _join_or_fail(threads: list[threading.Thread]) -> None:
    for th in threads:
        th.join(_JOIN_DEADLINE_S)
    alive = [th.name for th in threads if th.is_alive()]
    assert not alive, f"потоки не завершились за {_JOIN_DEADLINE_S} с: {alive}"


@pytest.mark.parametrize("round_no", range(8))
def test_invariant_holds_under_two_threads(round_no: int):
    """Три потока put/take на общих ключах: инвариант в конце и в каждом снимке stats()."""
    box = LatestMailbox(max_keys=_MAX_KEYS)
    stop_reader = threading.Event()
    snapshots_bad: list[dict[str, int]] = []
    snapshots_taken = [0]
    # результаты писателей: локальные счётчики независимы от проверяемого ящика
    local_accepted = [0] * _WRITERS
    local_rejected = [0] * _WRITERS
    local_taken: list[list[tuple[int, int]]] = [[] for _ in range(_WRITERS)]
    errors: list[BaseException] = []

    def writer(idx: int) -> None:
        try:
            for i in range(_ITERATIONS):
                key = _KEYS[(i + idx) % len(_KEYS)]
                if box.put(key, (idx, i), nbytes=_NBYTES):
                    local_accepted[idx] += 1
                else:
                    local_rejected[idx] += 1
                got = box.take(_KEYS[(i + idx + 1) % len(_KEYS)])
                if got is not None:
                    local_taken[idx].append(got[0])
        except BaseException as exc:  # noqa: BLE001 - показать в тесте
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop_reader.is_set():
                s = box.stats()
                snapshots_taken[0] += 1
                if (
                    s["put"] != s["taken"] + s["superseded"] + s["pending"]
                    or s["bytes_held"] != _NBYTES * s["pending"]
                    or s["pending"] > _MAX_KEYS
                    or s["max_bytes_held"] > _NBYTES * _MAX_KEYS
                ):
                    snapshots_bad.append(s)
                box.pending_keys()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        writers = [threading.Thread(target=writer, args=(n,), daemon=True, name=f"w{n}") for n in range(_WRITERS)]
        reader_th = threading.Thread(target=reader, daemon=True, name="reader")
        reader_th.start()
        for th in writers:
            th.start()
        _join_or_fail(writers)
        stop_reader.set()
        _join_or_fail([reader_th])
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, errors
    assert snapshots_taken[0] > 0, "читатель не успел снять ни одного снимка"
    assert not snapshots_bad, snapshots_bad[:3]

    s = box.stats()
    assert s["put"] == s["taken"] + s["superseded"] + s["pending"], s
    # счётчики ящика совпадают с тем, что насчитали сами потоки
    assert s["put"] == sum(local_accepted), s
    assert s["rejected"] == sum(local_rejected), s
    all_taken = [item for per in local_taken for item in per]
    assert s["taken"] == len(all_taken), s
    assert s["put"] + s["rejected"] == _WRITERS * _ITERATIONS, s
    # ни один элемент не отдан дважды
    assert len(set(all_taken)) == len(all_taken)
    assert s["bytes_held"] == _NBYTES * s["pending"], s
    assert len(box.pending_keys()) == s["pending"]


def test_clear_races_with_put_and_take():
    """clear() из третьего потока не нарушает баланс счётчиков при гонке с put/take."""
    box = LatestMailbox(max_keys=_MAX_KEYS)
    stop = threading.Event()
    bad: list[dict[str, int]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for i in range(_ITERATIONS):
                box.put(_KEYS[i % len(_KEYS)], i, nbytes=_NBYTES)
                box.take(_KEYS[(i + 1) % len(_KEYS)])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def clearer() -> None:
        try:
            while not stop.is_set():
                box.clear()
                s = box.stats()
                if s["put"] != s["taken"] + s["superseded"] + s["pending"]:
                    bad.append(s)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        workers = [threading.Thread(target=worker, daemon=True, name=f"cw{n}") for n in range(2)]
        clear_th = threading.Thread(target=clearer, daemon=True, name="clearer")
        clear_th.start()
        for th in workers:
            th.start()
        _join_or_fail(workers)
        stop.set()
        _join_or_fail([clear_th])
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, errors
    assert not bad, bad[:3]
    s = box.stats()
    assert s["put"] == s["taken"] + s["superseded"] + s["pending"], s
    assert s["bytes_held"] == _NBYTES * s["pending"], s


def test_take_age_is_never_negative_under_race():
    """Два писателя и читатель на одном ключе: age_s из take() никогда не меньше 0.

    Часы в take, прочитанные до замка, давали отрицательный возраст (put успевал между
    чтением часов и захватом замка): на таком коде около половины взятых элементов.
    """
    box = LatestMailbox()
    stop = threading.Event()
    ages: list[float] = []
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            i = 0
            while not stop.is_set():
                box.put("k", i)
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                got = box.take("k")
                if got is not None:
                    ages.append(got[1])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=writer, daemon=True, name=f"aw{n}") for n in range(2)]
        threads.append(threading.Thread(target=reader, daemon=True, name="ar"))
        for th in threads:
            th.start()
        stop.wait(2.0)
        stop.set()
        _join_or_fail(threads)
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, errors
    assert len(ages) > 0, "читатель не взял ни одного элемента"
    assert min(ages) >= 0.0, f"отрицательный age_s: {min(ages)}"
