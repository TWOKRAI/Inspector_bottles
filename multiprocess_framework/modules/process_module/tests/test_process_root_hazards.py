"""Hazard-тесты автора: корень процесса (lifecycle-owner-scope, Task 1.2a, ADR-PM-054).

Гонки ``cancel``/``close``, reporter после логгера, провал ``initialize``, застрявший
воркер в ``survivors``, статика (хук удалён, у наследников нет своего ``shutdown``).
Вызовы, которые могут зависнуть, — в daemon-потоке с дедлайном join; числа — литералы.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import multiprocess_framework.modules.process_module.lifecycle.process_lifecycle as lifecycle

from ...app_module.orchestrator import GenericProcessManagerApp
from ...process_manager_module.process.process_manager_process import ProcessManagerProcess
from ..core.process_module import ProcessModule
from ..generic.generic_process import GenericProcess

_REPO = Path(__file__).resolve().parents[4]


class _Logger:
    """Логгер, который после своего гашения записи не принимает, а считает потерянными."""

    def __init__(self) -> None:
        self.alive = True
        self.written: list[str] = []
        self.lost: list[str] = []

    def _accept(self, message: Any, **_kw: Any) -> None:
        (self.written if self.alive else self.lost).append(str(message))

    debug = info = warning = error = critical = _accept

    def clear_base_context(self) -> None: ...

    def shutdown(self) -> bool:
        self.alive = False
        return True


class _Counting:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    def shutdown(self) -> bool:
        self.calls += 1
        if self._fail:
            raise RuntimeError("отказ гашения (инъекция теста)")
        return True


def _process_with_root(name: str = "hz_root", *, stats_fail: bool = False):
    process = ProcessModule(name)
    logger = _Logger()
    managers = {
        "error": _Counting(),
        "stats": _Counting(fail=stats_fail),
        "observation": _Counting(),
        "router": _Counting(),
        "command": _Counting(),
        "console": _Counting(),
    }
    process.logger_manager = logger
    process.error_manager = managers["error"]
    process.stats_manager = managers["stats"]
    process.observation_manager = managers["observation"]
    process.router_manager = managers["router"]
    process.command_manager = managers["command"]
    process.console_manager = managers["console"]
    process.register_manager("logger", logger)
    process.worker_manager = None
    process.shared_resources = None
    process.update_process_state = Mock()
    process._open_root()
    segments = process.lifetime_segments
    process._register_planes(segments["planes"])
    process._register_transport(segments["transport"])
    return process, logger, managers


def _bounded(fn, timeout_s: float = 10.0):
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="root_hazard_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


# --------------------------------------------------------------------------- #
# Гонки cancel / close
# --------------------------------------------------------------------------- #


def test_concurrent_stop_and_shutdown_close_each_manager_once() -> None:
    process, _logger, managers = _process_with_root()
    start = threading.Barrier(8)
    results: list[Any] = []

    def worker(fn) -> None:
        start.wait(5.0)
        results.append(fn())

    threads = [threading.Thread(target=worker, args=(fn,), daemon=True) for fn in [process.stop, process.shutdown] * 4]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10.0)
    assert not any(th.is_alive() for th in threads), "stop()/shutdown() зависли в гонке"
    assert results.count(True) == 4, results
    assert {name: m.calls for name, m in managers.items()} == {
        "error": 1,
        "stats": 1,
        "observation": 1,
        "router": 1,
        "command": 1,
        "console": 1,
    }


def test_stop_only_cancels_and_closes_nothing() -> None:
    process, logger, managers = _process_with_root()
    done, _, error = _bounded(process.stop)
    assert done and error is None, error
    assert sum(m.calls for m in managers.values()) == 0
    assert logger.alive is True
    done, result, error = _bounded(process.shutdown)
    assert done and error is None and result is True, (result, error)


# --------------------------------------------------------------------------- #
# Reporter после логгера
# --------------------------------------------------------------------------- #


def test_root_report_after_logger_goes_to_emergency_not_dead_logger(monkeypatch) -> None:
    process, logger, managers = _process_with_root(stats_fail=True)
    heard: list[str] = []
    monkeypatch.setattr(lifecycle, "emergency_log", lambda *a, **k: heard.append(" ".join(str(x) for x in a)))

    done, result, error = _bounded(process.shutdown)
    assert done and error is None, error
    assert result is False, "ошибка записи stats обязана дать False"
    assert managers["stats"].calls == 1
    assert logger.lost == [], f"строки уехали в мёртвый логгер: {logger.lost}"
    assert any("root close proc/hz_root" in line and "stats" in line for line in heard), heard


# --------------------------------------------------------------------------- #
# Провал initialize
# --------------------------------------------------------------------------- #


def test_failed_initialize_closes_root_and_planes() -> None:
    process = ProcessModule("hz_fail")
    logger = _Logger()
    stats = _Counting()

    def init_managers() -> None:
        process.logger_manager = logger
        process.stats_manager = stats
        process._register_planes(process.lifetime_segments["planes"])

    process._init_configuration = Mock()
    process._init_queues = Mock()
    process._init_managers = init_managers
    process._init_communication = Mock(side_effect=RuntimeError("подъём упал (инъекция теста)"))
    process.update_process_state = Mock()

    done, result, error = _bounded(process.initialize)
    assert done and error is None, error
    assert result is False
    assert process._root.closed is True
    assert stats.calls == 1
    assert logger.alive is False


# --------------------------------------------------------------------------- #
# Застрявший воркер
# --------------------------------------------------------------------------- #


class _StuckWorkers:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def stop_all_workers(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def list_workers(self) -> list[str]:
        return ["camera_loop"]

    def get_worker_status(self, name: str) -> dict:
        return {"is_alive": True}


def test_stuck_worker_is_named_in_survivors() -> None:
    process = ProcessModule("hz_stuck")
    process.attach_stop_budget({"work_s": 0.6, "infra_s": 0.2})
    process._open_root()
    process.worker_manager = _StuckWorkers()
    process.lifetime_segments["work"].own(lifecycle._WorkersStop(process), name="workers", kind="workers")

    done, report, error = _bounded(process.close_root)
    assert done and error is None, error
    assert "proc/hz_stuck/work/workers" in report.survivors
    assert len(process.worker_manager.timeouts) == 1
    assert 0.0 < process.worker_manager.timeouts[0] <= 0.7  # срок work 0,6 + дискрет monotonic Windows


# --------------------------------------------------------------------------- #
# Одноразовость процесса (ревью кода р.1, находка 2)
# --------------------------------------------------------------------------- #


def _live_extra_threads(before: set[str]) -> list[str]:
    time.sleep(0.5)
    return sorted(t.name for t in threading.enumerate() if t.name not in before and t.is_alive())


def test_second_initialize_on_live_process_rebuilds_nothing() -> None:
    """Повторный ``initialize()`` живого процесса: ``True``, тот же корень и те же менеджеры, ничего не гасится."""
    before = {t.name for t in threading.enumerate()}
    process = ProcessModule("hz_twice", config={})
    try:
        assert _bounded(process.initialize)[1] is True
        root, router, worker_manager = process._root, process.router_manager, process.worker_manager
        calls: list[str] = []
        real_shutdown = router.shutdown
        router.shutdown = lambda *a, **k: (calls.append("router"), real_shutdown(*a, **k))[1]

        done, result, error = _bounded(process.initialize)

        assert done and error is None, repr(error)
        assert result is True
        assert process._root is root and not root.closed
        assert process.router_manager is router and process.worker_manager is worker_manager
        assert calls == []
    finally:
        _bounded(process.shutdown)
    assert _live_extra_threads(before) == []


def test_initialize_after_shutdown_is_refused_without_new_root() -> None:
    """``initialize()`` после ``shutdown()``: ``False``, одна строка в лог, корня и менеджеров заново нет."""
    before = {t.name for t in threading.enumerate()}
    process = ProcessModule("hz_reinit", config={})
    errors: list[str] = []
    assert _bounded(process.initialize)[1] is True
    assert _bounded(process.shutdown)[1] is True
    root, router = process._root, process.router_manager
    process._log_error = lambda msg, *a, **k: errors.append(str(msg))

    done, result, error = _bounded(process.initialize)

    assert done and error is None, repr(error)
    assert result is False
    assert process._root is root and process.router_manager is router
    assert len([line for line in errors if "одноразовый после shutdown" in line]) == 1, errors
    assert _live_extra_threads(before) == []


# --------------------------------------------------------------------------- #
# Статика
# --------------------------------------------------------------------------- #


def test_static_no_teardown_hook() -> None:
    """Ноль ``_before_observability_teardown`` в коде фреймворка и прототипа (без tests, *.py)."""
    hits: list[str] = []
    scanned = 0
    for top in ("multiprocess_framework", "multiprocess_prototype"):
        for path in (_REPO / top).rglob("*.py"):
            # Фильтр по пути ОТНОСИТЕЛЬНО корня репозитория: само дерево может лежать под
            # ``.claude/worktrees/``, и абсолютный путь отсёк бы все файлы (пустая проверка).
            if "tests" in path.relative_to(_REPO).parts:
                continue
            scanned += 1
            if "_before_observability_teardown" in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path.relative_to(_REPO)))
    assert scanned > 800, f"просмотрено {scanned} файлов: проверка пуста"
    assert hits == []


_PROTOTYPE_HEIRS = (
    ("multiprocess_prototype/frontend/headless_process.py", "HeadlessGuiProcess"),
    ("multiprocess_prototype/frontend/process.py", "GuiProcess"),
    ("multiprocess_prototype/frontend/bridge_process.py", "BridgeGuiProcess"),
    ("multiprocess_prototype/generic_process_app.py", "GenericProcessApp"),
    ("multiprocess_prototype/orchestrator.py", "ProcessManagerProcessApp"),
)


def test_static_no_subclass_shutdown() -> None:
    """Восемь наследников ``ProcessModule`` без своего ``shutdown``: три фреймворковых —
    импортом, пять прототипных — разбором AST (без импорта прототипа из фреймворка).
    Нет файла прототипа — ``skip`` с путём, после проверки остальных."""
    for cls in (GenericProcessManagerApp, ProcessManagerProcess, GenericProcess):
        assert "shutdown" not in cls.__dict__, cls.__name__
    missing: list[str] = []
    for rel, class_name in _PROTOTYPE_HEIRS:
        path = _REPO / rel
        if not path.exists():
            missing.append(rel)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
        assert len(classes) == 1, f"{class_name} не найден в {rel}"
        methods = [n.name for n in classes[0].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert "shutdown" not in methods, f"{class_name} ({rel}) переопределяет shutdown()"
    if missing:
        pytest.skip(f"нет файлов прототипа: {missing}")
