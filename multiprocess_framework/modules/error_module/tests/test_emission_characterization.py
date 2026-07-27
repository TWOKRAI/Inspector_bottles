# -*- coding: utf-8 -*-
"""Ф4.2 — характеризация эмиссии ErrorManager ДО слияния развилки.

Зафиксировано ДО правки и прогнано на старом коде (полный override
``ErrorManager.log``), чтобы слияние развилки судилось по поведению, а не по
намерению автора. Vision §4 требует характеризационные тесты перед перестройкой
доставки; здесь они же — страховка от «переписал и не заметил».

Что именно различало два пути (и потому проверяется):
  * severity-путь резолвит ОДИН канал по уровню, а не список каналов скоупа;
  * severity-путь **не спрашивает гейт** ``should_log`` вовсе;
  * DEBUG/INFO уходят родителю и идут по каналам скоупа;
  * ``messages_processed`` растёт на 1 на обеих ветках (в старом коде — через
    инкремент и обратный декремент перед делегированием).

Два места, где поведение меняется НАМЕРЕННО, названы в docstring'ах своих
тестов: отказ канала статусом теперь считается (``channel_refused_records``),
а построчный ``_fallback_log`` на исключении заменён одноразовым
предупреждением базового счётчика.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from ...channel_routing_module.interfaces import IChannel
from ...logger_module.core.log_config import LogLevel, LogScope
from ..core.error_manager import ErrorManager


class _SpyChannel(IChannel):
    """Канал, который можно заставить отказать или бросить."""

    def __init__(self, name: str, *, mode: str = "ok") -> None:
        self._name = name
        self.mode = mode
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.mode == "raise":
            raise RuntimeError("канал сломан")
        if self.mode == "refuse":
            return {"status": "error", "channel": self._name}
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _manager(tmp_path: Path, **overrides: Any) -> ErrorManager:
    config: Dict[str, Any] = {
        "app_name": "char",
        "log_directory": str(tmp_path),
        "default_level": "DEBUG",
        "enable_batching": False,
    }
    config.update(overrides)
    em = ErrorManager(config=config)
    em.initialize()
    return em


def _replace(em: ErrorManager, name: str, mode: str = "ok") -> _SpyChannel:
    """Подменить канал реестра шпионом, сохранив имя (и severity-маршрут)."""
    spy = _SpyChannel(name, mode=mode)
    em._channel_registry.unregister(name)
    em._channel_registry.register(spy)
    return spy


def _messages(spy: _SpyChannel) -> List[str]:
    return [str(rec.get("message", "")) for rec in spy.written]


# ---------------------------------------------------------------------------
# Резолв канала: severity vs scope
# ---------------------------------------------------------------------------


def test_error_goes_to_severity_channel_only(tmp_path: Path) -> None:
    """ERROR уходит в ``errors_file`` и НЕ веером по каналам скоупа."""
    em = _manager(tmp_path)
    try:
        errors = _replace(em, "errors_file")
        critical = _replace(em, "critical_file")

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char")

        assert _messages(errors) == ["ошибка"]
        assert _messages(critical) == []
    finally:
        em.shutdown()


def test_critical_goes_to_critical_channel(tmp_path: Path) -> None:
    """CRITICAL адресуется отдельно от ERROR."""
    em = _manager(tmp_path)
    try:
        errors = _replace(em, "errors_file")
        critical = _replace(em, "critical_file")

        em.log(LogScope.SYSTEM, LogLevel.CRITICAL, "падение", module="char")

        assert _messages(critical) == ["падение"]
        assert _messages(errors) == []
    finally:
        em.shutdown()


def test_warning_without_own_channel_falls_back_to_errors(tmp_path: Path) -> None:
    """WARNING без ``warnings_file`` садится на ``errors_file`` (см. _setup_level_routes)."""
    em = _manager(tmp_path)
    try:
        assert "warnings_file" not in em._channel_registry.names(), "предусловие: своего канала нет"
        errors = _replace(em, "errors_file")

        em.log(LogScope.SYSTEM, LogLevel.WARNING, "предупреждение", module="char")

        assert _messages(errors) == ["предупреждение"]
    finally:
        em.shutdown()


def test_info_uses_scope_channels(tmp_path: Path) -> None:
    """DEBUG/INFO идут родительским путём — по каналам скоупа, а не по severity.

    Скоуп BUSINESS, а не SYSTEM: у SYSTEM порог ``WARNING``, и INFO отсекается
    гейтом раньше, чем дело доходит до резолва каналов. На SYSTEM тест был бы
    зелёным по неверной причине — «канал пуст, потому что запись не дошла».
    """
    em = _manager(tmp_path)
    try:
        errors = _replace(em, "errors_file")
        system = _replace(em, "system_file")

        em.log(LogScope.BUSINESS, LogLevel.INFO, "информация", module="char")

        assert _messages(system) == ["информация"]
        assert _messages(errors) == []
    finally:
        em.shutdown()


def test_severity_path_ignores_scope_gate(tmp_path: Path) -> None:
    """Главное различие путей: severity НЕ спрашивает ``should_log``.

    Скоуп выключен целиком — INFO не проходит, а ERROR проходит. Это поведение
    старого кода, и слияние развилки не имеет права его изменить: гейт скоупа
    не должен уметь заглушить ошибку.
    """
    em = _manager(tmp_path)
    try:
        errors = _replace(em, "errors_file")
        system = _replace(em, "system_file")
        em.config.scopes["SYSTEM"].enabled = False
        em.invalidate_decision_cache()

        em.log(LogScope.SYSTEM, LogLevel.INFO, "заглушённое", module="char")
        em.log(LogScope.SYSTEM, LogLevel.ERROR, "незаглушаемое", module="char")

        assert _messages(system) == [], "гейт скоупа перестал работать для INFO"
        assert _messages(errors) == ["незаглушаемое"], "гейт скоупа заглушил ОШИБКУ"
    finally:
        em.shutdown()


# ---------------------------------------------------------------------------
# Общая часть записи: контекст, tap'ы, счётчики
# ---------------------------------------------------------------------------


def test_severity_record_carries_process_context(tmp_path: Path) -> None:
    """База процесса (Ф0.5) доезжает до severity-пути — то, что теряла развилка."""
    em = _manager(tmp_path)
    try:
        errors = _replace(em, "errors_file")
        em.set_base_context(proc_name="camera_0")
        em.push_context(job="кадр-17")

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char", extra_field=1)

        assert len(errors.written) == 1
        extra = errors.written[0]["extra"]
        assert extra["proc_name"] == "camera_0"
        assert extra["job"] == "кадр-17"
        assert extra["extra_field"] == 1
    finally:
        em.shutdown()


def test_severity_record_reaches_taps(tmp_path: Path) -> None:
    """Tap'ы получают severity-записи (tail не слепнет на главном пути ошибок)."""
    em = _manager(tmp_path)
    try:
        _replace(em, "errors_file")
        tap = _SpyChannel("tap")
        em.add_tap(tap, min_level="DEBUG", name="tap")

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char")

        assert _messages(tap) == ["ошибка"]
    finally:
        em.shutdown()


