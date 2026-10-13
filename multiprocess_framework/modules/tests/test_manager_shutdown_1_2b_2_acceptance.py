"""Слепая приёмка Task 1.2b-2 (lifecycle-owner-scope): кодмод ``shutdown`` 23 классов, Р4, формула второго вызова.

Источник — только разделы брифа «Гарантии для инъекций 1.2b-2», «Приёмка», «Инвентарь 1.2b-2»
и «Слепой тестер». Тесты написаны ДО кода. Ожидаемые значения — литералы гарантий.
Имя теста несёт номер гарантии (``test_g24_...``); статика — ``test_static_...``.
Всё, что может зависнуть, идёт в daemon-потоке со сроком; корни ``t02…`` закрываются.
Services и прототип не импортируются (статика читает их только как текст через ``ast``).
"""

from __future__ import annotations

import ast
import functools
import importlib
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import open_scope, unclosed_roots
from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.base_manager.interfaces import CloseReport
from multiprocess_framework.modules.chain_module import WorkerPoolExecutor
from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.logger_core import OBSERVABILITY_EPOCH
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_manager_module.core.stop_budget import stop_budget
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)
from multiprocess_framework.modules.process_manager_module.runner import process_runner
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.process_module.interfaces import IProcessModule
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

DEADLINE_S = 15.0
ENTER_S = 5.0  # сколько ждём, пока первый вызов дойдёт до _on_shutdown (до кода он не дойдёт — тест краснеет быстро)
WAIT_LINE = "первый вызов не завершился за"

# ---------------------------------------------------------------------------
# Литералы гарантий
# ---------------------------------------------------------------------------

# 23 класса со своим shutdown до кодмода (Инвентарь 1.2b-2).
FRAMEWORK_23 = [
    "multiprocess_framework.modules.chain_module.metrics.latency.LatencyTracker",
    "multiprocess_framework.modules.chain_module.thread_pool.worker_pool_executor.WorkerPoolExecutor",
    "multiprocess_framework.modules.chain_module.worker_pool.dispatcher.WorkerPoolDispatcher",
    "multiprocess_framework.modules.worker_module.core.worker_manager.WorkerManager",
    "multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager.ChannelRoutingManager",
    "multiprocess_framework.modules.logger_module.core.logger_core.LoggerCore",
    "multiprocess_framework.modules.logger_module.core.logger_manager.LoggerManager",
    "multiprocess_framework.modules.router_module.core.router_manager.RouterManager",
    "multiprocess_framework.modules.command_module.core.command_manager.CommandManager",
    "multiprocess_framework.modules.config_module.core.config_manager.ConfigManager",
    "multiprocess_framework.modules.console_module.core.console_manager.ConsoleManager",
    "multiprocess_framework.modules.dispatch_module.core.dispatcher.Dispatcher",
    "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendManager",
    "multiprocess_framework.modules.process_manager_module.process.topology_manager.TopologyManager",
    "multiprocess_framework.modules.process_module.core.process_module.ProcessModule",
    "multiprocess_framework.modules.process_module.plugins.manager.PluginManager",
    "multiprocess_framework.modules.registers_module.core.manager.RegistersManager",
    "multiprocess_framework.modules.shared_resources_module.core.shared_resources_manager.SharedResourcesManager",
    "multiprocess_framework.modules.shared_resources_module.events.core.manager.EventManager",
    "multiprocess_framework.modules.shared_resources_module.memory.core.manager.MemoryManager",
    "multiprocess_framework.modules.shared_resources_module.queues.core.manager.QueueRegistry",
    "multiprocess_framework.modules.state_store_module.manager.state_store_manager.StateStoreManager",
    "multiprocess_framework.modules.state_store_module.proxy.state_proxy.StateProxy",
]

# 9 классов без своего shutdown; вместе с 23 дают FRAMEWORK_MANAGER_CLASSES (32).
FRAMEWORK_9 = [
    "multiprocess_framework.modules.chain_module.thread_pool.pool.ChainThreadPool",
    "multiprocess_framework.modules.error_module.core.error_manager.ErrorManager",
    "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess",
    "multiprocess_framework.modules.app_module.orchestrator.GenericProcessManagerApp",
    "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy",
    "multiprocess_framework.modules.statistics_module.observation.observation_manager.ObservationManager",
    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessManagerProcess",
    "multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy.RemoteStateProxy",
    "multiprocess_framework.modules.statistics_module.core.stats_manager.StatsManager",
]

