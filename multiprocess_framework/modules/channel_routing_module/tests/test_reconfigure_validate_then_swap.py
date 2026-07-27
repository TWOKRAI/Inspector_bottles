# -*- coding: utf-8 -*-
"""R9 — ``reconfigure``: сначала проверить, потом разрушать; сбой пересборки откатывать.

Резидуал R9 (вердикт по Ф0.3, 2026-07-27): ``_close_all_channels()`` стоял ПЕРЕД
разбором нового конфига, разбор жил у наследника внутри ``_rebuild_from_config``.
Любой отвергнутый reload оставлял менеджер с пустым реестром — воспроизведено на
живом логгере: 12 каналов → 0, ``system.log`` 0 байт.

Здесь — опасности самого механизма, а не внешний контракт: два рубежа защищают от
РАЗНОГО (валидация — конфиг не разобрался; откат — разобрался, но пересборка
развалилась), и каждый обязан падать отдельно от другого. Плюс граничные случаи,
которые механизм породил сам: откат без принятого конфига, падение самого отката,
и вопрос «к чему именно откатывает» после серии неудачных reload.

Слом-инъекции, измерено (каждое свойство откатывалось отдельно):
  B1 убрать вызов ``self._validate_config(normalized)`` из ``reconfigure``
     → красные: validation_keeps_registry, validation_keeps_state,
       validation_does_not_touch_channels, rebuild_not_called,
       rollback_target_is_last_accepted (+ тест ошибок)
  B2 сделать ``_rollback_to`` пустым (``return False`` первой строкой)
     → красные: rollback_restores_channels, rollback_target_is_last_accepted,
       rollback_loses_runtime_channel (+ тесты логгера и ошибок)
  B3 не обновлять ``_last_applied_config`` после успешной пересборки
     → красные: rollback_target_is_last_accepted, valid_reconfigure_still_applies
  B4 пробросить исключение из ``_rollback_to`` наружу (снять except)
     → красный: failed_rollback_does_not_raise
  B6 снять проверку ``_UNNORMALIZABLE``
     → красные: non_dict_config_rejected_as_before[42], [строка]

Предсказание по B1 было НЕВЕРНЫМ и записано здесь как есть: ожидалось, что откат
замаскирует снятую валидацию и умрёт один тест. Умерло шесть — потому что для
модельного наследника невалидный конфиг не бросает исключение при пересборке
вовсе (он просто применяется), а у логгера с ошибками слепок для отката до этого
прогона был пуст, то есть второго рубежа у них не было. Второе — настоящий
дефект, найденный именно инъекцией; чинится в ``LoggerCore.__init__``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from ..core.channel_routing_manager import ChannelRoutingManager
from ..interfaces import IChannel


class _Channel(IChannel):
    def __init__(self, name: str) -> None:
        self._name = name
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "mock"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        self.closed = True


class _Manager(ChannelRoutingManager):
    """Наследник с валидацией и пересборкой — модель Logger/Error/Stats.

    Конфиг: ``{"channels": [имена]}``. Невалидным считается имя, начинающееся
    с ``bad_`` (аналог опечатки в значении поля), падение ПЕРЕСБОРКИ моделирует
    имя ``boom_`` — оно проходит валидацию и взрывается при создании канала.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__("R9Manager", config=config)
        self.rebuild_calls: List[Any] = []

    def initialize(self) -> bool:
        result = super().initialize()
        self._build_channels(self._config)
        return result

    def _validate_config(self, config: Dict[str, Any]) -> None:
        for name in config.get("channels", []):
            if str(name).startswith("bad_"):
                raise ValueError(f"неизвестный канал {name}")

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        self.rebuild_calls.append(config)
        self._build_channels(config)

    def _build_channels(self, config: Any) -> None:
        cfg = config if isinstance(config, dict) else {}
        for name in cfg.get("channels", []):
            if str(name).startswith("boom_"):
                raise RuntimeError(f"канал {name} не открылся")
            self.register_channel(_Channel(str(name)))


def _manager(*names: str) -> _Manager:
    mgr = _Manager({"channels": list(names)})
    mgr.initialize()
    return mgr


# ---------------------------------------------------------------------------
# Рубеж 1 — валидация до разрушения
# ---------------------------------------------------------------------------


def test_validation_keeps_registry() -> None:
    """Отвергнутый конфиг не имеет права стоить ни одного канала."""
    mgr = _manager("a", "b")
    try:
        assert mgr.reconfigure({"channels": ["bad_typo"]}) is False
        assert sorted(mgr._channel_registry.names()) == ["a", "b"]
    finally:
        mgr.shutdown()


def test_validation_does_not_touch_channels() -> None:
    """Рубеж 1 отличим от рубежа 2 только тождеством объектов.

    Откат воссоздаёт каналы с теми же именами — по ``names()`` «не разрушали» и
    «разрушили и вернули» выглядят одинаково. Разница видна оператору: при
    откате файловые каналы переоткрываются, а буфер пересоздаётся.
    """
    mgr = _manager("a")
    try:
        channel_before = mgr._channel_registry.get("a")
        mgr.reconfigure({"channels": ["bad_typo"]})

        assert mgr._channel_registry.get("a") is channel_before, "канал пересоздан вместо «не тронут»"
        assert channel_before.closed is False, "канал закрывали на отвергнутом конфиге"
    finally:
        mgr.shutdown()


def test_validation_keeps_state() -> None:
    """Отказ не оставляет менеджера с наполовину применённым конфигом.

    Реестр мог бы уцелеть и при том, что ``self._config`` уже подменён — тогда
    следующий откат или readback показал бы конфиг, которого нет в реальности.
    """
    mgr = _manager("a")
    try:
        mgr.reconfigure({"channels": ["bad_typo"]})
        assert mgr._config == {"channels": ["a"]}
        assert mgr._last_applied_config == {"channels": ["a"]}
    finally:
        mgr.shutdown()


