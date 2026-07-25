# -*- coding: utf-8 -*-
"""Тесты boot-порядка процессов по ``depends_on`` (Ф5 3.9).

Три уровня:
  1. ``_compute_boot_waves`` — чистый топосорт (chain/diamond/parallel/cycle/order).
  2. ``_plan_boot_waves`` + ``_create_processes_from_config`` — планирование волн и
     ГЕЙТ readiness: перед волной >0 вызывается ``_wait_processes_ready`` апстримов.
  3. Проброс ``depends_on`` от ``ProcessConfig`` до верхнего уровня ``proc_dict``.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from ..process.process_manager_process import ProcessManagerProcess
from ..topology.blueprint import ProcessConfig


# ── Уровень 1: чистый топосорт _compute_boot_waves ───────────────────────────


class TestComputeBootWaves:
    def test_no_deps_single_wave_original_order(self) -> None:
        waves, cycle = ProcessManagerProcess._compute_boot_waves(["a", "b", "c"], {})
        assert cycle is False
        assert waves == [["a", "b", "c"]]

    def test_chain(self) -> None:
        # c←b←a: три волны по одному
        waves, cycle = ProcessManagerProcess._compute_boot_waves(["a", "b", "c"], {"b": ["a"], "c": ["b"]})
        assert cycle is False
        assert waves == [["a"], ["b"], ["c"]]

    def test_diamond(self) -> None:
        # b,c←a ; d←b,c
        waves, cycle = ProcessManagerProcess._compute_boot_waves(
            ["a", "b", "c", "d"], {"b": ["a"], "c": ["a"], "d": ["b", "c"]}
        )
        assert cycle is False
        assert waves == [["a"], ["b", "c"], ["d"]]

    def test_stable_order_within_wave(self) -> None:
        # порядок внутри волны = исходный ordered_names, не порядок ключей deps_map
        waves, _ = ProcessManagerProcess._compute_boot_waves(["x", "y", "z"], {"z": ["x"], "y": ["x"]})
        assert waves == [["x"], ["y", "z"]]

    def test_cycle_detected(self) -> None:
        waves, cycle = ProcessManagerProcess._compute_boot_waves(["a", "b"], {"a": ["b"], "b": ["a"]})
        assert cycle is True
        assert waves == []


# ── Уровень 2: планирование волн + гейт readiness ────────────────────────────


class _FakeProc:
    def __init__(self, name: str, rec: List[Tuple[str, Any]]) -> None:
        self.name = name
        self._rec = rec
        self._pid: int | None = None

    def start(self) -> None:
        self._rec.append(("start", self.name))
        self._pid = 4321

    def is_alive(self) -> bool:
        return True

    @property
    def pid(self) -> int | None:
        return self._pid


class _FakeRegistry:
    def __init__(self, rec: List[Tuple[str, Any]]) -> None:
        self._rec = rec
        self._procs: dict[str, _FakeProc] = {}

    def create_and_register(self, name: str, class_path: str, config: dict, priority: str) -> _FakeProc:
        proc = _FakeProc(name, self._rec)
        self._procs[name] = proc
        return proc

    def get_process_by_name(self, name: str) -> _FakeProc | None:
        return self._procs.get(name)


class _FakePriority:
    def register_priority(self, *a: Any) -> None: ...
    def apply_priority(self, *a: Any) -> None: ...


def _make_pm(rec: List[Tuple[str, Any]], *, timeout: float = 5.0) -> ProcessManagerProcess:
    """Лёгкий PM без тяжёлого initialize: только атрибуты для boot-пути."""
    pm = object.__new__(ProcessManagerProcess)
    pm._process_configs = {}
    pm.shared_resources = None
    pm._process_registry = _FakeRegistry(rec)  # type: ignore[attr-defined]
    pm._priority = _FakePriority()  # type: ignore[attr-defined]
    pm._mark_instance_started = lambda name: None  # type: ignore[assignment]
    pm._cleanup_process_resources = lambda name: None  # type: ignore[assignment]
    pm._log_info = lambda *a, **k: None  # type: ignore[assignment]
    pm._log_warning = lambda *a, **k: rec.append(("warn", a[0] if a else ""))  # type: ignore[assignment]
    pm._log_error = lambda *a, **k: rec.append(("error", a[0] if a else ""))  # type: ignore[assignment]
    pm.get_config = lambda k: timeout if k == "boot_ready_timeout_s" else None  # type: ignore[assignment]

    def _fake_wait(names: list[str], t: float, reason: str) -> dict[str, bool]:
        rec.append(("wait", tuple(names)))
        return {n: True for n in names}

    pm._wait_processes_ready = _fake_wait  # type: ignore[assignment]
    return pm


def _cfg(class_path: str = "pkg.Mod", depends_on: list[str] | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"class": class_path}
    if depends_on is not None:
        d["depends_on"] = depends_on
    return d


class TestBootGate:
    def test_flat_when_no_deps(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(), "b": _cfg()})
        # ни одного "wait" — одна волна
        assert [e for e in rec if e[0] == "wait"] == []
        assert [e for e in rec if e[0] == "start"] == [("start", "a"), ("start", "b")]

    def test_chain_gates_upstream_before_dependent(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(), "b": _cfg(depends_on=["a"]), "c": _cfg(depends_on=["b"])})
        seq = [e for e in rec if e[0] in ("start", "wait")]
        assert seq == [
            ("start", "a"),
            ("wait", ("a",)),
            ("start", "b"),
            ("wait", ("b",)),
            ("start", "c"),
        ]

    def test_diamond_waits_both_upstreams(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config(
            {
                "a": _cfg(),
                "b": _cfg(depends_on=["a"]),
                "c": _cfg(depends_on=["a"]),
                "d": _cfg(depends_on=["b", "c"]),
            }
        )
        seq = [e for e in rec if e[0] in ("start", "wait")]
        assert seq == [
            ("start", "a"),
            ("wait", ("a",)),
            ("start", "b"),
            ("start", "c"),
            ("wait", ("b", "c")),
            ("start", "d"),
        ]

    def test_flag_off_flat_even_with_deps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FW_DEPENDS_ON_BOOT_ORDER", "0")
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(), "b": _cfg(depends_on=["a"])})
        assert [e for e in rec if e[0] == "wait"] == []
        assert [e for e in rec if e[0] == "start"] == [("start", "a"), ("start", "b")]

    def test_timeout_zero_orders_without_wait(self) -> None:
        # boot_ready_timeout_s=0 → волны сохраняются (порядок), но gate-ожидание не зовётся
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec, timeout=0.0)
        pm._create_processes_from_config({"a": _cfg(), "b": _cfg(depends_on=["a"])})
        assert [e for e in rec if e[0] == "wait"] == []
        assert [e for e in rec if e[0] == "start"] == [("start", "a"), ("start", "b")]

    def test_cycle_falls_back_to_flat(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(depends_on=["b"]), "b": _cfg(depends_on=["a"])})
        assert [e for e in rec if e[0] == "wait"] == []  # плоский фолбэк
        assert any(e[0] == "error" and "цикл" in e[1] for e in rec)
        assert {e[1] for e in rec if e[0] == "start"} == {"a", "b"}

    def test_missing_dep_dropped_with_warning(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(depends_on=["ghost"])})
        assert any(e[0] == "warn" and "ghost" in e[1] for e in rec)
        # единственное валидное ребро отброшено → плоский старт a
        assert [e for e in rec if e[0] == "start"] == [("start", "a")]

    def test_self_dep_dropped_with_warning(self) -> None:
        rec: List[Tuple[str, Any]] = []
        pm = _make_pm(rec)
        pm._create_processes_from_config({"a": _cfg(depends_on=["a"])})
        assert any(e[0] == "warn" and "сам на себя" in e[1] for e in rec)
        assert [e for e in rec if e[0] == "start"] == [("start", "a")]


# ── Уровень 3: проброс depends_on до proc_dict ───────────────────────────────


class TestDependsOnThreading:
    def test_proc_config_threads_to_proc_dict(self) -> None:
        pc = ProcessConfig(process_name="worker", depends_on=["source"])
        _name, proc_dict = pc.as_generic_config().build()
        assert proc_dict.get("depends_on") == ["source"]

    def test_empty_depends_on_absent_from_proc_dict(self) -> None:
        # форму proc_dict не меняем при пустом depends_on
        pc = ProcessConfig(process_name="worker")
        _name, proc_dict = pc.as_generic_config().build()
        assert "depends_on" not in proc_dict
