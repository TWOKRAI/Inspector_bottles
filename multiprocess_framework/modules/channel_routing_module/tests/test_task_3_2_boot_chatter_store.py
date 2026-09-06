# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.2 плана ``observability-closure`` — К1, СКВОЗНОЙ вариант.

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t32-tester``) на коммите ``9d9cb8e1``, не видел diff/
реализацию. Источник критериев — раздел «### Task 3.2» в
``plans/observability-closure/phase-3-store-and-signal.md``, строка К1: «счёт
строк в сторе, литералы» (в отличие от К2/К3/К4/К6, помеченных «unit» без
уточнения — К1 отдельно называет именно СТОР, не спай на ``_log_info``).

======================================================================
Почему этот файл лежит здесь, а не в dispatch_module/tests (отклонение от
брифа, названо явно — см. отчёт тестера)
======================================================================
Бриф называет три места: ``dispatch_module/tests``, ``command_module/tests``,
``logger_module/tests``. Здесь — ЧЕТВЁРТОЕ, по аналогии с уже существующим
файлом-соседом по фазе ``test_task_3_1_store_and_dedup.py`` (тот же каталог,
тот же ``ObservabilityStore``, предыдущая задача ЭТОЙ ЖЕ фазы плана). Причина:
``dispatch_module``/``command_module`` тесты (в соседних файлах) проверяют
границу ``_log_info``/``_log_debug`` МЕНЕДЖЕРА — это эквивалентно «в стор
ничего не попадёт» ТОЛЬКО если единственный путь записи в стор — через эту
границу (что верно, но само по себе не проверено в тех файлах). Этот файл
проверяет СКВОЗНОЙ путь Dispatcher -> LoggerManager -> StoreTapChannel ->
ObservabilityStore целиком — буквально то, что просит К1, реальными
классами, без спая.

**Важная деталь, найденная прогоном (не догадка):**
``wire_observability_store(error_manager, logger_manager, ..., min_level=)``
по умолчанию аргумента функции имеет ``min_level="ERROR"`` — но ПРОДАКШН
вызывает её с порогом из ``observability.history.level``, чей схемный дефолт —
``"INFO"`` (``ObservabilityHistoryConfig.level``,
``process_module/configs/observability_config.py:262``, подтверждено
чтением). Если бы этот тест использовал дефолт САМОЙ функции (``"ERROR"``),
tap отсекал бы все INFO-записи и ``store.count()`` был бы 0 ВСЕГДА —
независимо от того, чинили Task 3.2 или нет (вырожденный, всегда-зелёный
тест). Поэтому ``min_level="INFO"`` передан явно, литералом, тем же самым
значением, что и в проде.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityStore
from multiprocess_framework.modules.dispatch_module.core.dispatcher import Dispatcher
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    wire_observability_store,
)


def _wired(tmp_path: Path) -> Tuple[LoggerManager, ObservabilityStore, list]:
    """Реальный LoggerManager с одним файловым каналом на все скоупы + реальный
    ObservabilityStore, повешенный tap'ом на logger_manager с порогом INFO
    (см. докстринг файла — почему именно INFO, не дефолт функции).

    ``error_manager=None`` в ``wire_observability_store`` — сознательно: с
    ДВУМЯ разными объектами на местах error/logger получилось бы ДВА tap'а на
    одну и ту же запись (проверено прогоном при отладке этого файла: с
    одним и тем же менеджером в обеих ролях каждая строка дублировалась —
    это была ошибка ПОДГОТОВКИ теста, не находка про прод, и она сюда не
    попала).
    """
    log_mgr = LoggerManager(
        manager_name="StoreProbe",
        config={
            "app_name": "probe",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "channels": {
                "a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")},
            },
            "scopes": {
                "BUSINESS": {"channels": ["a"]},
                "SYSTEM": {"channels": ["a"]},
                "DEBUG": {"channels": ["a"]},
                "PERFORMANCE": {"channels": ["a"]},
            },
        },
    )
    log_mgr.initialize()
    store, taps = wire_observability_store(
        None,
        log_mgr,
        db_path=str(tmp_path / "obs.db"),
        process="probe",
        min_level="INFO",
    )
    return log_mgr, store, taps


class TestK1StoreNeverGetsTheHandlerRegisteredRow:
    """К1 сквозным путём: ``Dispatcher`` -> ``LoggerManager`` -> ``StoreTapChannel``
    -> ``ObservabilityStore``.

    Контроль достижимости в ТОМ ЖЕ тесте (правило проекта: утверждение об
    ОТСУТСТВИИ строки требует парной проверки, что путь вообще способен
    донести строку) — контрольная INFO-строка той же severity через тот же
    ``log_mgr``; если бы tap/стор не принимал INFO вовсе, контроль тоже дал
    бы 0 совпадений, и тест упал бы на КОНТРОЛЬНОЙ строке с понятной
    причиной, а не молчаливо согласился с любым числом целевых строк.
    """

    def test_two_handlers_leave_zero_matching_rows_while_the_control_line_lands(self, tmp_path: Path) -> None:
        log_mgr, store, taps = _wired(tmp_path)
        try:
            disp = Dispatcher("probe_disp", managers={"logger": log_mgr}, config={"logger": True})
            disp.initialize()
            try:
                ok_alpha = disp.register_handler("alpha", lambda m: m)
                ok_beta = disp.register_handler("beta", lambda m: m)
                assert ok_alpha and ok_beta, "предусловие: обе регистрации обязаны пройти успешно"
            finally:
                disp.shutdown()

            # Контрольная строка — тот же logger_manager, тот же уровень INFO.
            log_mgr.info("control line reaches the store", module="probe")

            # Task 3.3: запись в стор ушла в очередь с фоновым дренажем. Снять
            # tap = дожать её (``remove_tap`` зовёт ``close()`` канала); сам
            # объект tap'а отсюда недостижим — он живёт внутри менеджера.
            # Без этого «ноль целевых строк» ниже означал бы «очередь ещё не
            # слита», а контрольная строка не нашлась бы вовсе.
            for mgr, tap_name in taps:
                assert mgr.remove_tap(tap_name) is True, f"tap {tap_name} не был поставлен"

            recs = store.list_records(limit=1000)
            texts = [str(r.get("message", "")) for r in recs]

            control_matches = [t for t in texts if "control line reaches the store" in t]
            assert control_matches, (
                "предусловие теста нарушено: контрольная INFO-строка не дошла до "
                f"стора — 'ноль совпадений' ниже ничего не доказывает: {texts!r}"
            )

            target_matches = [t for t in texts if "registered successfully" in t]
            assert target_matches == [], (
                "К1 нарушен: 'registered successfully' всё ещё лежит в РЕАЛЬНОМ "
                f"ObservabilityStore: {target_matches!r} (все строки стора: {texts!r})"
            )
        finally:
            store.close()
            log_mgr.shutdown()
