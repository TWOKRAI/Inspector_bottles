# -*- coding: utf-8 -*-
"""Task 1.2 плана observability-closure — независимый тестер, ДО реализации.

Источник контракта: акцептанс-критерии задачи (переданы координатором, НЕ читались
из ``plans/observability-closure/**`` — запрещённый путь для этого файла). Проверяются
две живые части контракта, завязанные именно на РЕАЛЬНЫЙ запущенный ``ProcessManager``
(поэтому не unit-тест, а ``harness_smoke``):

2. ``introspect.observability(ProcessManager).counters.logger.unresolved_channel_records
   == 0`` на чистом старте.
3. ``system_overview().anomalies`` не содержит ``observability_loss`` для
   ``ProcessManager`` на чистом старте.

Живой замер координатора ДО фикса (2026-08-29): ``unresolved_channel_records == 12``
у ProcessManager на чистом старте.

**Boot: реальная топология прототипа (``BackendHarness(with_base=True)``), НЕ
``examples/minimal_app``.** Первая редакция этого файла поднимала лёгкий
framework-only ``minimal_app`` (2 процесса, ``app_module.build_app``) — дешевле, но
это оказалось ЛОЖНЫМ УПРОЩЕНИЕМ: ручной замер на нём дал
``unresolved_channel_records == 0`` уже СЕГОДНЯ, до всякого фикса — дефект на
минимальном дереве не воспроизводится вовсе (2 процесса, мало каналов, видимо не
попадает в то же окно гонки при старте ProcessManager). Ручной замер на
``BackendHarness(with_base=True)`` (полная топология прототипа, 9 процессов)
воспроизвёл ровно заявленную координатором величину — 12. Тест обязан ловить
регрессию на ТОЙ конфигурации, где дефект реально есть, поэтому здесь — боевая
топология прототипа, дороже по времени (~секунды больше), но не подделка.
"""

from __future__ import annotations

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness

_PORT = 8813  # уникальный порт этого модуля (свободен на момент написания, см. AGENTS.md)


@pytest.fixture(scope="module")
def clean_start_backend(tmp_path_factory: pytest.TempPathFactory):
    """Один headless-boot прототипа (``with_base=True``) на весь модуль — оба теста
    читают ОДИН чистый старт.

    Каталог логов — свой temp (``BackendHarness(log_dir=...)``), не cwd репозитория.
    """
    log_dir = tmp_path_factory.mktemp("t12_clean_start_log")
    harness = BackendHarness(with_base=True, port=_PORT, log_dir=log_dir)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
class TestProcessManagerLoggerPlaneOnCleanStart:
    """Критерий 2: unresolved_channel_records у ProcessManager обязан быть 0."""

    def test_unresolved_channel_records_is_zero_on_clean_start(self, clean_start_backend: BackendDriver) -> None:
        drv = clean_start_backend
        counters = drv.observability_counters("ProcessManager", flush=True, timeout=15.0)

        assert counters.ok, f"introspect.observability(ProcessManager) не ответила: {counters.raw!r}"
        assert counters.planes is not None, f"секция counters отсутствует в ответе: {counters.raw!r}"

        logger_plane = counters.planes.get("logger")
        assert isinstance(logger_plane, dict), f"секция planes.logger отсутствует или не dict: {counters.planes!r}"
        value = logger_plane.get("unresolved_channel_records")
        assert value == 0, (
            "unresolved_channel_records ожидался 0 на чистом старте ProcessManager, "
            f"получено {value!r}. Живой замер координатора до фикса — 12. "
            f"logger_plane={logger_plane!r}"
        )


@pytest.mark.harness_smoke
class TestSystemOverviewNoObservabilityLossForProcessManager:
    """Критерий 3: анти-двойник критерия 2 — тот же дефект глазами ``system_overview``."""

    def test_no_observability_loss_anomaly_for_process_manager(self, clean_start_backend: BackendDriver) -> None:
        drv = clean_start_backend
        overview = drv.system_overview(timeout=20.0)

        assert overview.get("success") is True, f"system_overview не success: {overview!r}"
        anomalies = overview.get("anomalies", [])
        hits = [a for a in anomalies if a.get("kind") == "observability_loss" and a.get("process") == "ProcessManager"]
        assert not hits, (
            "system_overview().anomalies содержит observability_loss для ProcessManager "
            f"на чистом старте: {hits}. Полный список аномалий: {anomalies}"
        )
