# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.1 плана ``framework-heartbeat-import-race`` (C-92) — ДО реализации.

Симптом: на старте дочернего процесса два потока лениво импортируют подмодули пакета
``multiprocess_framework.modules.process_module.heartbeat`` (``process_heartbeat``,
``cpu_clock``) в одно окно — CPython 3.12 бросает ``_DeadlockError`` (цикл замков импорта:
поток A держит замок ``process_heartbeat`` и ждёт замок пакета ``heartbeat``, поток B
исполняет ``heartbeat/__init__`` и ждёт замок ``process_heartbeat``).

Свойства R1-R5 (критерии приёмки плана):

* R1 — ``import ...core.process_module`` загружает ``heartbeat.process_heartbeat`` и
  ``heartbeat.cpu_clock`` (импорт до старта потоков).
* R2 — гонка по сценарию ``plans/framework-heartbeat-import-race/repro_import_deadlock.py det``
  (поток ``msgproc`` — настоящий ``BuiltinCommands._cmd_introspect_status``, основной —
  ``from ...heartbeat.process_heartbeat import ProcessHeartbeat``): оба исхода ``ok``.
* R3 — гонка только на пакете (поток B ``import ...heartbeat.cpu_clock``): оба исхода ``ok``.
* R4 — без таймингов: ``import ...heartbeat`` НЕ тянет ``process_heartbeat``; обращение
  ``heartbeat.ProcessHeartbeat`` — тянет.
* R5 — охрана публичного пути ``from ...heartbeat import ProcessHeartbeat`` и т.п.

**Почему subprocess.** Spawn-ребёнок не наследует ``sys.modules`` родителя, а pytest-раннер
уже загрузил пакет. Только свежий интерпретатор показывает то, что видит ребёнок.

**Допущение о «чистом» состоянии (проверено запуском, а не предположено).** Сам
``import multiprocess_framework`` (и любой импорт подпакета ``process_module``) выполняет
``process_module/__init__`` -> ``core.process_module``; поэтому состояние «``core.process_module``
НЕ импортирован» (формулировка R3 в плане) в живом интерпретаторе недостижимо. Предусловие
«``heartbeat``, ``heartbeat.process_heartbeat``, ``heartbeat.cpu_clock`` не в ``sys.modules``»
для R3/R4/R5 создаётся ВЫСЕЛЕНИЕМ этих трёх модулей из ``sys.modules`` после
``import multiprocess_framework`` (и ``delattr`` на родителе) — тогда ленивый путь гоняется
независимо от того, прогрузила ли их шапка (П1). R2 выселения НЕ делает (ловушка плана: R2 —
канарейка симптома «как у ребёнка», она зелёная и при П1, и при П3 по отдельности); если
шапка уже прогрузила ``heartbeat`` (П1), гонка сконструирована быть не может — тогда тест
требует, чтобы это было именно так (оба подмодуля в ``sys.modules`` после шапки).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# tests/ -> process_module -> modules -> multiprocess_framework -> корень worktree
_REPO_ROOT = Path(__file__).resolve().parents[4]
_TIMEOUT_S = 60.0

# Пролог: все скрипты видят дерево _REPO_ROOT (PYTHONPATH), и это проверяется первым делом.
_PROLOGUE = """
import importlib
import json
import os
import sys
import threading
import time
import traceback
import types

ROOT = __ROOT__
PKG = "multiprocess_framework.modules.process_module"
H = PKG + ".heartbeat"
PH = H + ".process_heartbeat"
CC = H + ".cpu_clock"
"""

_ASSERT_TREE = """
import multiprocess_framework
assert os.path.realpath(multiprocess_framework.__file__).startswith(os.path.realpath(ROOT) + os.sep), (
    multiprocess_framework.__file__, ROOT)
"""

# Выселить heartbeat из sys.modules -> предусловие «не загружено» не зависит от шапки (П1).
_EVICT = """
def evict():
    for k in (H, PH, CC):
        sys.modules.pop(k, None)
    parent = sys.modules[PKG]
    if hasattr(parent, "heartbeat"):
        delattr(parent, "heartbeat")

evict()
res = {"precondition_unloaded": [k in sys.modules for k in (H, PH, CC)] == [False, False, False]}
"""

