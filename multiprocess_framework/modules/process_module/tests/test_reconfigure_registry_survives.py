# -*- coding: utf-8 -*-
"""Страж R9: отвергнутый reload не имеет права оставить процесс без каналов.

Требование вердикта по Ф0.3 (эскалация к teamlead, 2026-07-27). Резидуал R9
гласит: ``ChannelRoutingManager.reconfigure`` зовёт ``_close_all_channels()``
ДО валидации нового конфига и не откатывается — любой отвергнутый reload
оставляет менеджер с пустым реестром. Воспроизведено вердиктом:
``lm.reconfigure({**валидный, "sampling_max_level": "ЖЁЛТЫЙ"})`` →
каналов 12 → 0, ``system.log`` = 0 байт, логгер больше не пишет никуда.

**Причина устранена 2026-07-27** (validate-then-swap + откат в
``CRM.reconfigure``). Файл остаётся стражем ДВУХ независимых рубежей, и это не
дубль: фасадная валидация (``expand_observability`` разбирает секцию до касания
менеджеров) и защита самого менеджера закрывают разные пути. Снятие любого из
них по отдельности здесь видно.

ВАЖНО про формулировку — история, ради которой файл и заведён. В плане было
написано, что симптом снят «валидацией на границе конфига», и это ПОЧТИ правда,
которая опаснее лжи: валидатор ``LoggerManagerConfig`` действительно есть, но
срабатывал ВНУТРИ ``_rebuild_from_config`` — то есть уже после
``_close_all_channels()``. Спасала только валидация на фасаде. Прочитав старую
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
    apply_observability_layers,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    ObservabilityLayers,
)


def _apply_section(section, **kwargs):
    """Применить голую секцию ``observability`` — одноэтажный стек «сказал только L1».

    Раньше это была функция фреймворка ``apply_observability_reconfigure``. Продакшн-
    вызывающих у неё не было НИ ОДНОГО (ревью Ф5, корзина 2 п.10): поверхность
    выглядела входом в применение, обслуживала только эти тесты — и питала докстринги,
    утверждавшие, будто через неё идёт ``config.reload``. Помощник переехал туда, где
    живут его вызывающие; продакшн-путь (``apply_observability_layers`` со стеком
    процесса) тесты зовут напрямую.
    """
    # `origin` здесь с дефолтом — и это не послабление дисциплины аудита: стек
    # создаётся ПРЯМО В ВЫЗОВЕ и умирает вместе с ним, записывать некуда и некому
    # читать. Дефолт описывает ровно этот факт, а не прячет незнание источника.
    kwargs.setdefault("origin", "reconfigure")
    return apply_observability_layers(
        ObservabilityLayers(app=dict(section) if isinstance(section, dict) else {}),
        **kwargs,
    )


def _logger(tmp_path: Path) -> LoggerManager:
    mgr = LoggerManager(
        manager_name="R9Guard",
        config=LoggerManagerConfig(
            app_name="r9_guard",
            log_directory=str(tmp_path),
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
            _apply_section(
                # Негодное значение поля САМОЙ секции observability (Ф7.4: прежним
                # было batch_overflow_policy, снятое вместе с батчингом).
                {"log_level": "DEBUG", "retention_days": -5},
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
    ``_apply_section`` вообще перестала что-либо применять.
    """
    mgr = _logger(tmp_path)
    try:
        _apply_section(
            {"sampling_first_n": 42, "sampling_max_level": "INFO"},
            logger=mgr,
        )
        assert mgr.config.sampling_first_n == 42, "валидный reload не применился"
        assert mgr.config.sampling_max_level == "INFO"
        assert mgr._channel_registry.names(), "валидный reload оставил менеджер без каналов"
    finally:
        mgr.shutdown()


def test_direct_manager_reconfigure_keeps_registry(tmp_path: Path) -> None:
    """R9 ЗАКРЫТ: прямой ``manager.reconfigure(сырой_dict)`` больше не разрушает реестр.

    Раньше здесь стоял обратный тест — он фиксировал дефект как известный, пока
    задача «validate-then-swap» не сделана, и был написан так, чтобы покраснеть
    в день починки. Он покраснел (``assert not names()`` → ``['system_file']``),
    и это был правильный сигнал. Проверка развёрнута, а не удалена: защита
    теперь в ``CRM.reconfigure`` (валидация до ``_close_all_channels``), и путь
    мимо фасада обязан держать её самостоятельно.
    """
    mgr = _logger(tmp_path)
    try:
        before = sorted(mgr._channel_registry.names())
        raw: dict[str, Any] = mgr.config.model_dump()
        raw["sampling_max_level"] = "ЖЁЛТЫЙ"

        applied = mgr.reconfigure(raw)

        assert applied is False, "невалидный конфиг не должен применяться"
        assert sorted(mgr._channel_registry.names()) == before, (
            "отказ применить конфиг превратился в разрушение реестра"
        )

        mgr.error("после прямого отвергнутого reconfigure логгер обязан писать", module="r9")
        mgr.flush()
        content = (tmp_path / "system.log").read_text(encoding="utf-8", errors="replace")
        assert "после прямого отвергнутого reconfigure" in content
    finally:
        mgr.shutdown()


def test_rejected_reconfigure_keeps_previous_settings(tmp_path: Path) -> None:
    """Отказ не применяет ЧАСТЬ конфига: соседние поля тоже остаются прежними.

    Реестр мог бы уцелеть при том, что валидные поля из отвергнутого конфига уже
    просочились в ``self.config`` — тогда система жила бы по конфигу, которого
    никто не утверждал.
    """
    mgr = _logger(tmp_path)
    try:
        before_first_n = mgr.config.sampling_first_n
        raw: dict[str, Any] = mgr.config.model_dump()
        raw["sampling_first_n"] = before_first_n + 777
        raw["sampling_max_level"] = "ЖЁЛТЫЙ"

        assert mgr.reconfigure(raw) is False
        assert mgr.config.sampling_first_n == before_first_n, "поле из отвергнутого конфига просочилось"
    finally:
        mgr.shutdown()
