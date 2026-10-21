# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.9m: исполнитель по имени в ``CommandManager`` (REDS R6, R7).

Написаны независимым тестером ТОЛЬКО по контракту ``plans/lifecycle-stop-ownership/tasks/T1.9m.md``
(D4: ``CommandManager(executors=...)``, ``register_command(executor="<имя>")``) и разделу
«REDS — слепой тестер» ``T1.9m_facts.md``; реализации нет в дереве тестера.

Ожидание до реализации: R6, R7 красные - ``ExecutorManager`` не существует (``ImportError`` внутри
теста) / ``CommandManager`` не знает kwarg ``executors`` и строку в ``executor=``. Новые имена
импортируются ВНУТРИ тестов: каждый тест докладывает свой красный.

WARNING ``CommandManager`` ловит фейк-логгер в слоте ``managers={"logger": fake}`` (образец -
``test_command_executor_fork_acceptance.py``); без слота миксин молчит. Исполнители - настоящие, с
настоящим ``WorkerManager``. Каждый ждущий вызов - с дедлайном.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.worker_module import WorkerManager

# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


class FakeLogger:
    """Слот ``logger``: запоминает записи по уровням."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, message: Any) -> None:
        with self._lock:
            self.records.append((level, str(message() if callable(message) else message)))

    def debug(self, message: Any, **kw: Any) -> None:
        self._add("debug", message)

    def info(self, message: Any, **kw: Any) -> None:
        self._add("info", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self._add("warning", message)

    def error(self, message: Any, **kw: Any) -> None:
        self._add("error", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self._add("critical", message)

    def warnings(self) -> list[str]:
        with self._lock:
            return [m for lvl, m in self.records if lvl == "warning"]


class Adapter:
    """Готовый объект ``OrderedExecutor`` для ``register`` (как адаптеры PM): своё ``.name``."""

    name = "pm-gate"

    def submit(self, action, key, reply, *, inline_if_idle: bool = False) -> bool:
        reply(action())
        return False

    def request_stop(self) -> None:
        return None

    def join_until(self, deadline: float) -> bool:
        return True

    def shutdown(self, deadline: float) -> bool:
        return True


class Env:
    """``WorkerManager`` "t" + ``ExecutorManager`` + ``CommandManager`` с фейк-логгером; уборка."""

    def __init__(self) -> None:
        self.wm = WorkerManager(manager_name="t", process=None)
        assert self.wm.initialize() is True
        self.cm_log = FakeLogger()
        self._managers: list[Any] = []

    def executor_manager(self) -> Any:
        from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

        mgr = ExecutorManager("t_executors", worker_manager=self.wm)
        self._managers.append(mgr)
        assert mgr.initialize() is True
        return mgr

    def command_manager(self, **kwargs: Any) -> CommandManager:
        cm = CommandManager("p", managers={"logger": self.cm_log}, **kwargs)
        self._managers.append(cm)
        assert cm.initialize() is True
        return cm

    def close(self) -> None:
        for mgr in self._managers:
            self._bounded(mgr.shutdown)
        self._bounded(self.wm.shutdown)

    @staticmethod
    def _bounded(fn) -> None:
        t = threading.Thread(target=lambda: _swallow(fn), daemon=True)
        t.start()
        t.join(10.0)


def _swallow(fn) -> None:
    try:
        fn()
    except BaseException:  # noqa: BLE001 - уборка не маскирует провал теста
        pass


@pytest.fixture
def env():
    e = Env()
    yield e
    e.close()


def command_names(cm: CommandManager) -> list[str]:
    return [c.get("key") for c in cm.get_commands()]


# ---------------------------------------------------------------------------
# R6
# ---------------------------------------------------------------------------


def test_register_command_by_name_resolves_executor(env):
    """R6: ``executor="io"`` разрешается в объект менеджера; ``metadata["executor"]`` - имя реестра."""
    from multiprocess_framework.modules.command_module import DEFERRED

    mgr = env.executor_manager()
    cm = env.command_manager(executors=mgr)
    mgr.create("io", {"serial": True})

    seen_threads: list[str] = []

    def handler(data: dict) -> dict:
        seen_threads.append(threading.current_thread().name)
        return {"success": True, "v": 7}

    assert cm.register_command("cmd", handler, executor="io", key_from="process_name") is True
    assert cm.get_command_info("cmd")["metadata"]["executor"] == "io"

    replies: list[Any] = []
    got = threading.Event()

    def reply(result: Any) -> None:
        replies.append(result)
        got.set()

    result = cm.handle_command({"command": "cmd", "data": {"process_name": "p1"}}, reply=reply)

    assert result is DEFERRED
    assert got.wait(5.0), "reply не вызван за 5 с"
    assert replies == [{"success": True, "v": 7}]
    assert len(seen_threads) == 1 and "keyed-io-" in seen_threads[0], seen_threads

    # Зарегистрированный адаптер: метаданные несут имя реестра, а не ``adapter.name``.
    mgr.register("gate", Adapter())
    assert cm.register_command("cmd2", handler, executor="gate", targets="all") is True
    assert cm.get_command_info("cmd2")["metadata"]["executor"] == "gate"


# ---------------------------------------------------------------------------
# R7
# ---------------------------------------------------------------------------


def test_register_command_unknown_name_fails_fast(env):
    """R7: неизвестное имя, отсутствие менеджера и пустое имя - ``False`` + WARNING, команды нет."""
    mgr = env.executor_manager()
    cm = env.command_manager(executors=mgr)

    def handler(data: dict) -> dict:
        return {"success": True}

    assert cm.register_command("cmd", handler, executor="nope", key_from="process_name") is False
    assert cm.get_command_info("cmd") is None
    assert "cmd" not in command_names(cm)
    hits = [w for w in env.cm_log.warnings() if "'nope'" in w and "не найден" in w]
    assert hits, f"нет WARNING с 'nope' и «не найден»: {env.cm_log.warnings()!r}"

    # CM без менеджера исполнителей, имя в executor=.
    env.cm_log.records.clear()
    cm_bare = env.command_manager()
    assert cm_bare.register_command("cmd", handler, executor="io", key_from="process_name") is False
    assert cm_bare.get_command_info("cmd") is None
    hits = [w for w in env.cm_log.warnings() if "без менеджера исполнителей" in w]
    assert hits, f"нет WARNING «без менеджера исполнителей»: {env.cm_log.warnings()!r}"

    # Пустое имя.
    assert cm.register_command("cmd3", handler, executor="", key_from="process_name") is False
    assert cm.get_command_info("cmd3") is None
