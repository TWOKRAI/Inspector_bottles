# -*- coding: utf-8 -*-
"""Ф2.2 — проводка иерархии имён: гейт, маршрут, плоскость ошибок, конфиг.

Резолв сам по себе проверен в ``test_name_hierarchy.py`` без единого файла.
Здесь — то, что дефект резолва увидеть не даст: **куда физически легла запись**.
Судим по содержимому файлов и по счётчикам, а не по тому, какие методы были
вызваны: спай на имя внутреннего метода сторожил бы имя, а не свойство.

Заявленные свойства:

  G. правило имени задаёт порог СИЛЬНЕЕ скоупа — в обе стороны (мягче/строже);
  H. правило будит выключенный скоуп (иначе главная ручка фазы мертва в
     дефолтной поставке — ``DEBUG`` выключен), а без правила выключенный скоуп
     продолжает молчать;
  I. пустая таблица правил → поведение бит-в-бит прежнее (характеризация);
  J. приёмники берутся у правила; объявленная пустота = «приёмников нет» и
     считается потерей своего класса, а не подменяется набором скоупа;
  K. пересборка конфига пересобирает дерево: снятое правило перестаёт
     действовать (устаревшее правило = лог уходит не туда);
  L. severity-путь плоскости ошибок правилом имени НЕ заглушается;
  M. секция ``observability.loggers`` доезжает до менеджера настоящим швом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerRuleSchema,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.log_enums import LogLevel, LogScope

SOURCE = "vision.capture.hikvision"


def _config(directory: Path, loggers: Dict[str, LoggerRuleSchema] | None = None) -> LoggerManagerConfig:
    """Стенд: два файловых приёмника, три скоупа, один из которых выключен.

    Выключенный ``DEBUG`` здесь не для полноты — это дефолт боевой поставки
    (пер-кадровый firehose), и свойство H проверяется именно на нём.
    """
    return LoggerManagerConfig(
        app_name="name_routing",
        log_directory=str(directory),
        enable_batching=False,
        loggers=loggers or {},
        channels={
            "main_file": LoggerChannelSchema(
                name="main_file", type="file", enabled=True, file_path="main.log", rotate=False
            ),
            "named_file": LoggerChannelSchema(
                name="named_file", type="file", enabled=True, file_path="named.log", rotate=False
            ),
        },
        scopes={
            "BUSINESS": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["main_file"]),
            "SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["main_file"]),
            "DEBUG": LoggerScopeSchema(enabled=False, min_level="DEBUG", channels=["main_file"]),
        },
    )


def _manager(directory: Path, loggers: Dict[str, LoggerRuleSchema] | None = None) -> LoggerManager:
    return LoggerManager(config=_config(directory, loggers))


def _text(directory: Path, name: str) -> str:
    path = directory / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


class TestNameBeatsScope:
    """G — порог задаёт правило имени; проверка по файлу, обе стороны."""

    def test_rule_looser_than_scope_lets_the_record_through(self, tmp_path: Path) -> None:
        """Скоуп молчит ниже WARNING, правило разрешает INFO — запись на диске.

        Это и есть запрошенная ручка: болтливость выдана ОДНОМУ поддереву, а
        порог скоупа не тронут.
        """
        mgr = _manager(tmp_path, {"vision.capture": LoggerRuleSchema(level="INFO")})
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "по правилу имени", SOURCE)
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "по скоупу", "Plugins.roi")
        finally:
            mgr.shutdown()
        body = _text(tmp_path, "main.log")
        assert "по правилу имени" in body
        assert "по скоупу" not in body

    def test_rule_stricter_than_scope_rejects_the_record(self, tmp_path: Path) -> None:
        """Обратная сторона: правило умеет и заглушить поддерево.

        Без этой половины «имя главнее» проверено в одну сторону, и реализация
        «правило только разрешает» прошла бы тест G целиком.
        """
        mgr = _manager(tmp_path, {"vision.capture": LoggerRuleSchema(level="ERROR")})
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.WARNING, "заглушено правилом", SOURCE)
            mgr.log(LogScope.BUSINESS, LogLevel.WARNING, "прошло по скоупу", "Plugins.roi")
        finally:
            mgr.shutdown()
        body = _text(tmp_path, "main.log")
        assert "заглушено правилом" not in body
        assert "прошло по скоупу" in body

    def test_predicate_agrees_with_what_lands_on_disk(self, tmp_path: Path) -> None:
        """``is_enabled_for`` обязан отвечать то же, что решит маршрут.

        Расхождение здесь означало бы второй гейт — ровно та развилка, которую
        закрывала Ф4.2: вызывающий не платит за сборку сообщения, а запись
        всё-таки пишется (или наоборот).
        """
        mgr = _manager(tmp_path, {"vision.capture": LoggerRuleSchema(level="INFO")})
        try:
            allowed = mgr.is_enabled_for(SOURCE, LogLevel.INFO, LogScope.BUSINESS)
            denied = mgr.is_enabled_for("Plugins.roi", LogLevel.INFO, LogScope.BUSINESS)
            assert (allowed, denied) == (True, False)
            assert (mgr._route(LogScope.BUSINESS, LogLevel.INFO, SOURCE) is not None) is allowed  # noqa: SLF001
            assert (mgr._route(LogScope.BUSINESS, LogLevel.INFO, "Plugins.roi") is not None) is denied  # noqa: SLF001
        finally:
            mgr.shutdown()


class TestDisabledScope:
    """H — пара: правило будит выключенный скоуп / без правила он молчит."""

    def test_rule_wakes_the_disabled_debug_scope(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path, {"vision": LoggerRuleSchema(level="DEBUG")})
        try:
            mgr.log(LogScope.DEBUG, LogLevel.DEBUG, "разбужено правилом", SOURCE)
        finally:
            mgr.shutdown()
        assert "разбужено правилом" in _text(tmp_path, "main.log")

    def test_without_a_rule_the_disabled_scope_stays_silent(self, tmp_path: Path) -> None:
        """Парный. Без него «будит» доказано, а «по умолчанию тихо» — нет."""
        mgr = _manager(tmp_path)
        try:
            mgr.log(LogScope.DEBUG, LogLevel.DEBUG, "не должно появиться", SOURCE)
        finally:
            mgr.shutdown()
        assert "не должно появиться" not in _text(tmp_path, "main.log")

    def test_rule_on_a_sibling_subtree_does_not_wake_the_scope_for_others(self, tmp_path: Path) -> None:
        """Цена решения названа вслух — и ограничена поддеревом, а не скоупом."""
        mgr = _manager(tmp_path, {"vision": LoggerRuleSchema(level="DEBUG")})
        try:
            mgr.log(LogScope.DEBUG, LogLevel.DEBUG, "чужая ветка", "Plugins.roi")
        finally:
            mgr.shutdown()
        assert "чужая ветка" not in _text(tmp_path, "main.log")


class TestEmptyTableIsCharacterisation:
    """I — без правил поведение обязано остаться прежним."""

    @pytest.mark.parametrize(
        "scope, level, expected",
        [
            (LogScope.BUSINESS, LogLevel.WARNING, True),
            (LogScope.BUSINESS, LogLevel.INFO, False),
            (LogScope.SYSTEM, LogLevel.ERROR, True),
            (LogScope.SYSTEM, LogLevel.DEBUG, False),
            (LogScope.DEBUG, LogLevel.DEBUG, False),
        ],
    )
    def test_gate_answers_come_from_the_scope(
        self, tmp_path: Path, scope: LogScope, level: LogLevel, expected: bool
    ) -> None:
        mgr = _manager(tmp_path)
        try:
            assert mgr.should_log(scope, level, SOURCE) is expected
        finally:
            mgr.shutdown()

    def test_channels_come_from_the_scope(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        try:
            assert list(mgr._route(LogScope.BUSINESS, LogLevel.WARNING, SOURCE) or []) == ["main_file"]  # noqa: SLF001
        finally:
            mgr.shutdown()


class TestChannelsFromRule:
    """J — раскладка по файлам: то, ради чего задача и делается."""

    def test_rule_sends_the_subtree_to_its_own_file(self, tmp_path: Path) -> None:
        """«Какой файл» задаётся конфигом, а не совпадением имени процесса."""
        mgr = _manager(
            tmp_path,
            {"vision.capture": LoggerRuleSchema(level="INFO", channels=["named_file"])},
        )
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "в свой файл", SOURCE)
            mgr.log(LogScope.BUSINESS, LogLevel.WARNING, "в общий файл", "Plugins.roi")
        finally:
            mgr.shutdown()
        assert "в свой файл" in _text(tmp_path, "named.log")
        assert "в свой файл" not in _text(tmp_path, "main.log")
        assert "в общий файл" in _text(tmp_path, "main.log")

    def test_declared_empty_is_a_named_loss_not_a_fallback_to_scope(self, tmp_path: Path) -> None:
        """``channels: []`` — «никуда», и это ВИДНО снаружи счётчиком.

        Подмена объявленной пустоты набором скоупа была бы худшим исходом:
        оператор написал «этому поддереву никуда», а записи продолжали бы идти
        в общий файл — и молча.
        """
        mgr = _manager(
            tmp_path,
            {"vision.capture": LoggerRuleSchema(level="INFO", channels=[])},
        )
        try:
            before = mgr.stats.get("records_without_channels", 0)
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "никуда", SOURCE)
            after = mgr.stats.get("records_without_channels", 0)
        finally:
            mgr.shutdown()
        assert after == before + 1
        assert "никуда" not in _text(tmp_path, "main.log")
        assert "никуда" not in _text(tmp_path, "named.log")


class TestRebuild:
    """K — снятое конфигом правило обязано перестать действовать."""

    def test_removed_rule_stops_acting_after_reconfigure(self, tmp_path: Path) -> None:
        """Устаревшее дерево = запись уходит не туда; симптом ищется днями.

        Проверка по ФАЙЛУ до и после: «кэш очищен» — утверждение про внутренности,
        а доказывать надо наблюдаемое.
        """
        mgr = _manager(tmp_path, {"vision.capture": LoggerRuleSchema(level="INFO", channels=["named_file"])})
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "пока правило живо", SOURCE)
            mgr.reconfigure(_config(tmp_path))
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "после снятия правила", SOURCE)
            mgr.log(LogScope.BUSINESS, LogLevel.WARNING, "после снятия, по скоупу", SOURCE)
        finally:
            mgr.shutdown()
        named, main = _text(tmp_path, "named.log"), _text(tmp_path, "main.log")
        assert "пока правило живо" in named
        assert "после снятия правила" not in named
        assert "после снятия правила" not in main  # INFO снова ниже порога скоупа
        assert "после снятия, по скоупу" in main

    def test_added_rule_starts_acting_after_reconfigure(self, tmp_path: Path) -> None:
        """Парный: дерево, которое не пересобралось, ответит старым молчанием."""
        mgr = _manager(tmp_path)
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "до правила", SOURCE)
            mgr.reconfigure(_config(tmp_path, {"vision": LoggerRuleSchema(level="INFO")}))
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "после правила", SOURCE)
        finally:
            mgr.shutdown()
        body = _text(tmp_path, "main.log")
        assert "до правила" not in body
        assert "после правила" in body


class TestErrorPlaneInvariant:
    """L — правилом имени ошибку заглушить нельзя."""

    def test_severity_path_ignores_the_name_rule(self, tmp_path: Path) -> None:
        """Инвариант 1 плана: ошибка не теряется. Правило про неё не спрашивают.

        Severity-маршрут ``ErrorManager`` не ходит ни в скоуп, ни в иерархию —
        приёмник определяет уровень. Тест закрепляет, что Ф2.2 этого не сдвинула:
        новая ручка не имеет права стать способом молча погасить ERROR.
        """
        from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig

        mgr = ErrorManager(
            config=ErrorManagerConfig(
                app_name="name_routing_errors",
                log_directory=str(tmp_path),
                enable_batching=False,
            )
        )
        try:
            mgr.config.loggers = {"vision": LoggerRuleSchema(level="CRITICAL")}
            mgr.invalidate_decision_cache()
            mgr._name_hierarchy = type(mgr._name_hierarchy)(mgr.config.loggers)  # noqa: SLF001
            routed = mgr._route(LogScope.SYSTEM, LogLevel.ERROR, SOURCE)  # noqa: SLF001
        finally:
            mgr.shutdown()
        assert routed, "ERROR обязан получить приёмник вопреки правилу CRITICAL-и-выше"


class TestConfigSeam:
    """M — ручка доезжает настоящим швом, а не подстановкой в тесте."""

    def test_observability_section_reaches_the_manager_config(self) -> None:
        """``observability.loggers`` → ``expand_observability`` → ``LoggerManagerConfig``.

        Тест ходит через прод-функцию раскладки: без него «поле есть» доказано,
        а «его можно задать из конфига» — нет (класс «вакуумный тест», Ф6.х.9).
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        expanded = expand_observability({"loggers": {"vision.capture": {"level": "debug", "channels": ["named_file"]}}})
        cfg = LoggerManagerConfig.model_validate(expanded["logger"])
        rule = cfg.loggers["vision.capture"]
        assert rule.level == "DEBUG"
        assert rule.channels == ["named_file"]

    def test_absent_section_emits_nothing(self) -> None:
        """Молчащая секция не имеет права materialise пустой словарь.

        По правилу Г3 пустота — это ВЛАДЕНИЕ: эмитируй ``expand`` пустой
        ``loggers``, слой приложения стирал бы правила нижнего слоя.
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        assert "loggers" not in expand_observability({})["logger"]


class TestHotPathUnchanged:
    """Авторские тесты на опасности механизма, а не на его контракт."""

    def test_empty_table_does_not_enter_the_resolver(self, tmp_path: Path) -> None:
        """Гарантия «бит-в-бит прежнее» стоит на дешёвом вопросе о пустоте.

        Проверяем не «метод не вызван» (это сторожило бы имя), а то, что после
        сотни записей кэш резолва пуст — то есть резолв действительно не
        работал ни разу.
        """
        mgr = _manager(tmp_path)
        try:
            for i in range(100):
                mgr.log(LogScope.BUSINESS, LogLevel.WARNING, "запись %s", SOURCE, i)
            assert not mgr._name_hierarchy._level_cache  # noqa: SLF001
            assert not mgr._name_hierarchy._channels_cache  # noqa: SLF001
        finally:
            mgr.shutdown()

    def test_cache_grows_by_names_not_by_records(self, tmp_path: Path) -> None:
        """Кэш растёт по числу ИМЁН, а не по числу записей.

        Сравниваются два замера одного и того же стенда (10 записей против 100),
        а не абсолютный размер: сам менеджер логирует свой подъём из источника
        ``logger_manager``, и константа «ровно один ключ» была бы подгонкой под
        текущий состав стартовых записей — то есть тестом, который сломается от
        безобидной правки и ничего при этом не защитит.

        Рост по записям был бы утечкой того же класса, что Ф0.3: потолок стоял
        не там, где росла память.
        """
        mgr = _manager(tmp_path, {"vision": LoggerRuleSchema(level="DEBUG")})
        try:
            for i in range(10):
                mgr.log(LogScope.BUSINESS, LogLevel.INFO, "запись %s", SOURCE, i)
            after_ten = len(mgr._name_hierarchy._level_cache)  # noqa: SLF001
            for i in range(90):
                mgr.log(LogScope.BUSINESS, LogLevel.INFO, "запись %s", SOURCE, i)
            after_hundred = len(mgr._name_hierarchy._level_cache)  # noqa: SLF001
            assert after_ten == after_hundred
            assert SOURCE in mgr._name_hierarchy._level_cache  # noqa: SLF001
        finally:
            mgr.shutdown()

    def test_unknown_level_in_a_rule_passes_the_record(self, tmp_path: Path) -> None:
        """Опечатка в имени уровня — не повод устроить тишину.

        Та же политика, что у ``LoggerScopeSchema.should_log``: незнакомый
        уровень пропускает. Две соседние ветки одного решения с разной политикой
        были бы худшим вариантом — «тише DEBUG» в одном месте и firehose в
        другом.
        """
        mgr = _manager(tmp_path, {"vision": LoggerRuleSchema(level="ВАЖНО")})
        try:
            mgr.log(LogScope.BUSINESS, LogLevel.INFO, "опечатка в уровне", SOURCE)
        finally:
            mgr.shutdown()
        assert "опечатка в уровне" in _text(tmp_path, "main.log")
