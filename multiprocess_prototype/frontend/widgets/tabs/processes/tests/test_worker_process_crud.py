# -*- coding: utf-8 -*-
"""Тесты Фазы C (processes-workers-runtime): presenter CRUD воркеров и процессов.

Проверяет: персист в топологию (TopologyRepositoryStore.save) + live-IPC через
WorkerBridge (fake command_sender), protected-guard, синтетический message_processor.
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import (
    DEFAULT_MAIN_WORKER,
    ProcessesPresenter,
)

from ._helpers import make_processes_services


class _FakeSender:
    """Записывает отправленные IPC-команды (CommandSender-совместимый)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def send_command(self, target: str, command: str, args: dict[str, Any] | None = None) -> None:
        self.calls.append((target, command, args or {}))


class _FakeTopologyBridge:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def hot_remove_process(self, name: str) -> bool:
        self.removed.append(name)
        return True


def _make_presenter() -> tuple[ProcessesPresenter, _FakeSender, _FakeTopologyBridge]:
    services = make_processes_services(use_holder=True)  # реальный store с save()
    sender = _FakeSender()
    bridge = _FakeTopologyBridge()
    presenter = ProcessesPresenter(services, command_sender=sender, topology_bridge=bridge)
    return presenter, sender, bridge


def _workers_in_topology(presenter: ProcessesPresenter, process_name: str) -> list[str]:
    proc = presenter._find_domain_process(process_name)
    return [w.worker_name for w in proc.workers] if proc else []


# ====================================================================== #
#  get_workers — синтетический message_processor                        #
# ====================================================================== #


class TestGetWorkers:
    def test_synthetic_main_worker_when_empty(self) -> None:
        presenter, _s, _b = _make_presenter()
        workers = presenter.get_workers("camera_0")
        assert len(workers) == 1
        assert workers[0]["worker_name"] == DEFAULT_MAIN_WORKER
        assert workers[0]["protected"] is True

    def test_workers_are_dicts(self) -> None:
        """GUI получает dict, не SchemaBase (dict at boundary для GUI)."""
        presenter, _s, _b = _make_presenter()
        presenter.add_worker("camera_0", worker_name="grabber", priority="REALTIME")
        workers = presenter.get_workers("camera_0")
        assert all(isinstance(w, dict) for w in workers)
        names = [w["worker_name"] for w in workers]
        assert DEFAULT_MAIN_WORKER in names
        assert "grabber" in names


# ====================================================================== #
#  add_worker                                                           #
# ====================================================================== #


class TestAddWorker:
    def test_add_persists_and_sends_ipc(self) -> None:
        presenter, sender, _b = _make_presenter()
        ok = presenter.add_worker("camera_0", worker_name="grabber", priority="REALTIME", target_interval_ms=33)
        assert ok is True
        # Персист в топологию
        assert "grabber" in _workers_in_topology(presenter, "camera_0")
        # Live-IPC
        assert len(sender.calls) == 1
        target, command, data = sender.calls[0]
        assert target == "camera_0"
        assert command == "worker.create"
        assert data["worker_name"] == "grabber"
        assert data["priority"] == "REALTIME"
        assert data["target_interval_ms"] == 33

    def test_add_duplicate_rejected(self) -> None:
        presenter, sender, _b = _make_presenter()
        presenter.add_worker("camera_0", worker_name="grabber")
        ok = presenter.add_worker("camera_0", worker_name="grabber")
        assert ok is False
        assert _workers_in_topology(presenter, "camera_0").count("grabber") == 1

    def test_cannot_add_message_processor(self) -> None:
        presenter, _s, _b = _make_presenter()
        ok = presenter.add_worker("camera_0", worker_name=DEFAULT_MAIN_WORKER)
        assert ok is False

    def test_empty_name_rejected(self) -> None:
        presenter, _s, _b = _make_presenter()
        assert presenter.add_worker("camera_0", worker_name="   ") is False


# ====================================================================== #
#  remove_worker                                                        #
# ====================================================================== #


class TestRemoveWorker:
    def test_remove_persists_and_sends_ipc(self) -> None:
        presenter, sender, _b = _make_presenter()
        presenter.add_worker("camera_0", worker_name="grabber")
        sender.calls.clear()
        ok = presenter.remove_worker("camera_0", "grabber")
        assert ok is True
        assert "grabber" not in _workers_in_topology(presenter, "camera_0")
        assert sender.calls == [("camera_0", "worker.remove", {"worker_name": "grabber"})]

    def test_cannot_remove_protected_main(self) -> None:
        presenter, sender, _b = _make_presenter()
        ok = presenter.remove_worker("camera_0", DEFAULT_MAIN_WORKER)
        assert ok is False
        assert sender.calls == []


# ====================================================================== #
#  update_worker                                                        #
# ====================================================================== #


class TestUpdateWorker:
    def test_update_priority_persists_and_sends_ipc(self) -> None:
        presenter, sender, _b = _make_presenter()
        presenter.add_worker("camera_0", worker_name="grabber", priority="NORMAL")
        sender.calls.clear()
        ok = presenter.update_worker("camera_0", "grabber", priority="BATCH", target_interval_ms=200)
        assert ok is True
        proc = presenter._find_domain_process("camera_0")
        spec = next(w for w in proc.workers if w.worker_name == "grabber")
        assert spec.priority == "BATCH"
        assert spec.target_interval_ms == 200
        assert sender.calls[0][1] == "worker.update"

    def test_cannot_update_protected(self) -> None:
        presenter, _s, _b = _make_presenter()
        assert presenter.update_worker("camera_0", DEFAULT_MAIN_WORKER, priority="BATCH") is False

    def test_update_no_fields_returns_false(self) -> None:
        presenter, _s, _b = _make_presenter()
        presenter.add_worker("camera_0", worker_name="grabber")
        assert presenter.update_worker("camera_0", "grabber") is False


# ====================================================================== #
#  create / delete process                                             #
# ====================================================================== #


class TestProcessCrud:
    def test_create_process_persists(self) -> None:
        presenter, _s, _b = _make_presenter()
        ok = presenter.create_process("new_proc", category="processing")
        assert ok is True
        names = presenter.get_process_names()
        assert "new_proc" in names

    def test_create_duplicate_rejected(self) -> None:
        presenter, _s, _b = _make_presenter()
        assert presenter.create_process("camera_0") is False

    def test_create_empty_name_rejected(self) -> None:
        presenter, _s, _b = _make_presenter()
        assert presenter.create_process("  ") is False

    def test_delete_process_persists_and_hot_removes(self) -> None:
        presenter, _s, bridge = _make_presenter()
        ok = presenter.delete_process("processor")
        assert ok is True
        assert "processor" not in presenter.get_process_names()
        assert bridge.removed == ["processor"]

    def test_delete_missing_returns_false(self) -> None:
        presenter, _s, _b = _make_presenter()
        assert presenter.delete_process("ghost") is False
