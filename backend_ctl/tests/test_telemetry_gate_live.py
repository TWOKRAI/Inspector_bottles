# -*- coding: utf-8 -*-
"""Task 6.1 ГАП 1 — ``telemetry_set``/``telemetry_reconfigure`` реально меняют gate на
живом бэкенде, доказано ДЕТЕРМИНИРОВАННО (не гонкой).

Замер координатора (2026-07-22): publisher-enable/disable САМ ПО СЕБЕ не имеет
детерминированного black-box наблюдателя в снимке read-model'а — там хранится только
ПОСЛЕДНЕЕ значение метрики, отдельного per-path ingest-счётчика нет, поэтому «частота
публикации изменилась» пришлось бы ловить статистически (несколько замеров интервалов
между точками истории) — флаки по конструкции.

Детерминированный наблюдатель есть — серверный флаг ``capped_by_throttle``
(``multiprocess_framework/modules/process_module/managers/telemetry_reload.py:
detect_throttle_caps``, driver.py:606-736): он вычисляется СИНХРОННО внутри самой
команды ``telemetry.broadcast`` сравнением объявленного publisher-``interval_sec`` с
живым central-правилом ``ThrottleMiddleware`` оркестратора — НЕ зависит от того, успела
ли реальная телеметрия физически потечь по дереву. Пара ON/OFF строится без единого
``time.sleep``-ожидания ingest'а (в отличие от ``test_ingest_active_and_ingested_total_live``
в ``test_telemetry_driver.py``, которому нужен реальный ingest):

  - **ON:** сперва явно ужесточить central-правило (``plane="throttle"``, интервал
    заведомо больше дефолтного мягкого предохранителя 0.05с — см.
    ``multiprocess_prototype/backend/state/manager_setup.py:_default_throttle_rules``),
    затем поднять publisher-частоту ТОЙ ЖЕ метрики НИЖЕ этого правила → ответ несёт
    ``capped_by_throttle`` с обеими сторонами конфликта.
  - **OFF:** та же publisher-правка БЕЗ предварительного ужесточения (дефолтный мягкий
    троттл 0.05с мягче любого разумного ``interval_sec``, см. эталонный unit
    ``test_no_flag_with_soft_default_throttle`` в ``test_telemetry_broadcast.py``) →
    ``capped_by_throttle`` в ответе отсутствует.

Метрика ``fps`` и glob ``processes.**.state.fps`` — фан-аут на ВСЕХ процессов рецепта
(process="all"), поэтому тест не зависит от конкретных имён процессов топологии
``region_pipeline`` (не хардкодит ``camera_0``) — переживёт смену топологии рецепта.
"""

from __future__ import annotations

import pytest

from backend_ctl.harness import BackendHarness

_PORT = 8796  # уникальный порт этого модуля (назначен координатором, Task 6.1 плана)


@pytest.mark.harness_smoke
def test_capped_by_throttle_appears_when_central_rule_is_stricter_live() -> None:
    """ON: строгое central-правило + поднятие publisher-частоты НИЖЕ него → флаг виден."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()

        # Снимок ДО — контекст: свежий driver, read-model ещё пуст.
        before = drv.telemetry_snapshot()
        assert before["count"] == 0

        # Central-правило заведомо строже дефолтного мягкого предохранителя (0.05с):
        # 5с не пропустит ничего чаще раза в 5 секунд.
        throttle_res = drv.telemetry_set("all", "processes.**.state.fps", interval_sec=5.0, plane="throttle")
        assert throttle_res["success"] is True
        assert throttle_res["throttle"]["applied"] is True

        # Publisher поднимает частоту fps НИЖЕ central-правила (0.1с < 5.0с) — троттл
        # НЕ ослабляется автоматически («no silent caps», ADR-PM-017): ответ обязан
        # явно предупредить, а не тихо доставить publish и молча срезать в дереве.
        gate_res = drv.telemetry_set("all", "fps", enabled=True, interval_sec=0.1, plane="publisher")
        assert gate_res["success"] is True
        caps = gate_res["publish"].get("capped_by_throttle")
        assert caps is not None, "central-правило строже publisher-интервала — cap обязан быть виден"
        assert caps == {"fps": {"publisher_interval_sec": 0.1, "throttle_interval_sec": 5.0}}
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_capped_by_throttle_absent_under_default_soft_rule_live() -> None:
    """OFF: без предварительного ужесточения та же publisher-правка не несёт флага."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()

        # Ни одного telemetry_set(plane="throttle") не звалось — central-правила те же,
        # что boot-дефолты (мягкий предохранитель 0.05с, заведомо мягче 0.1с publisher).
        gate_res = drv.telemetry_set("all", "fps", enabled=True, interval_sec=0.1, plane="publisher")
        assert gate_res["success"] is True
        assert "capped_by_throttle" not in gate_res["publish"]
    finally:
        harness.stop()
