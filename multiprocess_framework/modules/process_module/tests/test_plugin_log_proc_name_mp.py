# -*- coding: utf-8 -*-
"""W1-c (multicam-observability) — имя процесса в строках плагина из настоящего spawn-процесса (слепые тесты).

Purpose: каждая строка, которую плагин пишет через ``ctx.log_info``, в ``messages.log`` процесса несёт
``[<имя процесса>]`` (формат ``%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s``), в том числе
строки из ``configure`` и ``start`` плагина, а не ``[-]``.

Стенд — НАСТОЯЩИЙ дочерний процесс (``multiprocessing.get_context("spawn")`` + ``run_process_function`` +
``GenericProcess``), а не поток: имя процесса в строке лога зависит от того, что видит ребёнок после spawn.
Плагин-зонд ``W1cProbe`` лежит на уровне модуля (spawn импортирует его по имени). Один процесс на модуль
(фикстура ``scope="module"``), три теста читают один файл ``<log_dir>/w1c_child/messages.log``.

Ожидания — циклы с дедлайном 30 с; остановка и ``terminate()`` — в ``finally`` фикстуры.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.plugins import register_plugin
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

__all__ = []

_THIS = "multiprocess_framework.modules.process_module.tests.test_plugin_log_proc_name_mp"
_PROCESS_NAME = "w1c_child"
_GENERIC_PROCESS = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"
_WAIT_S = 30.0
_JOIN_S = 15.0


@register_plugin("w1c_probe", category="processing")
class W1cProbe(ProcessModulePlugin):
    """Зонд: по одной узнаваемой строке в ``configure``, ``start`` и ``shutdown``."""

    name = "w1c_probe"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None:
        ctx.log_info("w1c-configure-line")

    def start(self, ctx: PluginContext) -> None:
        ctx.log_info("w1c-start-line")

    def process(self, items):
        return items

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info("w1c-shutdown-line")


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _wait_for_line(path: Path, needle: str, deadline_s: float, proc: Any) -> bool:
    """Ждать строку ``needle`` в файле; ранний выход, если процесс умер, а строки нет."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if any(needle in line for line in _read_lines(path)):
            return True
        if not proc.is_alive():
            return any(needle in line for line in _read_lines(path))
        time.sleep(0.1)
    return any(needle in line for line in _read_lines(path))


@pytest.fixture(scope="module")
def messages_lines(tmp_path_factory: pytest.TempPathFactory) -> Iterator[list[str]]:
    """Запустить настоящий spawn-процесс, дождаться ``w1c-start-line``, остановить, отдать строки ``messages.log``."""
    log_dir = tmp_path_factory.mktemp("w1c_logs")
    log_file = log_dir / _PROCESS_NAME / "messages.log"

    ctx = multiprocessing.get_context("spawn")
    stop = ctx.Event()
    ready = ctx.Event()
    cfg: dict[str, Any] = {
        "config": {
            "plugins": [{"plugin_class": f"{_THIS}.W1cProbe", "plugin_name": "w1c_probe"}],
            "chain_targets": [],
        },
        "managers": {"logger": {"log_directory": str(log_dir)}},
    }
    bundle = {
        "queues": {"data": ctx.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": ready},
    }
    proc = ctx.Process(
        target=run_process_function,
        args=(_GENERIC_PROCESS, _PROCESS_NAME, stop, bundle, None),
        daemon=True,
        name="w1c-child",
    )
    proc.start()
    try:
        found = _wait_for_line(log_file, "w1c-start-line", _WAIT_S, proc)
        if not found:
            tree = sorted(str(p.relative_to(log_dir)) for p in log_dir.rglob("*"))
            pytest.fail(
                f"STOP: строка w1c-start-line не появилась за {_WAIT_S} с в {log_file}; "
                f"файлы под {log_dir}: {tree}; процесс жив={proc.is_alive()}, exitcode={proc.exitcode}"
            )
        stop.set()
        proc.join(_JOIN_S)
        # shutdown-строка пишется при выходе процесса; даём ей дописаться, если процесс ещё жив
        _wait_for_line(log_file, "w1c-shutdown-line", 5.0, proc)
        yield _read_lines(log_file)
    finally:
        stop.set()
        proc.join(_JOIN_S)
        if proc.is_alive():
            proc.terminate()
            proc.join(5.0)


def test_configure_line_of_plugin_carries_process_name(messages_lines: list[str]) -> None:
    """Строка ``configure`` плагина несёт ``[w1c_child]``, не ``[-]``; такая строка ровно одна."""
    hits = [line for line in messages_lines if "w1c-configure-line" in line]
    assert len(hits) == 1, f"строк с w1c-configure-line: {len(hits)}: {hits}"
    assert "[w1c_child] w1c_probe: w1c-configure-line" in hits[0], hits[0]
    assert not any("[-] w1c_probe" in line for line in messages_lines), [
        line for line in messages_lines if "[-] w1c_probe" in line
    ]


def test_start_line_of_plugin_carries_process_name(messages_lines: list[str]) -> None:
    """Строка ``start`` плагина (шаг 6 ``boot()``) несёт ``[w1c_child]``, не ``[-]``."""
    hits = [line for line in messages_lines if "w1c-start-line" in line]
    assert hits, "строки w1c-start-line нет в messages.log"
    assert any("[w1c_child] w1c_probe: w1c-start-line" in line for line in hits), hits


def test_shutdown_line_of_plugin_carries_process_name(messages_lines: list[str]) -> None:
    """Охранный: строка ``shutdown`` плагина несёт ``[w1c_child]`` (зелёный и до кода)."""
    hits = [line for line in messages_lines if "w1c-shutdown-line" in line]
    assert hits, "строки w1c-shutdown-line нет в messages.log"
    assert any("[w1c_child] w1c_probe: w1c-shutdown-line" in line for line in hits), hits
