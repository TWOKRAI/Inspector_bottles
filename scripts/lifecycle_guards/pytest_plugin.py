"""pytest-плагин стражей lifecycle: G3 (незакрытые корни) и G4 (потоки без пути области).

Подключение: ``-p scripts.lifecycle_guards.pytest_plugin`` (ключ ``addopts`` в ``pytest.ini``
и ``pyproject.toml``). Плагин ``-p`` грузится ДО ``pytest_configure`` из ``modules/conftest.py``,
который ставит метод запуска процессов ``spawn``, поэтому на импорте здесь только stdlib:
ни ``multiprocessing``, ни ``PySide6``, ни ``base_manager``. Всё тяжёлое делается лениво.

Ручки (окружение): ``LIFECYCLE_G3``, ``LIFECYCLE_G4`` ∈ ``off|report|fail``, умолчание ``report``.
Неизвестное значение читается как ``report`` плюс строка предупреждения в отчёте.

* G3: в конце сессии ``gc.collect()`` и ``base_manager.unclosed_roots()`` — все записи в отчёт.
* G4: перепись ``threading.enumerate()`` до и после каждого теста; новый живой поток без ``/``
  в имени (имя потока ``spawn`` — путь области ``r/tab/w``) после ожидания до 0,2 с на тест — запись.
  ``MainThread`` и ``Dummy-*`` не считаются.

Режим ``report`` код возврата не меняет; ``fail`` при N > 0 переводит успешный прогон в код 1.
G5 здесь не реализован (открытый вопрос О1).
"""

from __future__ import annotations

import gc
import os
import sys
import threading
import time
from typing import Any

_MODES = ("off", "report", "fail")
_DEFAULT = "report"
_G4_WAIT_S = 0.2  # суммарное ожидание завершения новых потоков на один тест
_BASE_MANAGER = "multiprocess_framework.modules.base_manager"

# Состояние сессии. Плагин на сессию один; xdist не поддерживается (отчёт по процессу).
_state: dict[str, Any] = {}


def _reset_state() -> None:
    _state.clear()
    _state.update(
        {
            "g3": _DEFAULT,
            "g4": _DEFAULT,
            "warnings": [],
            "roots": None,  # None — страж не отработал / недоступен
            "g3_note": "",
            "g4_entries": [],  # (nodeid, имя потока)
            "before": set(),
            "nodeid": "",
        }
    )


_reset_state()


def _read_knob(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return _DEFAULT
    value = raw.strip().lower()
    if value in _MODES:
        return value
    _state["warnings"].append(f"{name}={raw!r}: неизвестное значение, принято {_DEFAULT} (допустимо: off|report|fail)")
    return _DEFAULT


def pytest_configure(config: Any) -> None:
    _reset_state()
    _state["g3"] = _read_knob("LIFECYCLE_G3")
    _state["g4"] = _read_knob("LIFECYCLE_G4")


# ---------------------------------------------------------------------------
# G4
# ---------------------------------------------------------------------------


def _counts_for_g4(thread: threading.Thread) -> bool:
    name = thread.name
    if thread is threading.main_thread() or name == "MainThread" or name.startswith("Dummy-"):
        return False
    return "/" not in name


def pytest_runtest_logstart(nodeid: str, location: Any) -> None:
    if _state["g4"] == "off":
        return
    _state["nodeid"] = nodeid
    _state["before"] = set(threading.enumerate())


def pytest_runtest_logfinish(nodeid: str, location: Any) -> None:
    if _state["g4"] == "off":
        return
    before: set[threading.Thread] = _state["before"]
    fresh = [t for t in threading.enumerate() if t not in before and t.is_alive() and _counts_for_g4(t)]
    if not fresh:
        return
    deadline = time.monotonic() + _G4_WAIT_S
    for thread in fresh:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    for thread in fresh:
        if thread.is_alive():
            _state["g4_entries"].append((nodeid, thread.name))


# ---------------------------------------------------------------------------
# G3 и итог сессии
# ---------------------------------------------------------------------------


def _collect_roots() -> None:
    gc.collect()
    module = sys.modules.get(_BASE_MANAGER)
    if module is None:
        # base_manager в процессе не загружен: корней быть не может, импортировать ради нуля незачем.
        _state["roots"] = []
        return
    try:
        _state["roots"] = list(module.unclosed_roots())
    except (AttributeError, ImportError) as exc:
        _state["g3_note"] = f"страж G3 недоступен: {type(exc).__name__}: {exc}"


def _violations() -> dict[str, int]:
    roots = _state["roots"] or []
    return {
        "g3": len(roots) if _state["g3"] != "off" else 0,
        "g4": len(_state["g4_entries"]) if _state["g4"] != "off" else 0,
    }


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    if _state["g3"] != "off":
        _collect_roots()
    counts = _violations()
    failing = (_state["g3"] == "fail" and counts["g3"] > 0) or (_state["g4"] == "fail" and counts["g4"] > 0)
    if failing and session.exitstatus == 0:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter: Any, exitstatus: Any, config: Any) -> None:
    if _state["g3"] == "off" and _state["g4"] == "off":
        return
    write = terminalreporter.write_line
    terminalreporter.section("lifecycle-guards report")
    for warning in _state["warnings"]:
        write(f"предупреждение: {warning}")
    if _state["g3"] != "off":
        if _state["g3_note"]:
            write(_state["g3_note"])
        else:
            roots = _state["roots"] or []
            write(f"G3 unclosed roots: {len(roots)}")
            for rec in roots:
                write(f"  {rec['path']} ({rec['state']})")
    if _state["g4"] != "off":
        entries = _state["g4_entries"]
        write(f"G4 threads without scope path: {len(entries)}")
        for nodeid, name in entries:
            write(f"  {nodeid} :: {name}")
