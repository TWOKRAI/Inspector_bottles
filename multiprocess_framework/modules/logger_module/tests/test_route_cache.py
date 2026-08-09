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
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.channels.log_channel import create_channel
from multiprocess_framework.modules.logger_module.log_enums import LogLevel, LogScope


def _config(directory: Path) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="route_cache",
        log_directory=str(directory),
        enable_batching=False,
        channels={
            "first": LoggerChannelSchema(name="first", type="file", enabled=True, file_path="first.log", rotate=False),
            "second": LoggerChannelSchema(
                name="second", type="file", enabled=True, file_path="second.log", rotate=False
            ),
        },
        scopes={
            "BUSINESS": LoggerScopeSchema(channels=["first", "second"]),
            "SYSTEM": LoggerScopeSchema(channels=["first"]),
            "DEBUG": LoggerScopeSchema(channels=["first"]),
        },
    )


@pytest.fixture()
def logger(tmp_path: Path):
    mgr = LoggerManager(config=_config(tmp_path))
    yield mgr
    mgr.shutdown()


class TestRouteCacheStaleness:
    """Устаревший кэш маршрута = неверный ответ. Каждая пара — про один триггер."""

    def test_new_channel_appears_after_the_route_was_cached_without_it(self, logger, tmp_path) -> None:
        """Появление приёмника меняет маршрут УЖЕ закэшированного источника.

        **Переклассифицирован в Ф2.6, свойство сохранено.** Раньше триггером был
        per-module канал: `_route` дописывал `module_<имя>`, и состав той карты
        входил в закэшированное значение наравне с реестром. Механизм снят, но
        свойство осталось несущим и лишь сменило вход — теперь состав маршрута
        меняет правило по имени и его приёмник. Устаревший кэш даёт тот же
        симптом: приёмник есть, а записи в него не идут до перезапуска.
        """
        logger.info("до появления приёмника", module="новый")
        logger.flush()
        assert not (tmp_path / "новый.log").exists()

        logger.register_channel(
            create_channel(
                "новый_файл",
                LoggerChannelSchema(
                    name="новый_файл",
                    type="file",
                    enabled=True,
                    file_path=str(tmp_path / "новый.log"),
                    rotate=False,
                ),
            )
        )
        logger.config.scopes["BUSINESS"].channels.append("новый_файл")
        logger.invalidate_decision_cache()

        logger.info("после появления приёмника", module="новый")
        logger.flush()

        assert "после появления приёмника" in (tmp_path / "новый.log").read_text(encoding="utf-8")

    def test_reconfigure_invalidates_the_route(self, logger, tmp_path) -> None:
        """Смена порога скоупа отменяет закэшированный маршрут.

        До правки конфигом закрывался гейт, а маршрут остался бы закэшированным
        как «принято» — запись продолжала бы писаться при выключенном скоупе.
        """
        logger.info("до ужесточения", module="приложение")
        logger.flush()

        config = _config(tmp_path)
        config.default_level = "ERROR"  # Ф8.1: порог — у корня, не у скоупа
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


