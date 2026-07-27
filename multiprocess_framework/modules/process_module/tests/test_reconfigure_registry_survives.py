# -*- coding: utf-8 -*-
"""Страж R9: отвергнутый reload не имеет права оставить процесс без каналов.

Требование вердикта по Ф0.3 (эскалация к teamlead, 2026-07-27). Резидуал R9
гласит: ``ChannelRoutingManager.reconfigure`` зовёт ``_close_all_channels()``
ДО валидации нового конфига и не откатывается — любой отвергнутый reload
оставляет менеджер с пустым реестром. Воспроизведено вердиктом:
``lm.reconfigure({**валидный, "batch_overflow_policy": "drop_middle"})`` →
каналов 12 → 0, ``system.log`` = 0 байт, логгер больше не пишет никуда.

Причина не устранена и вынесена отдельной задачей вне Ф0 — граница признана
верной. Но санкционированный операторский путь ДОЛЖЕН быть закрыт, и держится
это исключительно на порядке вызовов внутри ``apply_observability_reconfigure``
(валидация в ``expand_observability`` происходит до касания менеджеров).
Порядок вызовов ничем не зафиксирован — значит его снесут при первом же
рефакторинге, и снесут молча: тестов на это не было.

ВАЖНО про формулировку. В плане было написано, что симптом снят «валидацией на
границе конфига», и это ПОЧТИ правда, которая опаснее лжи: валидатор
``LoggerManagerConfig`` действительно есть, но срабатывает ВНУТРИ
``_rebuild_from_config`` — то есть уже после ``_close_all_channels()``.
Спасает только валидация в ``ObservabilityConfig`` на фасаде. Прочитав старую
формулировку, следующий разработчик снял бы фасадную проверку как дубль.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_reconfigure,
)


def _logger(tmp_path: Path) -> LoggerManager:
    mgr = LoggerManager(
        manager_name="R9Guard",
        config=LoggerManagerConfig(
            app_name="r9_guard",
            log_directory=str(tmp_path),
            enable_batching=True,
            modules={},
            channels={
                "system_file": LoggerChannelSchema(
                    name="system_file",
                    type="file",
                    enabled=True,
                    file_path="system.log",
                    format="%(message)s",
                    rotate=False,
                ),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])},
        ),
    )
    mgr.initialize()
    return mgr


def test_rejected_observability_reload_keeps_channels(tmp_path: Path) -> None:
    """Опечатка в секции ``observability`` → реестр каналов ЦЕЛ, логгер пишет.

    Отказ применить конфиг обязан быть отказом, а не разрушением. Процесс,
    оставшийся без единого канала из-за опечатки оператора, теряет не только
    новую настройку, но и всю наблюдаемость — включая возможность узнать,
    что именно случилось.
    """
    mgr = _logger(tmp_path)
    try:
        before = sorted(mgr._channel_registry.names())
        assert before, "предусловие: у менеджера есть каналы"

        with pytest.raises(Exception):
            apply_observability_reconfigure(
                {"log_level": "DEBUG", "batch_overflow_policy": "drop_middle"},
                logger=mgr,
            )

        assert sorted(mgr._channel_registry.names()) == before, (
            "отвергнутый reload снёс каналы: отказ превратился в разрушение"
        )

        mgr.error("после отвергнутого reload логгер обязан писать", module="r9")
        mgr.flush()
        content = (tmp_path / "system.log").read_text(encoding="utf-8", errors="replace")
        assert "после отвергнутого reload" in content, "логгер онемел после отказа применить конфиг"
    finally:
        mgr.shutdown()


def test_valid_observability_reload_still_applies(tmp_path: Path) -> None:
    """Парная половина: страж выше не должен держаться на том, что reload не работает.

    Без этой проверки предыдущий тест зеленел бы и в случае, когда
    ``apply_observability_reconfigure`` вообще перестала что-либо применять.
    """
    mgr = _logger(tmp_path)
    try:
        apply_observability_reconfigure(
            {"batch_max_pending": 42, "batch_overflow_policy": "drop_newest"},
            logger=mgr,
        )
        assert mgr.config.batch_max_pending == 42, "валидный reload не применился"
        assert mgr.config.batch_overflow_policy == "drop_newest"
        assert mgr._channel_registry.names(), "валидный reload оставил менеджер без каналов"
    finally:
        mgr.shutdown()


def test_direct_manager_reconfigure_still_destroys_registry(tmp_path: Path) -> None:
    """ЗАФИКСИРОВАНО КАК ИЗВЕСТНЫЙ ДЕФЕКТ (R9), а не как желаемое поведение.

    Прямой ``manager.reconfigure(сырой_dict)`` минует фасад и по-прежнему
    оставляет пустой реестр. Это записано здесь намеренно: пока задача
    «validate-then-swap + rollback в ``CRM.reconfigure``» не сделана, граница
    защиты должна быть видимой и проверяемой, а не подразумеваемой.

    Когда R9 закроют, этот тест ПОКРАСНЕЕТ — и это будет правильный сигнал
    «поведение сменилось намеренно», а не поломка.
    """
    mgr = _logger(tmp_path)
    try:
        raw: dict[str, Any] = mgr.config.model_dump()
        raw["batch_overflow_policy"] = "drop_middle"

        applied = mgr.reconfigure(raw)

        assert applied is False, "невалидный конфиг не должен применяться"
        assert not mgr._channel_registry.names(), (
            "реестр уцелел — похоже, R9 закрыт; тогда этот тест надо удалить, а резидуал R9 в плане пометить закрытым"
        )
    finally:
        mgr.shutdown()
