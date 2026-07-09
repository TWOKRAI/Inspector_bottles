"""Контракт-тесты ``assemble_launcher`` — шов E3 (Task 5.2).

Проверяем Pre/Post контракта из ``launcher/builder.py``: proc_dicts + DI-параметры
оркестратора → сконфигурированный ``SystemLauncher`` (порядок/имена процессов, проброс
orchestrator_class_path/config/stop_timeout, чистота входа, отсутствие спавна).
"""

from __future__ import annotations

import copy

from ..launcher.builder import SpawnBackend, assemble_launcher
from ..launcher.system_launcher import SystemLauncher


def _proc_dicts() -> dict:
    return {
        "gui": {"class": "app.Gui", "priority": "high"},
        "worker": {"class": "app.Worker"},
    }


class TestAssembleLauncher:
    """Post-контракт assemble_launcher."""

    def test_returns_configured_launcher_with_all_processes(self) -> None:
        """Каждая (name, proc_dict) добавлена; порядок и имена сохранены."""
        launcher = assemble_launcher(_proc_dicts())
        assert isinstance(launcher, SystemLauncher)
        assert [name for name, _ in launcher._processes] == ["gui", "worker"]

    def test_orchestrator_di_passed_through(self) -> None:
        """orchestrator_class_path/config/stop_timeout проброшены без изменений."""
        oc = {"initial_state": {"a": 1}}
        launcher = assemble_launcher(
            _proc_dicts(),
            orchestrator_class_path="app.Orch",
            orchestrator_config=oc,
            stop_timeout=9.0,
        )
        assert launcher._orchestrator_class_path == "app.Orch"
        assert launcher._orchestrator_config == oc
        assert launcher._stop_timeout == 9.0

    def test_input_not_mutated(self) -> None:
        """proc_dicts не мутируется (Invariant)."""
        src = _proc_dicts()
        snapshot = copy.deepcopy(src)
        assemble_launcher(src)
        assert src == snapshot

    def test_empty_proc_dicts(self) -> None:
        """Пустой mapping → launcher без процессов (Pre допускает пустой)."""
        launcher = assemble_launcher({})
        assert launcher._processes == []

    def test_spawn_backend_is_protocol(self) -> None:
        """SpawnBackend — runtime-checkable Protocol (задел multi-node)."""

        class _Local:
            def launch(self, launcher: SystemLauncher) -> None: ...

        assert isinstance(_Local(), SpawnBackend)