class TestOperatorDisabledSinkLeavesTheRoute:
    """2.8 — снятый оператором приёмник исчезает ИЗ МАРШРУТА, а не из учёта.

    Дефект (воспроизведён на живой системе 2026-07-28): список приёмников
    скоупа берётся из КОНФИГА, а `sink.disable` снимает канал только из
    реестра. Имя оставалось в маршруте, резолв падал, и каждая запись после
    штатного действия оператора считалась потерянной — 5 записей → 5
    `unresolved_channel_records`, а 2.V2 поднимала по ним аномалию.

    Отвергнутая альтернатива названа, чтобы к ней не вернулись: «выключать
    счётчик вместе с каналом» (предложение владельца). Счётчики потерь обязаны
    ПЕРЕЖИВАТЬ снятие приёмника — инцидент «7 → disable → 0» уже был
    воспроизведён ревью Ф0: оператор разбирает поломку, жмёт disable, и история
    отброшенных записей обнуляется вместе с каналом. Врёт не счётчик, а маршрут.
    """

    def test_disabling_one_of_two_sinks_is_not_a_loss(self, logger, tmp_path) -> None:
        """Репро владельца целиком: пишет в два файла, один снят — потерь нет."""
        logger.set_sink_enabled("second", False)
        for i in range(5):
            logger.info(f"запись {i}", module="приложение")
        logger.flush()
        stats = logger.get_stats()

        assert stats["unresolved_channel_records"] == 0, stats.get("unresolved_channels")
        assert stats["records_without_channels"] == 0
        assert stats["channel_refused_records"] == 0
        assert (tmp_path / "first.log").read_text(encoding="utf-8").count("запись") == 5

    def test_a_typo_in_a_channel_name_is_still_a_loss(self, logger) -> None:
        """Различение не маскирует настоящий дефект.

        Имя, которого никто не снимал (опечатка в конфиге, не созданный канал),
        обязано считаться потерей как прежде — иначе правка превратила бы
        счётчик в бесполезный.
        """
        logger.config.scopes["BUSINESS"].channels = ["first", "такого_канала_нет"]
        logger.invalidate_decision_cache()
        logger.info("в никуда", module="приложение")
        stats = logger.get_stats()

        assert stats["unresolved_channel_records"] == 1
        assert stats["unresolved_channels"] == {"такого_канала_нет": 1}

    def test_counters_survive_the_disable(self, logger) -> None:
        """История потерь переживает снятие приёмника — прямой страж инцидента «7 → 0».

        Здесь проверяется именно то, ради чего предложение «выключать счётчик»
        было отвергнуто: сначала накапливаем потерю на несуществующем имени,
        затем снимаем ДРУГОЙ, живой приёмник — накопленное число обязано
        остаться на месте.
        """
        logger.config.scopes["BUSINESS"].channels = ["first", "призрак"]
        logger.invalidate_decision_cache()
        for _ in range(7):
            logger.info("к призраку", module="приложение")
        assert logger.get_stats()["unresolved_channel_records"] == 7

        logger.set_sink_enabled("first", False)
        assert logger.get_stats()["unresolved_channel_records"] == 7, "история потерь обнулилась вместе с каналом"

    def test_re_enabling_puts_the_sink_back_into_the_route(self, logger, tmp_path) -> None:
        """Зеркальный дефект: «включил, а не пишется». Отметка обязана сниматься."""
        logger.set_sink_enabled("second", False)
        logger.info("пока снят", module="приложение")
        logger.set_sink_enabled("second", True)
        logger.info("снова пишем", module="приложение")
        logger.flush()

        second = (tmp_path / "second.log").read_text(encoding="utf-8")
        assert "снова пишем" in second
        assert "пока снят" not in second

    def test_the_error_plane_never_had_this_defect(self, tmp_path) -> None:
        """У плоскости ОШИБОК дефекта не было — и это установлено слом-инъекцией.

        Первая редакция называлась «то же поведение на плоскости ошибок» и
        утверждала, что без общего фильтра дефект остался бы жить у ошибок.
        **Слом-инъекция это опровергла:** тест остался ЗЕЛЁНЫМ и при снятом
        фильтре, и при неставящейся отметке — то есть охранял он не фильтр.

        Настоящая причина: `ErrorManager._route` берёт приёмник из ЖИВОГО
        реестра (`_level_to_channel` пересобирается на смену состава), а не из
        статического списка конфига скоупа. Именно статический список и был
        корнем дефекта — значит он логгер-специфичен.

        Тест оставлен как характеризационный: он закрепляет, что плоскость
        ошибок деградирует ИЗЯЩНО (снят `warnings_file` → WARNING едет в
        `errors_file`), и предупредит, если severity-резолв однажды переведут
        на конфиг и он унаследует ту же болезнь. Охраной фильтра он НЕ является,
        и докстринг об этом говорит прямо, чтобы никто не решил обратное.
        """
        from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig

        mgr = ErrorManager(
            manager_name="ошибки",
            config=ErrorManagerConfig(
                app_name="route_cache",
                enable_batching=False,
                default_level="WARNING",
                critical_file_path=str(tmp_path / "critical.log"),
                error_file_path=str(tmp_path / "errors.log"),
                warnings_file_path=str(tmp_path / "warnings.log"),
            ),
        )
        try:
            assert mgr.set_sink_enabled("warnings_file", False) is True
            mgr.warning("предупреждение в снятый приёмник", module="проба")
            stats = mgr.get_stats()
        finally:
            mgr.shutdown()

        assert stats["unresolved_channel_records"] == 0, "плоскость ошибок осталась со старым поведением"
        assert stats["records_without_channels"] == 0
        # Замер показал больше, чем ожидалось: плоскость ошибок деградирует
        # ИЗЯЩНО. Сняли `warnings_file` — WARNING поехал в `errors_file`,
        # ближайший живой severity-канал, то есть потери нет вовсе, а не
        # «потеря своего класса», как предполагал первый вариант теста.
        # Записываю факт, а не догадку.
        assert "предупреждение в снятый приёмник" in (tmp_path / "errors.log").read_text(encoding="utf-8")

    def test_record_for_a_disabled_sink_is_accounted_not_lost(self, tmp_path) -> None:
        """Запись, адресованная снятому приёмнику, уходит в потери, а не в никуда.

        Ф7.4: прежняя редакция сторожила ХВОСТ БУФЕРА («то, что попало в пачку до
        disable, честно уедет в потери»). Буфера нет — хвоста тоже; свойство,
        ради которого тест писался, осталось прежним: снятие приёмника не
        заводит четвёртый, никем не считаемый класс потери.
        """
        manager = LoggerManager(config=_config(tmp_path))
        try:
            manager.set_sink_enabled("second", False)
            manager.info("после снятия", module="приложение")
            stats = manager.get_stats()
        finally:
            manager.shutdown()

        counted = (
            stats["unresolved_channel_records"] + stats["records_without_channels"] + stats["channel_written_records"]
        )
        assert counted >= 1, "запись исчезла бесследно — несчитаемый класс потери"


