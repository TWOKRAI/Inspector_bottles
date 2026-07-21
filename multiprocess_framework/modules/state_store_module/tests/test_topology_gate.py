# -*- coding: utf-8 -*-
"""Гейт топологии: записи в processes.<name>.* для снятого процесса отклоняются.

Юнит покрывает решение фильтра и его границы fail-open. Что он НЕ доказывает —
что гейт реально проведён в живой системе: это проверяет
``backend_ctl/tests/test_switch_honest_state_live.py::test_switch_state_matches_os``
(парой ON/OFF по ``FW_STATE_TOPOLOGY_GATE``).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
    StateStoreManager,
)
from multiprocess_framework.modules.state_store_module.middleware.topology_gate import (
    TopologyGateMiddleware,
)


def _gate(known: set[str], rejected: list | None = None) -> TopologyGateMiddleware:
    hook = (lambda path, name: rejected.append((path, name))) if rejected is not None else None
    return TopologyGateMiddleware(lambda name: name in known, on_reject=hook)


def _allowed(gate: TopologyGateMiddleware, path: str) -> bool:
    proceed, _ = gate.before_set(path, 1, "src", {})
    return proceed


# --- решение фильтра ---------------------------------------------------------


def test_known_process_passes() -> None:
    assert _allowed(_gate({"camera_0"}), "processes.camera_0.state.fps")


def test_unknown_process_rejected() -> None:
    assert not _allowed(_gate({"camera_0"}), "processes.preprocessor.state.fps")


def test_reject_hook_gets_path_and_name() -> None:
    rejected: list = []
    _allowed(_gate({"camera_0"}, rejected), "processes.stitcher.workers.x")
    assert rejected == [("processes.stitcher.workers.x", "stitcher")]


def test_merge_gated_same_as_set() -> None:
    proceed, _ = _gate({"camera_0"}).before_merge("processes.stitcher", {"a": 1}, "src", {})
    assert not proceed


def test_delete_never_gated() -> None:
    """Снос поддерева несуществующего процесса — это и есть штатная уборка."""
    assert _gate({"camera_0"}).before_delete("processes.stitcher", "src", {}) == (True,)


# --- границы fail-open -------------------------------------------------------


def test_path_outside_processes_passes() -> None:
    assert _allowed(_gate(set()), "wires.a->b.status")


def test_root_write_passes() -> None:
    """Запись в сам корень (bootstrap дерева) — без имени процесса, не гейтится."""
    assert _allowed(_gate(set()), "processes")


def test_provider_exception_fails_open() -> None:
    def _boom(_name: str) -> bool:
        raise RuntimeError("PSR недоступен")

    proceed, _ = TopologyGateMiddleware(_boom).before_set("processes.x.y", 1, "s", {})
    assert proceed


# --- context при отказе (Task 2 — гейт называет себя, ADR-SS-019 follow-up) --
#
# Конвенция общая с ThrottleMiddleware ("throttled") / ValidationMiddleware
# ("validation"): context["rejection_reason"] называет middleware, отклонивший
# запись, вместо безымянного fallback'а state_store_manager.py
# (``context.get("rejection_reason", "middleware")``).


def test_reject_sets_rejection_reason_and_process_name_before_set() -> None:
    context: dict = {}
    proceed, _ = _gate({"camera_0"}).before_set("processes.stitcher.state.fps", 1, "src", context)

    assert proceed is False
    assert context["rejection_reason"] == "topology_gate"
    assert context["rejected_process"] == "stitcher"


def test_reject_sets_rejection_reason_and_process_name_before_merge() -> None:
    context: dict = {}
    proceed, _ = _gate({"camera_0"}).before_merge("processes.stitcher", {"a": 1}, "src", context)

    assert proceed is False
    assert context["rejection_reason"] == "topology_gate"
    assert context["rejected_process"] == "stitcher"


def test_no_rejection_reason_when_known_process_passes() -> None:
    """Зеркало test_throttle.py::TestRejectionContext.test_no_rejection_reason_when_passed."""
    context: dict = {}
    proceed, _ = _gate({"camera_0"}).before_set("processes.camera_0.state.fps", 1, "src", context)

    assert proceed is True
    assert "rejection_reason" not in context
    assert "rejected_process" not in context


# --- fail-open границы не сломаны context'ом отказа --------------------------


def test_no_rejection_reason_for_path_outside_processes() -> None:
    context: dict = {}
    proceed, _ = _gate(set()).before_set("wires.a->b.status", 1, "src", context)

    assert proceed is True
    assert "rejection_reason" not in context


def test_no_rejection_reason_for_root_write() -> None:
    context: dict = {}
    proceed, _ = _gate(set()).before_set("processes", 1, "src", context)

    assert proceed is True
    assert "rejection_reason" not in context


def test_no_rejection_reason_when_provider_raises() -> None:
    def _boom(_name: str) -> bool:
        raise RuntimeError("PSR недоступен")

    context: dict = {}
    proceed, _ = TopologyGateMiddleware(_boom).before_set("processes.x.y", 1, "s", context)

    assert proceed is True
    assert "rejection_reason" not in context


# --- сквозь StateStoreManager ------------------------------------------------


def test_rejected_write_does_not_create_node() -> None:
    """Ровно та гонка: поздний state.set не должен воскресить снятый процесс."""
    mgr = StateStoreManager(router=None, initial_state={"processes": {}}, auto_register_ipc=False)
    mgr.use(_gate({"camera_0"}))

    res = mgr.handle_state_set({"data": {"path": "processes.stitcher.state.fps", "value": 23.3, "source": "stitcher"}})

    assert res is not None and res.get("status") == "rejected"
    subtree = mgr.handle_state_get_subtree({"data": {"path": "processes"}})
    assert "stitcher" not in (subtree.get("value") or {})