FRAMEWORK_32 = FRAMEWORK_23 + FRAMEWORK_9

# G-17: классы с литералом 7.0; все прочие из 32 и сам BaseManager — 5.0.
WAIT_7_NAMES = {"LoggerCore", "LoggerManager", "ErrorManager", "RouterManager"}


def _short(dotted: str) -> str:
    return dotted.rpartition(".")[2]


def _load(dotted: str):
    module_name, _, class_name = dotted.rpartition(".")
    assert module_name.startswith("multiprocess_framework."), dotted
    return getattr(importlib.import_module(module_name), class_name)


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


@pytest.fixture
def make_root():
    """Настоящие корни ``t02…``; все закрываются в teardown (G3)."""
    roots: list = []

    def factory(budget_s: float = 2.0, kill_reserve_s: float = 0.0):
        root = open_scope(f"t02{uuid.uuid4().hex[:10]}", budget_s=budget_s, kill_reserve_s=kill_reserve_s)
        roots.append(root)
        return root

    yield factory
    for root in roots:
        try:
            root.close()
        except Exception:  # noqa: BLE001 - уборка, не предмет теста
            pass


class HoldManager(BaseManager):
    """Первый вызов ``shutdown()`` держится в ``_on_shutdown`` на ``gate``; ``_ON_SHUTDOWN_WAIT_S = 0.4`` (G-15)."""

    _ON_SHUTDOWN_WAIT_S = 0.4

    def __init__(self, name: str, entered: threading.Event, gate: threading.Event) -> None:
        super().__init__(name)
        self._entered = entered
        self._gate = gate
        self.body_calls = 0

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        self.body_calls += 1
        self._entered.set()
        self._gate.wait(DEADLINE_S)
        return True


