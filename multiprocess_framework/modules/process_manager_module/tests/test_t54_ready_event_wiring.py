# -*- coding: utf-8 -*-
"""Task 5.4 — проводка ``system_ready_event`` PM -> ProcessRegistry -> ребёнок.

Независимые acceptance-тесты (слепой тестер, до реализации). Источник контракта —
раздел «Task 5.4» phase-5.md:

* ``run_process_function(..., *, system_ready_event=None)`` — keyword-only;
* ``ProcessRegistry`` отдаёт событие через ``Process(kwargs={"system_ready_event": ...})``,
  НЕ позиционно и НЕ в bundle custom;
* runner кладёт событие в атрибут экземпляра ``_sources_ready_event`` (до ``run()``),
  НЕ через ``attach_ready_event``; событие только читается, взводит его один PM.

Решения тестера (зафиксированы в отчёте):

* Имя kwarg конструктора ``ProcessRegistry(system_ready_event=...)`` — ДОГАДКА по аналогии
  с ``system_stop_event`` (спека называет только «аргумент ProcessRegistry рядом с
  system_stop_event»). Это единственный угаданный символ; на нём стоят все тесты ниже,
  кроме runner-ных и контроля.
* «Настоящий spawn» = реальный путь ``ProcessRegistry.create_and_register(...)`` +
  ``Process.start()`` (spawn на Windows) с дочерним классом ``PrerollChild`` из этого
  модуля (грузится по dotted-path, как ``QuickChild`` в ``_no_orphans_helpers``).
  ``PrerollChild`` ведёт себя как ``ProcessModule``: ``attach_ready_event`` запоминает
  СВОЁ событие, а в конце ``run()`` взводит его. Поэтому, если бы runner передал
  system-событие в ``attach_ready_event``, ребёнок сам взвёл бы его и тест «ни один
  ребёнок не зовёт set()» покраснел. Кадры производит НАСТОЯЩИЙ ``SourceProducer`` с
  ``ready_event=self._sources_ready_event``; счёт кадров — размер файла (по байту на
  кадр) в каталоге из env ``T54_DIR`` (дочерний процесс наследует окружение).
* PM -> реестр проверяем на границе конструктора: ``_create_components`` с замоканным
  ``ProcessRegistry`` — реальный PM не поднимаем (цена и недетерминизм).
"""

from __future__ import annotations

import inspect
import multiprocessing
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ..core import process_registry as registry_mod
from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import ProcessManagerProcess
from ..runner.process_runner import run_process_function

_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_t54_ready_event_wiring"
CHILD_CLASS_PATH = f"{_THIS}.PrerollChild"
QUICK_CHILD_CLASS_PATH = "multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers.QuickChild"

_SPAWN_DEADLINE_S = 30.0


# ---------------------------------------------------------------------------
# Дочерний класс для настоящего spawn
# ---------------------------------------------------------------------------


class _FramePlugin:
    """Source-плагин: каждый produce() дописывает байт в файл кадров."""

    is_source = True

    def __init__(self, path: str) -> None:
        self.name = "t54_frames"
        self._path = path

    def produce(self) -> list:
        with open(self._path, "ab") as fh:
            fh.write(b"x")
        return []


