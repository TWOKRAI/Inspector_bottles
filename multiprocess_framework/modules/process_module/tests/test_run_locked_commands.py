# -*- coding: utf-8 -*-
"""Task 2.7d (system-run-state) — слепые приёмочные тесты «команды плагина заперты, пока система в ``running``».

Контракт (из брифа тестера): плагин в СВОЁМ конфиге перечисляет ``run_locked_commands: [...]`` (внутри ``config:``
записи плагина или плоско в записи). Пока флаг ``run_active`` взведён (= состояние ``running`` и система не гасится),
эти команды отказаны литералом ``{"status": "error", "error": "running", "message": "сначала ОСТАНОВИТЬ"}``; в любом
другом состоянии работают; команды вне списка ведут себя как раньше. Флаг PM — ``ProcessManagerProcess._run_active``
(``RunFlag``); ребёнок видит его атрибутом ``_run_active``, плагин — ``ctx.services._run_active``.

Тесты 2-6 гоняют настоящие объекты: ``PluginOrchestrator`` + ``CommandManager`` + ``MockProcessServices``;
команды вызываются только через ``cm.handle_command``.
Тест 7 — проводка реестр -> ``Process`` kwargs -> ``run_process_function``.

Решения тестера (ASSUMPTION): см. отчёт; в тексте помечены ASSUMPTION.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.process_manager_module.core.run_flag import RunFlag
from multiprocess_framework.modules.process_manager_module.tests.test_run_commands import make_run_pm
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_run_locked_commands"
_JOIN_S = 20.0
_REFUSAL = {"status": "error", "error": "running", "message": "сначала ОСТАНОВИТЬ"}


def _in_daemon(fn, deadline_s: float = _JOIN_S) -> Any:
    """Выполнить ``fn`` в daemon-потоке с дедлайном; исключение потока пробрасывается, результат возвращается."""
    box: dict[str, Any] = {}

    def go() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    th = threading.Thread(target=go, daemon=True, name="run-locked-scenario")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


# --------------------------------------------------------------------------- #
# 1. PM: флаг run_active следует за состоянием
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_run_active_flag_follows_run_state(run_gate: bool) -> None:
    """Флаг есть при любом ``run_gate``; ready -> clear; START -> set; STOP -> clear уже в ``stopping``;
    settled -> ready, clear; START, потеря готовности -> ``fault``, clear; ack -> clear."""
    pm = make_run_pm(run_gate, boot=False)
    flag = pm._run_active
    assert flag is not None
    assert isinstance(flag, RunFlag)
    assert flag.is_set() is False, "после создания"

    pm._run_apply("settled", ready=True)
    assert pm._run_state == "ready"
    assert flag.is_set() is False, "ready"

    assert pm._cmd_system_run_start()["success"] is True
    assert pm._run_state == "running"
    assert flag.is_set() is True, "после START"

    pm._run_apply("stop")
    assert pm._run_state == "stopping"
    assert flag.is_set() is False, "уже в stopping"

    pm._run_apply("settled", ready=True)
    assert pm._run_state == "ready"
    assert flag.is_set() is False, "после settled"

    assert pm._cmd_system_run_start()["success"] is True
    assert flag.is_set() is True, "второй START"
    pm._run_apply("tick", ready=False)
    assert pm._run_state == "fault"
    assert flag.is_set() is False, "после fault"

    # Ack через автомат: остановку в аварии ставит такт монитора, голый ``_run_apply("tick")`` её
    # не запускает, и команда ack отказала бы ``fault_stopping`` при любом коде флага (правка лида).
    pm._run_apply("ack", stop_done=True)
    assert pm._run_state == "not_ready"
    assert flag.is_set() is False, "после ack"


# --------------------------------------------------------------------------- #
# Харнесс плагина (настоящие объекты)
# --------------------------------------------------------------------------- #


class GuardPlugin(ProcessModulePlugin):
    """Двойник плагина: две команды со счётчиками вызовов."""

    name = "guard"
    category = "processing"
    commands = {"release_device": "cmd_release_device", "get_status": "cmd_get_status"}

    def __init__(self) -> None:
        super().__init__()
        self.release_calls = 0
        self.status_calls = 0

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items

    def cmd_release_device(self, data: dict) -> dict:
        self.release_calls += 1
        return {"status": "ok", "released": True}

    def cmd_get_status(self, data: dict) -> dict:
        self.status_calls += 1
        return {"status": "ok", "busy": False}


class _Rig:
    def __init__(self, orch: PluginOrchestrator, services: MockProcessServices, cm: CommandManager, flag: RunFlag):
        self.orch = orch
        self.services = services
        self.cm = cm
        self.flag = flag

    @property
    def plugin(self) -> GuardPlugin:
        return self.orch.plugins[0]

    def call(self, command: str) -> Any:
        return self.cm.handle_command({"command": command, "data": {}})

    def error_lines(self) -> list[str]:
        return [str(rec["msg"]) for rec in self.services.logs if rec["level"] == "ERROR"]


def _rig(
    config: dict[str, Any] | None,
    *,
    flag_set_at_boot: bool = False,
    with_flag: bool = True,
    flat: bool = False,
) -> _Rig:
    """Собрать и загрузить плагин: ``config`` — содержимое ``config:`` записи (``None`` — без ключа)."""
    services = MockProcessServices(name="run_locked")
    cm = CommandManager("run_locked_cm")
    cm.initialize()
    services.command_manager = cm
    flag = RunFlag(flag_set_at_boot)
    if with_flag:
        services._run_active = flag
    pdef: dict[str, Any] = {"plugin_class": f"{_THIS}.GuardPlugin", "plugin_name": "guard"}
    if config is not None:
        if flat:
            pdef.update(config)
        else:
            pdef["config"] = config
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers([pdef])
    orch.boot()
    return _Rig(orch, services, cm, flag)


# --------------------------------------------------------------------------- #
# 2-3. Запертая команда отказана при взведённом флаге; флаг читается на каждом вызове
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_locked_command_refused_only_while_flag_set_boot_clear() -> None:
    """boot при СНЯТОМ флаге: set -> отказ литералом, счётчик 0; get_status работает; clear -> команда работает."""

    def scenario() -> None:
        rig = _rig({"run_locked_commands": ["release_device"]})
        rig.flag.set()
        assert rig.call("release_device") == _REFUSAL
        assert rig.plugin.release_calls == 0

        status = rig.call("get_status")
        assert status["status"] == "ok", status
        assert rig.plugin.status_calls == 1

        rig.flag.clear()
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.plugin.release_calls == 1

    _in_daemon(scenario)


@pytest.mark.timeout(60)
def test_locked_command_follows_flag_after_boot_with_flag_set() -> None:
    """boot при ВЗВЕДЁННОМ флаге: clear -> работает (счётчик 1); set -> отказ, счётчик остаётся 1."""

    def scenario() -> None:
        rig = _rig({"run_locked_commands": ["release_device"]}, flag_set_at_boot=True)
        rig.flag.clear()
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.plugin.release_calls == 1

        rig.flag.set()
        assert rig.call("release_device") == _REFUSAL
        assert rig.plugin.release_calls == 1

    _in_daemon(scenario)


@pytest.mark.timeout(60)
def test_locked_commands_key_flat_in_plugin_entry() -> None:
    """Плоская запись (ключ на верхнем уровне определения плагина): тот же отказ при взведённом флаге."""

    def scenario() -> None:
        rig = _rig({"run_locked_commands": ["release_device"]}, flat=True)
        rig.flag.set()
        assert rig.call("release_device") == _REFUSAL
        assert rig.plugin.release_calls == 0

    _in_daemon(scenario)


# --------------------------------------------------------------------------- #
# 4. Без ключа — как раньше (зелёный контроль на базе)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_no_key_flag_set_command_runs() -> None:
    """Ключа нет, флаг взведён: ``release_device`` работает."""

    def scenario() -> None:
        rig = _rig(None)
        rig.flag.set()
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.plugin.release_calls == 1

    _in_daemon(scenario)


# --------------------------------------------------------------------------- #
# 5. Негодный ключ — одна ERROR-строка
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("bad", ["release_device", [1]], ids=["string", "list_of_int"])
def test_invalid_key_logs_one_error_and_does_not_lock(bad: Any) -> None:
    """Ключ — строка или список не строк: ровно одна ERROR-строка ``run_locked_commands негоден``;
    при взведённом флаге команда работает (запирание не включается)."""

    def scenario() -> None:
        rig = _rig({"run_locked_commands": bad})
        errors = rig.error_lines()
        assert len(errors) == 1, errors
        assert "run_locked_commands негоден" in errors[0], errors[0]

        rig.flag.set()
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.plugin.release_calls == 1

    _in_daemon(scenario)


@pytest.mark.timeout(60)
def test_unknown_names_logged_truncated_once_known_still_locked() -> None:
    """Имена вне ``commands`` плагина: одна ERROR-строка, имя режется до 40 символов, показано не больше пяти
    имён (``n4`` есть, ``n5`` нет), хвост — ``(+2)``; известное имя ``release_device`` при этом заперто."""

    def scenario() -> None:
        names = ["release_device", "a" * 60, "n1", "n2", "n3", "n4", "n5", "n6"]
        rig = _rig({"run_locked_commands": names})
        errors = rig.error_lines()
        assert len(errors) == 1, errors
        line = errors[0]
        assert "a" * 40 in line, line
        assert "a" * 41 not in line, line
        assert "n4" in line, line
        assert "n5" not in line, line
        assert "(+2)" in line, line

        rig.flag.set()
        assert rig.call("release_device") == _REFUSAL
        assert rig.plugin.release_calls == 0

    _in_daemon(scenario)


# --------------------------------------------------------------------------- #
# 6. Нет атрибута _run_active у services (зелёный контроль на базе)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_services_without_run_active_command_runs() -> None:
    """У ``services`` нет ``_run_active``, ключ задан: ``release_device`` работает (запирать нечем — не падаем)."""

    def scenario() -> None:
        rig = _rig({"run_locked_commands": ["release_device"]}, with_flag=False)
        assert not hasattr(rig.services, "_run_active")
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.plugin.release_calls == 1

    _in_daemon(scenario)


# --------------------------------------------------------------------------- #
# 7. Проводка: ProcessRegistry -> Process kwargs -> run_process_function
# --------------------------------------------------------------------------- #

_QUICK_CHILD = "multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers.QuickChild"
_RUNNER_MOD = "multiprocess_framework.modules.process_manager_module.runner.process_runner"


class _RecordingProcess:
    """Заглушка ``multiprocessing.Process``: запоминает kwargs каждого построенного экземпляра."""

    built: list["_RecordingProcess"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs_seen = kwargs.get("kwargs", {})
        self.name = kwargs.get("name")
        self.pid = None
        _RecordingProcess.built.append(self)

    def is_alive(self) -> bool:
        return False


def _build_twice(registry: Any) -> list[_RecordingProcess]:
    """Старт и рестарт: два ``create_and_register`` с одним именем; возвращает построенные ``Process``."""
    from multiprocess_framework.modules.process_manager_module.core import process_registry as registry_mod

    _RecordingProcess.built = []
    with patch.object(registry_mod, "Process", _RecordingProcess):
        first = registry.create_and_register("run_active_child", _QUICK_CHILD, {}, "normal")
        second = registry.create_and_register("run_active_child", _QUICK_CHILD, {}, "normal")
    assert first is not None and second is not None
    return list(_RecordingProcess.built)


@pytest.mark.timeout(60)
def test_registry_hands_run_active_to_every_incarnation() -> None:
    """``ProcessRegistry(run_active=flag)``: kwargs ``Process`` и первого старта, и рестарта несут ТОТ ЖЕ флаг."""
    from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry

    flag = RunFlag()
    built = _in_daemon(lambda: _build_twice(ProcessRegistry(logger=None, run_active=flag)))
    assert len(built) == 2, built
    for proc in built:
        assert proc.kwargs_seen.get("run_active") is flag, proc.kwargs_seen


@pytest.mark.timeout(60)
def test_registry_without_run_active_passes_none() -> None:
    """Реестр без ``run_active``: kwarg ``run_active`` в ``Process`` есть и равен ``None``."""
    from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry

    built = _in_daemon(lambda: _build_twice(ProcessRegistry(logger=None)))
    assert len(built) == 2, built
    for proc in built:
        assert "run_active" in proc.kwargs_seen, proc.kwargs_seen
        assert proc.kwargs_seen["run_active"] is None, proc.kwargs_seen


class _RunnerProbe:
    """Процесс-двойник для ``run_process_function``: запоминает экземпляр."""

    instances: list["_RunnerProbe"] = []

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name
        _RunnerProbe.instances.append(self)

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        pass

    def should_stop(self) -> bool:
        return True


def _run_runner(**kwargs: Any) -> _RunnerProbe:
    import multiprocessing

    from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function

    _RunnerProbe.instances = []
    bundle = {"queues": {}, "config": {}, "custom": {}}

    def go() -> None:
        with patch(f"{_RUNNER_MOD}._load_process_class", return_value=_RunnerProbe):
            run_process_function("fake.Probe", "run_active_probe", multiprocessing.Event(), bundle, **kwargs)

    _in_daemon(go)
    assert len(_RunnerProbe.instances) == 1, _RunnerProbe.instances
    return _RunnerProbe.instances[0]


@pytest.mark.timeout(60)
def test_runner_sets_run_active_attribute() -> None:
    """``run_process_function(..., run_active=flag)`` -> у экземпляра ``_run_active is flag``."""
    flag = RunFlag()
    instance = _run_runner(run_active=flag)
    assert instance._run_active is flag


@pytest.mark.timeout(60)
def test_runner_without_run_active_leaves_no_attribute() -> None:
    """``run_active=None`` -> атрибута ``_run_active`` у экземпляра нет."""
    instance = _run_runner(run_active=None)
    assert not hasattr(instance, "_run_active")