class SleepManager(BaseManager):
    """Атрибут по умолчанию; ``_on_shutdown`` спит 0.2 с и возвращает ``True`` (G-16)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.body_calls = 0

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        self.body_calls += 1
        time.sleep(0.2)
        return True


def _second_call_while_first_held(mgr, gate: threading.Event, entered: threading.Event):
    """Первый вызов висит в ``_on_shutdown``; вернуть (поток первого, ящик первого, итог второго)."""
    box: dict = {}

    def first() -> None:
        box["first"] = mgr.shutdown()

    a = threading.Thread(target=first, daemon=True, name="first_call")
    a.start()
    assert entered.wait(ENTER_S), "первый вызов не дошёл до _on_shutdown (тело останова не вызвано)"
    second = call_bounded(mgr.shutdown, DEADLINE_S)
    return a, box, second


def _wait_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if WAIT_LINE in r.getMessage()]


# ---------------------------------------------------------------------------
# Статика: G-9 (AST по git ls-files) и G-9a (23 + 32 классов)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SIX_ROOTS = ["multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "apps", "backend_ctl"]


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


@functools.cache
def _classes_with_own_shutdown() -> dict[str, list[str]]:
    """{корень: ['путь:Класс', ...]} — производственные потомки ``BaseManager`` с ``def shutdown`` в теле."""
    out = subprocess.run(
        ["git", "ls-files", *SIX_ROOTS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    files = [line for line in out.splitlines() if line.endswith(".py")]
    classes: list[tuple[str, str, list[str], bool]] = []  # (путь, имя, базы, есть ли свой shutdown)
    for rel in files:
        try:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [b for b in (_base_name(x) for x in node.bases) if b]
                own = any(
                    isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "shutdown" for s in node.body
                )
                classes.append((rel, node.name, bases, own))
    # транзитивное наследование от BaseManager по простым именам (по всем файлам, тесты тоже участвуют в цепочке)
    descendants = {"BaseManager"}
    changed = True
    while changed:
        changed = False
        for _rel, name, bases, _own in classes:
            if name not in descendants and any(b in descendants for b in bases):
                descendants.add(name)
                changed = True
    result: dict[str, list[str]] = {root: [] for root in SIX_ROOTS}
    for rel, name, _bases, own in classes:
        if name == "BaseManager" or name not in descendants or not own or _is_test_path(rel):
            continue
        result[rel.split("/")[0]].append(f"{rel}:{name}")
    return result


@pytest.mark.parametrize(("scope_name", "expected"), [("framework", 0), ("repo", 0)])
def test_static_own_shutdown_count(scope_name: str, expected: int) -> None:
    """G-9: производственных потомков BaseManager со своим ``shutdown`` — 0 по шести корням (1.2b-3)."""
    found = _classes_with_own_shutdown()
    if scope_name == "framework":
        offenders = found["multiprocess_framework"]
    else:
        offenders = [item for root in SIX_ROOTS for item in found[root]]
    assert len(offenders) == expected, f"{scope_name}: {len(offenders)} вместо {expected}: {sorted(offenders)}"


@pytest.mark.parametrize("dotted", FRAMEWORK_23, ids=_short)
def test_static_g9a_own_hook_no_own_shutdown(dotted: str) -> None:
    """G-9a: у каждого из 23 нет своего ``shutdown`` и есть свой ``_on_shutdown``."""
    cls = _load(dotted)
    assert "shutdown" not in cls.__dict__, f"{cls.__name__}: свой shutdown остался"
    assert "_on_shutdown" in cls.__dict__, f"{cls.__name__}: нет своего _on_shutdown"


@pytest.mark.parametrize("dotted", FRAMEWORK_32, ids=_short)
def test_static_g9a_shutdown_is_base_template(dotted: str) -> None:
    """G-9a: у каждого из 32 ``cls.shutdown is BaseManager.shutdown``."""
    cls = _load(dotted)
    assert cls.shutdown is BaseManager.shutdown, f"{cls.__name__}.shutdown переопределён"


# ---------------------------------------------------------------------------
# G-17: литералы _ON_SHUTDOWN_WAIT_S на классах
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dotted", ["multiprocess_framework.modules.base_manager.core.base_manager.BaseManager"] + FRAMEWORK_32, ids=_short
)
def test_g17_class_wait_literal(dotted: str) -> None:
    cls = _load(dotted)
    expected = 7.0 if cls.__name__ in WAIT_7_NAMES else 5.0
    value = getattr(cls, "_ON_SHUTDOWN_WAIT_S", None)
    assert value == expected, f"{cls.__name__}._ON_SHUTDOWN_WAIT_S = {value!r}, ожидалось {expected}"
    assert value != 8.0, f"{cls.__name__}: 8.0 на классе недопустим"


# ---------------------------------------------------------------------------
# G-15: формула второго вызова (замер)
# ---------------------------------------------------------------------------


def test_g15_second_call_wait_with_real_scope(make_root, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    entered, gate = threading.Event(), threading.Event()
    mgr = HoldManager("g15_scope_mgr", entered, gate)
    mgr.attach_scope(make_root(budget_s=0.3, kill_reserve_s=0.2))
    try:
        a, box, (done, result, error, elapsed) = _second_call_while_first_held(mgr, gate, entered)
        assert done, "второй вызов завис дольше срока"
        assert error is None, repr(error)
        assert result is False
        assert 0.85 <= elapsed < 1.9, f"второй вызов ждал {elapsed:.3f} с, ожидалось 0,9 с"
    finally:
        gate.set()
    a.join(DEADLINE_S)
    assert box["first"] is True
    expected = "shutdown g15_scope_mgr: первый вызов не завершился за 0.9 с — второй вызов вернул False"
    lines = _wait_lines(caplog)
    assert lines.count(expected) == 1 and len(lines) == 1, lines


def test_g15_second_call_wait_without_scope(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    entered, gate = threading.Event(), threading.Event()
    mgr = HoldManager("g15_noscope_mgr", entered, gate)
    try:
        a, box, (done, result, error, elapsed) = _second_call_while_first_held(mgr, gate, entered)
        assert done, "второй вызов завис дольше срока"
        assert error is None, repr(error)
        assert result is False
        assert 5.3 <= elapsed < 7.0, f"второй вызов ждал {elapsed:.3f} с, ожидалось 5,4 с"
    finally:
        gate.set()
    a.join(DEADLINE_S)
    assert box["first"] is True
    expected = "shutdown g15_noscope_mgr: первый вызов не завершился за 5.4 с — второй вызов вернул False"
    lines = _wait_lines(caplog)
    assert lines.count(expected) == 1 and len(lines) == 1, lines


# ---------------------------------------------------------------------------
# G-16: репро ADR-BM-009 закрыт
# ---------------------------------------------------------------------------


def test_g16_adr_bm_009_repro_second_call_gets_first_result(make_root) -> None:
    mgr = SleepManager("g16_mgr")
    root = make_root(budget_s=0.5, kill_reserve_s=0.0)
    root.spawn(lambda _stop: time.sleep(2.0), name="ignores_stop")  # поток области игнорирует стоп
    mgr.attach_scope(root)
    box: dict = {}

    def first() -> None:
        box["first"] = mgr.shutdown()

    a = threading.Thread(target=first, daemon=True, name="g16_first")
    a.start()
    time.sleep(0.05)
    done, result, error, elapsed = call_bounded(mgr.shutdown, DEADLINE_S)
    a.join(DEADLINE_S)
    assert done, "второй вызов завис"
    assert error is None, repr(error)
    assert result is True, "второй вызов должен получить результат первого (до 1.2b-2: False через 0,51 с)"
    assert 0.4 <= elapsed < 2.0, f"второй вызов ждал {elapsed:.3f} с"
    assert box.get("first") is True
    assert mgr.body_calls == 1


# ---------------------------------------------------------------------------
# G-24, G-25: срок идёт за бюджетом корня
# ---------------------------------------------------------------------------


def _close_process(proc) -> None:
    call_bounded(proc.shutdown, 30.0)
    proc.close_root()


def test_g24_process_module_wait_follows_stop_budget() -> None:
    proc = ProcessModule("t02p", config={})
    try:
        proc.attach_stop_budget(stop_budget(1.0))
        assert proc.initialize() is True
        assert proc._ON_SHUTDOWN_WAIT_S == pytest.approx(0.8)
    finally:
        _close_process(proc)


def test_g24_process_manager_wait_follows_stop_budget() -> None:
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    try:
        pm.attach_stop_budget(stop_budget(1.0))
        assert pm.initialize() is True
        assert pm._ON_SHUTDOWN_WAIT_S == pytest.approx(3.2)
    finally:
        _close_process(pm)


def test_g24_attach_stop_budget_alone_leaves_default() -> None:
    proc = ProcessModule("t02p", config={})
    try:
        proc.attach_stop_budget(stop_budget(1.0))
        assert proc._ON_SHUTDOWN_WAIT_S == 5.0, "атрибут ставит открытие корня, а не attach_stop_budget"
    finally:
        _close_process(proc)


def test_g24_class_attribute_stays_default_after_instance_budget() -> None:
    proc = ProcessModule("t02p", config={})
    try:
        proc.attach_stop_budget(stop_budget(1.0))
        assert proc.initialize() is True
        assert ProcessModule._ON_SHUTDOWN_WAIT_S == 5.0, "срок живёт на экземпляре, класс не меняется"
    finally:
        _close_process(proc)


def test_g24_measured_second_call_wait_follows_budget(capfd) -> None:
    entered, gate = threading.Event(), threading.Event()

    class HeldProcess(ProcessModule):
        def _on_shutdown(self) -> bool:
            entered.set()
            gate.wait(DEADLINE_S)
            return super()._on_shutdown()

    proc = HeldProcess("t02p", config={})
    proc.attach_stop_budget({"work_s": 0.3, "infra_s": 0.2})
    assert proc.initialize() is True
    first_thread = None
    try:
        first_thread, _box, (done, result, error, elapsed) = _second_call_while_first_held(proc, gate, entered)
        assert done, "второй вызов завис дольше срока"
        assert error is None, repr(error)
        assert result is False
        assert 5.4 <= elapsed < 7.0, f"второй вызов ждал {elapsed:.3f} с, ожидалось 5,5 с (5,0 без области + 0,5)"
    finally:
        gate.set()
        if first_thread is not None:
            first_thread.join(DEADLINE_S)
        proc.close_root()
    expected_part = "первый вызов не завершился за 5.5 с — второй вызов вернул False"
    # После initialize() живёт LoggerManager: строка шаблона идёт в его консольный канал (stderr),
    # а не в stdlib, поэтому caplog слеп; читаем stderr через capfd.
    captured = capfd.readouterr()
    lines = [m for m in (captured.out + captured.err).splitlines() if WAIT_LINE in m]
    assert sum(expected_part in m for m in lines) == 1 and len(lines) == 1, lines
    assert not [r for r in unclosed_roots() if r["path"].endswith("t02p") and r["state"] == "open"], unclosed_roots()


def test_g25_before_root_opens_class_default() -> None:
    proc = ProcessModule("t02p", config={})
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    assert proc._ON_SHUTDOWN_WAIT_S == 5.0
    assert pm._ON_SHUTDOWN_WAIT_S == 5.0


def test_g25_process_module_default_member_of_root() -> None:
    proc = ProcessModule("t02p", config={})
    try:
        assert proc.initialize() is True
        assert proc._ON_SHUTDOWN_WAIT_S == 4.0, "3.0 + 1.0"
    finally:
        _close_process(proc)


def test_g25_process_manager_default_member_of_root() -> None:
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    try:
        assert pm.initialize() is True
        assert pm._ON_SHUTDOWN_WAIT_S == 8.0, "7.0 + 1.0"
    finally:
        _close_process(pm)


# ---------------------------------------------------------------------------
# G-18: Р4, интерфейс
# ---------------------------------------------------------------------------


def test_g18_interface_requires_close_root_and_attach_stop_budget() -> None:
    assert {"close_root", "attach_stop_budget"} <= IProcessModule.__abstractmethods__


def test_g18_interface_has_no_lifetime_segments() -> None:
    assert "lifetime_segments" not in vars(IProcessModule)


def test_g18_process_module_is_iprocess_module() -> None:
    assert isinstance(ProcessModule("t02p", config={}), IProcessModule) is True


# ---------------------------------------------------------------------------
# G-19, G-20: Р4, раннер; настоящий ProcessModule через run_process_function
# ---------------------------------------------------------------------------

STOP_BUDGET_G19 = {"work_s": 0.3, "infra_s": 0.1, "pm_graceful_s": 0.5, "pm_total_s": 2.0, "outer_s": 3.5}


class _Probe:
    instances: list = []
    attach_budgets: list = []
    close_calls: int = 0
    shutdown_calls: int = 0

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.attach_budgets = []
        cls.close_calls = 0
        cls.shutdown_calls = 0


class CountingProc(ProcessModule):
    """Настоящий ``ProcessModule`` без выживших; считает вызовы раннера."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _Probe.instances.append(self)

    def attach_stop_budget(self, budget: dict) -> None:
        _Probe.attach_budgets.append(dict(budget))
        super().attach_stop_budget(budget)

    def close_root(self):
        _Probe.close_calls += 1
        return super().close_root()

    def _on_shutdown(self) -> bool:
        _Probe.shutdown_calls += 1
        return super()._on_shutdown()


