# -*- coding: utf-8 -*-
"""Приёмочный тест A9 (RED, Task 1.1, plans/observability-closure/phase-1-invisible-failures.md).

Контракт — в спеке задачи (раздел «Контракт», п.11), interface.py нет
(MODULE_CONTRACT: new-lite). Источник истины — ``backend_ctl/overview.py``
(``system_overview``) и ``backend_ctl/protocol.py`` (``OBSERVABILITY_LOSS_KEYS``),
оба СУЩЕСТВУЮТ на этом HEAD — только двух конкретных свойств у них ещё нет:

  1. ``counters.error.thread_exceptions > 0`` не даёт аномалию ``kind="thread_exceptions"``
     — overview.py про это имя ничего не знает вовсе.
  2. ``hook_delivery_failures`` не входит в ``OBSERVABILITY_LOSS_KEYS`` — тот же
     счётчик > 0 не попадает в штатную аномалию ``observability_loss``.

Оба теста красные ``AssertionError`` (аномалии нет), НЕ ``ImportError``: вся
используемая инфраструктура (``BackendDriver``, ``system_overview``,
``_healthy_responses``/``_quiet_planes``/``_fake_backend`` из соседнего
``test_overview.py``) уже существует и импортируется на уровне модуля.

**Почему по одному тесту на критерий, а не отдельно позитив/негатив.** Правило
задачи требует ВСЕ тесты красными сейчас. Контроль «на нуле аномалии нет» уже
верен и сегодня (аномалии нет вообще ни для какого значения — некому её
выставить), то есть отдельный тест на этот случай был бы зелёным уже сейчас и
нарушал бы правило. Поэтому ноль-контроль и позитив живут ВНУТРИ одной
функции: функция целиком красная (падает на позитивной половине), а
ноль-контроль всё равно зафиксирован и обязан остаться верным после
реализации.
"""

from __future__ import annotations

from typing import Any, Dict

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.test_overview import _fake_backend, _healthy_responses, _quiet_planes


def _responses_with_error_counters(overrides: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """``_healthy_responses()`` с подменённой секцией ``counters.error`` в introspect.observability."""
    responses = _healthy_responses()
    planes = _quiet_planes()
    planes["error"] = {**planes["error"], **overrides}
    responses["introspect.observability"] = {
        "success": True,
        "process": "cam",
        "effective": {},
        "counters": planes,
    }
    return responses


class TestA9ThreadExceptionsAnomaly:
    def test_positive_thread_exceptions_produces_named_anomaly_but_zero_does_not(self, monkeypatch) -> None:
        # Контроль: на нуле аномалии не было и не будет — верно уже сегодня.
        d_zero = BackendDriver()
        _fake_backend(
            monkeypatch, d_zero, procs=["cam"], responses=_responses_with_error_counters({"thread_exceptions": 0})
        )
        zero_res = d_zero.system_overview()
        assert not any(a.get("kind") == "thread_exceptions" for a in zero_res["anomalies"])

        # A9, позитив: thread_exceptions=2 обязан дать именованную аномалию.
        # Красный на этом HEAD: overview.py вообще не знает имени thread_exceptions.
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_responses_with_error_counters({"thread_exceptions": 2}))
        res = d.system_overview()

        matches = [a for a in res["anomalies"] if a.get("kind") == "thread_exceptions" and a.get("process") == "cam"]
        assert len(matches) == 1, f"ожидалась ровно одна аномалия thread_exceptions, получено: {res['anomalies']}"
        assert "2" in matches[0].get("detail", ""), matches[0]


class TestA9HookDeliveryFailuresFeedsObservabilityLoss:
    def test_positive_hook_delivery_failures_feeds_observability_loss_but_zero_does_not(self, monkeypatch) -> None:
        # Контроль: на нуле observability_loss по этому ключу не было и не будет.
        d_zero = BackendDriver()
        _fake_backend(
            monkeypatch,
            d_zero,
            procs=["cam"],
            responses=_responses_with_error_counters({"hook_delivery_failures": 0}),
        )
        zero_res = d_zero.system_overview()
        assert not any(
            a.get("kind") == "observability_loss" and "hook_delivery_failures" in a.get("detail", "")
            for a in zero_res["anomalies"]
        )

        # A9, позитив: hook_delivery_failures=1 обязан войти в OBSERVABILITY_LOSS_KEYS
        # и дать штатную observability_loss плоскости error.
        # Красный на этом HEAD: ключа нет в OBSERVABILITY_LOSS_KEYS.
        d = BackendDriver()
        _fake_backend(
            monkeypatch, d, procs=["cam"], responses=_responses_with_error_counters({"hook_delivery_failures": 1})
        )
        res = d.system_overview()

        matches = [
            a
            for a in res["anomalies"]
            if a.get("kind") == "observability_loss"
            and a.get("process") == "cam"
            and "hook_delivery_failures" in a.get("detail", "")
        ]
        assert len(matches) == 1, f"ожидалась observability_loss с hook_delivery_failures, получено: {res['anomalies']}"
        assert "hook_delivery_failures=1" in matches[0]["detail"]
