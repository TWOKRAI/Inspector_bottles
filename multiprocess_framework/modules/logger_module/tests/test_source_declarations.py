# -*- coding: utf-8 -*-
"""Ф2.7 — объявление источника рядом с модулем становится активным.

План: plans/observability-unified-routing.md, задача 2.7.

Ф2.6 положила имя константой `LOG_SOURCE` в `interfaces.py`, но объявление осталось
пассивным: узнать «какие имена вообще объявлены» можно было только грепом, а
правило-дефолт модуля пришлось бы писать в центральный конфиг. Здесь модуль зовёт
`declare_log_source` рядом со своей константой — и каталог наполняется импортом.

Резидуал 2.6 («два объявления на один префикс — конфликтовать нечему, потому что
объявления никуда не собираются») закрывается здесь же: теперь есть чему конфликтовать,
и конфликт — отказ, а не выбор по порядку импортов.

Независимый `tester` не вызывался — инструментальный запрет на субагентов в сессии.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from multiprocess_framework.modules.log_declarations import (
    declare_log_source,
    declared_rules,
    declared_sources,
    forget_declarations,
)
from multiprocess_framework.modules.logger_module.configs import LoggerRuleSchema


@pytest.fixture()
def чистый_реестр() -> Any:
    """Свой реестр на тест: иначе порядок тестов начал бы значить.

    Восстановление обязательно — реестр процессный, и оставленная запись сломала бы
    соседний тест, который про неё ничего не знает.
    """
    было = {name: (owner, None) for name, owner in declared_sources().items()}
    правила = declared_rules()
    forget_declarations()
    yield
    forget_declarations()
    for name, (owner, _r) in было.items():
        declare_log_source(name, owner=owner, rule=правила.get(name))


class TestModuleBringsItsNameAlong:
    """Каталог наполняется импортом — центральных правок ноль."""

    def test_real_modules_declared_themselves(self) -> None:
        """Живая проводка, а не фейк: три настоящих модуля уже в каталоге.

        Тест на фейковом реестре доказал бы реестр. Здесь проверяется, что
        объявление реально стоит в `interfaces.py` и срабатывает на импорте —
        то есть что механизм подключён, а не просто написан.
        """
        каталог = declared_sources()

        for имя in (
            "multiprocess_framework.modules.command_module",
            "multiprocess_framework.modules.dispatch_module",
            "multiprocess_framework.modules.statistics_module",
        ):
            assert имя in каталог, каталог
            assert каталог[имя].endswith("interfaces"), "владелец — файл объявления"

    def test_catalogue_answers_before_anyone_wrote(self, чистый_реестр: Any) -> None:
        """Отличие от `seen_sources`: там кто ПИСАЛ, здесь кто МОЖЕТ.

        Источник, у которого всё гасится порогом, в журнале не появится вовсе —
        а разбирают обычно именно его («почему от него пусто»).
        """
        declare_log_source("пакет.молчун", owner="пакет.interfaces")

        assert declared_sources() == {"пакет.молчун": "пакет.interfaces"}

    def test_declaration_returns_the_name(self, чистый_реестр: Any) -> None:
        """Объявление пишется одной строкой рядом с константой, а не двумя."""
        assert declare_log_source("пакет.имя", owner="пакет.interfaces") == "пакет.имя"


class TestConflictIsRefusedNotResolved:
    """Резидуал 2.6: два объявления на один префикс — громко."""

    def test_two_owners_on_one_name_are_refused(self, чистый_реестр: Any) -> None:
        declare_log_source("общее.имя", owner="первый.interfaces")

        with pytest.raises(ValueError, match="первый.interfaces"):
            declare_log_source("общее.имя", owner="второй.interfaces")

    def test_the_same_owner_may_re_declare(self, чистый_реестр: Any) -> None:
        """Повторный импорт того же модуля — не конфликт.

        Модуль переимпортируют (reload в тестах, spawn дочернего процесса), и
        падать на этом нельзя: иначе механизм ломал бы штатный запуск системы.
        """
        declare_log_source("своё.имя", owner="мой.interfaces")
        declare_log_source("своё.имя", owner="мой.interfaces")

        assert declared_sources() == {"своё.имя": "мой.interfaces"}

    def test_the_same_owner_with_a_different_rule_is_refused(self, чистый_реестр: Any) -> None:
        """Иначе «правило поменялось при переимпорте» прошло бы молча."""
        declare_log_source("своё.имя", owner="мой.interfaces", rule=LoggerRuleSchema(level="INFO"))

        with pytest.raises(ValueError):
            declare_log_source("своё.имя", owner="мой.interfaces", rule=LoggerRuleSchema(level="DEBUG"))

    def test_an_equal_rule_re_declared_passes(self, чистый_реестр: Any) -> None:
        """Пара к предыдущему: сравнение по СОДЕРЖИМОМУ, не по identity.

        Повторный импорт создаёт новый объект схемы с теми же полями. Сравнение по
        identity объявило бы конфликт там, где его нет, — то есть уронило бы
        процесс на совершенно законном reload.
        """
        declare_log_source("своё.имя", owner="мой.interfaces", rule=LoggerRuleSchema(level="INFO"))
        declare_log_source("своё.имя", owner="мой.interfaces", rule=LoggerRuleSchema(level="INFO"))

        assert list(declared_rules()) == ["своё.имя"]


class TestDeclaredRuleIsTheBottomLayer:
    """Модуль знает про себя, но последнее слово — за тем, кто систему собирает."""

    def test_declared_rule_acts_without_touching_the_central_config(self, чистый_реестр: Any) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source("пакет.шумный", owner="пакет.interfaces", rule=LoggerRuleSchema(level="ERROR"))

        expanded = expand_observability({})

        assert expanded["logger"]["loggers"]["пакет.шумный"]["level"] == "ERROR"

    def test_the_application_overrides_the_declaration(self, чистый_реестр: Any) -> None:
        """Пара: объявление — слой ПОД конфигом приложения, а не поверх него.

        Переставь порядок — и правка в `system.yaml` перестанет действовать,
        оставаясь видимой в файле. Тихий отказ того же класса, что дал 288 пустых
        файлов: работает не так, а не ломается.
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source("пакет.шумный", owner="пакет.interfaces", rule=LoggerRuleSchema(level="ERROR"))

        expanded = expand_observability({"loggers": {"пакет.шумный": {"level": "DEBUG"}}})

        assert expanded["logger"]["loggers"]["пакет.шумный"]["level"] == "DEBUG"

    def test_a_declaration_without_a_rule_adds_nothing(self, чистый_реестр: Any) -> None:
        """Имя объявляют почти все, порог — только тот, кому есть что сказать."""
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source("пакет.обычный", owner="пакет.interfaces")

        assert "loggers" not in expand_observability({})["logger"]


