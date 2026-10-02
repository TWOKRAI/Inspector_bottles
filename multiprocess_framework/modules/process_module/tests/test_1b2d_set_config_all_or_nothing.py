# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2d (в): generic ``ProcessModulePlugin.cmd_set_config`` — всё или ничего.

Решение владельца (2026-10-02): отказ = ничего не записано. Сегодня ``cmd_set_config``
делает ``setattr`` по полю за полем: отвергнутое поле бросает ``ValidationError`` НАРУЖУ из
команды, а предыдущие поля уже записаны. Ожидание: результат ``{"status": "error", ...}``,
исключение наружу не вылетает, НИ ОДНО из полей не изменилось. Механизм не предполагается.

Плагин — минимальный подкласс с ``_reg`` (самый дешёвый способ: ``configure`` пуст, регистр —
маленький ``SchemaBase`` со связью ``lo <= hi``). Контроль: валидная правка применяется целиком.
Вызовы без блокирующих операций (чистый pydantic), потоки с deadline не нужны.
"""

from __future__ import annotations

from typing import Any

from pydantic import model_validator

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin


class _Pair(SchemaBase):
    lo: int = 1
    hi: int = 10

    @model_validator(mode="after")
    def _lo_le_hi(self) -> "_Pair":
        if self.lo > self.hi:
            raise ValueError(f"lo ({self.lo}) must be <= hi ({self.hi})")
        return self


class _Plugin(ProcessModulePlugin):
    name = "pair_plugin"

    def configure(self, ctx: Any) -> None:  # pragma: no cover — не вызывается тестом
        return None


def _plugin() -> _Plugin:
    plugin = _Plugin()
    plugin._reg = _Pair()
    return plugin


def _call(plugin: _Plugin, data: dict[str, Any]) -> tuple[dict[str, Any] | None, BaseException | None]:
    try:
        return plugin.cmd_set_config(data), None
    except BaseException as exc:  # noqa: BLE001 — исключение наружу и есть предмет проверки
        return None, exc


def test_set_config_cross_field_rejection_changes_nothing() -> None:
    """Post: ``{"hi": 20, "lo": 50}`` (итог нарушает lo <= hi) -> status error, без исключения, lo == 1, hi == 10."""
    plugin = _plugin()
    result, exc = _call(plugin, {"hi": 20, "lo": 50})
    assert exc is None, f"исключение вылетело из команды: {exc!r}"
    assert result is not None and result.get("status") == "error", f"результат: {result!r}"
    assert (plugin._reg.lo, plugin._reg.hi) == (1, 10), f"поля изменились: lo={plugin._reg.lo} hi={plugin._reg.hi}"


def test_set_config_type_rejection_of_second_field_changes_nothing() -> None:
    """Post: ``{"lo": 3, "hi": "x"}`` (второе поле — неверный тип) -> status error, без исключения, поля прежние."""
    plugin = _plugin()
    result, exc = _call(plugin, {"lo": 3, "hi": "x"})
    assert exc is None, f"исключение вылетело из команды: {exc!r}"
    assert result is not None and result.get("status") == "error", f"результат: {result!r}"
    assert (plugin._reg.lo, plugin._reg.hi) == (1, 10), f"поля изменились: lo={plugin._reg.lo} hi={plugin._reg.hi}"


def test_set_config_valid_edit_applies_both_control() -> None:
    """Контроль (зелёный сегодня): валидная правка двух полей -> status ok, оба применены."""
    plugin = _plugin()
    result, exc = _call(plugin, {"lo": 2, "hi": 30})
    assert exc is None, f"исключение: {exc!r}"
    assert result is not None and result.get("status") == "ok", f"результат: {result!r}"
    assert (plugin._reg.lo, plugin._reg.hi) == (2, 30)
