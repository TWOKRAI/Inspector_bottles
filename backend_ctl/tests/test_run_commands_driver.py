# -*- coding: utf-8 -*-
"""Приёмка вслепую (RED, до реализации): команды run-состояния в ``BackendDriver`` и в MCP.

Критерии (из брифа слепого tester'а, лента Ф 2.1):

  1. ``BackendDriver.run_start/run_stop/run_ack/run_status(timeout=...)`` — тонкие обёртки: подмена
     ``request`` драйвера (НЕ ``system_command``) видит ``command == "process.command"``,
     ``targets == ["ProcessManager"]``, ``data == {"cmd": "system.run.<...>"}``; ``process_name``
     в ``data`` нет; ответ возвращается без изменений.
  2. MCP: ``run_start``, ``run_stop``, ``run_ack``, ``run_status`` есть в ``build_registry``;
     классы безопасности READ / WRITE / WRITE / WRITE; регистрация не бросает, дубликата имени нет.

Состояние на ТЕКУЩЕМ коде (до реализации) — какие тесты красные:

  * ВСЕ тесты этого файла красные: ни метода ``run_*`` у драйвера, ни четырёх имён в ``TOOLS`` /
    ``TOOL_SAFETY`` ещё нет (AttributeError / AssertionError про отсутствие имени).
  * Единственные зелёные «контроли» — тесты-проверки самого стенда: ``test_control_system_command_*``
    (подмена ``request`` видит конверт ``system_command`` — стенд рабочий) и
    ``test_control_existing_tool_*`` (регистрация уже существующего инструмента проходит).

Транспорт фейковый: сокетов и процессов нет; всё, что могло бы зависнуть, идёт в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_tools import TOOL_SAFETY, TOOLS, build_registry, call_tool

_CALL_DEADLINE_S = 10.0

#: Литералы контракта: метод драйвера -> имя системной команды ProcessManager.
_RUN_COMMANDS = {
    "run_start": "system.run.start",
    "run_stop": "system.run.stop",
    "run_ack": "system.run.ack",
    "run_status": "system.run.status",
}

#: Литералы контракта: MCP-инструмент -> класс безопасности.
_RUN_TOOL_SAFETY = {
    "run_start": "write",
    "run_stop": "write",
    "run_ack": "write",
    "run_status": "read",
}

#: Ответ-заглушка в форме живого конверта PM. Объект, а не копия: проверяем возврат «как есть» через ``is``.
_REPLY: dict[str, Any] = {
    "type": "response",
    "command": "process.command.response",
    "success": True,
    "result": {"success": True, "state": "running"},
}


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший драйвер валит тест, а не набор."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _driver_with_request(monkeypatch: pytest.MonkeyPatch) -> tuple[BackendDriver, list[tuple[dict, float | None]]]:
    """Драйвер без сокета, у которого подменён ИМЕННО ``request`` (не ``system_command``)."""
    drv = BackendDriver()
    sent: list[tuple[dict, float | None]] = []

    def fake_request(message: dict, timeout: float | None = None) -> dict:
        sent.append((message, timeout))
        return _REPLY

    monkeypatch.setattr(drv, "request", fake_request)
    return drv, sent


# ---------------------------------------------------------------------------
# Критерий 1: обёртки драйвера
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "cmd"), sorted(_RUN_COMMANDS.items()))
def test_run_method_sends_process_command_to_pm_with_cmd(
    monkeypatch: pytest.MonkeyPatch, method: str, cmd: str
) -> None:
    """Одна команда -> одно сообщение: ``process.command`` в ProcessManager с ``data == {"cmd": ...}``."""
    drv, sent = _driver_with_request(monkeypatch)

    _bounded(lambda: getattr(drv, method)(timeout=3.0))

    assert len(sent) == 1, sent
    msg, _timeout = sent[0]
    assert msg["command"] == "process.command", msg
    assert msg["targets"] == ["ProcessManager"], msg
    assert msg["data"] == {"cmd": cmd}, msg


@pytest.mark.parametrize("method", sorted(_RUN_COMMANDS))
def test_run_method_does_not_address_a_process_by_name(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Команда адресована всей системе: ``process_name`` в ``data`` (адрес одного процесса) быть не должно."""
    drv, sent = _driver_with_request(monkeypatch)

    _bounded(lambda: getattr(drv, method)(timeout=3.0))

    assert len(sent) == 1, sent
    assert "process_name" not in sent[0][0]["data"], sent[0][0]


