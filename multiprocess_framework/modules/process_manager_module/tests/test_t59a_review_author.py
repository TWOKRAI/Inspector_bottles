"""Авторские тесты Task 5.9a по ревью кода (итерация 1).

1. Граница модели доступности ключей — ХАРАКТЕРИЗАЦИОННЫЙ тест (фиксирует известную
   дыру, не одобряет её). Валидатор считает «ключ живёт до перезаписи», а рантайм
   теряет его, когда плагин возвращает СВЕЖИЙ dict (``line_filter``, ``center_crop``,
   ``stitcher``, ``renderer_compositor``: ``plugin_runner`` переносит только системные
   поля). Валидатор этого не видит. Вопрос модели — к CTO (OPEN_QUESTIONS 2026-10-03,
   решение при приёмке фазы), см. ADR-PM-052 в ``process_module/DECISIONS.md``.
   Когда решение будет принято и модель изменится, этот тест ОБЯЗАН покраснеть —
   тогда его литерал ``== []`` переписывается под новое решение.

2. Разбор адреса провода: процессы ``proc`` и ``proc.a`` (имя с точкой). Провод на
   ``proc.a.<плагин>.frame`` не должен покрывать вход процесса ``proc``.
"""

from __future__ import annotations

import pytest

from ...process_manager_module.topology.blueprint import SystemBlueprint
from ...process_module.plugins.base import ProcessModulePlugin
from ...process_module.plugins.port import Port
from ...process_module.plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(saved)


class _FrameSource(ProcessModulePlugin):
    name = "frame_source"
    category = "source"
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _KeepsFrame(ProcessModulePlugin):
    """Берёт frame, отдаёт frame (как blob_detector)."""

    name = "keeps_frame"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _FreshDictLike(ProcessModulePlugin):
    """Декларирует только ``mask``; в рантайме такой плагин (line_filter и др.) вернул бы свежий dict."""

    name = "fresh_dict_like"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
    outputs = [Port(name="mask", dtype="image/gray", shape="(H, W)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _NeedsFrame(ProcessModulePlugin):
    name = "needs_frame"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


def _register(*classes: type[ProcessModulePlugin]) -> None:
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _plugins(*names: str) -> list[dict]:
    return [{"plugin_name": n, "plugin_class": ""} for n in names]


def test_model_boundary_fresh_dict_plugin_in_the_middle_is_invisible_to_check() -> None:
    """ХАРАКТЕРИЗАЦИЯ известной дыры (ADR-PM-052), не одобрение.

    proc = [keeps_frame, fresh_dict_like, needs_frame], провод кладёт ``frame`` только на
    узел 0. В рантайме средний плагин, вернув свежий dict, сбросил бы ``frame`` до
    ``needs_frame``; валидатор по имени ключа видит ``frame`` живым -> ``check() == []``.
    """
    _register(_FrameSource, _KeepsFrame, _FreshDictLike, _NeedsFrame)
    bp = SystemBlueprint.model_validate(
        {
            "name": "boundary",
            "processes": [
                {"process_name": "cam", "plugins": _plugins("frame_source")},
                {"process_name": "proc", "plugins": _plugins("keeps_frame", "fresh_dict_like", "needs_frame")},
            ],
            "wires": [{"source": "cam.frame_source.frame", "target": "proc.keeps_frame.frame"}],
        }
    )
    assert bp.check() == []


def test_dotted_process_name_wire_does_not_cover_the_shorter_named_process() -> None:
    """Процессы ``proc`` (без провода) и ``proc.a`` (с проводом): ошибка ровно у ``proc.needs_frame.frame``."""
    _register(_FrameSource, _NeedsFrame)
    bp = SystemBlueprint.model_validate(
        {
            "name": "dotted",
            "processes": [
                {"process_name": "cam", "plugins": _plugins("frame_source")},
                {"process_name": "proc", "plugins": _plugins("needs_frame")},
                {"process_name": "proc.a", "plugins": _plugins("needs_frame")},
            ],
            "wires": [{"source": "cam.frame_source.frame", "target": "proc.a.needs_frame.frame"}],
        }
    )
    errors = bp.check()
    assert len(errors) == 1, errors
    assert "'proc.needs_frame.frame'" in errors[0], errors[0]