class DuckProc:
    """Простой класс (не ``IProcessModule``) со всеми методами, включая ``close_root`` и ``attach_stop_budget``."""

    def __init__(self, *args, **kwargs) -> None:
        _Probe.instances.append(self)

    def initialize(self) -> bool:
        return True

    def should_stop(self) -> bool:
        return True

    def run(self) -> None:
        return None

    def close_root(self):
        _Probe.close_calls += 1
        return CloseReport(path="proc/duck", elapsed_s=0.0, survivors=(), killed=(), errors=())

    def attach_stop_budget(self, budget: dict) -> None:
        _Probe.attach_budgets.append(dict(budget))

    def shutdown(self) -> bool:
        _Probe.shutdown_calls += 1
        return True


_MOCK_PROC_BOX: dict = {}


def make_mock_proc(*_args, **_kwargs):
    """Фабрика для ``class_path``: возвращает ``MagicMock`` без ``close_root``."""
    return _MOCK_PROC_BOX["proc"]


@pytest.fixture
def probe():
    _Probe.reset()
    yield _Probe
    _Probe.reset()


def _run_child(monkeypatch, class_path: str, process_config: dict) -> list:
    """Прогнать раннер в процессе pytest с подменённым выходом; вернуть вызовы ``_hard_exit``."""
    import multiprocessing
    import os

    hard_exit_calls: list = []
    exit_report = [0, 0, 0]
    monkeypatch.setattr(os, "_exit", lambda code: hard_exit_calls.append(("os._exit", code)))
    monkeypatch.setattr(process_runner, "_hard_exit", lambda code: hard_exit_calls.append((code, exit_report[0])))

    name = "t02r"
    srm = SharedResourcesManager()
    srm.process_state_registry.register_process(name)
    srm.get_process_data(name).custom["process_config"] = process_config
    stop_event = multiprocessing.Event()
    stop_event.set()
    try:
        done, _, error, _ = call_bounded(
            lambda: process_runner.run_process_function(
                class_path, name, stop_event=stop_event, shared_resources_or_bundle=srm, exit_report=exit_report
            ),
            60.0,
        )
        assert done, "run_process_function завис"
        assert error is None, repr(error)
    finally:
        call_bounded(srm.shutdown, 15.0)
    return hard_exit_calls