@pytest.mark.parametrize("level", [LogLevel.ERROR, LogLevel.INFO])
def test_messages_processed_counts_once(tmp_path: Path, level: LogLevel) -> None:
    """Одна запись — один инкремент, на обеих ветках."""
    em = _manager(tmp_path)
    try:
        _replace(em, "errors_file")
        _replace(em, "system_file")
        before = em.stats["messages_processed"]

        em.log(LogScope.SYSTEM, level, "сообщение", module="char")

        assert em.stats["messages_processed"] - before == 1
    finally:
        em.shutdown()


# ---------------------------------------------------------------------------
# Потери на severity-пути
# ---------------------------------------------------------------------------


def test_dead_severity_channel_falls_to_floor(tmp_path: Path) -> None:
    """Канал бросает → запись спасает пол, потеря учтена."""
    em = _manager(tmp_path)
    try:
        _replace(em, "errors_file", mode="raise")

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char")

        assert em.stats["errors_to_floor"] == 1
        assert em.stats["channel_write_errors"] == 1
    finally:
        em.shutdown()


def test_unresolved_severity_channel_falls_to_floor(tmp_path: Path) -> None:
    """Имя severity-канала не резолвится → пол + счётчик «канала нет»."""
    em = _manager(tmp_path)
    try:
        em._channel_registry.unregister("errors_file")
        before = em.stats["unresolved_channel_records"]

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char")

        assert em.stats["errors_to_floor"] == 1
        assert em.stats["unresolved_channel_records"] - before == 1
    finally:
        em.shutdown()


def test_refused_severity_channel_is_counted(tmp_path: Path) -> None:
    """НАМЕРЕННОЕ ИЗМЕНЕНИЕ: отказ канала статусом теперь считается.

    В старом коде ``_write_error_to_channel`` при ``status=error`` уходил в пол,
    **не увеличивая** ``channel_refused_records``: запись была цела, но третий
    класс потери на главном пути ошибок оставался невидимым. После слияния
    severity-путь идёт через общий ``_write_record_to_channels``, который этот
    класс считает. Тест красный до слияния — это ожидаемо и объявлено.
    """
    em = _manager(tmp_path)
    try:
        _replace(em, "errors_file", mode="refuse")

        em.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка", module="char")

        assert em.stats["errors_to_floor"] == 1, "запись обязана уцелеть в полу"
        assert em.stats["channel_refused_records"] == 1, "отказ канала не учтён"
    finally:
        em.shutdown()
