# -*- coding: utf-8 -*-
"""Ф2.6 — полное имя адресуют правила, сокращённое видит глаз.

План: plans/observability-unified-routing.md, задача 2.6, решение Р-2.6-Д.

Зачем понадобилось. Переход трёх шумных источников с плоских ярлыков на точечные
имена пакетов нужен правилам: плоское имя — лист без поддерева, префиксный резолв
Ф2.2 на нём не работает. Но имя стоит в КАЖДОЙ строке, и замер прогона 2026-08-03
показал цену перехода без сокращения: +9.27% к весу ``system.log`` у ProcessManager,
**+16.38%** у region_splitter, +4.74% у gui. Фаза, которая борется за объём логов,
добавила бы объёма — поэтому имя сокращается при выводе, как ``%logger{N}`` в logback.

Главный инвариант файла — **разъезд двух представлений**: в записи и в правилах имя
полное, в файле сокращённое. Перепутать их местами дороже, чем не сокращать вовсе:
резолв начал бы получать ``m.m.dispatch_module``, и правило, написанное человеком по
полному имени, молча перестало бы совпадать — ровно тот класс тишины, что оставил на
диске 288 нулевых файлов.
"""

from __future__ import annotations

from typing import Any


from multiprocess_framework.modules.dispatch_module.interfaces import LOG_SOURCE as DISPATCH_SOURCE
from multiprocess_framework.modules.logger_module.channels.log_channel import abbreviate_source
from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class TestAbbreviationRule:
    """Правило сжатия — против литералов, отдельно от проводки."""

    def test_leading_segments_shrink_last_stays_whole(self) -> None:
        assert abbreviate_source("multiprocess_framework.modules.dispatch_module", 20) == "m.m.dispatch_module"

    def test_stops_as_soon_as_it_fits(self) -> None:
        """Сжимается ровно столько сегментов, сколько нужно — не все подряд."""
        assert abbreviate_source("multiprocess_framework.modules.dispatch_module", 28) == "m.modules.dispatch_module"

    def test_short_name_untouched(self) -> None:
        assert abbreviate_source("dispatcher", 20) == "dispatcher"

    def test_zero_limit_prints_full_name(self) -> None:
        """0 — «печатать полностью»; на нём дефолт схемы, поведение прежнее."""
        full = "multiprocess_framework.modules.dispatch_module"
        assert abbreviate_source(full, 0) == full

    def test_single_segment_survives_even_over_the_limit(self) -> None:
        """Сжать имя без точек до одной буквы значило бы уничтожить его."""
        assert abbreviate_source("command_manager", 5) == "command_manager"

    def test_last_segment_survives_an_unreachable_limit(self) -> None:
        """Недостижимый потолок сдаётся, но последний сегмент не трогает.

        Добавлен по итогу слом-инъекции, а не «на всякий случай»: правка
        ``range(len(parts) - 1)`` → ``range(len(parts))`` (последний сегмент тоже
        сжимается) оставила ВЕСЬ файл зелёным. На боевых именах цикл попадает в
        потолок раньше, чем дошёл бы до последнего сегмента, поэтому гарантия
        «последний цел» не проверялась ничем. Здесь потолок заведомо недостижим —
        единственный вход в эту ветку.
        """
        assert abbreviate_source("a.b.command_manager", 5) == "a.b.command_manager"

    def test_long_migrated_name_shrinks_too(self) -> None:
        """Имена после Ф6 длиннее наших — сокращение чинит и их (74 → 20).

        Литерал поймал мою арифметику при написании файла: ожидание было посчитано
        от потолка 36 и осталось после смены потолка на 20. Ровно тот случай, ради
        которого ожидаемое пишется литералом, а не выводится из кода под тестом —
        сравнение с ``abbreviate_source(...)`` согласилось бы с любым ответом.
        """
        migrated = "multiprocess_framework.modules.shared_resources_module.queues.core.manager"
        assert abbreviate_source(migrated, 20) == "m.m.s.q.core.manager"


def _manager(tmp_path, name_max_len: int) -> Any:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="abbr26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "f": LoggerChannelSchema(
                    type="file",
                    enabled=True,
                    file_path="out.log",
                    rotate=False,
                    name_max_len=name_max_len,
                    format="%(name)s: %(message)s",
                )
            },
            default_level="DEBUG",
            scopes={"SYSTEM": LoggerScopeSchema(channels=["f"])},
        )
    )


class TestTwoRepresentationsDoNotSwap:
    """Файл видит сокращённое, правила — полное. Обе половины проверяются."""

    def test_file_gets_the_short_form(self, tmp_path) -> None:
        manager = _manager(tmp_path, name_max_len=20)
        try:
            manager.system(LogLevel.INFO, "проба", module=DISPATCH_SOURCE)
            manager.flush()
        finally:
            manager.shutdown()

        written = (tmp_path / "out.log").read_text(encoding="utf-8", errors="replace")
        assert "m.m.dispatch_module: проба" in written
        assert DISPATCH_SOURCE not in written

    def test_zero_keeps_the_full_form_in_the_file(self, tmp_path) -> None:
        """Пара к предыдущему: без настройки вид строки прежний, бит-в-бит."""
        manager = _manager(tmp_path, name_max_len=0)
        try:
            manager.system(LogLevel.INFO, "проба", module=DISPATCH_SOURCE)
            manager.flush()
        finally:
            manager.shutdown()

        assert f"{DISPATCH_SOURCE}: проба" in (tmp_path / "out.log").read_text(encoding="utf-8")

    def test_routing_still_sees_the_full_name(self, tmp_path) -> None:
        """Сокращение НЕ доезжает до резолва — правило пишется по полному имени.

        Проверяется через маршрут: правило на полный префикс уводит запись в свой
        приёмник. Если бы сокращение случалось до резолва, правило не совпало бы —
        и запись ушла бы в канал скоупа.
        """
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="abbr26r",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={
                    "scope_file": LoggerChannelSchema(
                        type="file", enabled=True, file_path="scope.log", rotate=False, name_max_len=20
                    ),
                    "ruled_file": LoggerChannelSchema(
                        type="file", enabled=True, file_path="ruled.log", rotate=False, name_max_len=20
                    ),
                },
                default_level="DEBUG",
                scopes={"SYSTEM": LoggerScopeSchema(channels=["scope_file"])},
                loggers={"multiprocess_framework.modules": {"channels": ["ruled_file"]}},
            )
        )
        try:
            manager.system(LogLevel.INFO, "по правилу", module=DISPATCH_SOURCE)
            manager.flush()
        finally:
            manager.shutdown()

        assert "по правилу" in (tmp_path / "ruled.log").read_text(encoding="utf-8", errors="replace")
        scope_log = tmp_path / "scope.log"
        assert "по правилу" not in (
            scope_log.read_text(encoding="utf-8", errors="replace") if scope_log.exists() else ""
        )


class TestFrameworkDefaultsEnableIt:
    def test_shipped_channels_abbreviate(self) -> None:
        """Дефолт схемы 0, но поставляемые каналы включают сокращение явно.

        Литералом, а не сравнением с ``_NAME_MAX_LEN``: вывод ожидаемого из того же
        кода согласился бы и с ``0``, то есть с молча выключённым сокращением.
        """
        shipped = LoggerManagerConfig().channels
        assert {name: ch.name_max_len for name, ch in shipped.items()} == {
            "system_file": 20,
            "messages_file": 20,
            "performance_file": 20,
            "console": 20,
        }

    def test_schema_default_is_off(self) -> None:
        assert LoggerChannelSchema().name_max_len == 0