def test_g19_real_process_runner_attach_once_close_once_no_shutdown(monkeypatch, probe) -> None:
    class_path = f"{CountingProc.__module__}.{CountingProc.__name__}"
    calls = _run_child(monkeypatch, class_path, {"stop_budget": STOP_BUDGET_G19})
    assert calls == [], calls
    assert len(probe.instances) == 1
    assert probe.attach_budgets == [pytest.approx(STOP_BUDGET_G19)], probe.attach_budgets
    assert probe.close_calls == 1, f"close_root: {probe.close_calls}"
    assert probe.shutdown_calls == 0, f"shutdown: {probe.shutdown_calls}"


def test_g20_runner_duck_typing_removed_plain_class_gets_shutdown_only(monkeypatch, probe) -> None:
    class_path = f"{DuckProc.__module__}.{DuckProc.__name__}"
    _run_child(monkeypatch, class_path, {"stop_budget": STOP_BUDGET_G19})
    assert (probe.shutdown_calls, probe.close_calls, len(probe.attach_budgets)) == (1, 0, 0), (
        "shutdown/close_root/attach_stop_budget: "
        f"{probe.shutdown_calls}/{probe.close_calls}/{len(probe.attach_budgets)} (до 1.2b-2: 0/1/1)"
    )


def test_g20_runner_mock_without_close_root_gets_shutdown(monkeypatch) -> None:
    from unittest.mock import MagicMock

    proc = MagicMock()
    proc.initialize.return_value = True
    proc.should_stop.return_value = True
    del proc.close_root
    _MOCK_PROC_BOX["proc"] = proc
    try:
        class_path = f"{make_mock_proc.__module__}.{make_mock_proc.__name__}"
        _run_child(monkeypatch, class_path, {"stop_budget": STOP_BUDGET_G19})
    finally:
        _MOCK_PROC_BOX.clear()
    assert proc.shutdown.call_count == 1, f"shutdown: {proc.shutdown.call_count}"


