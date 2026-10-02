# -*- coding: utf-8 -*-
"""Task 5.2 — слепые приёмочные тесты входа ``PluginContext.scheduler``.

Источник — только раздел «Task 5.2» плана ``plans/transport-single-policy/phase-5.md``.
Реализации на момент написания нет; тесты красные по построению.

Контракт, который пинят тесты:

* ``PluginContext.scheduler`` — ленивое свойство, ОДИН ``ActuationScheduler`` на процесс;
* ``PluginContext`` у каждого плагина свой (``with_config`` создаёт новый), поэтому объект хранится
  на ``self.services`` (атрибут ``_actuation_scheduler``), get-or-create под замком;
* первое обращение при ``worker_manager is not None`` запускает воркер ``actuation``
  (``create_worker("actuation", scheduler.run_loop, ThreadConfig(...), auto_start=True)``);
  **``auto_start=True`` — явно**: у настоящих ``WorkerAdapter`` / ``WorkerManager`` умолчание ``False``;
* при ``worker_manager is None`` — без воркера, ``tick()`` зовут руками;
* протокол ``IActuationScheduler`` (``schedule``, ``pending``, ``tick``, ``stats``) в
  ``process_module/plugins/interfaces.py``, экспорт в ``plugins/__init__.py``.

Фейк ``plugins/testing.py::MockWorkerManager`` здесь намеренно не используется для проверки запуска
воркера: его ``create_worker`` объявляет ``auto_start=True`` по умолчанию, и он записал бы «запущен»,
даже если плагин забыл передать аргумент. Для строгости — собственный регистратор с умолчанием
``False`` (как у настоящих) и настоящие ``WorkerAdapter`` / ``WorkerManager``.

Любой вызов, способный блокироваться, идёт в daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


def _services(name: str = "proc", worker_manager: Any = None) -> MockProcessServices:
    """Сервисы процесса; ``worker_manager`` подменяется ДО создания контекста (контекст читает его в ``__init__``)."""
    svc = MockProcessServices(name=name)
    svc.worker_manager = worker_manager  # type: ignore[assignment]
    return svc


def _bounded(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Вызов в daemon-потоке с дедлайном на join: зависание = падение, а не висящий прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросим в поток теста
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов завис дольше {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _StrictWorkerManager:
    """Записывает вызовы ``create_worker`` как настоящий: умолчание ``auto_start`` — ``False``."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.created: list[dict[str, Any]] = []
        self._delay = delay_s
        self._lock = threading.Lock()

    def create_worker(self, *args: Any, **kwargs: Any) -> bool:
        if self._delay:
            time.sleep(self._delay)  # расширяет окно гонки «проверил — создал»
        name = args[0] if args else kwargs.get("worker_name", kwargs.get("name"))
        target = args[1] if len(args) > 1 else kwargs.get("target")
        config = args[2] if len(args) > 2 else kwargs.get("config")
        auto_start = args[3] if len(args) > 3 else kwargs.get("auto_start", False)
        with self._lock:
            self.created.append({"name": name, "target": target, "config": config, "auto_start": auto_start})
        return True

    def pause_worker(self, name: str) -> None: ...

    def resume_worker(self, name: str) -> None: ...

    def start_worker(self, name: str) -> None: ...

    def is_worker_running(self, name: str) -> bool:
        return False


class _CallablePayload(dict):
    """Полезная нагрузка, безопасная для любого ``fire``: словарь, который к тому же можно вызвать."""

    def __init__(self) -> None:
        super().__init__(kind="t52_probe")
        self.calls: list = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


# --- Один планировщик на процесс -----------------------------------------------------------------


def test_two_plugin_contexts_of_one_process_get_the_same_scheduler_object() -> None:
    svc = _services()
    ctx_a = PluginContext(svc, plugin_name="robot_control")
    ctx_b = ctx_a.with_config({}, plugin_name="other_plugin")  # with_config создаёт НОВЫЙ контекст
    ctx_c = PluginContext(svc, plugin_name="third")

    first = ctx_a.scheduler

    assert ctx_b is not ctx_a  # якорь: контексты действительно разные объекты
    assert ctx_b.scheduler is first
    assert ctx_c.scheduler is first


