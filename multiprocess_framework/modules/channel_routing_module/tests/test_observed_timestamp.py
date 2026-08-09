# -*- coding: utf-8 -*-
"""Ф3.4 — отметка ПРИЁМА записи (OTel ``ObservedTimestamp``).

``ts`` отвечает «когда это случилось», и на вопрос «свеж ли хвост» ответить не
может: встала плоскость наблюдаемости — в GUI приедут записи с честными старыми
``ts``, и «застряло» будет неотличимо от «тихо». Разность
``observed_ts - ts`` и есть задержка доставки.

Свойства, которые здесь стерегутся:

1. штампует ПРИНИМАЮЩАЯ сторона, часы приходят параметром (глобальный патч
   часов — источник флейка, зависимость передаётся явно);
2. чужая отметка не перетирается — иначе задержка обнулялась бы на каждой
   пересылке;
3. эмитент отметку НЕ ставит: у него она равнялась бы ``ts`` и врала бы о
   свежести (это отрицательная половина пары, и без неё первая ничего не стоит).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.observability.record_display import (
    OBSERVED_TS_KEY,
    hub_record_to_display,
    log_record_to_display,
    stamp_observed,
)


class TestStamping:
    def test_records_get_the_receivers_clock(self) -> None:
        records: List[Dict[str, Any]] = [{"ts": 100.0, "message": "a"}, {"ts": 101.0, "message": "b"}]
        stamp_observed(records, now=150.5)
        assert [r[OBSERVED_TS_KEY] for r in records] == [150.5, 150.5]

    def test_lag_is_the_difference(self) -> None:
        """Тот самый вопрос, ради которого поле заведено."""
        record = {"ts": 100.0}
        stamp_observed([record], now=108.25)
        assert record[OBSERVED_TS_KEY] - record["ts"] == pytest.approx(8.25)

    def test_existing_stamp_is_not_overwritten(self) -> None:
        """Пересылка через вторые руки сохраняет отметку ПЕРВОГО, кто увидел."""
        record = {"ts": 100.0, OBSERVED_TS_KEY: 105.0}
        stamp_observed([record], now=999.0)
        assert record[OBSERVED_TS_KEY] == 105.0, "вторая рука обнулила задержку первой"

    def test_returns_the_same_list_for_readable_call_sites(self) -> None:
        records: List[Dict[str, Any]] = [{"ts": 1.0}]
        assert stamp_observed(records, now=2.0) is records

    @pytest.mark.parametrize(
        "records",
        [
            pytest.param([], id="пусто"),
            pytest.param(None, id="не список"),
            pytest.param(["мусор", 42], id="не словари"),
        ],
    )
    def test_junk_input_does_not_raise(self, records: Any) -> None:
        """Хвост — наблюдение за работой, а не сама работа: падать он не вправе."""
        stamp_observed(records, now=1.0)


class TestEmitterDoesNotStampIt:
    """Отрицательная половина: у источника отметки нет и быть не должно.

    Если бы нормализаторы ставили её сами, значение равнялось бы ``ts``
    (наблюдатель и источник — один процесс), задержка всегда была бы нулевой, а
    «хвост свеж» — неотличимо от «хвост застрял». То есть поле выглядело бы
    работающим и врало.
    """

    def test_hub_record_has_no_observed_stamp(self) -> None:
        display = hub_record_to_display({"kind": "log", "module": "m", "ts": 1.0, "severity": "info"})
        assert OBSERVED_TS_KEY not in display

    def test_log_record_has_no_observed_stamp(self) -> None:
        display = log_record_to_display({"timestamp": 1.0, "level": "ERROR", "message": "x", "module": "m"})
        assert OBSERVED_TS_KEY not in display

    def test_the_forwarder_side_does_not_stamp(self) -> None:
        """Шов: форвардер (сторона ОТПРАВКИ) гоняет записи через нормализатор.

        Пара к предыдущим двум на живом коде проводки: если отметка когда-нибудь
        переедет внутрь нормализатора, она начнёт ставиться у отправителя — и
        задержка станет тождественным нулём молча.
        """
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            wire_observability_forward,
        )

        pushed: List[Any] = []

        class _Router:
            def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
                pushed.append(message)

        forwarder, _taps = wire_observability_forward(
            _Router(), "subscriber", "camera_0", logger_manager=None, error_manager=None
        )
        forwarder([{"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x"}])

        assert pushed, "форвардер ничего не отправил — шов проверить нечем"
        records = pushed[0].get("data", {}).get("records", [])
        assert records, "в конверте нет записей"
        assert OBSERVED_TS_KEY not in records[0], "отметку приёма поставила сторона ОТПРАВКИ"