class TestLayerOverridesByAxisNotWholesale:
    """Ф2.х (Н1): правило приложения перекрывает объявленное ПО ОСЯМ.

    «Две оси резолвятся независимо» — аксиома дерева (Ф2.2); шов слоёв обязан
    говорить на том же языке. Находка ревью Ф2: `{**declared, **layered}`
    замещал запись целиком, и приложение, правившее только `level`, молча
    стирало `channels`, объявленные модулем.
    """

    def test_app_overriding_level_keeps_the_declared_channels(self, чистый_реестр: Any) -> None:
        """Репро находки: правка одной оси не имеет права стереть соседнюю."""
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source(
            "пакет.шумный",
            owner="пакет.interfaces",
            rule=LoggerRuleSchema(level="ERROR", channels=["busy_file"]),
        )

        expanded = expand_observability({"loggers": {"пакет.шумный": {"level": "DEBUG"}}})
        rule = expanded["logger"]["loggers"]["пакет.шумный"]

        assert rule["level"] == "DEBUG", "ось level — за приложением"
        assert rule["channels"] == ["busy_file"], "ось channels модуля обязана уцелеть"

    def test_app_erases_channels_explicitly_with_an_empty_list(self, чистый_реестр: Any) -> None:
        """Пара: стирание оси осталось выразимым — но ЯВНО, штатным `[]` (Г3)."""
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source(
            "пакет.шумный",
            owner="пакет.interfaces",
            rule=LoggerRuleSchema(level="ERROR", channels=["busy_file"]),
        )

        expanded = expand_observability({"loggers": {"пакет.шумный": {"channels": []}}})
        rule = expanded["logger"]["loggers"]["пакет.шумный"]

        assert rule["channels"] == [], "`[]` — решение, а не молчание"
        assert rule["level"] == "ERROR", "нетронутая ось наследуется от модуля"

    def test_declared_silence_does_not_materialize_keys(self, чистый_реестр: Any) -> None:
        """Объявление претендует только на оси, про которые модуль сказал.

        Материализованный `channels: None` был бы словом слоя там, где модуль
        молчал, — ровно класс «молчание ≠ пустота», из-за которого ключи
        наверх не эмитятся (ADR-PM-020).
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        declare_log_source("пакет.тихий", owner="пакет.interfaces", rule=LoggerRuleSchema(level="ERROR"))

        rule = expand_observability({})["logger"]["loggers"]["пакет.тихий"]

        assert rule == {"level": "ERROR"}, "молчащие оси не становятся ключами"


class TestRuleShapeIsCheckedAtTheBorder:
    """Ф2.х (Н3): форма правила проверяется на границе реестра, не в сборке.

    Находка ревью Ф2: правило-словарь принималось молча и падало позже в
    `expand_observability` — AttributeError без имени виновника, далеко от
    объявившего модуля (класс «model_copy не валидирует», третий заход).
    """

    def test_a_dict_rule_is_refused_naming_the_owner(self, чистый_реестр: Any) -> None:
        with pytest.raises(ValueError, match="мой.interfaces"):
            declare_log_source("пакет.имя", owner="мой.interfaces", rule={"level": "INFO"})

    def test_a_schema_rule_is_accepted(self, чистый_реестр: Any) -> None:
        """Пара: настоящая схема проходит той же дверью."""
        declare_log_source("пакет.имя", owner="мой.interfaces", rule=LoggerRuleSchema(level="INFO"))

        assert list(declared_rules()) == ["пакет.имя"]


class TestLateRuleDeclarationIsAudible:
    """Ф2.х (Н2): правило, объявленное ПОСЛЕ снимка, слышно.

    Boot-конфиг детям собирает ассемблер в РОДИТЕЛЕ, пересборку — сам ребёнок;
    оба берут снимок `declared_rules()` на момент чтения. Правило позднего
    импорта (плагин) в уже собранные конфиги не попало — молчать об этом
    значило бы «правило написано, а не действует» без единого сигнала.
    """

    def test_a_rule_declared_after_the_snapshot_is_announced(self, чистый_реестр: Any, caplog: Any) -> None:
        declared_rules()  # снимок взят — так делает сборка конфига

        with caplog.at_level(logging.WARNING):
            declare_log_source("поздний.модуль", owner="поздний.interfaces", rule=LoggerRuleSchema(level="ERROR"))

        жалобы = [r.getMessage() for r in caplog.records if "поздний.модуль" in r.getMessage()]
        assert len(жалобы) == 1, caplog.records
        assert "ПОСЛЕ сборки" in жалобы[0]

    def test_a_name_only_declaration_after_the_snapshot_is_silent(self, чистый_реестр: Any, caplog: Any) -> None:
        """Пара: каталог имён читается живьём (readback), опаздывать ему нечем."""
        declared_rules()

        with caplog.at_level(logging.WARNING):
            declare_log_source("поздний.молчун", owner="поздний.interfaces")

        assert [r for r in caplog.records if "поздний.молчун" in r.getMessage()] == []

    def test_a_rule_declared_before_the_snapshot_is_silent(self, чистый_реестр: Any, caplog: Any) -> None:
        """Пара: штатный порядок (импорт → сборка) не шумит."""
        with caplog.at_level(logging.WARNING):
            declare_log_source("ранний.модуль", owner="ранний.interfaces", rule=LoggerRuleSchema(level="ERROR"))
            declared_rules()

        assert [r for r in caplog.records if "ранний.модуль" in r.getMessage()] == []