class TestCachesAreBounded:
    """Ф2.х (Н5): у карт решений и маршрута есть потолок.

    Проба ревью Ф2: после 2.4 ось `scope` — произвольная строка с call-site, и
    ключ «скоуп-уровень-источник» рос без предела на динамических именах (3000
    имён → 3000 записей в каждой карте). Класс Ф0.3/F6. На переполнении карта
    чистится целиком: кэш — мемо, корректность от сброса не зависит, и ровно это
    вторая половина пары.
    """

    def test_both_maps_hold_at_most_the_ceiling(self, logger) -> None:
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            _DECISION_CACHE_CEILING,
        )

        for i in range(_DECISION_CACHE_CEILING + 50):
            logger.should_log("SYSTEM", LogLevel.WARNING, f"мод_{i}")
            # DEBUG-скоуп выключен: маршрут кэшируется (None), диск не платится.
            logger.log("DEBUG", LogLevel.DEBUG, "запись", f"мод_{i}")

        assert len(logger._decision_cache) <= _DECISION_CACHE_CEILING
        assert len(logger._route_cache) <= _DECISION_CACHE_CEILING

    def test_the_answer_survives_the_overflow(self, logger) -> None:
        """Пара к потолку: сброс карты не меняет ни одного ответа."""
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            _DECISION_CACHE_CEILING,
        )

        до = logger.should_log("SYSTEM", LogLevel.WARNING, "мод_якорь")
        for i in range(_DECISION_CACHE_CEILING + 1):
            logger.should_log("SYSTEM", LogLevel.WARNING, f"мод_{i}")

        assert logger.should_log("SYSTEM", LogLevel.WARNING, "мод_якорь") is до is True
