# -*- coding: utf-8 -*-
"""Ф0.6 — внутренние опасности подъёма control-plane в базу (АВТОРСКИЕ тесты).

Контрактную половину пишет независимый тестировщик. Этот файл — про то, что
видно только автору подъёма: что именно ломается, если базовый метод получил
не тот наследник, если хук наследника соврал, или если состояние, которое
раньше было приватным у логгера, теперь общее.

Опасности:
  1. `RouterManager` — тоже наследник CRM, но транспорт. Он ПОЛУЧИЛ
     `set_sink_enabled` вместе с остальными и физически способен снять
     message-канал. Защита стоит на уровне команды (whitelist), а не класса —
     значит она обязана быть проверена именно как защита, а не как «у роутера
     метода нет» (метод у него как раз есть).
  2. Хук `_recreate_channel` не реализован → база обязана честно ответить
     False, а не молча «включил».
  3. `_tap_sinks` переехал в базу и стал общим полем. Два менеджера в одном
     процессе не должны видеть tap'ы друг друга.
  4. Tap переживает `reconfigure()` — это его смысл; после переезда легко
     потерять, потому что базовый `reconfigure` чистит реестр каналов.
  5. Порог tap'а на плоскости БЕЗ уровней (статистика): запись без поля level
     не должна молча исчезать при пороге по умолчанию и не должна проходить
     при высоком пороге.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core.channel_routing_manager import ChannelRoutingManager
from ..interfaces import IChannel


class _RecordingChannel(IChannel):
    """Канал, запоминающий всё принятое."""

    def __init__(self, name: str = "rec") -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success"}

    def close(self) -> None:
        self.closed = True


class _BareManager(ChannelRoutingManager):
    """Наследник БЕЗ реализации хука — проверяем поведение базы по умолчанию."""

    def __init__(self, name: str = "bare") -> None:
        super().__init__(manager_name=name)


class _RecreatingManager(ChannelRoutingManager):
    """Наследник С хуком: умеет пересоздать канал по имени."""

    def __init__(self, name: str = "recreating") -> None:
        super().__init__(manager_name=name)
        self.recreated: List[str] = []

    def _recreate_channel(self, name: str) -> bool:
        if name != "known":
            return False
        self.recreated.append(name)
        self.register_channel(_RecordingChannel(name))
        return True


# =============================================================================
# 1. Роутер физически способен снять свой канал — защита обязана быть на команде
# =============================================================================


def test_router_like_manager_can_disable_its_own_channel() -> None:
    """Документирует ОПАСНОСТЬ, а не желаемое поведение.

    После подъёма ``set_sink_enabled`` в базу его унаследовал и ``RouterManager``,
    который наблюдаемостью не является. Этот тест фиксирует, что метод у
    транспортного наследника РАБОТАЕТ и канал действительно снимается — то есть
    единственная преграда между командой и обрывом IPC это whitelist на уровне
    команды. Если кто-то однажды заменит whitelist на ``hasattr``-резолв, этот
    тест останется зелёным, а система станет уязвимой — поэтому парный тест
    «router НЕ адресуем командой» живёт на уровне process_module и обязателен.
    """
    transport = _BareManager("TransportLike")
    transport.register_channel(_RecordingChannel("messages"))
    assert "messages" in transport._channel_registry.names()

    assert transport.set_sink_enabled("messages", False) is True
    assert transport._channel_registry.names() == []


# =============================================================================
# 2. Хук по умолчанию честно отвечает «не умею»
# =============================================================================


def test_base_refuses_enable_without_hook() -> None:
    """Наследник без ``_recreate_channel`` не должен рапортовать об успехе.

    Молчаливый ``True`` был бы худшим из вариантов: оператор получил бы
    ``success=True`` и считал приёмник включённым, а записи продолжали бы
    пропадать.
    """
    mgr = _BareManager()
    assert mgr.set_sink_enabled("что_угодно", True) is False
    assert mgr._channel_registry.names() == []


def test_disable_is_generic_enable_is_delegated() -> None:
    """Полный цикл на наследнике с хуком: снять → вернуть."""
    mgr = _RecreatingManager()
    mgr.register_channel(_RecordingChannel("known"))

    assert mgr.set_sink_enabled("known", False) is True
    assert mgr._channel_registry.names() == []
    assert mgr.recreated == [], "выключение не имеет права звать хук пересоздания"

    assert mgr.set_sink_enabled("known", True) is True
    assert mgr._channel_registry.names() == ["known"]
    assert mgr.recreated == ["known"]

    # Имя, которого хук не знает, — честный отказ.
    assert mgr.set_sink_enabled("unknown", True) is False


def test_disable_of_absent_channel_is_false_not_crash() -> None:
    mgr = _RecreatingManager()
    assert mgr.set_sink_enabled("нет_такого", False) is False


def test_close_failure_does_not_block_disable() -> None:
    """Канал, падающий в ``close()``, всё равно обязан быть снят с реестра.

    Иначе сломанный приёмник остаётся адресуемым, и записи продолжают уходить
    в объект, который оператор считает выключенным.
    """

    class _BadClose(_RecordingChannel):
        def close(self) -> None:
            raise RuntimeError("не закрылся")

    mgr = _RecreatingManager()
    mgr.register_channel(_BadClose("bad"))
    assert mgr.set_sink_enabled("bad", False) is True
    assert mgr._channel_registry.names() == []


# =============================================================================
# 3. Tap'ы не общие между менеджерами
# =============================================================================


def test_taps_are_per_manager_not_shared() -> None:
    """``_tap_sinks`` объявлен в базе — легко случайно сделать его классовым.

    Классовый словарь означал бы, что подписка на tail логов начнёт получать
    ещё и метрики соседнего менеджера в том же процессе.
    """
    a, b = _BareManager("A"), _BareManager("B")
    tap_a, tap_b = _RecordingChannel("tap_a"), _RecordingChannel("tap_b")
    a.add_tap(tap_a, min_level="DEBUG")
    b.add_tap(tap_b, min_level="DEBUG")

    a._emit_to_taps({"msg": "из A"}, "INFO")

    assert [r["msg"] for r in tap_a.written] == ["из A"]
    assert tap_b.written == [], "tap соседнего менеджера получил чужую запись"


def test_remove_tap_reports_presence_and_closes() -> None:
    mgr = _BareManager()
    tap = _RecordingChannel("t")
    name = mgr.add_tap(tap, min_level="DEBUG")

    assert mgr.remove_tap(name) is True
    assert tap.closed is True
    assert mgr.remove_tap(name) is False, "повторное снятие обязано быть False"


def test_broken_tap_does_not_break_the_others() -> None:
    """Отказ одного tap'а не должен глушить остальные и ронять эмитента."""

    class _Boom(_RecordingChannel):
        def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
            raise RuntimeError("tap сломан")

    mgr = _BareManager()
    good = _RecordingChannel("good")
    mgr.add_tap(_Boom("boom"), min_level="DEBUG", name="boom")
    mgr.add_tap(good, min_level="DEBUG", name="good")

    mgr._emit_to_taps({"msg": "x"}, "ERROR")
    assert len(good.written) == 1


