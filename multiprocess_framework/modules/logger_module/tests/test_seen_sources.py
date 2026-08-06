# -*- coding: utf-8 -*-
"""Ф2.6, шаг 4 — какие имена источников реально писали в процессе.

План: plans/observability-unified-routing.md, задача 2.6.

``resolve_rule`` отвечает про имя, которое спрашивающий уже знает. На стенде вопрос
обычно обратный — **какие имена вообще бывают**, и до сих пор ответом был только греп
по файлу лога: то есть список тех, чьи записи куда-то доехали. Источник, у которого всё
гасится порогом, в такой список не попадал вовсе — а это ровно тот случай, который
оператор и разбирает («почему от него ничего нет»).

Новое состояние под это не заводится: обе карты решений ключуются
``(скоуп, уровень, имя)`` и заполняются на каждой записи, множество имён в них уже
лежит. Отдельный ``set`` на горячем пути стоил бы вставки за запись ради известного.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture()
def logger(tmp_path) -> Any:
    """Порог INFO — чтобы DEBUG-записи гасились и проверялся именно этот случай."""
    manager = LoggerManager(
        config=LoggerManagerConfig(
            app_name="seen26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"f": LoggerChannelSchema(type="file", enabled=True, file_path="f.log", rotate=False)},
            # Ф8.1: порог, ради которого фикстура и заведена (см. докстринг), —
            # теперь корневой. Автоматическая миграция поставила сюда DEBUG,
            # выбрав «самый низкий порог файла», и тем убила предмет теста:
            # DEBUG-запись обязана ГАСИТЬСЯ, иначе проверять нечего.
            default_level="INFO",
            scopes={"SYSTEM": LoggerScopeSchema(channels=["f"])},
        )
    )
    yield manager
    manager.shutdown()


class TestWhoWrote:
    def test_writers_are_listed(self, logger: Any) -> None:
        logger.system(LogLevel.INFO, "раз", module="альфа")
        logger.system(LogLevel.INFO, "два", module="бета")

        assert logger.seen_sources() == ["альфа", "бета"]

    def test_a_fully_gated_source_is_still_visible(self, logger: Any) -> None:
        """Главный случай: от источника НИЧЕГО не записано, а знать о нём надо.

        Греп по файлу его не найдёт по определению — записей там нет. Именно с
        этим вопросом («почему от него пусто») оператор и приходит, поэтому имя
        обязано быть видно, даже когда всё погашено порогом.
        """
        logger.system(LogLevel.DEBUG, "погашено", module="молчун")
        logger.flush()

        assert "молчун" in logger.seen_sources()

    def test_names_are_unique_and_sorted(self, logger: Any) -> None:
        """Устойчивый порядок: readback не должен прыгать между опросами."""
        for _ in range(3):
            logger.system(LogLevel.INFO, "x", module="бета")
            logger.system(LogLevel.INFO, "x", module="альфа")

        assert logger.seen_sources() == ["альфа", "бета"]

    def test_empty_before_anyone_wrote(self, logger: Any) -> None:
        assert logger.seen_sources() == []


class TestCheapPredicateCallerIsCoveredToo:
    """Вторая половина союза: источник, спросивший предикат и не писавший.

    Дисциплина дешёвого предиката (``if logger.is_enabled_for(...)`` перед сборкой
    дорогого сообщения) — штатный приём этого проекта. Такой источник до ``log()``
    не доходит вовсе, и в карте маршрута его нет: замер даёт
    ``decision == ['predikat_only']``, ``route == []``.

    Он обязан быть виден: «я поставил правило, а от источника всё равно тишина» —
    это ровно тот разбор, ради которого список и заведён, и «его гасит порог ещё
    на предикате» здесь и есть ответ.
    """

    def test_predicate_only_source_is_listed(self, logger: Any) -> None:
        assert logger.is_enabled_for("спросивший", LogLevel.DEBUG) is False
        assert logger._route_cache == {}  # noqa: SLF001 — предмет проверки: до маршрута не дошло

        assert logger.seen_sources() == ["спросивший"]


class TestErrorPlaneIsCoveredToo:
    """Плоскость ошибок — единственная причина брать ОБЕ карты решений.

    Добавлен по итогу слом-инъекции. Я объяснил союз двух карт тем, что «маршрут
    кэшируется только для прошедшей записи», и снятие одной из карт обязано было
    покраснеть. Не покраснело: замер показал, что на плоскости логов обе карты
    держат одно и то же (отклонённая запись тоже попадает в карту маршрута —
    там кэшируется сам факт отказа). Довод был неверен, а союз при этом нужен —
    но по другой причине: ``ErrorManager._route`` идёт severity-путём и гейт не
    спрашивает, поэтому у него карта решений остаётся ПУСТОЙ, и без карты
    маршрута источники ошибок не были бы видны вовсе.
    """

    def test_error_source_is_listed(self, tmp_path) -> None:
        from multiprocess_framework.modules.error_module.configs.error_manager_config import (
            ErrorManagerConfig,
        )
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

        manager = ErrorManager(
            config=ErrorManagerConfig(app_name="seen26e", log_directory=str(tmp_path), enable_batching=False)
        )
        try:
            manager.error("сбой", module="источник.ошибки")

            assert manager._decision_cache == {}  # noqa: SLF001 — предмет проверки: гейт не спрошен
            assert manager.seen_sources() == ["источник.ошибки"]
        finally:
            manager.shutdown()


class TestKnownLimits:
    def test_list_resets_with_the_decision_caches(self, logger: Any) -> None:
        """Ограничение названо вслух и закреплено, а не оставлено сюрпризом.

        Список живёт от последней пересборки конфигурации, а не от старта процесса:
        карты решений стареют в единой точке инвалидации, и имена уходят вместе с
        ними. Сразу после пересборки он пуст — это «с тех пор ещё никто не писал»,
        а не поломка. Тест существует, чтобы поведение нельзя было принять за баг
        и «починить» отдельным вечным множеством, не заметив, что оно тут не нужно.
        """
        logger.system(LogLevel.INFO, "до", module="альфа")
        assert logger.seen_sources() == ["альфа"]

        logger.invalidate_decision_cache()

        assert logger.seen_sources() == []

        logger.system(LogLevel.INFO, "после", module="бета")
        assert logger.seen_sources() == ["бета"]
