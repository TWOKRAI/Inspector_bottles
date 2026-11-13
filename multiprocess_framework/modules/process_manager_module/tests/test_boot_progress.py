# -*- coding: utf-8 -*-
"""Task 1.3b (system-run-state) — слепой набор: PM публикует ``system.progress.boot`` по фактам старта.

Контракт (из брифа, без чтения реализации и плана):
  * лист ``system.progress.boot`` = dict ``{percent, label, done, updated_at}``; пишется через
    ``_state_op("handle_state_set", {"path", "value", "source": "ProcessManager"}, ...)``;
  * шаги: стор поднят — 5; «процессы запущены» — 45 пропорционально k из N; «готовы» — 50 (барьер);
  * N=3 без ``depends_on``: percent по ходу 5, 20, 35, 50, затем после барьера 100 с ``done: true``;
  * N=0 — сразу ``finish`` без деления на ноль; ``finish`` один раз в конце ``initialize()``;
    ``label`` несёт «запущено k из N», если k < N; в волновом старте процент не убывает;
  * лист НЕ трогают: итог STOP/settle, рестарт процесса, apply; сбой записи в стор boot не валит.

Стенд — настоящий ``initialize()`` PM (образец ``test_run_state_hazards._initialize_bare_pm``): шаги вне boot подменены,
НАСТОЯЩИЕ ``_create_processes_from_config`` / ``_wait_boot_ready`` / ``_wait_processes_ready`` крутятся на фейковом
реестре с готовыми ``ready_event``. Стор — настоящий ``StateStoreManager`` (подкласс только журналирует записи).
Путь листа пишется ЛИТЕРАЛОМ: тест не импортирует ``progress.py`` и краснеет по поведению, а не по импорту.

Решения тестера (ASSUMPTION — см. отчёт 1.3b.tester.md):
  * стор подключается через подменённый ``_setup_state_store`` (хук, как в прототипе);
  * N = число записей ``processes_config`` с ключом ``class``;
  * барьер/волны крутятся настоящим кодом, ready-события выставлены заранее (мёртвый процесс — не жив).
"""

from __future__ import annotations

import copy
import threading
from multiprocessing import Event
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager

from ..process import process_manager_process as pm_mod
from ..process.process_manager_process import ProcessManagerProcess
from .test_run_commands import _PM_MOD, make_readiness_pm

BOOT_PATH = "system.progress.boot"
LEAF_KEYS = {"percent", "label", "done", "updated_at"}
_JOIN_S = 30.0


# --------------------------------------------------------------------------- #
# Стенд
# --------------------------------------------------------------------------- #