# =============================================================================
# 4. Tap переживает reconfigure, канал реестра — нет
# =============================================================================


def test_tap_survives_reconfigure_channel_does_not() -> None:
    """Смысл tap'а — подписка, не рвущаяся при hot-reload.

    Базовый ``reconfigure`` закрывает и чистит реестр каналов. Если бы tap'ы
    жили в реестре, подписка на tail логов рвалась бы при каждом применении
    нового конфига — и оператор терял бы поток ровно в тот момент, когда
    менял настройки, то есть когда смотрит внимательнее всего.
    """
    mgr = _RecreatingManager()
    mgr.register_channel(_RecordingChannel("in_registry"))
    tap = _RecordingChannel("survivor")
    mgr.add_tap(tap, min_level="DEBUG", name="survivor")

    mgr.reconfigure({})

    assert "in_registry" not in mgr._channel_registry.names()
    mgr._emit_to_taps({"msg": "после reconfigure"}, "INFO")
    assert [r["msg"] for r in tap.written] == ["после reconfigure"]


# =============================================================================
# 5. Порог на плоскости без уровней
# =============================================================================


def test_threshold_on_a_plane_without_levels() -> None:
    """Записи без уровня (метрики) получают ранг 0.

    Значит при пороге "DEBUG" они проходят, а при пороге по умолчанию
    ("ERROR") — нет. Оба факта закреплены: первый чтобы статистика вообще
    могла пользоваться tap'ами, второй чтобы дефолтный порог не оказался
    случайно всепропускающим для одной из плоскостей.
    """
    mgr = _BareManager()
    permissive, strict = _RecordingChannel("permissive"), _RecordingChannel("strict")
    mgr.add_tap(permissive, min_level="DEBUG", name="permissive")
    mgr.add_tap(strict, name="strict")  # порог по умолчанию — ERROR

    mgr._emit_to_taps({"metric": "fps", "value": 30})  # уровня нет вовсе

    assert len(permissive.written) == 1
    assert strict.written == []


def test_emit_to_taps_is_noop_without_taps() -> None:
    """Пустой набор tap'ов — тихий выход, без обхода и без исключений."""
    mgr = _BareManager()
    mgr._emit_to_taps({"msg": "никому"}, "CRITICAL")  # не должно бросить


# =============================================================================
# 6. _fallback_log доступен всем наследникам и не падает
# =============================================================================


def test_fallback_log_available_and_never_raises(caplog) -> None:
    """Последний рубеж обязан быть у любого наследника и не бросать наружу."""
    import logging

    mgr = _BareManager("Стенд")
    with caplog.at_level(logging.WARNING, logger="multiprocess_framework"):
        mgr._fallback_log("ERROR", "маршрут наблюдаемости недоступен")

    assert any("маршрут наблюдаемости недоступен" in r.getMessage() for r in caplog.records)
    assert any("Стенд" in r.getMessage() for r in caplog.records), "имя менеджера обязано быть в записи"
