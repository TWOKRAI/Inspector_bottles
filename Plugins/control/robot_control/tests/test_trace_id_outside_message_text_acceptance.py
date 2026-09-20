# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): trace_id вне текста.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «trace_id вне текста. Plugins/control/robot_control/plugin.py (~285):
    trace_id уезжает в extra.context.trace_id, текст сообщения — постоянный.
    Нужен линт-страж: сообщение не содержит 32-hex подстроки. Страж обязан
    краснеть на подсунутом ему нарушителе.»

Расхождение со строкой (называю прямо): строка ~285 в текущем файле — середина
``_write_unit_event``, где ``trace_id`` в тексте НЕТ вовсе (ни там, ни в
``_dump_flight``, ~236/328) — сверено grep'ом по всему файлу. Оба места уже
передают ``trace_id`` ИМЕННО kwarg'ом (``self._ctx.flight_dump(..., trace_id=...)``,
``self._ctx.write_event(..., trace_id=... через **fields)``), а не внутри
f-строки текста. Часть А теста ниже это проверяет ДИНАМИЧЕСКИ на реальном
плагине — и по моему прочтению кода она обязана оказаться ЗЕЛЁНОЙ уже сегодня
(это не провал теста, а находка: свойство по этим двум точкам уже выполнено).

Чего нет — «линт-стража» как переиспользуемого механизма, который поймает
БУДУЩУЮ регрессию (кто-то допишет f"... {trace_id} ..." в текст) в ЛЮБОЙ точке
кодовой базы, а не только в этих двух. Часть Б целится в такой страж как
именованную утилиту; я его НЕ ВИДЕЛ (в плане и реализации мне отказано в
доступе) и потому УГАДЫВАЮ его адрес по конвенции соседних модулей
наблюдаемости (``logger_module.core`` — туда же, где ``sampling.py``,
``name_hierarchy.py``). Если реализатор положит стража в другое место —
это только одна строка импорта в части Б, поведенческий контракт (просьба
ниже) не меняется.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import numpy as np
import pytest

from Plugins.control.robot_control.plugin import RobotControlPlugin

#: 32 hex-символа подряд — форма trace_id по этому проекту (``uuid4().hex``-подобная).
_HEX32 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")

_TRACE_ID = "0123456789abcdef0123456789abcdef"  # заведомо валидный 32-hex литерал


class _Ctx:
    """Лёгкий двойник PluginContext — форма скопирована с test_wide_event_emitter.py.

    Копия не моя выдумка: это уже существующий паттерн теста плагина
    (сигнатуры дословно повторяют PluginContext, включая ``/`` в аргументах —
    урок 1.1/4.1-И8, названный в оригинале).
    """

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.registers = None
        self.command_manager = None
        self.process_name = "inspector"
        self.plugin_name = "robot_control"
        self.events: List[Dict[str, Any]] = []
        self.flights: List[Dict[str, Any]] = []
        self.documents: List[Dict[str, Any]] = []
        self.infos: List[str] = []
        self.errors: List[str] = []

    def flight_dump(self, reason: str = "", /, **fields: Any) -> bool:
        self.flights.append({"reason": reason, **fields})
        return True

    def write_document(self, kind: str, summary: str = "", /, **fields: Any) -> bool:
        self.documents.append({"kind": kind, "summary": summary, **fields})
        return True

    def write_event(
        self, kind: str, summary: str = "", /, *, unit: Any = None, decisive: bool = False, **fields: Any
    ) -> bool:
        self.events.append({"kind": kind, "summary": summary, "decisive": decisive, "unit": unit, **fields})
        return True

    def log_info(self, message: str, **kwargs: Any) -> None:
        self.infos.append(message)

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)


def _frame() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _defect(area: int = 900, bbox=(10, 10, 50, 50)) -> dict:
    return {"bbox": list(bbox), "center": [30, 30], "area": area}


def _unit(detections: list, trace: str) -> dict:
    return {"frame": _frame(), "detections": detections, "trace_id": trace}


@pytest.fixture
def plugin() -> tuple:
    ctx = _Ctx()
    p = RobotControlPlugin()
    p.configure(ctx)
    p._reg.min_defect_area = 100
    return p, ctx


class TestTraceIdAlreadyStructuredAtCitedCallSites:
    """Часть А — реальный прогон двух точек, названных критерием.

    По моему прочтению кода ОБЕ проверки ниже обязаны быть ЗЕЛЁНЫМИ уже
    сегодня (свойство уже выполнено) — это не провал требования, а находка,
    честно отмеченная в отчёте тестера, а не выданная за «тест ничего не
    проверяет».
    """

    def test_flight_dump_carries_trace_id_as_kwarg_not_in_reason_text(self, plugin) -> None:
        p, ctx = plugin
        p.process([_unit([_defect(area=900)], trace=_TRACE_ID)])

        assert ctx.flights, "фронт pass→reject обязан вызвать flight_dump хотя бы раз"
        dump = ctx.flights[-1]
        assert dump.get("trace_id") == _TRACE_ID, "trace_id обязан приехать структурным полем flight_dump"
        assert not _HEX32.search(dump.get("reason", "")), (
            f"текст 'reason' дампа не должен содержать сырой 32-hex trace_id: {dump.get('reason')!r}"
        )

    def test_write_event_carries_trace_id_as_field_not_in_summary_text(self, plugin) -> None:
        p, ctx = plugin
        p.process([_unit([_defect(area=900)], trace=_TRACE_ID)])

        assert ctx.events, "широкая запись обязана быть хотя бы одна"
        record = ctx.events[-1]
        assert record.get("trace_id") == _TRACE_ID or (record.get("unit") or {}).get("trace_id") == _TRACE_ID, (
            "trace_id обязан быть доступен как структурное поле записи"
        )
        assert not _HEX32.search(record.get("summary", "")), (
            f"текст 'summary' широкой записи не должен содержать сырой 32-hex trace_id: {record.get('summary')!r}"
        )


class TestReusableGuardAgainstFutureRegression:
    """Часть Б — переиспользуемый страж (то, чего критерий требует «завести»).

    Адрес утилиты УГАДАН (см. докстринг модуля) — если он неверен, эта часть
    упадёт ``ModuleNotFoundError`` по неверному пути импорта, а не по факту
    отсутствия механизма; это ограничение названо честно, а не спрятано.
    """

    def test_guard_exists_and_flags_an_injected_violator(self) -> None:
        try:
            from multiprocess_framework.modules.logger_module.core.trace_id_guard import (
                assert_no_bare_trace_id,
            )
        except ImportError as exc:
            pytest.fail(
                f"страж trace_id не найден по угаданному адресу "
                f"'multiprocess_framework.modules.logger_module.core.trace_id_guard."
                f"assert_no_bare_trace_id' ({exc!r}) — механизм ещё не реализован "
                f"(ожидаемый RED) либо реализатор положил его в другое место "
                f"(тогда поправить только импорт в этом тесте)"
            )

        violator = f"widget failed for trace {_TRACE_ID}"
        with pytest.raises(AssertionError):
            assert_no_bare_trace_id(violator)

        # Отрицательный контроль — чистое сообщение страж обязан пропускать молча.
        assert_no_bare_trace_id("widget failed, no trace here")