# Гонка, построенная как repro_import_deadlock.py det: два загрузчика-обёртки закрепляют
# чередование со стенда. Замки не меняются: обёртки только ждут в exec_module — точке,
# где интерпретатор и так вправе переключить поток.
_RACE = """
import importlib.abc
import importlib.machinery
import importlib._bootstrap as _bs

ev_b_in_init = threading.Event()
ev_a_holds_ph = threading.Event()
tids = {}
flags = {"b_in_init": False, "a_holds_ph": False, "b_saw_a_holds_ph": None, "b_blocked_seen": None}


def blocked(tid):
    return bool(_bs._blocking_on.get(tid))


class Wrap(importlib.abc.Loader):
    def __init__(self, real, before):
        self.real, self.before = real, before

    def create_module(self, spec):
        return self.real.create_module(spec)

    def exec_module(self, module):
        self.before()
        return self.real.exec_module(module)


def before_pkg_init():  # в потоке msgproc: heartbeat уже в sys.modules, __init__ ещё не выполнен
    flags["b_in_init"] = True
    ev_b_in_init.set()
    flags["b_saw_a_holds_ph"] = ev_a_holds_ph.wait(5)


def before_ph_body():  # в основном потоке: он держит замок process_heartbeat, тело не выполнено
    flags["a_holds_ph"] = True
    ev_a_holds_ph.set()
    t0 = time.time()
    # ждём, пока B упрётся в замок; B завершился без блокировки — цикла нет, ждать нечего
    while not blocked(tids.get("B")) and tb.is_alive() and time.time() - t0 < 5:
        time.sleep(0.001)
    flags["b_blocked_seen"] = blocked(tids.get("B"))


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname not in (H, PH):
            return None
        me = threading.current_thread().name
        if fullname == H and me != "msgproc":
            return None
        if fullname == PH and me != "MainThread":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        spec.loader = Wrap(spec.loader, before_pkg_init if fullname == H else before_ph_body)
        return spec


def run_race(b_body):
    armed = H not in sys.modules
    out = {"armed": armed}
    if armed:
        sys.meta_path.insert(0, Finder())

    def thread_b():
        tids["B"] = threading.get_ident()
        try:
            out["B_result"] = b_body()
            out["B_err"] = None
        except BaseException as e:  # noqa: BLE001
            out["B_err"] = type(e).__name__ + ": " + str(e)
            out["B_tb"] = traceback.format_exc().splitlines()[-6:]

    global tb
    tb = threading.Thread(target=thread_b, name="msgproc", daemon=True)
    tb.start()
    out["a_saw_b_in_init"] = ev_b_in_init.wait(5) if armed else None
    try:
        from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (  # noqa: F401
            ProcessHeartbeat,
        )

        out["A_err"] = None
    except BaseException as e:  # noqa: BLE001
        out["A_err"] = type(e).__name__ + ": " + str(e)
    tb.join(10)
    out["B_alive_after_join"] = tb.is_alive()
    out["flags"] = flags
    return out
"""

_R1_SCRIPT = (
    _PROLOGUE
    + """
import importlib.util

spec = importlib.util.find_spec("multiprocess_framework")  # find_spec верхнего пакета его не импортирует
assert spec is not None and os.path.realpath(spec.origin).startswith(os.path.realpath(ROOT) + os.sep), spec
res = {
    "precondition_unloaded": [k in sys.modules for k in (H, PH, CC, PKG + ".core.process_module")] == [False] * 4,
}
import multiprocess_framework.modules.process_module.core.process_module  # noqa: E402,F401
import multiprocess_framework
assert os.path.realpath(multiprocess_framework.__file__).startswith(os.path.realpath(ROOT) + os.sep)
res["process_heartbeat_loaded"] = PH in sys.modules
res["cpu_clock_loaded"] = CC in sys.modules
print(json.dumps(res))
"""
)

# Шапка ребёнка: core.process_module и builtin_commands грузятся ДО потоков (ловушка плана:
# импорт внутри потока сделал бы R2 красным и при П1+П3).
_R2_SCRIPT = (
    _PROLOGUE
    + _ASSERT_TREE
    + _RACE
    + """
import multiprocess_framework.modules.process_module.core.process_module  # noqa: E402,F401
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands  # noqa: E402
try:
    import cv2  # noqa: F401  раннер ребёнка импортирует cv2 до сборки класса процесса
except ImportError:
    pass

res = {
    "header_loaded_heartbeat": [k in sys.modules for k in (H, PH, CC)],
}
fake_self = types.SimpleNamespace(
    _services=types.SimpleNamespace(name="camera_0", worker_manager=None, _current_process_status="ready")
)


def b_body():
    out = BuiltinCommands._cmd_introspect_status(fake_self)
    return {"success": out.get("success"), "process": out.get("process")}


res.update(run_race(b_body))
print(json.dumps(res))
"""
)