class _RecStore(StateStoreManager):
    """Настоящий ``StateStoreManager``; подкласс журналирует каждую запись ``(path, глубокая копия value)``."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, Any]] = []

    def handle_state_set(self, msg: dict) -> dict | None:
        data = msg["data"]
        self.writes.append((data["path"], copy.deepcopy(data["value"])))
        return super().handle_state_set(msg)

    def boot_leaves(self) -> list[dict]:
        """Все записи листа boot по порядку."""
        return [v for p, v in self.writes if p == BOOT_PATH]

    def boot_percents(self) -> list[int]:
        return [leaf["percent"] for leaf in self.boot_leaves()]


class _Proc:
    def __init__(self, name: str, alive: bool) -> None:
        self.name = name
        self._alive = alive
        self.pid = 4242

    def start(self) -> None:
        pass

    def is_alive(self) -> bool:
        return self._alive


class _Registry:
    """Фейковый реестр boot-пути: создание/старт/готовность процессов. ``fail`` — create не удаётся,
    ``dead`` — стартует и сразу не жив (ready-события нет)."""

    def __init__(self, fail: set[str], dead: set[str]) -> None:
        self._fail = fail
        self._dead = dead
        self._procs: dict[str, _Proc] = {}
        self._events: dict[str, Any] = {}

    @property
    def os_processes(self) -> list[_Proc]:
        return list(self._procs.values())

    def create_and_register(self, name: str, class_path: str, config: dict, priority: str) -> bool:
        if name in self._fail:
            return False
        self._procs[name] = _Proc(name, alive=name not in self._dead)
        ev = threading.Event()
        if name not in self._dead:
            ev.set()
        self._events[name] = ev
        return True

    def get_process_by_name(self, name: str) -> _Proc | None:
        return self._procs.get(name)

    def get_ready_event(self, name: str) -> Any:
        return self._events.get(name)


def _proc_cfg(depends_on: list[str] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"class": "pkg.Proc"}
    if depends_on is not None:
        cfg["depends_on"] = depends_on
    return cfg


def _flat(*names: str) -> dict[str, dict]:
    return {n: _proc_cfg() for n in names}


def _bare_boot_pm(configs: dict[str, dict], registry: _Registry) -> ProcessManagerProcess:
    """PM для настоящего ``initialize()``: компоненты — настоящий ``_create_components``, реестр — фейк boot-пути."""
    pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.shared_resources = None
    pm.config = {}
    pm.command_manager = MagicMock()
    pm.router_manager = MagicMock()
    pm._system_ready_event = Event()
    pm._backend_ctl_channel = None
    pm._process_configs = {}
    with (
        patch(f"{_PM_MOD}.ProcessRegistry"),
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor"),
        patch(f"{_PM_MOD}.QueueRegistry"),
        patch.object(ProcessManagerProcess, "get_config", return_value=None),
    ):
        pm._create_components()
    pm._process_registry = registry
    pm._priority = MagicMock()
    monitor = MagicMock()
    monitor.readiness_snapshot.return_value = {}  # дети не отчитались -> итог boot not_ready; прогрессу всё равно
    pm._process_monitor = monitor
    return pm


def _run_initialize(pm: ProcessManagerProcess, configs: dict[str, dict], store: StateStoreManager | None) -> bool:
    """Настоящий ``initialize()`` в daemon-потоке с join-дедлайном; ``store=None`` — стора нет."""

    def get_config(key: str, default: Any = None) -> Any:
        return configs if key == "processes_config" else default

    def setup_store(self: ProcessManagerProcess) -> None:
        if store is not None:
            self._state_store_manager = store

    box: dict[str, Any] = {}

    def go() -> None:
        try:
            with (
                patch.object(ProcessManagerProcess, "get_config", side_effect=get_config),
                patch.object(pm_mod.ProcessModule, "initialize", return_value=True),
                patch.object(ProcessManagerProcess, "_setup_lifecycle_executor", return_value=True),
                patch.object(ProcessManagerProcess, "_setup_console_manager"),
                patch.object(ProcessManagerProcess, "_setup_topology_manager"),
                patch.object(ProcessManagerProcess, "_setup_state_store", new=setup_store),
                patch.object(ProcessManagerProcess, "_register_builtin_commands"),
                patch.object(ProcessManagerProcess, "_log_active_feature_flags"),
                patch.object(ProcessManagerProcess, "_sweep_orphaned_log_dirs"),
                patch.object(ProcessManagerProcess, "_warn_foreign_log_roots"),
                patch.object(ProcessManagerProcess, "_mark_instance_started"),
                patch.object(ProcessManagerProcess, "_cleanup_process_resources"),
                patch.object(ProcessManagerProcess, "_log_info"),
                patch.object(ProcessManagerProcess, "_log_warning"),
                patch.object(ProcessManagerProcess, "_log_error"),
                patch.object(ProcessManagerProcess, "_log_debug"),
                patch(f"{_PM_MOD}.setup_backend_ctl_channel", return_value=None),
            ):
                box["result"] = pm.initialize()
        except BaseException as exc:  # noqa: BLE001 — исключение стенда/кода доносим в основной поток
            box["error"] = exc

    t = threading.Thread(target=go, daemon=True, name="pm-initialize")
    t.start()
    t.join(_JOIN_S)
    assert not t.is_alive(), f"initialize() завис дольше {_JOIN_S} с"
    assert "error" not in box, f"initialize() бросил: {box['error']!r}"
    return box["result"]


def _boot(
    configs: dict[str, dict],
    *,
    fail: set[str] | None = None,
    dead: set[str] | None = None,
    state_op: Any = None,
) -> tuple[_RecStore, ProcessManagerProcess, bool]:
    """Прогнать boot: ``(стор, pm, результат initialize())``. ``state_op`` — обёртка ``_state_op(orig)`` -> функция."""
    store = _RecStore()
    pm = _bare_boot_pm(configs, _Registry(fail or set(), dead or set()))
    if state_op is not None:
        pm._state_op = state_op(pm._state_op)
    result = _run_initialize(pm, configs, store)
    return store, pm, result


def _collapse(values: list[int]) -> list[int]:
    """Подряд идущие повторы схлопываются: ``advance("ready")`` и ``finish`` оба дают 100 разными записями."""
    out: list[int] = []
    for v in values:
        if not out or out[-1] != v:
            out.append(v)
    return out


# --------------------------------------------------------------------------- #
# ACCEPTANCE и контракт boot
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_three_processes_flat_boot_publishes_5_20_35_50_then_100_done() -> None:
    """N=3 без ``depends_on`` на реальном ``StateStoreManager``: percent листа boot 5, 20, 35, 50, затем 100 с done."""
    store, _pm, result = _boot(_flat("a", "b", "c"))
    assert result is True
    leaves = store.boot_leaves()
    assert leaves, "лист system.progress.boot не записан"
    assert _collapse(store.boot_percents()) == [5, 20, 35, 50, 100], store.boot_percents()
    # done=true — ровно у последней записи (finish один раз в конце initialize())
    assert [leaf["done"] for leaf in leaves].count(True) == 1 and leaves[-1]["done"] is True
    # итог читается из стора как лист: те же четыре литеральных ключа
    final = store.store.get(BOOT_PATH)
    assert set(final) == LEAF_KEYS, final
    assert (final["percent"], final["done"]) == (100, True)
    assert isinstance(final["label"], str) and isinstance(final["updated_at"], float)
    # k == N: пометки «запущено k из N» нет (она только при k < N)
    assert "запущено" not in final["label"], final["label"]


@pytest.mark.timeout(60)
def test_empty_topology_finishes_without_division() -> None:
    """N=0: ``initialize()`` не падает на делении на ноль, лист boot сразу финальный (100, done), без промежуточных."""
    store, _pm, result = _boot({})
    assert result is True
    final = store.store.get(BOOT_PATH)
    assert (final["percent"], final["done"]) == (100, True), final
    # ASSUMPTION: на пустой топологии допустимы только 5 («стор поднят») и 100; «k из N» процентов не бывает
    assert set(store.boot_percents()) <= {5, 100}, store.boot_percents()
    assert [leaf["done"] for leaf in store.boot_leaves()].count(True) == 1


@pytest.mark.timeout(60)
def test_failed_process_create_finish_label_says_k_of_n() -> None:
    """Один из трёх create провалился (k=2, N=3): boot завершён (100, done), label несёт «запущено 2 из 3»."""
    store, _pm, result = _boot(_flat("a", "b", "c"), fail={"b"})
    assert result is True
    final = store.store.get(BOOT_PATH)
    assert (final["percent"], final["done"]) == (100, True), final
    assert "запущено 2 из 3" in final["label"], final["label"]
    # finish один раз: done=true у единственной записи
    assert [leaf["done"] for leaf in store.boot_leaves()].count(True) == 1


@pytest.mark.timeout(60)
def test_waves_ready_is_union_percent_never_decreases() -> None:
    """Волновой старт (a <- b <- c), ``b`` умирает сразу после старта: процент по записям не убывает, итог 100/done.

    Барьеры волн возвращают готовность по подмножествам (апстрим волны), итоговый барьер — по всем; процент не
    берёт «последний результат», а накапливает объединением готовых.
    """
    configs = {"a": _proc_cfg(), "b": _proc_cfg(["a"]), "c": _proc_cfg(["b"])}
    gate_calls: list[tuple[str, ...]] = []
    orig_wait = ProcessManagerProcess._wait_processes_ready

    def spy_wait(self: ProcessManagerProcess, names: list[str], timeout_s: float, reason: str) -> dict[str, bool]:
        gate_calls.append(tuple(names))
        return orig_wait(self, names, timeout_s, reason)

    with patch.object(ProcessManagerProcess, "_wait_processes_ready", new=spy_wait):
        store, _pm, result = _boot(configs, dead={"b"})
    assert result is True
    # предпосылка стенда: волны реально гейтились (гейт a, гейт b) и был итоговый барьер по всем
    assert gate_calls[:2] == [("a",), ("b",)] and gate_calls[-1] == ("a", "b", "c"), gate_calls
    percents = store.boot_percents()
    assert percents == sorted(percents), f"процент убывал: {percents}"
    assert percents[0] == 5, percents
    final = store.store.get(BOOT_PATH)
    assert (final["percent"], final["done"]) == (100, True), final
    assert [leaf["done"] for leaf in store.boot_leaves()].count(True) == 1


@pytest.mark.timeout(60)
def test_store_write_raises_boot_continues_percent_not_rolled_back() -> None:
    """``_state_op`` бросает на записи percent=20: boot не падает, все три процесса стартовали, процент не откатан.

    Дошедшие до стора записи: 5, затем 35, 50, 100 (значение 35 — своё, а не «следующее после сбойного»).
    """

    def wrap(orig):
        def flaky(handler_name: str, payload: dict, ctx: str) -> None:
            value = payload.get("value")
            if payload.get("path") == BOOT_PATH and isinstance(value, dict) and value.get("percent") == 20:
                raise RuntimeError("store down")
            return orig(handler_name, payload, ctx)

        return flaky

    store, pm, result = _boot(_flat("a", "b", "c"), state_op=wrap)
    assert result is True, "сбой записи прогресса уронил initialize()"
    assert sorted(p.name for p in pm._process_registry.os_processes) == ["a", "b", "c"]
    assert _collapse(store.boot_percents()) == [5, 35, 50, 100], store.boot_percents()
    final = store.store.get(BOOT_PATH)
    assert (final["percent"], final["done"]) == (100, True), final


# --------------------------------------------------------------------------- #
# Чего boot-лист НЕ трогает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_settle_and_restart_do_not_touch_boot_leaf() -> None:
    """После boot: tick/start/stop, итог стопа (settled), apply, рестарт процесса — ни одной записи в лист boot,
    сам лист не изменился (ни percent, ни done, ни updated_at)."""
    pm, _monitor = make_readiness_pm({"worker": {"class": "m.W", "priority": "normal"}})
    store = _RecStore()
    pm._state_store_manager = store
    # лист завершённого boot, как его оставил initialize()
    sealed = {"percent": 100, "label": "", "done": True, "updated_at": 1000.5}
    store.handle_state_set({"data": {"path": BOOT_PATH, "value": dict(sealed), "source": "ProcessManager"}})
    before = len(store.writes)

    pm.send_message = MagicMock()
    pm._broadcast_routing_refresh = MagicMock()
    pm._publish_process_identity = MagicMock()
    pm._replay_telemetry_runtime_delta = MagicMock()

    pm._run_apply("tick", ready=True)
    pm._run_apply("start")
    pm._run_apply("stop")
    pm._settle_run_state()  # итог стопа: stopping -> ready/not_ready
    pm._run_apply("apply")  # apply: -> booting
    pm._settle_run_state()
    assert pm.restart_process("worker") is True

    later = store.writes[before:]
    assert later, "предпосылка: за время операций PM должен был писать в стор (system.run.*)"
    assert [p for p, _ in later if p.startswith("system.progress")] == [], later
    assert store.store.get(BOOT_PATH) == sealed
