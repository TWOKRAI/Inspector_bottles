# -*- coding: utf-8 -*-
"""Страж trace_id, применённый к ЖИВЫМ текстам плагина (тест АВТОРА, Ф1.4).

Приёмочный тест тестера проверяет две вещи: что ``trace_id`` уезжает полем в
двух названных точках, и что переиспользуемый страж существует и краснеет на
подсунутом нарушителе. Между ними остаётся щель: **страж, который никто не
зовёт, — мёртвый код**, и он останется зелёным, даже если завтра кто-то вклеит
идентификатор в текст.

Здесь страж применяется к текстам, которые плагин РЕАЛЬНО произвёл на прогоне —
ко всем сразу, а не к двум заранее известным полям. Это и делает его стражем
против БУДУЩЕЙ регрессии: новая точка записи попадает под проверку сама, без
правки теста.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from multiprocess_framework.modules.logger_module.core.trace_id_guard import (
    assert_no_bare_trace_id,
    find_bare_trace_id,
)

from Plugins.control.robot_control.plugin import RobotControlPlugin

_TRACE_ID = "0123456789abcdef0123456789abcdef"


class _Ctx:
    """Двойник PluginContext — форма как в соседних тестах плагина."""

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.registers = None
        self.command_manager = None
        self.process_name = "inspector"
        self.plugin_name = "robot_control"
        self.texts: List[str] = []
        self.records: List[Dict[str, Any]] = []

    def flight_dump(self, reason: str = "", /, **fields: Any) -> bool:
        self.texts.append(reason)
        self.records.append({"reason": reason, **fields})
        return True

    def write_document(self, kind: str, summary: str = "", /, **fields: Any) -> bool:
        self.texts.extend([kind, summary])
        self.records.append({"kind": kind, "summary": summary, **fields})
        return True

    def write_event(
        self, kind: str, summary: str = "", /, *, unit: Any = None, decisive: bool = False, **fields: Any
    ) -> bool:
        self.texts.extend([kind, summary])
        self.records.append({"kind": kind, "summary": summary, **fields})
        return True

    def log_info(self, message: str, **kwargs: Any) -> None:
        self.texts.append(message)

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.texts.append(message)


def _unit(area: int) -> dict:
    return {
        "frame": np.zeros((64, 64, 3), dtype=np.uint8),
        "detections": [{"bbox": [10, 10, 50, 50], "center": [30, 30], "area": area}],
        "trace_id": _TRACE_ID,
    }


@pytest.fixture
def driven_plugin():
    ctx = _Ctx()
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    plugin._reg.min_defect_area = 100
    # Прогоняем ОБА фронта (pass→reject и reject→pass): точки записи у них разные,
    # и проверять только один значило бы охранять половину.
    plugin.process([_unit(area=900)])
    plugin.process([_unit(area=10)])
    plugin.process([_unit(area=900)])
    return ctx


class TestGuardIsAppliedToRealPluginTexts:
    def test_no_emitted_text_carries_a_bare_trace_id(self, driven_plugin) -> None:
        ctx = driven_plugin
        assert ctx.texts, "плагин не произвёл ни одного текста — тест смотрел бы в пустоту"

        for text in ctx.texts:
            assert_no_bare_trace_id(text, where="Plugins/control/robot_control/plugin.py")

    def test_trace_id_is_present_as_a_field_somewhere(self, driven_plugin) -> None:
        """Пара к предыдущему: «текст чист» обязано соседствовать с «поле есть».

        Без этой половины требование выполнялось бы удалением ``trace_id``
        отовсюду — идентификатор исчез бы, тест позеленел, а корреляцию
        разбирать стало бы нечем.
        """
        ctx = driven_plugin
        carried = [rec for rec in ctx.records if rec.get("trace_id") == _TRACE_ID]
        assert carried, f"trace_id не приехал структурным полем ни в одной записи: {ctx.records!r}"


class TestGuardItselfDiscriminates:
    """Страж обязан отличать нарушителя от похожего на него текста."""

    def test_flags_a_bare_trace_id(self) -> None:
        with pytest.raises(AssertionError):
            assert_no_bare_trace_id(f"деталь отбракована {_TRACE_ID}")

    def test_passes_a_clean_text(self) -> None:
        assert_no_bare_trace_id("деталь отбракована, площадь дефекта 900")

    def test_does_not_flag_a_longer_hex_run(self) -> None:
        """sha-256 (64 hex) — не идентификатор корреляции.

        Без границ в регулярке страж срабатывал бы на любой подстроке длинного
        hex и краснел бы на дайджестах — ложная тревога, от которой стража
        отключают целиком.
        """
        assert find_bare_trace_id("a" * 64) is None

    def test_does_not_flag_a_shorter_run(self) -> None:
        assert find_bare_trace_id("deadbeef") is None
