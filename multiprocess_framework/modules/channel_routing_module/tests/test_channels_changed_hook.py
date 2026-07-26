# -*- coding: utf-8 -*-
"""Ф0.8 — протокол хука ``_on_channels_changed`` (АВТОРСКИЕ тесты).

Семантику кэша решений проверяет независимый тестировщик на стороне логгера.
Здесь — про сам хук: он живёт в базе и его контракт легко испортить незаметно,
потому что «лишний вызов» ничего не ломает видимо.

Опасности:
  1. Хук дёргается при НЕУДАЧНОМ toggle. Тогда «ничего не произошло» выглядит
     как событие; наследник сбрасывает кэш на пустом месте, и профилактика
     превращается в постоянную потерю кэша при опечатке в имени канала.
  2. Хук НЕ дёргается на одном из путей смены состава. Профилактика,
     закрывающая два пути из трёх, хуже отсутствующей — она создаёт
     ощущение защищённости.
  3. Наследник без кэша (статистика) обязан переживать хук молча: база зовёт
     его у всех.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core.channel_routing_manager import ChannelRoutingManager
from ..interfaces import IChannel


class _Channel(IChannel):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success"}

    def close(self) -> None:
        return None


class _CountingManager(ChannelRoutingManager):
    """Считает вызовы хука; умеет пересоздать канал с именем ``known``."""

    def __init__(self) -> None:
        super().__init__(manager_name="Счётчик")
        self.hook_calls: List[str] = []

    def _recreate_channel(self, name: str) -> bool:
        if name != "known":
            return False
        self.register_channel(_Channel(name))
        return True

    def _on_channels_changed(self) -> None:
        self.hook_calls.append("changed")


def test_hook_fires_once_on_successful_disable() -> None:
    mgr = _CountingManager()
    mgr.register_channel(_Channel("known"))

    assert mgr.set_sink_enabled("known", False) is True
    assert mgr.hook_calls == ["changed"]


def test_hook_fires_once_on_successful_enable() -> None:
    mgr = _CountingManager()

    assert mgr.set_sink_enabled("known", True) is True
    assert mgr.hook_calls == ["changed"]


def test_hook_silent_on_failed_disable() -> None:
    """Снятие несуществующего канала — не событие.

    Иначе опечатка оператора в имени канала стоила бы наследнику полного
    сброса кэша: цена ошибки не должна платиться системой, которая ничего
    не сделала.
    """
    mgr = _CountingManager()
    assert mgr.set_sink_enabled("нет_такого", False) is False
    assert mgr.hook_calls == []


def test_hook_silent_on_failed_enable() -> None:
    """Включение имени, которого нет в конфиге, тоже ничего не поменяло."""
    mgr = _CountingManager()
    assert mgr.set_sink_enabled("unknown", True) is False
    assert mgr.hook_calls == []


def test_base_hook_is_a_silent_noop() -> None:
    """Наследник без кэша (напр. статистика) обязан пережить хук молча.

    База зовёт хук у ВСЕХ наследников, включая тех, кому нечего сбрасывать.
    Базовая реализация обязана быть безопасным no-op, а не ``NotImplementedError``.
    """

    class _Plain(ChannelRoutingManager):
        def __init__(self) -> None:
            super().__init__(manager_name="БезКэша")

        def _recreate_channel(self, name: str) -> bool:
            self.register_channel(_Channel(name))
            return True

    mgr = _Plain()
    assert mgr.set_sink_enabled("any", True) is True
    assert mgr.set_sink_enabled("any", False) is True  # не бросило — этого достаточно