def test_schedulers_of_two_processes_are_different_objects() -> None:
    ctx_one = PluginContext(_services(name="p1"))
    ctx_two = PluginContext(_services(name="p2"))

    assert ctx_one.scheduler is not ctx_two.scheduler


def test_scheduler_is_lazy_and_lives_on_services_under_actuation_scheduler_attr() -> None:
    svc = _services()
    ctx = PluginContext(svc)

    assert getattr(svc, "_actuation_scheduler", None) is None  # до первого обращения не создан

    sch = ctx.scheduler

    assert svc._actuation_scheduler is sch  # type: ignore[attr-defined]


def test_scheduler_is_the_same_object_on_every_access() -> None:
    ctx = PluginContext(_services())

    assert ctx.scheduler is ctx.scheduler


def test_concurrent_first_access_from_eight_threads_makes_one_scheduler_and_one_worker() -> None:
    wm = _StrictWorkerManager(delay_s=0.05)
    svc = _services(worker_manager=wm)
    contexts = [PluginContext(svc, plugin_name=f"p{i}") for i in range(8)]
    barrier = threading.Barrier(8)
    got: list = []
    got_lock = threading.Lock()

    def grab(ctx: PluginContext) -> None:
        barrier.wait(5.0)
        s = ctx.scheduler
        with got_lock:
            got.append(s)

    threads = [threading.Thread(target=grab, args=(c,), daemon=True) for c in contexts]
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # частые переключения потоков: гонка «проверил — создал» ловится чаще
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(10.0)
            assert not t.is_alive(), "поток завис на первом обращении к ctx.scheduler"
    finally:
        sys.setswitchinterval(old_interval)

    assert len(got) == 8
    assert all(s is got[0] for s in got), "гонка get-or-create: разные объекты планировщика"
    assert len(wm.created) == 1, f"воркер actuation создан {len(wm.created)} раз(а)"


# --- Без воркер-менеджера (юниты) ----------------------------------------------------------------


def test_without_worker_manager_scheduler_works_by_hand_ticks() -> None:
    svc = _services(worker_manager=None)
    ctx = PluginContext(svc)
    assert ctx.worker_manager is None  # якорь: ветка «юниты»

    sch = ctx.scheduler

    assert sch.pending() == 0
    assert sch.tick() == 0
    stale = time.time() - 100.0
    assert sch.schedule(stale, stale, 4, None) == "missed"
    assert sch.stats()["missed_items"] == 4


# --- Запуск воркера actuation --------------------------------------------------------------------


def test_first_access_with_worker_manager_creates_worker_actuation_with_explicit_auto_start() -> None:
    wm = _StrictWorkerManager()
    ctx = PluginContext(_services(worker_manager=wm))

    sch = ctx.scheduler

    assert len(wm.created) == 1
    created = wm.created[0]
    assert created["name"] == "actuation"
    assert created["target"] == sch.run_loop  # цель воркера — именно run_loop этого планировщика
    # умолчание auto_start у фейка и у настоящих менеджеров — False; True обязан прийти явно
    assert created["auto_start"] is True


def test_worker_is_created_once_for_two_plugin_contexts_of_one_process_and_repeated_access() -> None:
    wm = _StrictWorkerManager()
    svc = _services(worker_manager=wm)
    ctx_a = PluginContext(svc, plugin_name="a")
    ctx_b = ctx_a.with_config({}, plugin_name="b")

    _ = ctx_a.scheduler
    _ = ctx_b.scheduler
    _ = ctx_a.scheduler
    _ = ctx_b.scheduler

    assert len(wm.created) == 1, f"create_worker('actuation') вызван {len(wm.created)} раз(а), ожидался один"


def test_scheduler_without_any_access_creates_no_worker() -> None:
    wm = _StrictWorkerManager()
    PluginContext(_services(worker_manager=wm))

    assert wm.created == []


# --- Настоящие WorkerAdapter / WorkerManager -----------------------------------------------------


def _real_worker_stack(kind: str, manager_name: str):
    """(то, что кладут в services.worker_manager, настоящий WorkerManager)."""
    from multiprocess_framework.modules.worker_module.adapters.worker_adapter import WorkerAdapter
    from multiprocess_framework.modules.worker_module.core.worker_manager import WorkerManager

    manager = WorkerManager(manager_name)
    manager.initialize()
    if kind == "adapter":
        adapter = WorkerAdapter(manager, None)
        assert adapter.setup() is True
        return adapter, manager
    return manager, manager