@pytest.mark.parametrize("method", sorted(_RUN_COMMANDS))
def test_run_method_returns_the_reply_unchanged(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Тонкая обёртка: тот же объект ответа, без распаковки и нормализации."""
    drv, _sent = _driver_with_request(monkeypatch)

    res = _bounded(lambda: getattr(drv, method)(timeout=3.0))

    assert res is _REPLY, res


@pytest.mark.parametrize("method", sorted(_RUN_COMMANDS))
def test_run_method_passes_the_timeout_to_the_request(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """``timeout=...`` доезжает до ``request`` (а не теряется на дефолт драйвера)."""
    drv, sent = _driver_with_request(monkeypatch)

    _bounded(lambda: getattr(drv, method)(timeout=7.5))

    assert sent[0][1] == 7.5, sent


def test_control_system_command_reaches_the_patched_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """КОНТРОЛЬ стенда (зелёный уже сейчас): подмена ``request`` видит конверт ``system_command``.

    Без него красные выше могли бы краснеть из-за сломанного шва, а не из-за отсутствия ``run_*``.
    """
    drv, sent = _driver_with_request(monkeypatch)

    res = _bounded(lambda: drv.system_command({"cmd": "system.run.status"}, timeout=3.0))

    assert res is _REPLY
    assert sent[0][0]["command"] == "process.command"
    assert sent[0][0]["targets"] == ["ProcessManager"]
    assert sent[0][0]["data"] == {"cmd": "system.run.status"}


# ---------------------------------------------------------------------------
# Критерий 2: MCP-инструменты
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_RUN_TOOL_SAFETY))
def test_run_tool_is_in_the_registry(name: str) -> None:
    assert name in build_registry(), f"инструмента {name!r} нет в build_registry()"


@pytest.mark.parametrize(("name", "expected"), sorted(_RUN_TOOL_SAFETY.items()))
def test_run_tool_safety_class(name: str, expected: str) -> None:
    """``run_status`` — read; ``run_start``/``run_stop``/``run_ack`` — write (меняют поведение бэкенда)."""
    assert TOOL_SAFETY.get(name) == expected, f"{name}: класс {TOOL_SAFETY.get(name)!r}, ждали {expected!r}"


@pytest.mark.parametrize("name", sorted(_RUN_TOOL_SAFETY))
def test_run_tool_name_is_unique_in_tools(name: str) -> None:
    """Дубликата имени нет: ровно одна запись в ``TOOLS`` (вторая валила бы ``build_registry`` ValueError)."""
    assert [spec.name for spec in TOOLS].count(name) == 1


def test_registration_does_not_raise_with_the_new_tools() -> None:
    """Реестр собирается заново (кэш сброшен) и не бросает; новые имена в нём есть.

    ``build_registry`` — ``lru_cache``: без ``cache_clear`` тест судил бы кэш, собранный ДО правки.
    """
    build_registry.cache_clear()
    registry = build_registry()

    missing = sorted(set(_RUN_TOOL_SAFETY) - set(registry))
    assert not missing, f"после пересборки реестра не хватает инструментов: {missing}"


def test_control_existing_tool_registers_and_is_read() -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): пересборка реестра проходит, ``get_status`` на месте и read."""
    build_registry.cache_clear()
    registry = build_registry()

    assert "get_status" in registry
    assert TOOL_SAFETY["get_status"] == "read"


@pytest.mark.parametrize(
    ("name", "cmd"),
    [
        ("run_start", "system.run.start"),
        ("run_stop", "system.run.stop"),
        ("run_ack", "system.run.ack"),
        ("run_status", "system.run.status"),
    ],
)
def test_run_tool_handler_sends_its_own_system_command(monkeypatch: pytest.MonkeyPatch, name: str, cmd: str) -> None:
    """Настоящие объекты: ``call_tool`` -> обработчик -> настоящий драйвер -> подменённый ``request``.

    Имя инструмента не должно «склеиться» с чужой командой (``run_stop`` не шлёт ``system.run.start``).
    Шов ответа не проверяем (форма вывода MCP — не критерий): только что ушло в ProcessManager.
    """
    drv, sent = _driver_with_request(monkeypatch)

    _bounded(lambda: call_tool(drv, name, {}))

    assert len(sent) == 1, sent
    assert sent[0][0]["command"] == "process.command", sent
    assert sent[0][0]["targets"] == ["ProcessManager"], sent
    assert sent[0][0]["data"] == {"cmd": cmd}, sent
