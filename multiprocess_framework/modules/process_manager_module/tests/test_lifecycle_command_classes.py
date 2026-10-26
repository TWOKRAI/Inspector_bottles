# -*- coding: utf-8 -*-
"""Task 1.9b (ревью р.1 п.4) — таблица классов команд (D2) привязана к тестам: настоящий ``CommandManager``.

Класс команды задаёт её РЕГИСТРАЦИЯ (``executor=``, ``key_from=``, ``targets=``), поэтому метаданные читаются у
настоящего менеджера команд настоящего PM после ``initialize()`` (настоящий ``ExecutorManager``, без двойников
``register_command``: фейк глотает ``**kwargs`` и не видит ни одной ошибки в таблице). Дети не порождаются.
Ожидаемые значения — литералы из таблицы D2 (``plans/lifecycle-stop-ownership/tasks/T1.9b.md``), не из кода.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from ...command_module import CommandManager
from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess

LIFECYCLE = "pm-lifecycle-submit"
GATE = "pm-transition-gate"

#: (команда, исполнитель, key_from, targets) — классы L и T из D2, 13 строк.
LT_TABLE = [
    ("process.create", LIFECYCLE, "process_name", None),
    ("process.start", LIFECYCLE, "process_name", None),
    ("process.stop", LIFECYCLE, "process_name", None),
    ("process.restart", LIFECYCLE, "process_name", None),
    ("topology.apply", LIFECYCLE, None, "all"),
    ("wire.setup", LIFECYCLE, None, "all"),
    ("wire.teardown", LIFECYCLE, None, "all"),
    ("process.relay", GATE, "target_process", None),
    ("process.pause", GATE, "process_name", None),
    ("process.resume", GATE, "process_name", None),
    ("telemetry.broadcast", GATE, None, "all"),
    ("observability.tail.subscribe_all", GATE, None, "all"),
    ("observability.tail.unsubscribe_all", GATE, None, "all"),
]

#: Классы R и S встроенных команд PM: никогда не исполнитель (``system.shutdown`` — S, остальные — R).
NO_EXECUTOR = [
    "process.list",
    "process.status",
    "system.stats",
    "supervision.status",
    "topology.get",
    "topology.diff",
    "wire.status",
    "system.shutdown",
]


@pytest.fixture(scope="module")
def real_pm():
    """Настоящий PM после ``initialize()`` (дети не заданы), закрытие — в daemon-потоке с дедлайном."""
    pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0})
    pm.attach_stop_budget(stop_budget(1.0))
    box: dict[str, Any] = {}

    def init() -> None:
        box["ok"] = pm.initialize()

    th = threading.Thread(target=init, daemon=True, name="classes-pm-initialize")
    th.start()
    th.join(60.0)
    assert not th.is_alive() and box.get("ok") is True, f"PM.initialize() не удался: {box}"
    try:
        yield pm
    finally:
        closer = threading.Thread(target=pm.shutdown, daemon=True, name="classes-pm-shutdown")
        closer.start()
        closer.join(30.0)


def _metadata(command_manager: Any, name: str) -> dict:
    info = command_manager.get_command_info(name)
    assert info is not None, f"команда '{name}' не зарегистрирована"
    return info["metadata"]


@pytest.mark.parametrize(("name", "executor", "key_from", "targets"), LT_TABLE, ids=[row[0] for row in LT_TABLE])
def test_lt_command_registration_matches_class_table(
    real_pm: ProcessManagerProcess, name: str, executor: str, key_from: str | None, targets: str | None
) -> None:
    """Каждая из 13 команд L/T зарегистрирована с исполнителем и ключом из таблицы D2."""
    metadata = _metadata(real_pm.command_manager, name)

    assert metadata.get("executor") == executor, f"{name}: executor={metadata.get('executor')!r}, ожидался {executor!r}"
    assert metadata.get("key_from") == key_from, f"{name}: key_from={metadata.get('key_from')!r}"
    assert metadata.get("targets") == targets, f"{name}: targets={metadata.get('targets')!r}"


@pytest.mark.parametrize("name", NO_EXECUTOR)
def test_read_and_system_commands_have_no_executor(real_pm: ProcessManagerProcess, name: str) -> None:
    """Классы R и S (``system.shutdown``) — без исполнителя, ключа и целей."""
    metadata = _metadata(real_pm.command_manager, name)

    assert "executor" not in metadata, f"{name}: исполнитель не должен быть задан: {metadata.get('executor')!r}"
    assert "key_from" not in metadata and "targets" not in metadata, f"{name}: key_from/targets без исполнителя"


def test_exactly_thirteen_commands_carry_an_executor(real_pm: ProcessManagerProcess) -> None:
    """Исполнитель есть ровно у 13 команд из таблицы: лишняя или потерянная запись краснеет здесь."""
    with_executor = sorted(
        info["key"] for info in real_pm.command_manager.get_commands() if "executor" in (info.get("metadata") or {})
    )

    assert with_executor == sorted(row[0] for row in LT_TABLE)


def test_prototype_registers_recipe_activate_as_lifecycle_class(
    real_pm: ProcessManagerProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``multiprocess_prototype/orchestrator.py`` (D2): ``recipe.activate`` — класс L (``pm-lifecycle-submit``,
    ``targets="all"``); остальные ``recipe.*`` — без исполнителя. Настоящий ``CommandManager`` с настоящим
    ``ExecutorManager`` PM; сервис рецептов подменён заглушкой с тремя обработчиками."""
    from multiprocess_prototype import orchestrator as proto

    def handler(data: Any = None, **kwargs: Any) -> dict:
        return {"success": True}

    service = SimpleNamespace(
        handlers=lambda: {"recipe.activate": handler, "recipe.list": handler, "recipe.get": handler}
    )
    monkeypatch.setattr(proto, "build_recipe_service", lambda pm, path: service)
    command_manager = CommandManager("classes-proto-cm", executors=real_pm.executor_manager)
    app = proto.ProcessManagerProcessApp.__new__(proto.ProcessManagerProcessApp)
    app.command_manager = command_manager
    app.get_config = lambda key, default=None: "manifest.yaml" if key == "manifest_path" else default
    monkeypatch.setattr(proto.ProcessManagerProcessApp, "_register_service_commands", lambda self: None)

    app._register_builtin_commands()

    activate = _metadata(command_manager, "recipe.activate")
    assert activate.get("executor") == LIFECYCLE
    assert activate.get("targets") == "all"
    assert "key_from" not in activate
    for other in ("recipe.list", "recipe.get"):
        assert "executor" not in _metadata(command_manager, other), f"{other} не должен быть в исполнителе"
