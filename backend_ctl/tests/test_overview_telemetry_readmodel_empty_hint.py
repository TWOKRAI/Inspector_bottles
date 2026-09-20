# -*- coding: utf-8 -*-
"""Task 2.8 (RED, стадия 1): подсказка ``telemetry_readmodel_empty`` в ``system_overview``.

Живая находка Ф1.5: холодная агентская сессия зовёт ``system_overview`` и получает
``telemetry.fps == {}`` — пустой read-model. Причина законная (задокументирована в
``BackendDriver.telemetry_snapshot``: наполняет её ``watch_like_gui``/``state_subscribe``),
но САМА СВОДКА о предусловии молчит — обещание «один вызов = вся картина» ломается
ровно для агентов, которые не знают, что подписаться нужно СНАЧАЛА.

Приёмка (задача 2.8 плана ``observability-closure``):

1. Холодный overview (снимок ``telemetry.fps`` пуст, подписки нет) → hint
   ``telemetry_readmodel_empty`` ЕСТЬ.
2. После подписки (``watch_like_gui``) и первой дельты (снимок непуст) → hint НЕТ.
3. Ложноположительная половина: подписка активна, а снимок ЕЩЁ пуст (дельт не было —
   законное «пока молчит», не поломка) → hint НЕТ.
4. Ложноотрицательная половина — та же сцена, что критерий 1: снимок пуст, подписки
   нет, а сводка молчит → тест обязан покраснеть. Ради этой половины задача и
   заведена, отдельного теста не пишем — это ``test_cold_overview_flags_...`` ниже.
5. Форма hint'а — литерал: ``kind == "telemetry_readmodel_empty"`` (строка в тексте
   теста, НЕ импорт константы из overview.py), ``detail`` — непустая строка.

Источник контракта: текст задачи и живая находка стенда (``docs/claude/memory`` /
план ``observability-closure``, Ф1.5) — отдельного ``interface.py`` под ``overview.py``
в дереве нет, у модуля есть только докстрока-контракт ``system_overview`` (Returns).
Это ``public-api-change`` формы существующего вызова, ожидаемая ошибка красного теста
— ``AssertionError`` на пустом списке hint'ов, а не ``ImportError``/``AttributeError``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.test_overview import _fake_backend, _feed_state, _healthy_responses


def _telemetry_hints(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [a for a in res["anomalies"] if a.get("kind") == "telemetry_readmodel_empty"]


class TestTelemetryReadmodelEmptyHint:
    def test_cold_overview_flags_empty_readmodel_without_subscription(self, monkeypatch) -> None:
        """Критерии 1 и 4 (одна сцена): подписки нет, снимок пуст → hint ЕСТЬ.

        Сегодня (до реализации) сводка о предусловии молчит целиком — этот тест
        обязан упасть ``AssertionError`` на пустом ``hits``. Это и есть красный
        тест, ради которого заведена задача (критерий 4 — «сводка молчит»).
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())

        # Контроль сцены: тест ещё ни разу не подписывался — ingest_active обязан
        # быть False, иначе сцена не та, что заявлена в критерии.
        cold_snap = d.telemetry_snapshot()
        assert cold_snap["ingest_active"] is False, "сцена сломана: подписка уже как-то активна"
        assert cold_snap["count"] == 0, "сцена сломана: read-model уже не пуст"

        res = d.system_overview()
        assert res["telemetry"]["fps"] == {}, "сцена: snapshot.fps действительно пуст (как в живой находке Ф1.5)"

        hits = _telemetry_hints(res)
        assert hits, "снимок пуст, подписки нет — сводка обязана назвать это, а не молчать (критерий 1 и 4)"
        assert hits[0]["kind"] == "telemetry_readmodel_empty"  # критерий 5, литерал
        detail = hits[0].get("detail")
        assert isinstance(detail, str) and detail, "detail обязан быть непустой строкой (критерий 5)"

    def test_subscribed_and_ingested_clears_the_hint(self, monkeypatch) -> None:
        """Критерий 2: ``watch_like_gui`` + первая дельта (снимок непуст) → hint НЕТ."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["state.subscribe"] = {"success": True, "sub_id": "s1"}
        responses["observability.tail.subscribe_all"] = {"success": True}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)

        watch_res = d.watch_like_gui(timeout=1.0)
        assert watch_res["success"] is True, "сцена обязана поднять watch, иначе тест ничего не проверяет"
        _feed_state(d, "processes.cam.workers.w1.state.fps", 12.5)  # первая дельта наполняет read-model

        snap = d.telemetry_snapshot()
        assert snap["ingest_active"] is True and snap["count"] > 0, "контроль сцены: read-model реально непуст"

        res = d.system_overview()
        assert res["telemetry"]["fps"], "сцена: snapshot.fps действительно непуст"
        assert _telemetry_hints(res) == [], "read-model уже наполнен подпиской — hint обязан пропасть"

    def test_subscribed_but_still_empty_is_not_flagged(self, monkeypatch) -> None:
        """Критерий 3 (ложноположительная половина): подписка активна, дельт ещё не было → hint НЕТ.

        Законное «дельт ещё не было», а не поломка. Тест обязан покраснеть, если
        реализация решит судить только по пустоте снимка и не посмотрит на
        ``ingest_active`` — ложный hint здесь хуже молчания (прямое требование
        задачи).
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["state.subscribe"] = {"success": True, "sub_id": "s1"}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)

        sub_res = d.state_subscribe("processes.**")
        assert sub_res["success"] is True, "сцена обязана зарегистрировать подписку"

        snap = d.telemetry_snapshot()
        assert snap["ingest_active"] is True, "контроль сцены: подписка активна"
        assert snap["count"] == 0, "контроль сцены: дельт ещё не было — снимок пуст ЗАКОННО"

        res = d.system_overview()
        assert res["telemetry"]["fps"] == {}, "сцена: snapshot.fps пуст, как и предполагает критерий 3"
        assert _telemetry_hints(res) == [], "снимок пуст ЗАКОННО (подписка есть, дельт не было) — ложный hint запрещён"
