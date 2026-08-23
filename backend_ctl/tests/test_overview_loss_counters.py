# -*- coding: utf-8 -*-
"""Тесты Т.2 (критерий 1) — независимый тестер, ДО реализации.

Источник контракта: акцептанс-критерии задачи Т.2 плана observation-port
(«queue_data_evicted» и «queue_never_drop_loss_total» распознаются
``RouterStats``, но НИКОГДА не всплывают в ``system_overview`` — ни в
карточке процесса, ни в ``anomalies``). Тесты пишутся ТОЛЬКО по этим
критериям, реализация ещё не тронута — ожидаемо красные.

Фейки/фикстуры переиспользованы из ``test_overview.py`` (``_fake_backend``,
``_healthy_responses``) без изменений — искать контекст там же.
"""

from __future__ import annotations

from typing import Any, Dict

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.conftest import full_router_stats
from backend_ctl.tests.test_overview import _fake_backend, _healthy_responses


def _responses_with_router(**overrides: Any) -> Dict[str, Dict[str, Any]]:
    responses = _healthy_responses()
    responses["introspect.router_stats"] = {"success": True, "router_stats": full_router_stats(**overrides)}
    return responses


class TestQueueDataEvictedSurfaces:
    """queue_data_evicted (потеря на потоке кадров, data-plane) обязана быть видна."""

    def test_positive_value_flagged_with_counter_name_value_and_process(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _responses_with_router(queue_data_evicted=7)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        hits = [a for a in res["anomalies"] if "queue_data_evicted" in a.get("detail", "")]
        assert hits, f"queue_data_evicted=7 обязан породить аномалию, anomalies={res['anomalies']}"
        assert hits[0]["process"] == "cam"
        assert "7" in hits[0]["detail"]

    def test_zero_value_raises_no_anomaly_twin_control(self, monkeypatch) -> None:
        """Плечо OFF парой к тесту выше: ноль — не потеря, аномалии нет вовсе."""
        d = BackendDriver()
        responses = _responses_with_router(queue_data_evicted=0)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        assert not [a for a in res["anomalies"] if "queue_data_evicted" in a.get("detail", "")]
        assert res["anomaly_count"] == 0, "здоровая сводка обязана остаться без сюрпризов"


class TestQueueNeverDropLossTotalSurfaces:
    """queue_never_drop_loss_total (потеря control-плоскости) обязана быть видна."""

    def test_positive_value_flagged_with_counter_name_value_and_process(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _responses_with_router(queue_never_drop_loss_total=13)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        hits = [a for a in res["anomalies"] if "queue_never_drop_loss_total" in a.get("detail", "")]
        assert hits, f"queue_never_drop_loss_total=13 обязан породить аномалию, anomalies={res['anomalies']}"
        assert hits[0]["process"] == "cam"
        assert "13" in hits[0]["detail"]

    def test_zero_value_raises_no_anomaly_twin_control(self, monkeypatch) -> None:
        """Плечо OFF: ноль по never-drop счётчику — тоже тишина."""
        d = BackendDriver()
        responses = _responses_with_router(queue_never_drop_loss_total=0)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        assert not [a for a in res["anomalies"] if "queue_never_drop_loss_total" in a.get("detail", "")]
        assert res["anomaly_count"] == 0


class TestPlanesAreDistinguishable:
    """never_drop_loss — control-плоскость, её нельзя молча слить в чужой kind."""

    def test_both_positive_produce_different_kinds(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _responses_with_router(queue_data_evicted=7, queue_never_drop_loss_total=13)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        data_hits = [a for a in res["anomalies"] if "queue_data_evicted" in a.get("detail", "")]
        never_drop_hits = [a for a in res["anomalies"] if "queue_never_drop_loss_total" in a.get("detail", "")]
        assert data_hits and never_drop_hits, res["anomalies"]
        assert data_hits[0]["kind"] != never_drop_hits[0]["kind"], (
            "data-plane и control-plane потери обязаны различаться по kind, "
            "иначе оператор не отличит их по одной только аномалии"
        )

    def test_never_drop_loss_kind_is_not_an_unrelated_existing_kind(self, monkeypatch) -> None:
        """never_drop_loss не должен молча притвориться уже существующим kind'ом.

        ``router_dropped``/``router_errors`` — уже занятые классы (middleware_dropped
        / errors), лепить туда control-plane потерю значило бы стереть различие,
        которое и есть суть критерия.
        """
        d = BackendDriver()
        responses = _responses_with_router(queue_never_drop_loss_total=13)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        never_drop_hits = [a for a in res["anomalies"] if "queue_never_drop_loss_total" in a.get("detail", "")]
        assert never_drop_hits, res["anomalies"]
        assert never_drop_hits[0]["kind"] not in ("router_dropped", "router_errors"), (
            f"never_drop_loss слит в чужой kind {never_drop_hits[0]['kind']!r}"
        )


class TestMissingDistinguishableFromZero:
    """«Не спросили» ≠ «нуль» — тот же инвариант 2.V2, что и у остальных счётчиков router'а."""

    def test_counter_not_carried_is_not_reported_as_positive_or_silent(self, monkeypatch) -> None:
        """Ответ БЕЗ ключей queue_data_evicted/queue_never_drop_loss_total вовсе.

        ``RouterStats.from_response`` в этом случае кладёт оба имени в ``missing``
        (строгий край protocol.py) — оверview обязан честно назвать «показаний
        нет», а не смолчать и не спутать это с «потерь не было».
        """
        d = BackendDriver()
        # Полная форма минус два новых счётчика — имитация СТАРОЙ сборки router'а,
        # которая их ещё не считает (а не «сбойной» ручки).
        stats = full_router_stats()
        del stats["queue_data_evicted"]
        del stats["queue_never_drop_loss_total"]
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {"success": True, "router_stats": stats}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        card = res["processes"]["cam"]
        assert card.get("missing", {}).get("router") and (
            "queue_data_evicted" in card["missing"]["router"]
            and "queue_never_drop_loss_total" in card["missing"]["router"]
        ), f"оба счётчика обязаны попасть в missing, card={card}"

        # «Не спросили» не должно читаться как позитивная аномалия потери (значения
        # нет, значит порог 0 не пересечён и утверждать нечего).
        loss_kind_hits = [
            a
            for a in res["anomalies"]
            if "queue_data_evicted" in a.get("detail", "") or "queue_never_drop_loss_total" in a.get("detail", "")
        ]
        # Не-вырожденность: список обязан быть непустым — иначе проверка ниже
        # была бы истинна на пустом множестве и не доказывала бы ничего.
        assert loss_kind_hits, (
            f"ни одна аномалия не упомянула отсутствующий счётчик — 'не спросили' "
            f"осталось совсем невидимым, anomalies={res['anomalies']}"
        )
        # Разрешена ТОЛЬКО generic-аномалия counter_missing (уже существующий
        # механизм protocol.py/overview.py), а не «потеря» с конкретным числом.
        for hit in loss_kind_hits:
            assert hit["kind"] == "counter_missing", (
                f"счётчик без показания не имеет права выглядеть как обнаруженная потеря: {hit}"
            )
