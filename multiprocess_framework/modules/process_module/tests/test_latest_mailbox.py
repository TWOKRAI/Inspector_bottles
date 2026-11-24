"""Слепые приёмочные тесты LatestMailbox (T1, plan gui-frame-path).

Purpose: проверить публичный контракт LatestMailbox: не больше одного ожидающего
элемента на ключ, новый вытесняет старый того же ключа, ключи независимы, память =
ключи x 1 элемент при любой частоте входа, счётчики stats() дают честный баланс
``put == taken + superseded + pending``.

Источник требований — только критерии приёмки; реализацию тесты не читают и не
предполагают её устройства. Ожидаемые значения — литералы, не вычисленные из
тестируемого кода. Часы подставляются параметром ``clock`` (контракт). Потоковый
тест ``test_invariant_holds_under_two_threads`` живёт в другом файле
(``test_latest_mailbox_hazards.py``).
"""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from multiprocess_framework.modules.process_module.generic.latest_mailbox import (
    LatestMailbox,
)

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MODULE_FILE = _REPO_ROOT / "multiprocess_framework" / "modules" / "process_module" / "generic" / "latest_mailbox.py"
_STATS_KEYS = {
    "put",
    "taken",
    "superseded",
    "rejected",
    "pending",
    "bytes_held",
    "max_bytes_held",
}