_R3_SCRIPT = (
    _PROLOGUE
    + _ASSERT_TREE
    + _RACE
    + _EVICT
    + """
def b_body():
    import multiprocess_framework.modules.process_module.heartbeat.cpu_clock  # noqa: F401

    return CC in sys.modules


res.update(run_race(b_body))
print(json.dumps(res))
"""
)

# probe: сбой одного обращения -> строка "raised:<Тип>" в этом ключе (красный ИМЕННО этот тест),
# а не падение всего сценария (иначе мутант публичного пути краснел бы «ошибкой фикстуры»).
_PROBE = """
def probe(key, fn):
    try:
        res[key] = fn()
    except BaseException as e:  # noqa: BLE001
        res[key] = "raised:" + type(e).__name__
"""

_R4_SCRIPT = (
    _PROLOGUE
    + _ASSERT_TREE
    + _EVICT
    + _PROBE
    + """
import multiprocess_framework.modules.process_module.heartbeat as heartbeat  # noqa: E402

res["ph_loaded_after_package_import"] = PH in sys.modules
res["package_in_sys_modules"] = H in sys.modules
probe("class_name", lambda: heartbeat.ProcessHeartbeat.__name__)
res["ph_loaded_after_attribute_access"] = PH in sys.modules
print(json.dumps(res))
"""
)

_MISSING = "\\u043d\\u0435\\u0442_\\u0442\\u0430\\u043a\\u043e\\u0433\\u043e"  # «нет_такого», ASCII-экранирование

_R5_SCRIPT = (
    _PROLOGUE
    + _ASSERT_TREE
    + _EVICT
    + _PROBE
    + """
MISSING = "__MISSING__"
heartbeat = importlib.import_module(H)


def from_import_class():
    from multiprocess_framework.modules.process_module.heartbeat import ProcessHeartbeat

    return [ProcessHeartbeat.__name__, ProcessHeartbeat.__module__]


def same_class_via_submodule():
    return heartbeat.ProcessHeartbeat is heartbeat.process_heartbeat.ProcessHeartbeat


def same_class_as_from_import():
    from multiprocess_framework.modules.process_module.heartbeat import ProcessHeartbeat

    return ProcessHeartbeat is heartbeat.ProcessHeartbeat


def from_import_telemetry():
    from multiprocess_framework.modules.process_module.heartbeat import telemetry

    return telemetry.__name__


def from_import_cpu_clock():
    from multiprocess_framework.modules.process_module.heartbeat import cpu_clock

    return [cpu_clock.__name__, callable(getattr(cpu_clock, "process_clock", None))]


def missing_attr():
    return "returned:" + repr(getattr(heartbeat, MISSING))


probe("from_import_class", from_import_class)
probe("same_class_via_submodule", same_class_via_submodule)
probe("same_class_as_from_import", same_class_as_from_import)
probe("from_import_telemetry", from_import_telemetry)
probe("from_import_cpu_clock", from_import_cpu_clock)
probe("missing_attr", missing_attr)
probe("hasattr_missing", lambda: hasattr(heartbeat, MISSING))
print(json.dumps(res))
""".replace("__MISSING__", _MISSING)
)


def _run(script_body: str) -> dict:
    """Выполнить сценарий в свежем интерпретаторе (БЕЗ ``-I``: он глушит PYTHONPATH и cwd) и
    разобрать JSON последней строки stdout. Сбой подпроцесса — словарь ``{"crash": ...}``."""
    script = script_body.replace("__ROOT__", repr(str(_REPO_ROOT)))
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT), "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if proc.returncode != 0 or not lines:
        return {"crash": f"rc={proc.returncode}\nSTDOUT:\n{proc.stdout[-1500:]}\nSTDERR:\n{proc.stderr[-3000:]}"}
    return json.loads(lines[-1])


def _need(result: dict) -> dict:
    """Сбой самого сценария — красный тест с текстом, а не скрытый «зелёный» и не error фикстуры."""
    if "crash" in result:
        pytest.fail("сценарий в подпроцессе упал:\n" + result["crash"])
    return result


# --------------------------------------------------------------------------- R1


@pytest.fixture(scope="module")
def r1() -> dict:
    return _run(_R1_SCRIPT)


def test_r1_precondition_clean_interpreter(r1):
    assert _need(r1)["precondition_unloaded"] is True


def test_r1_process_module_import_loads_process_heartbeat(r1):
    assert _need(r1)["process_heartbeat_loaded"] is True


