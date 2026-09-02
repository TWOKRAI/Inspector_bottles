# -*- coding: utf-8 -*-
"""Task 2.9 — приёмка: ``observability_verified`` не молчит НИ ПРО ОДИН лист схемы.

Независимый тестер, RED-режим, ДО реализации (см. plans/observability-closure/,
Task 2.9). Контракт дан оркестратором текстом (сигнатура/ключи ответа), файлы
``managers/observability_reload.py`` и ``core/stats_manager.py`` — ЗАПРЕЩЕНЫ к
чтению; поведение изучено ТОЛЬКО чёрным ящиком — вызовами публичных функций,
разрешённых для импорта.

Цель по акс. критериям: любой лист схемы ``observability``, поданный в
``config.reload``, обязан ЛИБО сверяться с readback (попасть в ``checked``),
ЛИБО быть НАЗВАН ПОИМЁННО в ``unverifiable``. Состояние «подан, а вердикт
молчит» (``checked == 0`` и ``unverifiable == []`` при непустом запросе)
недопустимо ни для одного листа.

Черновой запуск (чёрным ящиком, ДО написания этого файла) показал: из 52
листьев схемы это состояние нарушают РОВНО ТРИ — ``heartbeat_interval_sec``,
``documents.factory``, ``documents.config``. Остальные 49 уже обрабатываются
верно. Это не догадка о причине — это симптом, полученный прогоном; причина
(таблица ли частных случаев внутри ``observability_reload.py`` не содержит эти
три ключа, или что-то иное) тестеру не видна и не проверялась — файл читать
запрещено.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.configs.observability_config import (
    expand_observability,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_verified,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager


# ============================================================================
# Критерий 1 — heartbeat_interval_sec: скалярный лист ВЕРХНЕГО уровня, который
# ни в один manager-конфиг не раскладывается (см. докстринг
# ObservabilityConfig.heartbeat_interval_sec в configs/observability_config.py —
# читает его ProcessHeartbeat напрямую, третья точка дороги —
# apply_heartbeat_interval в managers/observability_reload.py). Тест не читает
# ни ту, ни другую реализацию — сравнивает вход/выход чёрного ящика.
# ============================================================================


class TestHeartbeatIntervalScalarLeaf:
    """Ломает: любая версия ``observability_verified``, которая для этого
    конкретного верхнеуровневого поля не сравнивает requested/effective и не
    называет его в unverifiable — молча теряет лист (проверено чёрным ящиком:
    сегодня оба сценария ниже дают БУКВАЛЬНО {"verdict": "unverifiable",
    "checked": 0, "mismatches": [], "unknown_keys": [], "unverifiable": []} —
    то есть матч и промах неотличимы, оба выглядят как «не смотрели вовсе»)."""

    def test_matching_value_is_confirmed(self) -> None:
        result = observability_verified({"heartbeat_interval_sec": 1.0}, {"heartbeat_interval_sec": 1.0})
        assert result["checked"] == 1, result
        assert result["verdict"] == "confirmed", result
        assert result["unverifiable"] == [], result

    def test_mismatching_value_is_failed_with_named_mismatch(self) -> None:
        result = observability_verified({"heartbeat_interval_sec": 1.0}, {"heartbeat_interval_sec": 5.0})
        assert result["verdict"] == "failed", result
        assert result["mismatches"] == [{"key": "heartbeat_interval_sec", "expected": 1.0, "actual": 5.0}], result


# ============================================================================
# Критерий 2 — stats.enabled: имя И полярность ключа ПЛОСКОСТИ ЧИСЕЛ должны
# совпадать со схемой (``enabled: False`` = плоскость выключена) — и на живом
# StatsManager.observability_readback(), и через вердикт целиком.
# ============================================================================


class TestStatsPlaneEnabledSchemaName:
    """Дорога в три точки: схема → expand_observability → StatsManager(config)
    → observability_readback() — тот же приём, что у ``test_bucket_hazards.py``
    (``test_the_knob_travels_the_whole_three_point_road``). Никаких приватных
    атрибутов не читаем — только публичный readback."""

    def test_live_stats_manager_readback_exposes_enabled_key_direct_polarity(self) -> None:
        """Ломает: readback, называющий ключ иначе (или инвертирующий смысл) —
        например, "plane_disabled" вместо "enabled" — эту проверку красит.

        Черновой прогон чёрным ящиком (ДО написания этого теста) уже показал
        именно это: реальный ``StatsManager(config=...).observability_readback()``
        при ``stats.enabled: False`` отдаёт ключи
        ``{'aggregation_interval', 'enable_logging', 'flush_interval',
        'max_series', 'plane_disabled'}`` — БЕЗ ключа ``enabled`` вовсе, вместо
        него — ``plane_disabled`` (другое имя, инвертированная полярность).
        """
        cfg = expand_observability({"stats": {"enabled": False}})["stats"]
        mgr = StatsManager(config=cfg)
        mgr.initialize()
        try:
            back = mgr.observability_readback()
            assert "enabled" in back, f"readback без ключа схемы 'enabled': ключи {sorted(back.keys())}"
            assert back["enabled"] is False, f"неверная полярность у ключа 'enabled': {back.get('enabled')!r}"
        finally:
            mgr.shutdown()

    def test_live_stats_manager_readback_enabled_true_when_plane_on(self) -> None:
        """Пара к предыдущему: приём, а не только отказ (дефолт enabled=True)."""
        cfg = expand_observability({"stats": {}})["stats"]
        mgr = StatsManager(config=cfg)
        mgr.initialize()
        try:
            back = mgr.observability_readback()
            assert "enabled" in back, f"readback без ключа схемы 'enabled': ключи {sorted(back.keys())}"
            assert back["enabled"] is True
        finally:
            mgr.shutdown()

    def test_verdict_confirms_matching_stats_enabled(self) -> None:
        """Через вердикт целиком (используя РЕАЛЬНЫЙ readback, не выдуманный effective).

        Сегодня уже проходит (readback хоть и без 'enabled', вердикт для
        буквально сконструированного effective с ключом 'enabled' сравнивает
        корректно) — включён как акс.-критерий/регрессионный замок, а не как
        репродукция дефекта: если это разъедется, значит фикс полярности сломал
        сравнение внутри observability_verified.
        """
        result = observability_verified({"stats": {"enabled": False}}, {"stats": {"enabled": False}})
        assert result["verdict"] == "confirmed", result
        assert result["checked"] == 1, result

    def test_verdict_fails_on_mismatching_stats_enabled_with_named_mismatch(self) -> None:
        result = observability_verified({"stats": {"enabled": False}}, {"stats": {"enabled": True}})
        assert result["verdict"] == "failed", result
        assert result["mismatches"] == [{"key": "stats.enabled", "expected": False, "actual": True}], result


# ============================================================================
# Критерий 3 — инвариант: непустой запрос с листом, которого readback не
# отдаёт, ДОЛЖЕН отличаться от пустого запроса. Дословный сценарий из задания
# («сегодня они побайтно равны») воспроизведён через heartbeat_interval_sec.
# ============================================================================


class TestUnverifiableInvariant:
    def test_unknown_to_readback_leaf_is_named_not_silently_dropped(self) -> None:
        """documents.factory: readback её не публикует нигде (проверено ниже,
        сама секция также входит в критерий 4) — обязана попасть в
        unverifiable ПОИМЕННО, а не потеряться."""
        result = observability_verified({"documents": {"factory": "mymodule:factory"}}, {})
        assert result["checked"] == 0, result
        assert result["unverifiable"] != [], "лист подан, а вердикт молчит о нём — состояние 'нигде'"

    def test_response_to_nonempty_request_differs_from_empty_request(self) -> None:
        """Дословно критерий 3: сегодня оба ответа ниже побайтно равны.

        ``observability_verified({}, {})`` — пустой запрос, законно
        "unverifiable"/"checked=0"/"unverifiable=[]" (нечего было просить).
        ``observability_verified({"heartbeat_interval_sec": 1.0}, {...})`` —
        НЕПУСТОЙ запрос с совпадающим effective — обязан отличаться (хотя бы
        confirmed/checked=1), а не давать тот же самый ответ.
        """
        non_empty = observability_verified({"heartbeat_interval_sec": 1.0}, {"heartbeat_interval_sec": 1.0})
        empty = observability_verified({}, {})
        assert non_empty != empty, f"запрос с листом и пустой запрос дали ОДИНАКОВЫЙ ответ: {non_empty} == {empty}"


# ============================================================================
# Критерий 4 — страж покрытия схемы: каждый лист ObservabilityConfig, поданный
# ОДИН РАЗ против ПОЛНОСТЬЮ ПУСТОГО effective, обязан попасть в unverifiable
# ПОИМЕННО (checked не может быть > 0 — сравнивать не с чем). Инвариант один
# на все 52 листа: НЕ (checked == 0 И unverifiable == []).
#
# Листья перечислены явно (а не сгенерированы обходом model_fields в самом
# тесте) — обход схемы сделан один раз вручную по configs/observability_config.py
# и configs/observation_policy.py (оба файла читать разрешено — это схемы,
# а не запрещённая реализация проводки). Значения — литералы, НАМЕРЕННО не
# совпадающие со схемными дефолтами.
#
# Единственное исключение из полноты, явно поимённое: вложенные листья ВНУТРИ
# словарных полей верхнего уровня (например, отдельные поля MetricRule внутри
# ``observation.rules``, или произвольные под-ключи ``channels``/``scopes``) не
# перечисляются по отдельности — сама секция-контейнер (например
# ``observation.rules`` целиком) уже проверяется одной строкой ниже, а её
# дальнейшая внутренняя структура — предмет ДРУГОЙ схемы (MetricRule), не
# ObservabilityConfig.
# ============================================================================

_LEAF_CASES: Dict[str, Dict[str, Any]] = {
    "log_level": {"log_level": "WARNING"},
    "log_directory": {"log_directory": "/tmp/probe_dir"},
    "console": {"console": False},
    "file": {"file": False},
    "channels": {"channels": {"probe": {"enabled": False}}},
    "scopes": {"scopes": {"BUSINESS": {"channels": ["probe"]}}},
    "loggers": {"loggers": {"some.prefix": {"level": "DEBUG"}}},
    "logger_groups": {"logger_groups": {"noisy": ["some.prefix"]}},
    "session_ttl_sec": {"session_ttl_sec": 42.0},
    "heartbeat_interval_sec": {"heartbeat_interval_sec": 2.0},
    "retention_days": {"retention_days": 7},
    "retention_total_mb": {"retention_total_mb": 500},
    "compress_rotated": {"compress_rotated": True},
    "retention_sweep_interval_sec": {"retention_sweep_interval_sec": 100.0},
    "sampling_first_n": {"sampling_first_n": 5},
    "sampling_every_mth": {"sampling_every_mth": 10},
    "sampling_burst_reset_sec": {"sampling_burst_reset_sec": 30.0},
    "sampling_max_level": {"sampling_max_level": "WARNING"},
    "errors.enabled": {"errors": {"enabled": False}},
    "errors.level": {"errors": {"level": "ERROR"}},
    "errors.include_stacktrace": {"errors": {"include_stacktrace": False}},
    "errors.channels": {"errors": {"channels": {"errors_file": {"enabled": False}}}},
    "stats.enabled": {"stats": {"enabled": False}},
    "stats.log_snapshots": {"stats": {"log_snapshots": False}},
    "stats.aggregation_interval": {"stats": {"aggregation_interval": 20.0}},
    "stats.flush_interval": {"stats": {"flush_interval": 3.0}},
    "stats.log_level": {"stats": {"log_level": "DEBUG"}},
    "stats.log_line_max_bytes": {"stats": {"log_line_max_bytes": 500}},
    "stats.max_series": {"stats": {"max_series": 77}},
    "stats.channels": {"stats": {"channels": {"file_stats": {"enabled": False}}}},
    "commands.log_success": {"commands": {"log_success": True}},
    "documents.factory": {"documents": {"factory": "mymodule:factory"}},
    "documents.config": {"documents": {"config": {"db_path": "x.db"}}},
    "events.first_n": {"events": {"first_n": 5}},
    "events.every_mth": {"events": {"every_mth": 3}},
    "flight.enabled": {"flight": {"enabled": True}},
    "flight.sink": {"flight": {"sink": "probe_ring"}},
    "flight.keep": {"flight": {"keep": 2}},
    "flight.limit": {"flight": {"limit": 100}},
    "observation.subtree_enabled": {"observation": {"subtree_enabled": False}},
    "observation.subtree_interval_sec": {"observation": {"subtree_interval_sec": 3.0}},
    "observation.rules": {"observation": {"rules": {"processes.*.state.plugins.*.fps": {"enabled": False}}}},
    "voices.default_window_sec": {"voices": {"default_window_sec": 2.0}},
    "voices.escalate_after_repeats": {"voices": {"escalate_after_repeats": 5}},
    "voices.max_tracked_keys": {"voices": {"max_tracked_keys": 100}},
    "voices.stale_windows": {"voices": {"stale_windows": 3}},
    "history.enabled": {"history": {"enabled": False}},
    "history.level": {"history": {"level": "WARNING"}},
    "history.max_rows": {"history": {"max_rows": 1000}},
    "history.max_age_sec": {"history": {"max_age_sec": 3600.0}},
    "history.purge_interval_sec": {"history": {"purge_interval_sec": 60.0}},
    "history.db_path": {"history": {"db_path": "/tmp/hist.db"}},
}


class TestSchemaCoverageGuard:
    """52 листа ObservabilityConfig — каждый один раз против {} effective.

    Ломает: реализация, у которой список «известных» верхнеуровневых/вложенных
    ключей для маппинга schema→manager неполон (не содержит какой-то из этих
    путей) — тот лист выпадет из БЕЗ переклички ни с checked, ни с unverifiable.
    Черновой прогон чёрным ящиком (до написания этого файла) показал ровно 3
    таких случая из 52: heartbeat_interval_sec, documents.factory,
    documents.config — остальные 49 уже проходят инвариант.
    """

    @pytest.mark.parametrize("leaf_name,requested", list(_LEAF_CASES.items()), ids=list(_LEAF_CASES.keys()))
    def test_leaf_is_checked_or_named_never_nowhere(self, leaf_name: str, requested: Dict[str, Any]) -> None:
        result = observability_verified(requested, {})
        assert result["checked"] == 0, (
            f"{leaf_name}: effective полностью пуст, сравнивать не с чем, а checked={result['checked']} > 0 — "
            f"вердикт заявляет проверку там, где её не было: {result}"
        )
        assert result["unverifiable"] != [], (
            f"{leaf_name}: лист подан ({requested}), effective пуст, а unverifiable пуст и checked=0 — "
            f"лист пропал из вердикта молча (состояние 'нигде'): {result}"
        )


# ============================================================================
# Критерий 5 — полный раунд-трип секции stats.* (+ heartbeat_interval_sec)
# против ПОЛНОГО readback. Разбит на два теста намеренно (правило «один тест —
# одна проверка»): (a) поля, которые живой StatsManager.observability_readback()
# СЕГОДНЯ реально возвращает — здесь единственная причина возможного красного
# это heartbeat_interval_sec.
#
# (b) — ПРАВКА оркестратора поверх черновика тестера (Task 2.9 реализации,
# зафиксировано в спеке задачи; тестер писал это ДО реализации и не видел
# `stats_manager.py`). Черновая редакция требовала `unverifiable == []` для
# ВСЕЙ секции `stats.*` (все 7 листьев) сразу, включая `log_level` и
# `log_line_max_bytes` — но эти два ключа читаются у ЖИВОГО КАНАЛА ЛОГОВ
# (`StatsManager.observability_readback`, `stats_manager.py`), а канал
# существует ТОЛЬКО когда есть живой `logger_manager` (`_build_log_channel`
# возвращает `None`, если `get_manager("logger")` и `process.logger_manager`
# оба пусты) И `log_snapshots` не выключен. Черновой сценарий строил голый
# `StatsManager(config=...)` БЕЗ `logger_manager` вовсе — то есть канал не
# поднимался НИ ПРИ каком значении `log_snapshots`, и требовать confirmed для
# этих двух ключей значило бы требовать ЭХА запроса вместо честного readback'а
# (запрещено правилом проекта: «readback живой, не эхо»; см. докстринг
# `StatsManager.observability_readback` — воспроизведено ДО правки этого
# теста: `mgr.observability_readback()` без `logger_manager` не отдаёт ни
# `log_level`, ни `log_line_max_bytes` НИ ПРИ `log_snapshots=True`, ни при
# `log_snapshots=False`).
#
# Решение (b1)+(b2): проверять КОНТРАКТ, а не эхо. (b1) — полная секция при
# РЕАЛЬНО вписанном `logger_manager` (`managers={"logger": lm}`, тот же
# конструкторский параметр, что использует боевая сборка) и `log_snapshots:
# True` — канал существует, все семь листьев секции живые, `unverifiable ==
# []` держит буквально. (b2) — та же секция при `log_snapshots: False` —
# канала нет, и `stats.log_level`/`stats.log_line_max_bytes` ОБЯЗАНЫ быть
# названы в `unverifiable` ПОИМЁННО (это и есть инвариант критерия 3,
# применённый к живому объекту, а не выдуманному `effective`). Оба варианта
# проверены прогоном ДО правки теста (пробный `python -c` с `managers={"logger":
# lm}`): `log_snapshots=True` → оба ключа в readback; `log_snapshots=False` →
# ни одного — подтверждено вручную, а не предположено.
# ============================================================================


class TestFullRoundTripStatsPlusHeartbeat:
    def test_confirmed_for_fields_the_live_readback_already_exposes(self) -> None:
        """(a) aggregation_interval/flush_interval/log_snapshots/max_series —
        все они СЕГОДНЯ реально есть в StatsManager.observability_readback()
        (проверено чёрным ящиком). Единственная ожидаемая причина красного —
        heartbeat_interval_sec (критерий 1): без его фикса checked будет 4
        вместо 5, хотя unverifiable может остаться пустым (тихая недосчитанность,
        а не явный отказ, — ровно та ловушка, которую критерий 3 и называет)."""
        requested_stats = {
            "log_snapshots": False,
            "aggregation_interval": 20.0,
            "flush_interval": 5.0,
            "max_series": 77,
        }
        expanded = expand_observability({"stats": requested_stats})
        mgr = StatsManager(config=expanded["stats"])
        mgr.initialize()
        try:
            real_readback = mgr.observability_readback()
            requested = {"heartbeat_interval_sec": 2.0, "stats": requested_stats}
            effective = {"heartbeat_interval_sec": 2.0, "stats": real_readback}
            result = observability_verified(requested, effective)
        finally:
            mgr.shutdown()

        assert result["mismatches"] == [], result
        assert result["unverifiable"] == [], result
        assert result["checked"] == 5, (
            f"ожидалось 5 сверенных листьев (4 из stats.* + heartbeat_interval_sec), "
            f"получено {result['checked']} — heartbeat, вероятно, посчитан молча пропущенным: {result}"
        )
        assert result["verdict"] == "confirmed", result

    @staticmethod
    def _stats_verified_with_live_logger(requested_stats: Dict[str, Any], *, tag: str) -> Dict[str, Any]:
        """Полная секция stats.* против РЕАЛЬНОГО readback, с настоящим `LoggerManager`
        вписанным конструкторским параметром `managers={"logger": ...}` (тем же приёмом,
        что боевая сборка процесса — не приватным атрибутом и не monkeypatch).

        Один живой логгер на оба теста (b1)/(b2) — единственная переменная между ними
        это `log_snapshots`, поэтому расхождение в unverifiable доказуемо приписать
        именно ему, а не разнице харнессов.
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"f2_t29_stats_{tag}_"))
        try:
            logger_manager = LoggerManager(
                manager_name=f"f2_t29_logger_{tag}",
                config=LoggerManagerConfig(app_name=f"f2_t29_{tag}", log_directory=str(tmp_dir)),
            )
            logger_manager.initialize()
            try:
                expanded = expand_observability({"stats": requested_stats})
                mgr = StatsManager(config=expanded["stats"], managers={"logger": logger_manager})
                mgr.initialize()
                try:
                    real_readback = mgr.observability_readback()
                    requested = {"heartbeat_interval_sec": 2.0, "stats": requested_stats}
                    effective = {"heartbeat_interval_sec": 2.0, "stats": real_readback}
                    return observability_verified(requested, effective)
                finally:
                    mgr.shutdown()
            finally:
                logger_manager.shutdown()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_confirmed_for_the_entire_stats_section_with_a_live_log_channel(self) -> None:
        """(b1) Правка оркестратора поверх чернового единого теста (см. комментарий
        блока выше критерия 5): секция stats.* + heartbeat_interval_sec, с ЖИВЫМ
        logger_manager — канал логов существует (`_build_log_channel` находит
        получателя), поэтому все запрошенные листья имеют живого читателя и
        подтверждаемы буквально.

        ``log_snapshots`` СОЗНАТЕЛЬНО не запрошен явно (а не запрошен как
        ``True``): его СХЕМНЫЙ дефолт уже ``True`` — ровно то, что нужно каналу,
        чтобы существовать, — а правило проекта требует значений, ОТЛИЧНЫХ от
        дефолта (иначе совпадение с дефолтом маскирует «ничего не применилось»).
        Подать явное ``log_snapshots: True`` здесь значило бы подать дефолт: путь
        `stats.enable_logging` совпал бы с ``baseline`` («запрос этот путь не
        менял») и молча выпал бы из счёта — не ошибка вердикта, а его СУЩЕСТВУЮЩЕЕ
        правило «совпало с дефолтом → не считать», просто применённое к ключу,
        который здесь не предмет проверки. Поэтому лист попросту не запрашивается:
        канал жив за счёт СХЕМНОГО умолчания, а не операторской правки, и это не
        то же самое свойство, что держат остальные шесть листьев ниже."""
        requested_stats = {
            "enabled": False,
            "aggregation_interval": 20.0,
            "flush_interval": 5.0,
            "log_level": "DEBUG",
            "log_line_max_bytes": 500,
            "max_series": 77,
        }
        result = self._stats_verified_with_live_logger(requested_stats, tag="on")

        assert result["mismatches"] == [], result
        assert result["unverifiable"] == [], (
            f"полная секция stats.*+heartbeat при живом канале логов обязана дать unverifiable=[]: {result}"
        )
        assert result["checked"] == 7, (
            f"ожидалось 7 сверенных листьев (6 запрошенных из stats.* + heartbeat_interval_sec), "
            f"получено {result['checked']}: {result}"
        )
        assert result["verdict"] == "confirmed", result

    def test_stats_log_channel_fields_are_named_unverifiable_without_a_live_channel(self) -> None:
        """(b2) Та же секция и тот же живой logger_manager, но log_snapshots=False —
        `_build_log_channel` не собирает канал (судьбу канала решает log_snapshots,
        не наличие logger_manager), поэтому stats.log_level/stats.log_line_max_bytes
        обязаны быть названы в unverifiable ПОИМЁННО — это и есть инвариант критерия 3
        («подан, а вердикт молчит — недопустимо»), применённый к живому объекту, а не
        к сконструированному effective."""
        requested_stats = {
            "enabled": False,
            "log_snapshots": False,
            "aggregation_interval": 20.0,
            "flush_interval": 5.0,
            "log_level": "DEBUG",
            "log_line_max_bytes": 500,
            "max_series": 77,
        }
        result = self._stats_verified_with_live_logger(requested_stats, tag="off")

        assert result["mismatches"] == [], result
        assert set(result["unverifiable"]) == {"stats.log_level", "stats.log_line_max_bytes"}, (
            f"без живого канала логов эти два листа обязаны быть названы поимённо, не пропасть молча: {result}"
        )
        assert result["checked"] == 6, (
            f"ожидалось 6 сверенных листьев (5 из stats.* + heartbeat_interval_sec, без "
            f"log_level/log_line_max_bytes — у них нет живого канала), получено {result['checked']}: {result}"
        )
        assert result["verdict"] == "confirmed", (
            f"расхождений нет, 6 путей сверены и совпали — ложный failed/unverifiable здесь тоже был бы дефектом: "
            f"{result}"
        )