def test_rebuild_not_called_on_invalid_config() -> None:
    """Пересборка не должна даже начинаться: каналы закрываются внутри неё."""
    mgr = _manager("a")
    try:
        mgr.reconfigure({"channels": ["bad_typo"]})
        assert mgr.rebuild_calls == []
    finally:
        mgr.shutdown()


def test_valid_reconfigure_still_applies() -> None:
    """Парная половина: защита не должна держаться на том, что reconfigure сломан."""
    mgr = _manager("a")
    try:
        assert mgr.reconfigure({"channels": ["x", "y"]}) is True
        assert sorted(mgr._channel_registry.names()) == ["x", "y"]
        assert mgr._last_applied_config == {"channels": ["x", "y"]}
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Рубеж 2 — откат при сбое пересборки
# ---------------------------------------------------------------------------


def test_rollback_restores_channels() -> None:
    """Конфиг прошёл валидацию, пересборка взорвалась → каналы возвращаются.

    Это ДРУГОЙ отказ, чем в рубеже 1: здесь реестр уже разрушен к моменту сбоя,
    и уцелеть сам по себе он не может.
    """
    mgr = _manager("a", "b")
    try:
        assert mgr.reconfigure({"channels": ["ok", "boom_fail"]}) is False
        assert sorted(mgr._channel_registry.names()) == ["a", "b"]
    finally:
        mgr.shutdown()


def test_rollback_target_is_last_accepted() -> None:
    """Откат целится в последний ПРИНЯТЫЙ конфиг, а не в последний поданный.

    Сценарий оператора: applied(x) → отвергнут(bad) → сбой(boom). Вернуться
    обязаны к x. Если бы слепок обновлялся на каждой попытке, откат воссоздал бы
    отвергнутый набор — то есть применил бы конфиг, который система только что
    признала негодным.
    """
    mgr = _manager("a")
    try:
        assert mgr.reconfigure({"channels": ["x"]}) is True
        assert mgr.reconfigure({"channels": ["bad_typo"]}) is False
        assert mgr.reconfigure({"channels": ["boom_fail"]}) is False
        assert sorted(mgr._channel_registry.names()) == ["x"]
    finally:
        mgr.shutdown()


def test_rollback_without_accepted_config_reports_and_does_not_raise() -> None:
    """Сбой пересборки, а откатываться не к чему (конфига при создании не было).

    Худший исход механизма — назван явно: reconfigure возвращает False, менеджер
    остаётся без каналов, исключение наружу не летит.
    """
    mgr = _Manager(None)
    mgr.initialize()
    try:
        assert mgr._last_applied_config is None
        assert mgr.reconfigure({"channels": ["boom_fail"]}) is False
        assert mgr._channel_registry.names() == []
    finally:
        mgr.shutdown()


def test_failed_rollback_does_not_raise() -> None:
    """Падение самого отката не должно подменять причину сбоя.

    ``reconfigure`` в этот момент уже возвращает False; исключение из обработчика
    сбоя заменило бы понятное «не смог пересобрать» на «не смог откатиться».
    """
    mgr = _manager("a")
    try:
        # Слепок указывает на конфиг, который сам взрывается при пересборке.
        mgr._last_applied_config = {"channels": ["boom_previous"]}
        assert mgr.reconfigure({"channels": ["boom_fail"]}) is False
        assert mgr._channel_registry.names() == []
    finally:
        mgr.shutdown()


def test_rollback_loses_runtime_channel() -> None:
    """ЗАФИКСИРОВАНО КАК ПОВЕДЕНИЕ ОТКАТА, а не как гарантия обратного.

    Откат восстанавливает КОНФИГ. Канал, добавленный после reconfigure в обход
    конфига (у логгера — ``enable_module_logging``), в слепок не входит и
    пропадает. Тест существует, чтобы это было написано в проверяемом виде: в
    докстринге ``reconfigure`` на него стоит ссылка.
    """
    mgr = _manager("a")
    try:
        mgr.register_channel(_Channel("runtime_added"))
        assert "runtime_added" in mgr._channel_registry.names()

        mgr.reconfigure({"channels": ["boom_fail"]})

        assert sorted(mgr._channel_registry.names()) == ["a"]
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Наследники без валидатора
# ---------------------------------------------------------------------------


def test_base_validate_is_noop() -> None:
    """Наследник без своего ``_validate_config`` (StatsManager, RouterManager)
    не должен получить отказов там, где их раньше не было."""

    class _NoValidator(ChannelRoutingManager):
        def __init__(self) -> None:
            super().__init__("NoValidator", config={"any": "shape"})
            self.rebuilt: List[Any] = []

        def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
            self.rebuilt.append(config)

    mgr = _NoValidator()
    mgr.initialize()
    try:
        assert mgr.reconfigure({"что угодно": ["любой", "мусор"]}) is True
        assert mgr.rebuilt == [{"что угодно": ["любой", "мусор"]}]
    finally:
        mgr.shutdown()


@pytest.mark.parametrize("bad", [None, 42, "строка"])
def test_non_dict_config_rejected_as_before(bad: Any) -> None:
    """Регресс: ранние отказы (None / не-dict) не изменились и до валидации не доходят."""
    mgr = _manager("a")
    try:
        assert mgr.reconfigure(bad) is False
        assert sorted(mgr._channel_registry.names()) == ["a"]
        assert mgr.rebuild_calls == []
    finally:
        mgr.shutdown()
