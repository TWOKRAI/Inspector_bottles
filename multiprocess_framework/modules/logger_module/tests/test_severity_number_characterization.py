# -*- coding: utf-8 -*-
"""Ф3.1 — характеризация оси уровня ДО переномерации в словарь OTel.

Снято на коде с рангами 0…4 и прогнано зелёным ДО правки: без этого «семантика
сохранилась поэлементно» было бы заявлением, а не измерением (правило фазы —
характеризация перед перестройкой доставки).

Файл пережил правку целиком: все ожидания здесь — про **наблюдаемое поведение**
(пропустил/не пропустил, доставил/не доставил), а не про конкретные числа.
Сами числа проверяет ``test_gate_predicate.py::TestLevelRanks``.

Измерено: после переномерации покраснели РОВНО два теста — оба в
``TestTypoInThresholdIsSilentFirehose``, оба про дефект, который задача чинит.
Решётка гейта (25 пар) и tap-контракт остались зелёными байт-в-байт, и это и
есть доказательство, что переномерация сменила константы, а не поведение.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    ChannelRoutingManager,
)
from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerScopeSchema
from multiprocess_framework.modules.logger_module.log_enums import LogLevel

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Ожидаемая решётка гейта: строка — порог скоупа, столбец — уровень записи.
#: Литералы, а не производная от таблицы рангов: тест, выводящий ожидание из
#: проверяемого кода, согласится с любой нумерацией, включая сломанную.
_GATE_GRID: Dict[str, List[bool]] = {
    #             DEBUG  INFO   WARNING ERROR  CRITICAL
    "DEBUG": [True, True, True, True, True],
    "INFO": [False, True, True, True, True],
    "WARNING": [False, False, True, True, True],
    "ERROR": [False, False, False, True, True],
    "CRITICAL": [False, False, False, False, True],
}


class _RecordingChannel(IChannel):
    def __init__(self, name: str = "rec") -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success"}

    def close(self) -> None:
        pass


class _BareManager(ChannelRoutingManager):
    def __init__(self, name: str = "bare") -> None:
        super().__init__(manager_name=name)


class TestGateGridIsPreservedByRenumbering:
    """25 пар (порог × уровень) — вердикт гейта не зависит от нумерации."""

    @pytest.mark.parametrize("min_level", _LEVELS)
    def test_row(self, min_level: str) -> None:
        scope = LoggerScopeSchema(enabled=True, min_level=min_level)
        observed = [scope.should_log(LogLevel(name), "any") for name in _LEVELS]
        assert observed == _GATE_GRID[min_level], f"порог {min_level}: решётка вердиктов изменилась"


class TestTapDeliveryIsPreservedByRenumbering:
    """Порог tap'а: что доставлялось до правки, доставляется и после."""

    @pytest.mark.parametrize(
        "min_level,level,expected",
        [
            ("DEBUG", "DEBUG", True),
            ("DEBUG", "CRITICAL", True),
            ("ERROR", "WARNING", False),
            ("ERROR", "ERROR", True),
            ("CRITICAL", "ERROR", False),
        ],
    )
    def test_levelled_record(self, min_level: str, level: str, expected: bool) -> None:
        mgr = _BareManager()
        sink = _RecordingChannel()
        mgr.add_tap(sink, min_level=min_level, name="t")
        mgr._emit_to_taps({"msg": "x"}, level)
        assert (len(sink.written) == 1) is expected

    def test_record_without_level_reaches_permissive_tap_only(self) -> None:
        """Запись без уровня (метрика) — проходит порог DEBUG, не проходит ERROR.

        Оба факта несущие: первый — чтобы плоскость статистики вообще могла
        пользоваться tap'ами, второй — чтобы дефолтный порог не оказался
        всепропускающим. Сегодня они держатся на совпадении «нет уровня → 0»
        с «DEBUG → 0»; после переномерации DEBUG=5 совпадение исчезает, и
        поведение обязано быть воспроизведено явно, а не случайно.
        """
        mgr = _BareManager()
        permissive, strict = _RecordingChannel("p"), _RecordingChannel("s")
        mgr.add_tap(permissive, min_level="DEBUG", name="p")
        mgr.add_tap(strict, name="s")  # порог по умолчанию — ERROR

        mgr._emit_to_taps({"metric": "fps", "value": 30})  # уровня нет вовсе

        assert len(permissive.written) == 1, "метрика перестала доходить до tap'а «дай всё»"
        assert strict.written == [], "метрика просочилась в tap порога ERROR"

    def test_unknown_level_text_reaches_permissive_tap_only(self) -> None:
        """Незнакомый ТЕКСТ уровня ведёт себя как самый низкий, а не как «всё».

        Отдельно от предыдущего: там уровня нет вовсе, здесь он есть, но не
        опознан. Судьба одинакова и до, и после правки.
        """
        mgr = _BareManager()
        permissive, strict = _RecordingChannel("p"), _RecordingChannel("s")
        mgr.add_tap(permissive, min_level="DEBUG", name="p")
        mgr.add_tap(strict, name="s")
        mgr._emit_to_taps({"msg": "x"}, "VERBOSE")
        assert len(permissive.written) == 1
        assert strict.written == []