class PrerollChild:
    """Процесс-ребёнок: настоящий SourceProducer за ``_sources_ready_event`` runner'а.

    Марки пишутся в ``marks.txt``: ``has_event=True|False`` (что увидел run()),
    ``SET_SEEN`` (его поток увидел ``is_set()``), ``WARN:<текст>`` (preroll-предупреждение).
    """

    def __init__(self, name: str, shared_resources, config) -> None:
        self.name = name
        self._dir = Path(os.environ["T54_DIR"])
        self._own_ready = None
        self._stop = threading.Event()

    def _mark(self, text: str) -> None:
        with open(self._dir / "marks.txt", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def initialize(self) -> bool:
        return True

    def attach_ready_event(self, event) -> None:
        # Как ProcessModule: запоминаем СВОЁ событие готовности, взведём в конце run().
        self._own_ready = event

    def run(self) -> None:
        from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer

        ev = getattr(self, "_sources_ready_event", None)
        self._mark(f"has_event={ev is not None}")
        producer = SourceProducer(
            plugin=_FramePlugin(str(self._dir / "frames.bin")),
            shm_middleware=None,
            send_fn=lambda target, msg: None,
            chain_targets=[],
            target_fps=50.0,
            node_name=self.name,
            ready_event=ev,
            log_warning=lambda m: self._mark("WARN:" + m),
        )
        threading.Thread(
            target=producer.run_loop, args=(self._stop, threading.Event()), daemon=True, name="t54-producer"
        ).start()
        if ev is not None:
            threading.Thread(target=self._watch, args=(ev,), daemon=True, name="t54-watch").start()
        if self._own_ready is not None:
            self._own_ready.set()  # готовность объявляет сам процесс — в конце run()

    def _watch(self, ev) -> None:
        while not self._stop.is_set():
            if ev.is_set():
                self._mark("SET_SEEN")
                return
            time.sleep(0.01)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        self._stop.set()

    def shutdown(self) -> None:
        self._stop.set()


class _Handle:
    def __init__(self, registry, process, sys_event, workdir: Path) -> None:
        self.registry = registry
        self.process = process
        self.sys_event = sys_event
        self.dir = workdir

    @property
    def frames(self) -> int:
        path = self.dir / "frames.bin"
        return path.stat().st_size if path.exists() else 0

    @property
    def marks(self) -> list[str]:
        path = self.dir / "marks.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def wait(self, predicate, deadline_s: float) -> bool:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()


@pytest.fixture
def spawned_child(tmp_path, monkeypatch):
    """Настоящий spawn через ProcessRegistry; ждём САМОГО ребёнка (его own ready), не sleep."""
    monkeypatch.setenv("T54_DIR", str(tmp_path))
    sys_event = multiprocessing.Event()
    registry = ProcessRegistry(logger=None, system_ready_event=sys_event)
    process = registry.create_and_register("t54_child", CHILD_CLASS_PATH, {}, "normal")
    assert process is not None, "create_and_register вернул None"
    handle = _Handle(registry, process, sys_event, tmp_path)
    try:
        process.start()
        own_ready = registry.get_ready_event("t54_child")
        assert own_ready is not None
        assert own_ready.wait(_SPAWN_DEADLINE_S), (
            f"ребёнок не объявил готовность за {_SPAWN_DEADLINE_S} с "
            f"(alive={process.is_alive()}, exitcode={process.exitcode}, marks={handle.marks})"
        )
        yield handle
    finally:
        try:
            registry.stop_all(timeout=5.0)
        finally:
            if process.is_alive():
                process.kill()
            process.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Настоящий spawn: то же событие, preroll держит кадры до set() родителя
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_real_spawn_child_gets_the_event_and_produces_no_frames_before_set(spawned_child) -> None:
    time.sleep(0.6)  # >= 100 мс (сетка Windows) после готовности ребёнка: кадров всё ещё нет
    assert "has_event=True" in spawned_child.marks, spawned_child.marks
    assert spawned_child.frames == 0, f"{spawned_child.frames} кадров до set() родителя"


@pytest.mark.timeout(120)
def test_real_spawn_parent_set_is_seen_by_child_and_frames_start(spawned_child) -> None:
    time.sleep(0.3)
    assert spawned_child.frames == 0
    spawned_child.sys_event.set()
    assert spawned_child.wait(lambda: "SET_SEEN" in spawned_child.marks, 5.0), (
        f"ребёнок не увидел is_set() после set() родителя: {spawned_child.marks}"
    )
    assert spawned_child.wait(lambda: spawned_child.frames >= 3, 5.0), (
        f"после set() кадры не пошли: frames={spawned_child.frames}"
    )
    assert not any(m.startswith("WARN:") for m in spawned_child.marks), spawned_child.marks


@pytest.mark.timeout(120)
def test_real_spawn_child_reached_ready_but_never_sets_the_system_event(spawned_child) -> None:
    # Ребёнок УЖЕ объявил свою готовность (fixture ждёт её); системное событие — нет.
    time.sleep(0.6)
    assert not spawned_child.sys_event.is_set(), "системное событие взведено ребёнком/runner'ом, а не PM"
    own = spawned_child.registry.get_ready_event("t54_child")
    assert own is not None and own.is_set(), "контроль: собственное событие готовности ребёнка не взведено"
    assert own is not spawned_child.sys_event


# ---------------------------------------------------------------------------
# ProcessRegistry: событие едет kwargs, не позиционно и не в bundle
# ---------------------------------------------------------------------------


class _RecordingProcess:
    """Заглушка ``multiprocessing.Process``: запоминает, как её построил реестр."""

    last: "_RecordingProcess | None" = None

    def __init__(self, *args, **kwargs) -> None:
        self.args_seen = kwargs.get("args", ())
        self.kwargs_seen = kwargs.get("kwargs", {})
        self.name = kwargs.get("name")
        self.pid = None
        _RecordingProcess.last = self

    def is_alive(self) -> bool:
        return False


def _capture_process_ctor(registry: ProcessRegistry) -> _RecordingProcess:
    _RecordingProcess.last = None
    with patch.object(registry_mod, "Process", _RecordingProcess):
        created = registry.create_and_register("t54_cap", QUICK_CHILD_CLASS_PATH, {}, "normal")
    assert created is not None
    assert _RecordingProcess.last is not None
    return _RecordingProcess.last


def test_registry_passes_the_event_in_process_kwargs() -> None:
    ev = multiprocessing.Event()
    rec = _capture_process_ctor(ProcessRegistry(logger=None, system_ready_event=ev))
    assert rec.kwargs_seen.get("system_ready_event") is ev, rec.kwargs_seen


def test_registry_does_not_pass_the_event_positionally() -> None:
    ev = multiprocessing.Event()
    rec = _capture_process_ctor(ProcessRegistry(logger=None, system_ready_event=ev))
    assert all(arg is not ev for arg in rec.args_seen), "событие уехало в позиционные args (шестой — new_session)"


def test_registry_does_not_put_the_event_into_bundle_custom() -> None:
    ev = multiprocessing.Event()
    rec = _capture_process_ctor(ProcessRegistry(logger=None, system_ready_event=ev))
    bundles = [a for a in rec.args_seen if isinstance(a, dict) and "custom" in a]
    assert bundles, "bundle не найден среди args"
    custom = bundles[0]["custom"]
    assert "system_ready_event" not in custom
    assert all(v is not ev for v in custom.values())


def test_registry_without_event_still_hands_parent_pid_control() -> None:
    """КОНТРОЛЬ (проходит и до реализации): соседние kwargs и чистый bundle на месте."""
    rec = _capture_process_ctor(ProcessRegistry(logger=None))
    assert rec.kwargs_seen.get("parent_pid") == os.getpid()
    assert "exit_report" in rec.kwargs_seen
    bundle = next(a for a in rec.args_seen if isinstance(a, dict) and "custom" in a)
    assert "system_ready_event" not in bundle["custom"]


# ---------------------------------------------------------------------------
# PM -> ProcessRegistry: тот самый self._system_ready_event
# ---------------------------------------------------------------------------


def test_process_manager_hands_its_system_ready_event_to_the_registry() -> None:
    ev = multiprocessing.Event()
    srm = MagicMock()
    pdata = MagicMock()
    pdata.custom = {"stop_event": multiprocessing.Event(), "system_ready_event": ev}
    srm.get_process_data.return_value = pdata
    pm_mod = "multiprocess_framework.modules.process_manager_module.process.process_manager_process"
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pm.name = "ProcessManager"
        pm.shared_resources = srm
        pm.config = {}
        pm._console_manager = None
        pm.config_handler = None
        with (
            patch(f"{pm_mod}.ProcessRegistry") as reg_cls,
            patch(f"{pm_mod}.ProcessPriority"),
            patch(f"{pm_mod}.ProcessStatusMonitor"),
            patch(f"{pm_mod}.ProcessMonitor"),
            patch(f"{pm_mod}.QueueRegistry"),
        ):
            pm._create_components()
    assert reg_cls.call_args.kwargs.get("system_ready_event") is ev, reg_cls.call_args


# ---------------------------------------------------------------------------
# run_process_function: keyword-only параметр, атрибут экземпляра, не attach
# ---------------------------------------------------------------------------


def test_run_process_function_event_param_is_keyword_only() -> None:
    params = inspect.signature(run_process_function).parameters
    assert "system_ready_event" in params
    assert params["system_ready_event"].kind is inspect.Parameter.KEYWORD_ONLY


def test_run_process_function_positional_event_raises_typeerror_control() -> None:
    """КОНТРОЛЬ (проходит и до реализации): девятый позиционный аргумент недопустим."""
    stop = multiprocessing.Event()
    stop.set()
    with pytest.raises(TypeError):
        run_process_function(
            "nonexistent_module.BadClass",
            "t54",
            stop,
            None,
            None,
            False,
            None,
            None,
            multiprocessing.Event(),
        )


class _RunnerProbe:
    """Фиксирует, что runner дал экземпляру к моменту run() и через attach_ready_event."""

    attach_calls: list = []
    at_run: list = []

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def attach_ready_event(self, event) -> None:
        _RunnerProbe.attach_calls.append(event)

    def run(self) -> None:
        _RunnerProbe.at_run.append(getattr(self, "_sources_ready_event", "MISSING"))

    def should_stop(self) -> bool:
        return True


def _run_probe(system_event, own_ready) -> None:
    _RunnerProbe.attach_calls = []
    _RunnerProbe.at_run = []
    bundle = {"queues": {}, "config": {}, "custom": {"ready_event": own_ready}}
    runner_mod = "multiprocess_framework.modules.process_manager_module.runner.process_runner"

    def _go() -> None:
        with patch(f"{runner_mod}._load_process_class", return_value=_RunnerProbe):
            run_process_function("fake.Probe", "t54", multiprocessing.Event(), bundle, system_ready_event=system_event)

    thread = threading.Thread(target=_go, daemon=True, name="t54-runner")
    thread.start()
    thread.join(timeout=20.0)
    assert not thread.is_alive(), "run_process_function не завершился за 20 с"


def test_runner_sets_sources_ready_event_attribute_before_run() -> None:
    ev = multiprocessing.Event()
    _run_probe(ev, multiprocessing.Event())
    assert _RunnerProbe.at_run == [ev], _RunnerProbe.at_run


def test_runner_does_not_hand_the_system_event_to_attach_ready_event() -> None:
    ev = multiprocessing.Event()
    own = multiprocessing.Event()
    _run_probe(ev, own)
    assert _RunnerProbe.attach_calls == [own], _RunnerProbe.attach_calls


def test_runner_never_sets_the_system_event() -> None:
    ev = multiprocessing.Event()
    _run_probe(ev, multiprocessing.Event())
    assert _RunnerProbe.at_run == [ev]  # предпосылка: runner событие получил
    assert not ev.is_set()