# ---------------------------------------------------------------------------
# G-21: цепочка LoggerManager
# ---------------------------------------------------------------------------


class _CountingChannel(IChannel):
    def __init__(self) -> None:
        self.closes = 0

    @property
    def name(self) -> str:
        return "t02_counter"

    def write(self, data: dict) -> dict:
        return {"status": "success", "channel": self.name}

    def close(self) -> None:
        self.closes += 1


def test_g21_logger_manager_chain_closes_channel_once_and_bumps_epoch_once() -> None:
    lm = LoggerManager()
    try:
        assert LoggerManager._instance is lm
        channel = _CountingChannel()
        assert lm.register_channel(channel) is True
        epoch_before = OBSERVABILITY_EPOCH[0]
        assert lm.shutdown() is True
        assert channel.closes == 1
        assert LoggerManager._instance is None
        assert OBSERVABILITY_EPOCH[0] - epoch_before == 1
        assert lm.shutdown() is True
        assert channel.closes == 1, "второй shutdown закрыл канал повторно"
        assert OBSERVABILITY_EPOCH[0] - epoch_before == 1, "второй shutdown сдвинул эпоху"
    finally:
        call_bounded(lm.shutdown, 15.0)
        if LoggerManager._instance is lm:
            LoggerManager._instance = None


# ---------------------------------------------------------------------------
# G-22: WorkerPoolExecutor
# ---------------------------------------------------------------------------