class TestNumberIsDerivedAndNotCarried:
    """Число выводится из имени уровня, а не едет в записи.

    Это фальсифицируемая половина решения Р2: если ``severity_number`` появится
    полем записи, вырастет объём логов, IPC и файлов — при базе 4.78 МБ/час это
    не бесплатно. Тест сторожит форму записи, а не намерение.
    """

    def test_record_dict_has_no_new_field(self) -> None:
        from multiprocess_framework.modules.logger_module.core.log_types import LogRecord

        record = LogRecord(
            timestamp=1.0,
            level=LogLevel.INFO,
            scope="SYSTEM",
            message="x",
            module="m",
            extra={},
        )
        assert set(record.to_dict()) == {
            "timestamp",
            "level",
            "scope",
            "message",
            "module",
            "extra",
            "seq",
        }

    def test_number_is_a_pure_function_of_the_level_name(self) -> None:
        """Выводимость: имени достаточно, ничего сопровождающего не нужно."""
        from multiprocess_framework.modules.channel_routing_module.levels import severity_of

        assert severity_of("INFO") == 9
        assert severity_of(LogLevel.INFO) == 9
        assert severity_of("info") == 9


class TestSeverityWhitelistIsDerived:
    """Список имён severity у drain-адаптера — производный, а не вторая копия.

    Копия здесь уже была: новый уровень требовал правки в двух местах, а
    расхождение проявилось бы тем, что запись законного уровня молча
    переписывается в ``info``.
    """

    def test_whitelist_follows_the_level_order(self) -> None:
        from multiprocess_framework.modules.channel_routing_module.levels import LEVEL_ORDER
        from multiprocess_framework.modules.channel_routing_module.observability import drain_adapter

        assert drain_adapter._LOG_SEVERITIES == frozenset(n.lower() for n in LEVEL_ORDER)
        assert len(drain_adapter._LOG_SEVERITIES) == len(LEVEL_ORDER)


class TestUnknownThresholdIsFailOpen:
    """Незнакомый ПОРОГ пропускает всё — и это защита, а не удобство.

    Противоположный дефолт (fail-closed) означал бы тишину от опечатки, то есть
    невидимую потерю. Позиция порога и позиция записи требуют РАЗНЫХ дефолтов —
    сегодня оба обслуживает одна функция, и держится это только на «0 = DEBUG».
    """

    def test_tap_with_unknown_threshold_receives_everything(self) -> None:
        mgr = _BareManager()
        sink = _RecordingChannel()
        mgr.add_tap(sink, min_level="VERBOSE", name="t")
        mgr._emit_to_taps({"msg": "x"}, "DEBUG")
        assert len(sink.written) == 1


class TestTypoInThresholdIsSilentFirehose:
    """ДЕФЕКТ, который чинит 3.1: опечатка в пороге скоупа = «пропускать всё».

    Оба ожидания здесь ПОМЕНЯЛИСЬ правкой — это единственные две строки файла,
    которым так и положено. Что было до неё (снято запуском на старом коде):

        min_level='WARN'    → should_log(DEBUG) = True   # порог не понят
        min_level='WARNIGN' → should_log(DEBUG) = True   # порог не понят

    ``WARN`` — не выдумка: это каноничное короткое имя уровня в OTel и в
    большинстве чужих логгеров. Оператор, написавший его, получал ровно
    противоположное задуманному, и молча.

    Разница между двумя строками теперь — смысловая: одно имя законный
    синоним, другое не значит ничего.
    """

    def test_warn_is_a_legal_synonym_of_warning(self) -> None:
        scope = LoggerScopeSchema(enabled=True, min_level="WARN")
        assert scope.min_level == "WARNING", "алиас обязан раскрыться в канон, а не остаться как есть"
        assert scope.should_log(LogLevel.DEBUG, "any") is False
        assert scope.should_log(LogLevel.WARNING, "any") is True

    def test_typo_threshold_is_refused(self) -> None:
        with pytest.raises(ValueError, match="неизвестный уровень"):
            LoggerScopeSchema(enabled=True, min_level="WARNIGN")