class _FakeClock:
    """Управляемые часы: ``clock()`` возвращает текущее ``t``."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _assert_balance(s: dict[str, int]) -> None:
    """Инвариант контракта: put == taken + superseded + pending."""
    assert s["put"] == s["taken"] + s["superseded"] + s["pending"], s


def _run_within(fn, deadline_s: float = 5.0):
    """Выполнить fn в daemon-потоке; не уложился в дедлайн -> тест красный, а не зависший."""
    out: dict[str, object] = {}

    def runner() -> None:
        try:
            out["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в тест
            out["error"] = exc

    th = threading.Thread(target=runner, daemon=True)
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с (взаимоблокировка?)"
    if "error" in out:
        raise out["error"]  # type: ignore[misc]
    return out.get("result")


# --------------------------------------------------------------------------- #
# Вытеснение: один ожидающий элемент на ключ
# --------------------------------------------------------------------------- #


def test_second_put_same_key_supersedes_first():
    """Второй put того же ключа вытесняет первый: take отдаёт только второй."""
    box = LatestMailbox()
    assert box.put("cam:1", "v1", nbytes=100) is True
    assert box.put("cam:1", "v2", nbytes=40) is True

    s = box.stats()
    assert s["put"] == 2
    assert s["superseded"] == 1
    assert s["pending"] == 1
    assert s["taken"] == 0
    assert s["rejected"] == 0
    assert s["bytes_held"] == 40  # байты старого вычтены, новые добавлены

    got = box.take("cam:1")
    assert got is not None
    item, _age = got
    assert item == "v2"
    assert box.take("cam:1") is None  # первый элемент не остался в очереди позади


def test_keys_are_independent_fast_key_does_not_evict_slow_key():
    """Частый ключ не вытесняет редкий; каждый ключ держит свой последний элемент."""
    box = LatestMailbox()
    assert box.put("slow", "S0", nbytes=10) is True
    for i in range(1000):
        assert box.put("fast", f"F{i}", nbytes=10) is True

    s = box.stats()
    assert s["pending"] == 2
    assert s["superseded"] == 999
    assert s["put"] == 1001
    assert box.pending_keys() == ["slow", "fast"]

    slow = box.take("slow")
    assert slow is not None and slow[0] == "S0"
    fast = box.take("fast")
    assert fast is not None and fast[0] == "F999"
    assert box.take("slow") is None
    assert box.take("fast") is None


def test_key_is_opaque_string():
    """Ключ непрозрачен: «похожие» ключи (префиксы, разделители, юникод) не склеиваются."""
    keys = ["cam", "cam:1", "cam:1/region.left", "sender|cam:1", "камера#1"]
    box = LatestMailbox()
    for i, k in enumerate(keys):
        assert box.put(k, f"item-{i}") is True

    assert box.stats()["pending"] == 5
    assert box.pending_keys() == keys
    for i, k in enumerate(keys):
        got = box.take(k)
        assert got is not None and got[0] == f"item-{i}"


# --------------------------------------------------------------------------- #
# Память = ключи x 1 элемент
# --------------------------------------------------------------------------- #


def test_bytes_held_never_exceeds_latest_per_key():
    """4 ключа x 2500 put по 4665600 байт: держится ровно по одному элементу на ключ."""
    nbytes = 4665600
    keys = ["cam1", "cam2", "cam3", "cam4"]
    box = LatestMailbox()

    worst_seen = 0
    for i in range(2500):
        for k in keys:
            assert box.put(k, (k, i), nbytes=nbytes) is True
        worst_seen = max(worst_seen, box.stats()["bytes_held"])

    assert worst_seen <= 18662400  # на каждом шаге не больше 4 элементов
    s = box.stats()
    assert s["put"] == 10000
    assert s["taken"] == 0
    assert s["pending"] == 4
    assert s["superseded"] == 9996
    assert s["bytes_held"] == 18662400
    assert s["max_bytes_held"] == 18662400
    assert s["rejected"] == 0

    for k in keys:
        got = box.take(k)
        assert got is not None and got[0] == (k, 2499)  # живёт самый свежий

    s = box.stats()
    assert s["taken"] == 4
    assert s["pending"] == 0
    assert s["bytes_held"] == 0
    assert s["max_bytes_held"] == 18662400


def test_max_bytes_held_is_peak_after_replacement():
    """Пик считается после вычитания старых байт замены, а не до него."""
    box = LatestMailbox()
    box.put("a", "a1", nbytes=100)
    box.put("b", "b1", nbytes=50)
    assert box.stats()["max_bytes_held"] == 150

    box.put("a", "a2", nbytes=120)  # реально удерживается 120 + 50
    s = box.stats()
    assert s["bytes_held"] == 170
    assert s["max_bytes_held"] == 170  # не 270 (150 + 120 без вычитания старых 100)

    box.put("a", "a3", nbytes=10)  # пик не снижается
    s = box.stats()
    assert s["bytes_held"] == 60
    assert s["max_bytes_held"] == 170


def test_nbytes_defaults_to_zero():
    """put без nbytes не добавляет байт."""
    box = LatestMailbox()
    assert box.put("a", "x") is True
    s = box.stats()
    assert s["pending"] == 1
    assert s["bytes_held"] == 0
    assert s["max_bytes_held"] == 0


# --------------------------------------------------------------------------- #
# take
# --------------------------------------------------------------------------- #


def test_take_empty_returns_none():
    """take на пустом ящике и на незнакомом ключе даёт None и ничего не считает."""
    box = LatestMailbox()
    assert box.take("nope") is None
    assert box.stats() == {
        "put": 0,
        "taken": 0,
        "superseded": 0,
        "rejected": 0,
        "pending": 0,
        "bytes_held": 0,
        "max_bytes_held": 0,
    }

    box.put("a", "x", nbytes=7)
    assert box.take("other") is None  # чужой ключ не трогает ожидающий
    s = box.stats()
    assert s["taken"] == 0
    assert s["pending"] == 1
    assert s["bytes_held"] == 7


def test_take_removes_item_second_take_returns_none():
    """take снимает запись: второй take даёт None, слот и байты освобождены."""
    box = LatestMailbox()
    assert box.put("a", "x", nbytes=100) is True
    before = box.stats()
    assert before["max_bytes_held"] == 100

    first = box.take("a")
    assert first is not None and first[0] == "x"
    assert box.take("a") is None

    s = box.stats()
    assert s["put"] == 1
    assert s["taken"] == 1
    assert s["pending"] == 0
    assert s["bytes_held"] == 0
    assert s["superseded"] == 0
    assert s["max_bytes_held"] == 100  # take пик не меняет
    assert box.pending_keys() == []


def test_take_returns_age_from_injected_clock():
    """age_s = clock при take минус clock при put ВОЗВРАЩЁННОГО элемента."""
    clock = _FakeClock(0.0)
    box = LatestMailbox(clock=clock)
    box.put("a", "first")  # t = 0.0
    clock.t = 5.0
    box.put("a", "second")  # замена при t = 5.0
    clock.t = 6.0
    got = box.take("a")
    assert got is not None
    item, age_s = got
    assert item == "second"
    assert age_s == pytest.approx(1.0)  # не 6.0 (от первого put)


def test_age_is_per_key():
    """У каждого ключа свой возраст от своего put."""
    clock = _FakeClock(1.0)
    box = LatestMailbox(clock=clock)
    box.put("a", "ia")  # t = 1.0
    clock.t = 4.0
    box.put("b", "ib")  # t = 4.0
    clock.t = 7.0
    got_a = box.take("a")
    got_b = box.take("b")
    assert got_a is not None and got_b is not None
    assert got_a[1] == pytest.approx(6.0)
    assert got_b[1] == pytest.approx(3.0)


def test_default_clock_gives_non_negative_float_age():
    """Без clock берутся штатные часы: age_s - неотрицательное число с плавающей точкой."""
    box = LatestMailbox()
    box.put("a", "x")
    got = box.take("a")
    assert got is not None
    _item, age_s = got
    assert isinstance(age_s, float)
    assert age_s >= 0.0


# --------------------------------------------------------------------------- #
# max_keys
# --------------------------------------------------------------------------- #


def test_max_keys_rejects_and_counts():
    """Новый ключ сверх max_keys отвергается (False) и считается только в rejected."""
    box = LatestMailbox(max_keys=2)
    assert box.put("a", "a1", nbytes=10) is True
    assert box.put("b", "b1", nbytes=20) is True
    assert box.put("c", "c1", nbytes=40) is False  # третий ключ при пределе 2

    s = box.stats()
    assert s["put"] == 2  # отвергнутый вызов в put не входит
    assert s["rejected"] == 1
    assert s["pending"] == 2
    assert s["bytes_held"] == 30  # байты отвергнутого не учтены
    assert s["max_bytes_held"] == 30
    _assert_balance(s)
    assert box.take("c") is None  # отвергнутый элемент не хранится
    assert box.pending_keys() == ["a", "b"]

    # замена существующего ключа при заполненном пределе принимается
    assert box.put("a", "a2", nbytes=15) is True
    s = box.stats()
    assert s["put"] == 3
    assert s["superseded"] == 1
    assert s["rejected"] == 1
    assert s["pending"] == 2
    assert s["bytes_held"] == 35
    _assert_balance(s)

    # take освобождает слот
    taken = box.take("a")
    assert taken is not None and taken[0] == "a2"
    assert box.put("c", "c2", nbytes=40) is True
    s = box.stats()
    assert s == {
        "put": 4,
        "taken": 1,
        "superseded": 1,
        "rejected": 1,
        "pending": 2,
        "bytes_held": 60,
        "max_bytes_held": 60,
    }
    _assert_balance(s)


def test_max_keys_counts_waiting_keys_not_keys_ever_seen():
    """Предел считает ожидающие ключи, а не все ключи за всё время."""
    box = LatestMailbox(max_keys=2)
    for i in range(10):
        key = f"k{i}"
        assert box.put(key, i) is True
        got = box.take(key)
        assert got is not None and got[0] == i

    s = box.stats()
    assert s["put"] == 10
    assert s["taken"] == 10
    assert s["rejected"] == 0
    assert s["pending"] == 0


def test_default_max_keys_is_64():
    """По умолчанию принимается 64 разных ключа, 65-й отвергается."""
    box = LatestMailbox()
    for i in range(64):
        assert box.put(f"k{i}", i) is True
    assert box.put("k64", 64) is False

    s = box.stats()
    assert s["put"] == 64
    assert s["rejected"] == 1
    assert s["pending"] == 64


# --------------------------------------------------------------------------- #
# clear
# --------------------------------------------------------------------------- #


def test_clear_counts_superseded():
    """clear выбрасывает ожидающие в superseded; накопительные счётчики и пик сохраняются."""
    box = LatestMailbox()
    box.put("a", "a1", nbytes=100)
    box.put("b", "b1", nbytes=200)
    assert box.stats()["max_bytes_held"] == 300

    box.clear()

    s = box.stats()
    assert s["put"] == 2
    assert s["taken"] == 0
    assert s["superseded"] == 2  # два выброшенных элемента
    assert s["rejected"] == 0
    assert s["pending"] == 0
    assert s["bytes_held"] == 0
    assert s["max_bytes_held"] == 300  # пик не обнулён
    _assert_balance(s)
    assert box.pending_keys() == []
    assert box.take("a") is None

    # счётчики после clear продолжают накапливаться, а не стартуют заново
    box.put("a", "a2", nbytes=50)
    s = box.stats()
    assert s["put"] == 3
    assert s["superseded"] == 2
    assert s["pending"] == 1
    assert s["bytes_held"] == 50
    assert s["max_bytes_held"] == 300
    _assert_balance(s)


def test_clear_frees_max_keys_slots():
    """После clear слоты max_keys свободны."""
    box = LatestMailbox(max_keys=1)
    assert box.put("a", 1) is True
    assert box.put("b", 2) is False
    box.clear()
    assert box.put("b", 2) is True
    assert box.stats()["rejected"] == 1


def test_clear_on_empty_box_changes_nothing():
    """clear пустого ящика ничего не считает."""
    box = LatestMailbox()
    box.clear()
    assert box.stats() == {
        "put": 0,
        "taken": 0,
        "superseded": 0,
        "rejected": 0,
        "pending": 0,
        "bytes_held": 0,
        "max_bytes_held": 0,
    }


# --------------------------------------------------------------------------- #
# pending_keys
# --------------------------------------------------------------------------- #


def test_pending_keys_lists_keys_with_waiting_item():
    """pending_keys: пусто; после put a, put b, take a - [b]; порядок - порядок первого put."""
    box = LatestMailbox()
    assert box.pending_keys() == []

    box.put("a", 1)
    box.put("b", 2)
    assert box.pending_keys() == ["a", "b"]
    box.take("a")
    assert box.pending_keys() == ["b"]
    box.take("b")
    assert box.pending_keys() == []

    # порядок нескольких ключей не алфавитный и не по значению: порядок первого put
    box2 = LatestMailbox()
    for key in ["k3", "k1", "k2"]:
        box2.put(key, key)
    assert box2.pending_keys() == ["k3", "k1", "k2"]


def test_pending_keys_replacement_keeps_position():
    """Замена элемента существующего ключа порядок не меняет."""
    box = LatestMailbox()
    for key in ["b", "a", "c"]:
        box.put(key, 1)
    box.put("b", 2)  # замена первого ключа
    assert box.pending_keys() == ["b", "a", "c"]


def test_pending_keys_key_after_take_and_new_put_goes_last():
    """После take и нового put ключ идёт как новый - в конец."""
    box = LatestMailbox()
    for key in ["x", "y", "z"]:
        box.put(key, 1)
    box.take("x")
    box.put("x", 2)
    assert box.pending_keys() == ["y", "z", "x"]


def test_pending_keys_is_a_snapshot():
    """pending_keys отдаёт список-снимок: его правка ящик не меняет."""
    box = LatestMailbox()
    box.put("a", 1)
    snap = box.pending_keys()
    assert isinstance(snap, list)
    snap.append("zzz")
    snap.clear()
    assert box.pending_keys() == ["a"]
    assert box.stats()["pending"] == 1


# --------------------------------------------------------------------------- #
# stats и инвариант (однопоточно; потоковый - в test_latest_mailbox_hazards.py)
# --------------------------------------------------------------------------- #


def test_stats_has_exactly_seven_int_keys():
    """stats() - dict ровно из 7 ключей контракта, значения int."""
    box = LatestMailbox()
    box.put("a", 1, nbytes=3)
    s = box.stats()
    assert isinstance(s, dict)
    assert set(s) == _STATS_KEYS
    assert len(s) == 7
    assert all(isinstance(v, int) for v in s.values())


def test_invariant_holds_across_mixed_sequence():
    """put == taken + superseded + pending на каждом шаге смеси put/take/clear/отказов."""
    box = LatestMailbox(max_keys=2)
    steps = [
        lambda: box.put("a", "a1", nbytes=10),  # True
        lambda: box.put("b", "b1", nbytes=20),  # True
        lambda: box.put("c", "c1", nbytes=40),  # False, отказ
        lambda: box.put("a", "a2", nbytes=30),  # True, замена
        lambda: box.take("b"),
        lambda: box.put("c", "c2", nbytes=5),  # True, слот свободен
        lambda: box.clear(),  # выбросит a и c
        lambda: box.put("a", "a3", nbytes=1),  # True
        lambda: box.take("a"),
        lambda: box.take("a"),  # None
    ]
    for step in steps:
        step()
        _assert_balance(box.stats())

    assert box.stats() == {
        "put": 5,
        "taken": 2,
        "superseded": 3,  # замена a + выброшенные clear a и c
        "rejected": 1,
        "pending": 0,
        "bytes_held": 0,
        "max_bytes_held": 50,  # b 20 + a 30 после замены; не 60 (до вычитания старых 10)
    }


def test_all_methods_return_without_deadlock():
    """Все публичные методы вызываются друг за другом без взаимоблокировки (один замок)."""

    def scenario():
        box = LatestMailbox(max_keys=2)
        box.put("a", 1, nbytes=1)
        box.put("a", 2, nbytes=1)
        box.pending_keys()
        box.stats()
        box.take("a")
        box.put("b", 3, nbytes=1)
        box.clear()
        return box.stats()

    result = _run_within(scenario)
    assert result == {
        "put": 3,
        "taken": 1,
        "superseded": 2,
        "rejected": 0,
        "pending": 0,
        "bytes_held": 0,
        "max_bytes_held": 1,
    }


# --------------------------------------------------------------------------- #
# Без Qt, экспорт
# --------------------------------------------------------------------------- #


def test_module_imports_without_qt_at_runtime():
    """Импорт модуля не тянет Qt-пакеты в sys.modules (запуск в чистом интерпретаторе)."""
    code = (
        "import sys; sys.path.insert(0, '.'); "
        "import multiprocess_framework.modules.process_module.generic.latest_mailbox; "
        "print(any(m.split('.')[0] in ('PySide6', 'shiboken6', 'PyQt5', 'PyQt6') "
        "for m in sys.modules))"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert proc.stdout.strip() == "False"


def test_module_source_has_no_qt_names():
    """Дополнение к рантайм-проверке: в исходнике модуля нет PySide6 / PyQt / QtCore."""
    text = _MODULE_FILE.read_text(encoding="utf-8")
    for banned in ("PySide6", "PyQt", "QtCore"):
        assert banned not in text, banned


def test_exported_from_generic_package():
    """LatestMailbox доступен из пакета generic и это тот же класс."""
    from multiprocess_framework.modules.process_module import generic

    assert generic.LatestMailbox is LatestMailbox
