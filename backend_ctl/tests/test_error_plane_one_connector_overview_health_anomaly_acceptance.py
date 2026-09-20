# -*- coding: utf-8 -*-
"""Приёмка (независимый тестер, plans/observability-closure): «один разъём на точку».

Критерий приёмки 1 (последняя часть, потреблена в Task 1.5): отказ, доехавший до
плоскости ошибок, обязан быть назван в ``system_overview().anomalies``.

Происхождение (чтобы перенос не выглядел потерей): файл написан СЛЕПЫМ тестером
на приёмке Task 1.3 (worktree ``D:/wt13``) и лежал непотреблённым до стенда фазы.
Его исходная форма («``health`` веткой внутри ``introspect.status``») была
объявлена самим тестером «моей моделью форм-фактора, не подтверждённым
контрактом» с прямым указанием переписать под реальную форму. Реальная форма
решена в Task 1.5: ``system_overview`` читает ветку ``processes.<p>.health`` из
УЖЕ получаемого state-поддерева (контракт ``process_module/health/schema.py``,
самопубликация heartbeat) — ноль новых IPC-команд, ноль новых round-trip.

Вторая правка модели тестера (тот же класс, что в его capture-файле, добор
2026-09-01): его сценарий «отказ ⇒ status=degraded» не воспроизводится продуктом —
``report_error`` растит ``errors`` и пишет ``last_error``, а статус меняет breaker
на пороге. Живой замер (стенд Б, 2026-09-01, камера device_id=7):
``health = {status: ok, errors: 1, last_error: {DeviceOpenFailed,
«не удалось открыть камеру 7», capture.start}}``. Поэтому приёмочный сценарий
отказа камеры проверяет аномалию по ``errors`` при ``status=ok``; сценарий
``degraded`` оставлен как исходное утверждение тестера (деградация статуса тоже
обязана быть названа).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.test_overview import _healthy_responses


def _fake_backend_with_health(
    monkeypatch,
    d: BackendDriver,
    *,
    procs: List[str],
    responses: Dict[str, Dict[str, Any]],
    health: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Как ``test_overview._fake_backend``, но state-поддерево несёт ветку health.

    ``health`` — {имя_процесса: ветка health} (процессы без записи едут без ветки,
    как старый бэкенд, у которого health ещё не публиковался).
    """
    sent: List[str] = []

    def fake_send(target: str, command: str, args: Any = None, *, timeout: Any = None) -> Dict[str, Any]:
        sent.append(command)
        if command == "state.get_subtree":
            subtree = {p: dict({"health": health[p]} if health and p in health else {}) for p in procs}
            return {"success": True, "result": {"subtree": subtree}}
        per_target = responses.get(f"{command}@{target}")
        if per_target is not None:
            return per_target
        return responses.get(command, {"success": False, "error": "нет ответа (fake)"})

    monkeypatch.setattr(d, "send_command", fake_send)
    return sent


class TestOverviewNamesHealthFailureAsAnAnomaly:
    def test_camera_open_failure_shape_produces_named_anomaly(self, monkeypatch) -> None:
        """Живая форма отказа камеры: status=ok, errors=1, last_error заполнен."""
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={
                "cam": {
                    "status": "ok",
                    "errors": 1,
                    "last_error": {
                        "type": "DeviceOpenFailed",
                        "message": "не удалось открыть камеру 7",
                        "context": "capture.start",
                        "ts": 1788259736.27,
                    },
                    "degraded_reason": None,
                    "updated_at": 1788259736.27,
                    "breaker": "closed",
                }
            },
        )
        res = d.system_overview()
        matches = [
            a for a in res["anomalies"] if "health" in str(a.get("kind", "")).lower() and a.get("process") == "cam"
        ]
        assert matches, (
            f"отказ камеры в плоскости ошибок (errors=1, last_error заполнен) не породил "
            f"ни одной именованной аномалии: {res['anomalies']}"
        )
        # Деталь называет сам отказ, а не только факт счётчика (добор 2026-09-01:
        # «"3" in blob» проходил и при потерянном контексте — здесь поле и значение).
        assert "не удалось открыть камеру 7" in matches[0].get("detail", ""), matches[0]
        assert "DeviceOpenFailed" in matches[0].get("detail", ""), matches[0]

    def test_degraded_health_produces_named_anomaly_but_ok_does_not(self, monkeypatch) -> None:
        # Контроль: health.status="ok", errors=0 — аномалии не было и не будет.
        d_ok = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d_ok,
            procs=["cam"],
            responses=_healthy_responses(),
            health={"cam": {"status": "ok", "errors": 0, "last_error": None, "degraded_reason": None}},
        )
        ok_res = d_ok.system_overview()
        assert not any("health" in str(a.get("kind", "")) for a in ok_res["anomalies"]), ok_res["anomalies"]

        # Позитив: деградация статуса обязана дать именованную аномалию с процессом
        # и причиной (исходное утверждение слепого тестера, форма — реальная).
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={
                "cam": {"status": "degraded", "errors": 0, "last_error": None, "degraded_reason": "камера отвалилась"}
            },
        )
        res = d.system_overview()
        matches = [
            a for a in res["anomalies"] if "health" in str(a.get("kind", "")).lower() and a.get("process") == "cam"
        ]
        assert matches, (
            f"health.status=degraded не породил ни одной именованной аномалии "
            f"(system_overview не знает о плоскости health вовсе): {res['anomalies']}"
        )
        assert "камера отвалилась" in matches[0].get("detail", ""), matches[0]
