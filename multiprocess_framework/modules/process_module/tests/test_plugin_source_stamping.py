# -*- coding: utf-8 -*-
"""Ф2.1 — плагин пишет под своим именем, а не под именем процесса.

План: plans/observability-unified-routing.md, задача 2.1.

Плагины логируют через ``ctx.log_info`` / ``ctx.log_error`` — это bound-методы
процесса, поэтому до Ф2.1 записи десятка плагинов одного процесса были
неразличимы между собой и от записей самого процесса. Штамп ставится в
``PluginContext``, а не на call-site: вызовов ``ctx.log_*`` в Plugins/ сотни, и
их правка в задачу не входит по построению.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
    PluginOrchestrator,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext


class _Services:
    """Минимальный IProcessServices: запоминает (сообщение, kwargs)."""

    def __init__(self, name: str = "vision_process") -> None:
        self.name = name
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def log_info(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("info", message, kwargs))

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("error", message, kwargs))

    @property
    def last_module(self) -> Any:
        return self.calls[-1][2].get("module")


def test_base_context_does_not_stamp() -> None:
    """Базовый контекст принадлежит процессу — его записи остаются процессными.

    Проверяется равенство функции, а не только отсутствие ``module``: обёртка на
    горячем пути без имени была бы лишней ценой на каждой записи плагина.
    Сравнение ``==``, а не ``is``: доступ к bound-методу каждый раз создаёт новый
    объект, но два bound-метода одного ``__self__``/``__func__`` равны, тогда как
    ``functools.partial`` не равен ни одному из них.
    """
    services = _Services()
    ctx = PluginContext(services=services)
    assert ctx.log_info == services.log_info
    ctx.log_info("процессная запись")
    assert services.last_module is None


def test_named_context_stamps_plugin_name() -> None:
    services = _Services()
    ctx = PluginContext(services=services).with_config({}, plugin_name="color_mask")
    ctx.log_info("маска построена")
    assert services.last_module == "color_mask"


def test_named_context_stamps_error_path_too() -> None:
    """log_error — отдельная привязка, отдельный шанс потерять имя."""
    services = _Services()
    ctx = PluginContext(services=services).with_config({}, plugin_name="capture")
    ctx.log_error("камера не отвечает")
    assert services.calls[-1][0] == "error"
    assert services.last_module == "capture"


def test_explicit_module_wins_over_plugin_name() -> None:
    services = _Services()
    ctx = PluginContext(services=services).with_config({}, plugin_name="capture")
    ctx.log_info("кадр", module="capture.hikvision")
    assert services.last_module == "capture.hikvision"


def test_with_config_without_name_keeps_process_identity() -> None:
    """Обратная совместимость: старый вызов ``with_config(cfg)`` не штампует."""
    services = _Services()
    ctx = PluginContext(services=services).with_config({"x": 1})
    ctx.log_info("без имени")
    assert services.last_module is None


def test_two_plugins_of_one_process_are_distinguishable() -> None:
    """Ровно тот случай, ради которого задача существует."""
    services = _Services()
    base = PluginContext(services=services)
    base.with_config({}, plugin_name="capture").log_info("кадр")
    base.with_config({}, plugin_name="color_mask").log_info("маска")
    assert [call[2].get("module") for call in services.calls] == ["capture", "color_mask"]


# ---------------------------------------------------------------------------
# Реальная проводка: имя приходит из pdef оркестратора, а не из теста
# ---------------------------------------------------------------------------


class _StubPlugin:
    """Плагин, который логирует ровно в configure_managers()."""

    def configure_managers(self, ctx: Any) -> None:
        ctx.log_info("плагин сконфигурирован")


def test_orchestrator_passes_plugin_name_from_pdef(monkeypatch: Any) -> None:
    """Тест на фейках выше доказывает контракт ``with_config``; этот — что
    оркестратор его действительно зовёт с именем из определения плагина.

    Без него переименование параметра оставило бы всё зелёным при мёртвом
    штампе в проде.
    """
    services = _Services()
    orch = PluginOrchestrator(services=services, io=None)

    monkeypatch.setattr(orch, "_resolve_plugin_class", lambda path, name: "stub.Plugin")
    monkeypatch.setattr(orch, "_load_plugin", lambda path, name: _StubPlugin())

    orch.load_and_configure_managers([{"plugin_name": "color_mask", "plugin_class": "stub.Plugin"}])

    assert services.calls, "плагин не был сконфигурирован — проверять нечего"
    assert services.last_module == "color_mask"
