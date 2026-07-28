# -*- coding: utf-8 -*-
"""2.2-перф — кэш РЕЗУЛЬТАТА маршрута вместо решения гейта.

Замер (эта машина, отклонённая запись): `LoggerCore.log` 351.5 → 226.1 нс,
через вид 583.5 → 462.5. Экономия — три кадра (`_route` → `_is_gate_open` →
`should_log` = 183 нс) схлопнуты в один поиск по словарю (54 нс).

Кэш маршрута ОПАСНЕЕ кэша гейта, и тесты здесь именно про это. Устаревший кэш
гейта даёт симптом «лог не пишется» — заметный. Устаревший кэш маршрута даёт
«лог пишется в снятый канал» либо «перестал писаться в живой» — то есть
неверный ОТВЕТ вместо отсутствия ответа, и ищется он днями.

Проверяется наблюдаемое: куда физически легла запись и что лежит в кэше, — а
не то, какие методы были вызваны.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerModuleSchema,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.log_enums import LogLevel, LogScope


def _config(directory: Path) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="route_cache",
        log_directory=str(directory),
        enable_batching=False,
        modules={"trace": LoggerModuleSchema(enabled=True, file_path="trace.log")},
        channels={
            "first": LoggerChannelSchema(name="first", type="file", enabled=True, file_path="first.log", rotate=False),
            "second": LoggerChannelSchema(
                name="second", type="file", enabled=True, file_path="second.log", rotate=False
            ),
        },
        scopes={
            "BUSINESS": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["first", "second"]),
            "SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["first"]),
            "DEBUG": LoggerScopeSchema(enabled=False, min_level="DEBUG", channels=["first"]),
        },
    )


@pytest.fixture()
def logger(tmp_path: Path):
    mgr = LoggerManager(config=_config(tmp_path))
    yield mgr
    mgr.shutdown()


class TestRouteCacheStaleness:
    """Устаревший кэш маршрута = неверный ответ. Каждая пара — про один триггер."""

    def test_module_channel_appears_after_it_was_cached_without_it(self, logger, tmp_path) -> None:
        """Появление module-канала меняет маршрут УЖЕ закэшированного модуля.

        `_route` дописывает `module_<имя>`, когда модуль есть в карте
        module-каналов, — то есть состав этой карты входит в закэшированное
        значение наравне с реестром.
        """
        logger.info("до module-канала", module="новый")
        logger.flush()
        assert not (tmp_path / "новый.log").exists()

        logger.enable_module_logging("новый", file_path="новый.log")
        logger.info("после module-канала", module="новый")
        logger.flush()

        assert "после module-канала" in (tmp_path / "новый.log").read_text(encoding="utf-8")

    def test_reconfigure_invalidates_the_route(self, logger, tmp_path) -> None:
        """Смена порога скоупа отменяет закэшированный маршрут.

        До правки конфигом закрывался гейт, а маршрут остался бы закэшированным
        как «принято» — запись продолжала бы писаться при выключенном скоупе.
        """
        logger.info("до ужесточения", module="приложение")
        logger.flush()

        config = _config(tmp_path)
        config.scopes["BUSINESS"].min_level = "ERROR"
        logger.reconfigure(config.to_dict() if hasattr(config, "to_dict") else config.model_dump())
        logger.info("после ужесточения", module="приложение")
        logger.flush()

        assert "после ужесточения" not in (tmp_path / "first.log").read_text(encoding="utf-8")


class TestRouteCacheShape:
    def test_cached_value_cannot_be_mutated_by_the_caller(self, logger) -> None:
        """Закэшированный маршрут неизменяем.

        Список отдавался бы наружу тем же объектом, и один вызывающий,
        дописавший в него имя, испортил бы маршрут ВСЕМ последующим записям с
        этим ключом. Кортеж закрывает класс целиком, а не конкретный случай.
        """
        logger.info("наполнить кэш", module="приложение")
        assert logger._route_cache, "кэш пуст — тест проверял бы не то"
        for value in logger._route_cache.values():
            assert value is None or isinstance(value, tuple), f"маршрут изменяем: {value!r}"

    def test_rejected_record_is_not_recomputed_on_every_call(self, tmp_path) -> None:
        """Отклонённая запись считается ОДИН раз, дальше берётся из кэша.

        Первая редакция этого теста проверяла лишь, что в кэше в итоге лежит
        `None`, — и осталась ЗЕЛЁНОЙ, когда слом-инъекция сняла часовой промаха
        (`dict.get(key)` вместо `get(key, _ROUTE_MISS)`): маршрут пересчитывался
        КАЖДЫЙ раз, но конечное состояние кэша не менялось. Тест утверждал
        итог, а свойство — «не пересчитывается». Считаем вызовы самой точки
        вычисления: `_route` — не имя ради имени, а тот самый механизм, обход
        которого и есть проверяемое свойство.
        """
        calls: list = []
        manager = LoggerManager(config=_config(tmp_path))
        original = type(manager)._route

        def counting(self, scope, level, module):
            calls.append((scope, level, module))
            return original(self, scope, level, module)

        try:
            manager.invalidate_decision_cache()
            type(manager)._route = counting
            for _ in range(5):
                manager.debug("отклонено", module="приложение")
        finally:
            type(manager)._route = original
            manager.shutdown()

        mine = [c for c in calls if c[2] == "приложение"]
        assert len(mine) == 1, f"маршрут пересчитан {len(mine)} раз вместо одного"

    def test_rejected_route_is_remembered_as_none(self, logger) -> None:
        """И само значение — `None`, а не отсутствие ключа."""
        key = (LogScope.DEBUG, LogLevel.DEBUG, "приложение")
        logger.invalidate_decision_cache()
        logger.debug("отклонено", module="приложение")

        assert key in logger._route_cache
        assert logger._route_cache[key] is None

    def test_cache_disabled_still_routes_correctly(self, logger, tmp_path) -> None:
        """С выключенным кэшем путь обязан остаться рабочим, а не «почти».

        Флаг существует ради диагностики; путь без кэша проходят реже, и именно
        поэтому он ломается незаметно.
        """
        logger._cache_enabled = False
        # Чистим ПОСЛЕ снятия флага: менеджер успевает залогировать себя при
        # сборке, и без этой строки тест ловил бы запись, сделанную ДО флага, —
        # то есть падал бы на верном коде (поймано первым же прогоном).
        logger._route_cache.clear()
        logger.info("без кэша", module="приложение")
        logger.flush()

        assert "без кэша" in (tmp_path / "first.log").read_text(encoding="utf-8")
        assert logger._route_cache == {}, "с выключенным кэшем в него всё равно писали"
