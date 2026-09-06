# -*- coding: utf-8 -*-
"""Ф2, задача 2.2 — добор ADR-PM-047: живая половина критерия приёмки по `history`.

Критерий приёмки задачи 2.2 (дословно, из плана): «Живьём:
`config_reload_verified(seg, history.level=WARNING)` → `confirmed`; **стор
перестаёт принимать INFO** (пара: до/после по счётчику строк)». Первая
половина была закрыта самой задачей 2.2 (readback честно показывает новый
уровень политики) — вторая была НАЗВАНА в ADR-PM-047 как остаток и НЕ
закрыта: живой SQLite-тап (`StoreTapChannel`) держал порог, выставленный
РОВНО ОДИН РАЗ на подъёме, и продолжал принимать INFO после
`config.reload {"history": {"level": "WARNING"}}}` вопреки вердикту
`confirmed` — ложный `confirmed`, худший класс вердикта этой фазы.

Харнесс — `_real_wired` из `test_f2_task22_schema_wiring.py` (НАСТОЯЩИЙ
`LoggerManager`/`ErrorManager`/`CommandManager`, вход — `handle_command` тем
же способом, каким доезжает IPC), плюс РЕАЛЬНЫЙ `ObservabilityStore`,
поднятый так же, как его поднимает `ProcessModule._wire_observability_hub`
на боевом старте. Это ОТДЕЛЬНЫЙ уровень проверки от
`test_observability_store_wiring.py::TestReapplyStoreLevel` — тот проверяет
МЕХАНИЗМ (`reapply_observability_store_level`) в изоляции с фальшивкой,
этот — что `_cmd_config_reload` реально ЗОВЁТ механизм на живом входе
команды, а не просто что механизм умеет работать сам по себе.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    resolve_history_policy,
    unwire_observability_store,
    wire_observability_store,
)

from .test_f2_task22_schema_wiring import _real_wired, _reload


class TestHistoryLevelReappliesLiveOnConfigReload:
    """Живая половина критерия 1 приёмки задачи 2.2 (ADR-PM-047, остаток)."""

    def test_confirmed_verdict_and_the_store_actually_stops_accepting_info(self) -> None:
        store_dir = Path(tempfile.mkdtemp(prefix="f2_t22_hist_store_"))
        try:
            with _real_wired("hist_reapply") as (process, logger, error, command_manager):
                store, taps = wire_observability_store(
                    error_manager=error,
                    logger_manager=logger,
                    db_path=str(store_dir / "obs.db"),
                    process=process.name,
                    min_level="INFO",
                )
                process._observability_store = store
                process._observability_store_taps = taps
                # Тот же снимок, что кладёт `_wire_observability_hub` на подъёме
                # (`process_module.py:582`) — стартовая политика читается из ПУСТЫХ
                # слоёв и совпадает с `min_level="INFO"` строкой выше.
                process._observability_history_policy = resolve_history_policy(process)
                try:
                    # ДО правки: порог INFO — INFO-запись обязана лечь в стор.
                    # `module="probe"` — фильтр, отсекающий INFO-строки АУДИТА
                    # самого `config.reload` (`[observability-audit] touch/rebuild`,
                    # «пересобрано из слоя ...») — они законно пишутся ДО того, как
                    # `reapply_observability_store_level` поднимет порог (аудит —
                    # часть обработки команды, а не пробный сигнал теста), и без
                    # фильтра засоряли бы счётчик ПАРЫ, которую проверяет этот тест.
                    logger.info("до правки: рутина", module="probe")
                    store.flush_writers()  # Task 3.3: дожать очередь store-tap'а ДО чтения
                    before = store.list_records(process=process.name, module="probe", severity_in=["info"])
                    assert len(before) == 1, f"порог INFO обязан пропускать INFO ДО правки: {before}"

                    result = _reload(command_manager, {"history": {"level": "WARNING"}})

                    assert result.get("success") is True, result
                    verified = result.get("verified") or {}
                    assert verified.get("verdict") == "confirmed", (
                        f"первая половина критерия приёмки 2.2: readback обязан подтвердить "
                        f"смену history.level немедленно: {verified}"
                    )
                    assert result.get("effective", {}).get("history", {}).get("level") == "WARNING", result

                    # ПОСЛЕ правки: порог WARNING — вторая INFO-запись НЕ имеет права
                    # лечь в стор (вторая половина критерия приёмки, ранее не
                    # закрытая — см. ADR-PM-047).
                    logger.info("после правки: рутина", module="probe")
                    store.flush_writers()  # Task 3.3: дожать очередь store-tap'а ДО чтения
                    after_info = store.list_records(process=process.name, module="probe", severity_in=["info"])
                    assert len(after_info) == 1, (
                        f"стор ПРОДОЛЖИЛ принимать INFO после config.reload history.level=WARNING "
                        f"(ложный confirmed, ADR-PM-047): {after_info}"
                    )

                    # WARNING по-прежнему проходит — порог поднят, а не заглушен целиком.
                    logger.warning("после правки: тревога", module="probe")
                    store.flush_writers()  # Task 3.3: дожать очередь store-tap'а ДО чтения
                    after_warning = store.list_records(process=process.name, module="probe", severity_in=["warning"])
                    assert len(after_warning) == 1, f"WARNING обязан лечь в стор при пороге WARNING: {after_warning}"
                finally:
                    unwire_observability_store(store, process._observability_store_taps)
        finally:
            shutil.rmtree(store_dir, ignore_errors=True)

    def test_reloading_with_the_same_level_does_not_recreate_taps(self) -> None:
        """Пара-контроль: `config.reload`, НЕ тронувший `history.level`, не обязан
        переустанавливать tap — иначе каждый reload плодил бы новые
        `StoreTapChannel` без наблюдаемого эффекта (см. докстринг правки в
        `_cmd_config_reload`: переустановка — только когда уровень РЕАЛЬНО сменился).
        """
        store_dir = Path(tempfile.mkdtemp(prefix="f2_t22_hist_store_noop_"))
        try:
            with _real_wired("hist_reapply_noop") as (process, logger, error, command_manager):
                store, taps = wire_observability_store(
                    error_manager=error,
                    logger_manager=logger,
                    db_path=str(store_dir / "obs.db"),
                    process=process.name,
                    min_level="INFO",
                )
                process._observability_store = store
                process._observability_store_taps = taps
                process._observability_history_policy = resolve_history_policy(process)
                try:
                    taps_before = logger._tap_sinks.get("observability_store::logger_error")
                    result = _reload(command_manager, {"log_level": "DEBUG"})
                    assert result.get("success") is True, result
                    taps_after = logger._tap_sinks.get("observability_store::logger_error")
                    assert taps_before is taps_after, (
                        "config.reload, не тронувший history.level, обязан оставить "
                        "СУЩЕСТВУЮЩИЙ tap на месте, а не пересоздать его молча"
                    )
                finally:
                    unwire_observability_store(store, process._observability_store_taps)
        finally:
            shutil.rmtree(store_dir, ignore_errors=True)


class TestConcurrentConfigReloadsAreSerializedByLayersLock:
    """Опасность, названная ADR-PM-047 («что если два `config.reload` гонятся за
    одним тапом»), проверена и на входе КОМАНДЫ, не только на механизме тапа.

    Находка при чтении: `_cmd_config_reload` держит `with layers.lock:` (RLock,
    `ObservabilityLayers._lock`) на ВСЁ время пересборки, включая
    `apply_observability_layers` И добавленный этой правкой вызов
    `reapply_observability_store_level` — докстринг `ObservabilityLayers.lock`
    прямо говорит «держится и на время пересборки», ради РОВНО этого класса
    гонки («две пересборки внахлёст»). Значит два `config.reload` НА ОДНОМ
    процессе сериализованы уже существующим механизмом, независимо от того,
    что их зовут с разных потоков (интерактивная консоль мимо роутера против
    IPC через `message_processor`, см. ADR-PM-047) — это не то, что добавляет
    ЭТА задача, а факт устройства кода, который стоило проверить, а не просто
    прочитать.
    """

    def test_two_concurrent_reloads_never_crash_and_leave_one_level_winning(self) -> None:
        import threading

        store_dir = Path(tempfile.mkdtemp(prefix="f2_t22_hist_store_concurrent_"))
        try:
            with _real_wired("hist_reapply_concurrent") as (process, logger, error, command_manager):
                store, taps = wire_observability_store(
                    error_manager=error,
                    logger_manager=logger,
                    db_path=str(store_dir / "obs.db"),
                    process=process.name,
                    min_level="INFO",
                )
                process._observability_store = store
                process._observability_store_taps = taps
                process._observability_history_policy = resolve_history_policy(process)
                results: list = []
                errors: list[BaseException] = []
                start = threading.Barrier(2, timeout=10)

                def reload_to(level: str) -> None:
                    try:
                        start.wait()
                        results.append(_reload(command_manager, {"history": {"level": level}}))
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)

                try:
                    t1 = threading.Thread(target=reload_to, args=("WARNING",))
                    t2 = threading.Thread(target=reload_to, args=("ERROR",))
                    t1.start()
                    t2.start()
                    t1.join(timeout=15)
                    t2.join(timeout=15)

                    assert not t1.is_alive() and not t2.is_alive(), "reload не завершился за 15с"
                    assert errors == [], f"конкурентный config.reload уронил поток: {errors!r}"
                    assert len(results) == 2 and all(r.get("success") is True for r in results), results

                    # Финальный уровень — ОДИН из двух запрошенных (последний, кто
                    # взял RLock, выигрывает), а не смесь двух половинчатых состояний.
                    final_level = process._observability_history_policy["level"]
                    assert final_level in ("WARNING", "ERROR"), (
                        f"после гонки уровень обязан быть ОДНИМ из двух валидных, а не мусором: {final_level}"
                    )
                    # tap-реестр обоих менеджеров согласован с ПОСЛЕДНИМ применённым
                    # уровнем — а не рассинхронизирован между error/logger менеджерами
                    # (что было бы возможно, если бы гонка расколола применение).
                    from multiprocess_framework.modules.channel_routing_module.levels import (
                        threshold_severity,
                    )

                    _, logger_threshold = logger._tap_sinks["observability_store::logger_error"]
                    _, error_threshold = error._tap_sinks["observability_store::error"]
                    assert logger_threshold == error_threshold == threshold_severity(final_level), (
                        f"два менеджера обязаны согласиться на ОДНОМ пороге: "
                        f"logger={logger_threshold} error={error_threshold} "
                        f"ожидание={threshold_severity(final_level)}"
                    )
                finally:
                    unwire_observability_store(store, process._observability_store_taps)
        finally:
            shutil.rmtree(store_dir, ignore_errors=True)
