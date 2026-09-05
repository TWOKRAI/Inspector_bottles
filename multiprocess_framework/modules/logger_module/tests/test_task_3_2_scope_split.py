# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.2 плана ``observability-closure`` — К6-К7 (раскладка файлов).

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t32-tester``) на коммите ``9d9cb8e1`` — ДО правки
Task 3.2, не видел diff/реализацию. Источник критериев — раздел «### Task 3.2»
в ``plans/observability-closure/phase-3-store-and-signal.md`` (Р-7 (а)).

======================================================================
К6 — дефолт скоупов
======================================================================
``BUSINESS -> ["messages_file"]``, ``SYSTEM -> ["console", "system_file"]``.
Сегодня (``logger_manager_config.py:491-500``) ``BUSINESS -> ["system_file",
"messages_file"]`` — тест ниже обязан упасть на литеральном сравнении списков.

======================================================================
К7 (unit-половина) — РЕАЛЬНАЯ переоценка брифа, найдена прогоном
======================================================================
Бриф предлагает формулировку «assert the two channel sets are not nested».
**Эта формулировка ПРОВЕРЕНА и ОТВЕРГНУТА** — см. класс
``TestK7ChannelSetsAreDisjoint`` ниже за числами и объяснением: буквальная
проверка «ни один список не является подмножеством другого» истинна СЕГОДНЯ
И ПОСЛЕ фикса одновременно (оба списка всегда содержат хотя бы один элемент,
которого нет у другого — ``console``/``messages_file`` — так что «подмножество»
в любую сторону ложно уже сейчас). Такой тест был бы вырожденным стражем
(ложно неотличимым до/после — то же семейство находок, что «сторож считает
kind=error по severity, а не по владельцу записи»). Правильная операционная
проверка того же самого «файлы больше не дублируют друг друга» —
**непересечение множеств каналов** (``set & set == set()``): сегодня оба
скоупа делят канал ``system_file`` (это и есть причина дубля), после фикса —
не делят ни одного. Проверено прогоном обеих версий перед тем, как эта версия
была зафиксирована в файле (см. отчёт тестера).
"""

from __future__ import annotations


from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class TestK6ScopeDefaultsAreTheLiteralListsFromR7a:
    """К6: дефолты скоупов — литералы, буквально из Р-7 (а)."""

    def test_business_default_is_messages_file_only(self) -> None:
        cfg = LoggerManagerConfig()
        assert cfg.scopes["BUSINESS"].channels == ["messages_file"], (
            f"К6 нарушен: BUSINESS обязан вести ТОЛЬКО в messages_file (Р-7а), "
            f"сейчас: {cfg.scopes['BUSINESS'].channels!r}"
        )

    def test_system_default_is_console_and_system_file(self) -> None:
        cfg = LoggerManagerConfig()
        assert cfg.scopes["SYSTEM"].channels == ["console", "system_file"], (
            f"К6 (контроль — SYSTEM не должен был поменяться): {cfg.scopes['SYSTEM'].channels!r}"
        )


class TestK7ChannelSetsAreDisjoint:
    """К7 (unit-половина): по дефолтным скоупам BUSINESS и SYSTEM не делят ни
    одного канала — именно ЭТО и создавало дубль ``messages.log`` ⊆ ``system.log``
    (оба сегодня пишут в ``system_file``).

    Резолюция берётся у РЕАЛЬНОГО ``LoggerManager._route(scope, level, module)``
    — тот же метод, которым уже пользуется существующий проектный тест
    ``test_lazy_message.py::test_called_once_regardless_of_channel_count``
    (``logger._route(LogScope.BUSINESS, LogLevel.INFO, "probe")``), не
    придуманный тестером API. Конфиг НЕ переопределяет ``channels``/``scopes``
    — используются схемные дефолты ``LoggerManagerConfig`` целиком, ровно то,
    что проверяет К6 выше.
    """

    @staticmethod
    def _default_logger_manager(tmp_path) -> LoggerManager:
        mgr = LoggerManager(
            manager_name="ScopeSplitProbe",
            config={"app_name": "probe", "log_directory": str(tmp_path), "enable_batching": False},
        )
        mgr.initialize()
        return mgr

    def test_business_and_system_routes_share_no_channel(self, tmp_path) -> None:
        mgr = self._default_logger_manager(tmp_path)
        try:
            business_channels = set(mgr._route(LogScope.BUSINESS, LogLevel.INFO, "probe"))
            system_channels = set(mgr._route(LogScope.SYSTEM, LogLevel.INFO, "probe"))

            # Контроль достижимости: обе стороны обязаны быть НЕПУСТЫМИ — иначе
            # «непересечение» выполнилось бы тривиально («никто никуда не пишет»).
            assert business_channels, "предусловие: BUSINESS обязан резолвиться хоть в один канал"
            assert system_channels, "предусловие: SYSTEM обязан резолвиться хоть в один канал"

            shared = business_channels & system_channels
            assert shared == set(), (
                f"К7 нарушен: BUSINESS и SYSTEM всё ещё делят канал(ы) {shared!r} "
                f"(BUSINESS={business_channels!r}, SYSTEM={system_channels!r}) — "
                f"это и есть источник дубля messages.log ⊆ system.log"
            )
        finally:
            mgr.shutdown()