def test_r1_process_module_import_loads_cpu_clock(r1):
    assert _need(r1)["cpu_clock_loaded"] is True


# --------------------------------------------------------------------------- R2


@pytest.fixture(scope="module")
def r2() -> dict:
    return _run(_R2_SCRIPT)


def test_r2_outcome_a_main_thread_import_ok(r2):
    assert _need(r2)["A_err"] is None, r2.get("A_err")


def test_r2_outcome_b_real_introspect_status_ok(r2):
    assert _need(r2)["B_err"] is None, (r2.get("B_err"), r2.get("B_tb"))
    assert r2["B_result"] == {"success": True, "process": "camera_0"}


def test_r2_b_thread_finished(r2):
    assert _need(r2)["B_alive_after_join"] is False


def test_r2_race_armed_or_heartbeat_preloaded_by_header(r2):
    """Перехватчик сработал — ИЛИ гонки быть не могло, потому что шапка (П1) уже
    прогрузила оба подмодуля. Третьего не дано: иначе тест зелёный впустую."""
    r = _need(r2)
    if r["armed"]:
        assert r["a_saw_b_in_init"] is True
        assert r["flags"]["b_in_init"] is True
        assert r["flags"]["a_holds_ph"] is True
        assert r["flags"]["b_saw_a_holds_ph"] is True
    else:
        assert r["header_loaded_heartbeat"] == [True, True, True]


# --------------------------------------------------------------------------- R3


@pytest.fixture(scope="module")
def r3() -> dict:
    return _run(_R3_SCRIPT)


def test_r3_precondition_package_unloaded(r3):
    assert _need(r3)["precondition_unloaded"] is True
    assert r3["armed"] is True


def test_r3_interceptors_fired(r3):
    r = _need(r3)
    assert r["a_saw_b_in_init"] is True
    assert r["flags"]["b_in_init"] is True
    assert r["flags"]["a_holds_ph"] is True
    assert r["flags"]["b_saw_a_holds_ph"] is True


def test_r3_outcome_a_process_heartbeat_import_ok(r3):
    assert _need(r3)["A_err"] is None, r3.get("A_err")


def test_r3_outcome_b_cpu_clock_import_ok(r3):
    assert _need(r3)["B_err"] is None, (r3.get("B_err"), r3.get("B_tb"))
    assert r3["B_result"] is True


def test_r3_b_thread_finished(r3):
    assert _need(r3)["B_alive_after_join"] is False


# --------------------------------------------------------------------------- R4


@pytest.fixture(scope="module")
def r4() -> dict:
    return _run(_R4_SCRIPT)


def test_r4_precondition_unloaded_before_action(r4):
    assert _need(r4)["precondition_unloaded"] is True


def test_r4_package_import_does_not_load_process_heartbeat(r4):
    assert _need(r4)["package_in_sys_modules"] is True
    assert r4["ph_loaded_after_package_import"] is False


def test_r4_attribute_access_loads_process_heartbeat(r4):
    assert _need(r4)["class_name"] == "ProcessHeartbeat"
    assert r4["ph_loaded_after_attribute_access"] is True


# --------------------------------------------------------------------------- R5


@pytest.fixture(scope="module")
def r5() -> dict:
    return _run(_R5_SCRIPT)


def test_r5_precondition_unloaded_before_action(r5):
    assert _need(r5)["precondition_unloaded"] is True


def test_r5_from_import_gives_the_class(r5):
    assert _need(r5)["from_import_class"] == [
        "ProcessHeartbeat",
        "multiprocess_framework.modules.process_module.heartbeat.process_heartbeat",
    ]


def test_r5_package_attribute_is_submodule_class(r5):
    assert _need(r5)["same_class_via_submodule"] is True


def test_r5_from_import_is_the_package_attribute(r5):
    assert _need(r5)["same_class_as_from_import"] is True


def test_r5_submodule_telemetry_via_fromlist(r5):
    assert _need(r5)["from_import_telemetry"] == "multiprocess_framework.modules.process_module.heartbeat.telemetry"


def test_r5_submodule_cpu_clock_via_fromlist(r5):
    assert _need(r5)["from_import_cpu_clock"] == [
        "multiprocess_framework.modules.process_module.heartbeat.cpu_clock",
        True,
    ]


def test_r5_unknown_attribute_raises_attribute_error(r5):
    assert _need(r5)["missing_attr"] == "raised:AttributeError"


def test_r5_hasattr_unknown_is_false(r5):
    assert _need(r5)["hasattr_missing"] is False