class _AppendTask:
    def __init__(self, sink: list, delay: float, tag: int) -> None:
        self._sink = sink
        self._delay = delay
        self._tag = tag

    def execute(self, d, c):
        time.sleep(self._delay)
        self._sink.append(self._tag)
        return self._tag

    def configure(self, p):
        pass


class _GateTask:
    """Держится на событии, потом дописывает в список."""

    def __init__(self, sink: list, started: threading.Event, release: threading.Event) -> None:
        self._sink = sink
        self._started = started
        self._release = release

    def execute(self, d, c):
        self._started.set()
        self._release.wait(DEADLINE_S)
        self._sink.append("first")
        return "first"

    def configure(self, p):
        pass


def _nowait_scenario():
    """(б): одна задача держится на событии, три в очереди; ``shutdown_nowait()`` из потока, событие через 0.3 с."""
    sink: list = []
    started, release = threading.Event(), threading.Event()
    ex = WorkerPoolExecutor(max_workers=1, step_timeout=5.0)
    ex.submit(_GateTask(sink, started, release), None, None)
    assert started.wait(DEADLINE_S), "первая задача не стартовала"
    for i in range(3):
        ex.submit(_AppendTask(sink, 0.0, i), None, None)
    timer = threading.Timer(0.3, release.set)
    timer.daemon = True
    timer.start()
    outcome = call_bounded(lambda: ex.shutdown_nowait(), DEADLINE_S)
    release.set()
    timer.join(DEADLINE_S)
    return ex, sink, outcome


def test_g22a_shutdown_drains_queue() -> None:
    sink: list = []
    ex = WorkerPoolExecutor(max_workers=1, step_timeout=5.0)
    for i in range(5):
        ex.submit(_AppendTask(sink, 0.05, i), None, None)
    done, result, error, _ = call_bounded(ex.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, repr(error)
    assert result is True
    assert len(sink) == 5, sink


def test_g22b_shutdown_nowait_drops_queue_keeps_running_task() -> None:
    ex, sink, (done, result, error, _) = _nowait_scenario()
    try:
        assert done, "shutdown_nowait() завис"
        assert error is None, repr(error)
        assert result is True
        assert len(sink) == 1, sink
    finally:
        call_bounded(lambda: ex.shutdown(), DEADLINE_S)


def test_g22c_after_nowait_shutdown_and_repeat_nowait_are_true() -> None:
    ex, _sink, (done, result, error, _) = _nowait_scenario()
    try:
        assert done and error is None and result is True, (done, result, repr(error))
        done_s, result_s, error_s, _ = call_bounded(ex.shutdown, DEADLINE_S)
        assert done_s and error_s is None, (done_s, repr(error_s))
        assert result_s is True
        done_n, result_n, error_n, _ = call_bounded(ex.shutdown_nowait, DEADLINE_S)
        assert done_n and error_n is None, (done_n, repr(error_n))
        assert result_n is True
    finally:
        call_bounded(ex.shutdown, DEADLINE_S)


def test_g22d_shutdown_wait_argument_is_type_error() -> None:
    ex = WorkerPoolExecutor(max_workers=1, step_timeout=5.0)
    try:
        with pytest.raises(TypeError):
            ex.shutdown(wait=True)
    finally:
        call_bounded(lambda: ex.shutdown(), DEADLINE_S)


# ---------------------------------------------------------------------------
# G-23: ProcessModule закрывает корень один раз
# ---------------------------------------------------------------------------


def test_g23_process_module_closes_root_once_on_two_shutdowns() -> None:
    proc = ProcessModule("t02p", config={})
    assert proc.initialize() is True
    calls: list = []
    original = proc.close_root

    def counting_close_root():
        calls.append(1)
        return original()

    proc.close_root = counting_close_root
    try:
        first = call_bounded(proc.shutdown, 30.0)
        second = call_bounded(proc.shutdown, 30.0)
        assert first[0] and second[0], "shutdown() завис"
        assert first[2] is None and second[2] is None, (first[2], second[2])
        assert first[1] is True and second[1] is True, (first[1], second[1])
        assert len(calls) == 1, f"close_root вызван {len(calls)} раз(а), ожидалось 1 (до 1.2b-2: 2)"
    finally:
        original()