def _alive_actuation_threads(manager_name: str) -> list[str]:
    return [t.name for t in threading.enumerate() if t.is_alive() and t.name == f"{manager_name}_actuation"]


@pytest.fixture(params=["adapter", "manager"])
def real_stack(request):
    name = f"t52real_{request.param}"
    facade, manager = _real_worker_stack(request.param, name)
    yield facade, manager, name
    _bounded(lambda: manager.stop_all_workers(timeout=2.0), timeout=10.0)


def test_real_worker_manager_first_access_starts_worker_actuation(real_stack) -> None:
    facade, manager, _ = real_stack
    ctx = PluginContext(_services(worker_manager=facade))

    _ = ctx.scheduler

    assert manager.has_worker("actuation")
    assert manager.is_worker_running("actuation"), (
        "воркер создан, но не запущен: create_worker без auto_start=True (у настоящего умолчание False)"
    )


def test_real_worker_fires_a_target_scheduled_50ms_ahead_within_200ms(real_stack) -> None:
    facade, manager, _ = real_stack
    ctx = PluginContext(_services(worker_manager=facade))
    sch = ctx.scheduler
    deadline_probe = time.perf_counter() + 2.0
    while not manager.is_worker_running("actuation") and time.perf_counter() < deadline_probe:
        time.sleep(0.005)
    assert manager.is_worker_running("actuation")  # якорь: без воркера выстрела ждать нечего

    payload = _CallablePayload()
    now = time.time()
    t0 = time.perf_counter()
    assert sch.schedule(now + 0.05, now + 0.05, 1, payload) == "scheduled"
    while sch.stats()["fired_items"] < 1 and time.perf_counter() - t0 < 0.2:
        time.sleep(0.005)
    waited = time.perf_counter() - t0

    assert sch.stats()["fired_items"] == 1, f"за {waited * 1000:.0f} мс цель не выстрелила"
    assert waited <= 0.2
    assert sch.pending() == 0


def test_real_stop_all_workers_stops_worker_actuation(real_stack) -> None:
    facade, manager, name = real_stack
    ctx = PluginContext(_services(worker_manager=facade))
    sch = ctx.scheduler
    deadline_probe = time.perf_counter() + 2.0
    while not manager.is_worker_running("actuation") and time.perf_counter() < deadline_probe:
        time.sleep(0.005)
    assert manager.is_worker_running("actuation")
    assert _alive_actuation_threads(name) != []  # якорь: поток живой ДО остановки

    _bounded(lambda: manager.stop_all_workers(timeout=2.0), timeout=10.0)

    assert not manager.is_worker_running("actuation")
    assert _alive_actuation_threads(name) == [], "поток actuation пережил stop_all_workers"
    # наблюдаемый эффект остановки: новая цель больше не стреляет
    now = time.time()
    sch.schedule(now + 0.05, now + 0.05, 1, _CallablePayload())
    time.sleep(0.3)
    assert sch.stats()["fired_items"] == 0
    assert sch.pending() == 1


# --- Протокол IActuationScheduler ----------------------------------------------------------------


def test_actuation_scheduler_protocol_is_declared_in_plugins_interfaces() -> None:
    from multiprocess_framework.modules.process_module.plugins import interfaces

    proto = interfaces.IActuationScheduler  # AttributeError пока протокола нет

    for member in ("schedule", "pending", "tick", "stats"):
        assert hasattr(proto, member), f"в IActuationScheduler нет {member}"


def test_actuation_scheduler_protocol_is_exported_from_plugins_package() -> None:
    from multiprocess_framework.modules.process_module import plugins

    assert "IActuationScheduler" in plugins.__all__
    assert plugins.IActuationScheduler is not None


def test_scheduler_object_has_every_member_of_the_protocol() -> None:
    sch = PluginContext(_services()).scheduler

    for member in ("schedule", "pending", "tick", "stats"):
        assert callable(getattr(sch, member, None)), f"у ctx.scheduler нет вызываемого {member}"
