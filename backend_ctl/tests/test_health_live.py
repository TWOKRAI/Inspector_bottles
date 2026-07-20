# -*- coding: utf-8 -*-
"""Live-тест Ф2 Task 2.1: наблюдаемость отказов через driver (acceptance).

harness_smoke: ошибка в процессе (диагностический впрыск ``health.report``) →
HealthState → self-publish через heartbeat → state-дерево ``processes.<name>.health.*``
→ driver ловит дельту через state_subscribe/events(). Это и есть acceptance:
«ошибка плагина видна в state-дереве и через driver».

Собственная module-фикстура на УНИКАЛЬНОМ порту (≥8770) — не переиспользуем общий
``headless_backend`` (порт 8765): ловушка «двух бэкендов» (см. backend_ctl/AGENTS.md,
project_concurrent_backends_trap) — свой порт изолирует этот бэкенд от чужих.
"""

from __future__ import annotations

import time
from backend_ctl.protocol import unwrap

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.tests.conftest import bookmark_cursor as _bookmark
from backend_ctl.tests.conftest import page_events as _page

_PROC = "preprocessor"  # тот же процесс, что в live-тестах Ф1
_PORT = 8774  # уникальный порт этого модуля (≥8770)


@pytest.fixture(scope="module")
def health_backend():
    """Свой headless-бэкенд на уникальном порту (изоляция от общей session-фикстуры)."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


def _collect_health_deltas(drv, deadline: float, *, want: tuple = ("errors", "last_error")) -> dict:
    """Слить события до дедлайна, вернуть {path: new_value} по health-путям процесса.

    Поля публикуются leaf-wise (по одному proxy.set) и приезжают ОТДЕЛЬНЫМИ
    дельтами, возможно в разных state.changed-пачках. Ранний выход — только когда
    собраны ВСЕ ожидаемые ``want``-листья (регресс: обрыв по первому ``errors``
    гонял last_error и давал флак).

    F.1: events_page курсором, персистентным на driver'е между вызовами этой функции
    в разных тестах модуля (``_health_test_cursor``) — вперёд-только чтение, как было
    у legacy events() (единый курсор драйвера), но недеструктивно.
    """
    prefix = f"processes.{_PROC}.health."
    found: dict = {}
    cursor = getattr(drv, "_health_test_cursor", None)
    while time.time() < deadline:
        evts, cursor = _page(drv, cursor)
        drv._health_test_cursor = cursor
        for e in evts:
            if e.get("command") != "state.changed":
                continue
            for d in (e.get("data") or {}).get("deltas", []) or []:
                path = d.get("path", "")
                if path.startswith(prefix):
                    found[path] = d.get("new_value")
        if all(f"{prefix}{leaf}" in found for leaf in want):
            break
        if not evts:
            time.sleep(0.2)
    return found


@pytest.mark.harness_smoke
def test_report_error_visible_in_state_tree_via_driver(health_backend) -> None:
    """report_error процесса виден в state-дереве и через driver (acceptance 2.1)."""
    drv = health_backend

    sub = unwrap(drv.state_subscribe(f"processes.{_PROC}.**", timeout=8.0), leaf=True)
    assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"

    drv._health_test_cursor = _bookmark(drv)  # осушить накопленное до провокации

    # Провокация: диагностический впрыск health-события в живой процесс.
    res = unwrap(
        drv.send_command(
            _PROC,
            "health.report",
            {"context": "selftest", "message": "camera lost"},
            timeout=5.0,
        ),
        leaf=True,
    )
    assert res.get("success") is True, f"health.report не success: {res}"
    assert res.get("errors", 0) >= 1, res

    # Дельта здоровья должна догнать нас в пределах пары тактов heartbeat.
    deltas = _collect_health_deltas(drv, deadline=time.time() + 20.0)

    errors_path = f"processes.{_PROC}.health.errors"
    last_error_path = f"processes.{_PROC}.health.last_error"
    status_path = f"processes.{_PROC}.health.status"

    assert errors_path in deltas, f"нет дельты health.errors; собрано: {sorted(deltas)}"
    assert isinstance(deltas[errors_path], int) and deltas[errors_path] >= 1, deltas[errors_path]

    # last_error виден и несёт наш синтетический тип/контекст.
    assert last_error_path in deltas, f"нет дельты last_error; собрано: {sorted(deltas)}"
    last = deltas[last_error_path]
    assert isinstance(last, dict), last
    assert last.get("type") == "HealthSelfTestError", last
    assert last.get("context") == "selftest", last

    # status опубликован (остался ok — report_error сам по себе не деградирует).
    assert deltas.get(status_path, "ok") == "ok"


@pytest.mark.harness_smoke
def test_health_status_command_reads_snapshot(health_backend) -> None:
    """health.status возвращает снапшот здоровья процесса (быстрый read-путь)."""
    drv = health_backend
    res = unwrap(drv.send_command(_PROC, "health.status", timeout=5.0), leaf=True)
    assert res.get("success") is True, res
    health = res.get("health") or {}
    # Контракт снапшота: ровно поля схемы (сверяем со схемой, не с копией списка —
    # Task 2.2 добавил breaker, копии в тестах устаревают молча).
    from multiprocess_framework.modules.process_module.health.schema import HEALTH_FIELDS

    assert set(health.keys()) == set(HEALTH_FIELDS)
    assert health["status"] in ("ok", "degraded", "failed")
    assert isinstance(health["errors"], int)
    assert health["breaker"] in ("closed", "open", "half_open")


@pytest.mark.harness_smoke
def test_breaker_opens_and_degrades_after_n_consecutive_errors(health_backend) -> None:
    """Acceptance Ф2.2: N подряд report_error → breaker open → health degraded.

    Порог по умолчанию 5 (INSPECTOR_HEALTH_BREAKER_THRESHOLD) — впрыскиваем 5 ошибок
    подряд через health.report и ждём в state-дереве status=degraded + breaker=open.
    """
    drv = health_backend
    for i in range(5):
        res = unwrap(
            drv.send_command(
                _PROC,
                "health.report",
                {"context": "breaker-acceptance", "message": f"fail #{i}"},
                timeout=5.0,
            ),
            leaf=True,
        )
        assert res.get("success") is True, res

    deltas = _collect_health_deltas(drv, deadline=time.time() + 20.0, want=("status", "breaker"))
    status_path = f"processes.{_PROC}.health.status"
    breaker_path = f"processes.{_PROC}.health.breaker"
    assert deltas.get(breaker_path) == "open", f"breaker не open; собрано: {deltas}"
    assert deltas.get(status_path) == "degraded", f"status не degraded; собрано: {deltas}"
    reason = deltas.get(f"processes.{_PROC}.health.degraded_reason")
    assert reason and "breaker" in str(reason), reason
