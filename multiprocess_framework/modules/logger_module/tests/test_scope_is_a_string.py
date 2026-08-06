# -*- coding: utf-8 -*-
"""Ф2.4 — скоуп стал строкой, новая группа заводится конфигом.

План: plans/observability-unified-routing.md, задача 2.4.

Задача снимает последнюю точку, где заведение группы логов требовало правки кода
фреймворка: ``log()`` требовал члена ``Enum``, значит любая новая группа — это
коммит в ``log_enums.py``. Заодно исчезает ВТОРОЕ написание того же имени
(``PERFORMANCE`` ключом конфига, ``perf`` в записи).

**Что здесь проверяется и чего здесь нет.** Тесты автора сторожат механику
(запасная ветка, приведение регистра, однократность сигнала) и характеризуют
поведение, которое менять не собирались (``AUDIT``/``SECURITY``). Независимый
``tester`` по контракту не вызывался — инструментальный запрет на субагентов в
сессии; названо вслух здесь и в плане, потому что контракт 2.4 наблюдаем снаружи
и правило требует независимого автора тестов.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import (
    PRESET_SCOPES,
    LogLevel,
    LogScope,
)
from multiprocess_framework.modules.logger_module.core.log_types import LogRecord
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


def _manager(tmp_path, **scopes: LoggerScopeSchema) -> LoggerManager:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="scope24",
            log_directory=str(tmp_path),
            enable_batching=False,
            channels={
                "первый": LoggerChannelSchema(type="file", enabled=True, file_path="первый.log", rotate=False),
                "цех": LoggerChannelSchema(type="file", enabled=True, file_path="цех.log", rotate=False),
            },
            scopes=dict(scopes),
        )
    )


@pytest.fixture()
def logger(tmp_path) -> Any:
    manager = _manager(
        tmp_path,
        SYSTEM=LoggerScopeSchema(channels=["первый"]),
    )
    yield manager
    manager.shutdown()


class TestNewGroupNeedsOnlyConfig:
    """Главное свойство задачи: группа заводится конфигом, кода фреймворка — 0 правок."""

    def test_group_declared_only_in_config_gets_its_own_sink(self, tmp_path) -> None:
        """Приёмник НОВОЙ группы действует — значит она настоящая, а не «прошла мимо».

        Ф8.1 сняла у группы вторую ось: порога у неё больше нет, и прежняя
        половина этого теста («запись ниже порога группы отклоняется») проверяла
        бы механизм, которого не существует. Осталась та ось, ради которой группа
        и заводится, — **какие приёмники**.

        Пара к утверждению обязательна и здесь: приёмник новой группы получает
        запись, а приёмник чужой группы её НЕ получает. «Запись где-то появилась»
        согласуется и с реализацией, где незнакомая группа молча стала SYSTEM.
        """
        manager = _manager(
            tmp_path,
            КОНВЕЙЕР=LoggerScopeSchema(channels=["цех"]),
        )
        try:
            assert manager._route("КОНВЕЙЕР", LogLevel.ERROR, "мод") == ["цех"]
            assert manager._route(LogScope.SYSTEM, LogLevel.ERROR, "мод") != ["цех"]
        finally:
            manager.shutdown()

    def test_preset_constants_are_plain_strings(self) -> None:
        """Константы — обычные строки, а не члены перечисления.

        Не косметика: именно равенство строке делает ключ конфига и значение в
        записи ОДНИМ объектом. Проверяется свойство, а не тип-обёртка.
        """
        assert LogScope.SYSTEM == "SYSTEM"
        assert LogScope.PERFORMANCE == "PERFORMANCE"
        assert isinstance(LogScope.DEBUG, str)

    def test_presets_are_defaults_not_a_whitelist(self, tmp_path) -> None:
        """Перечень дефолтов существует, но НЕ ограничивает ``log()``.

        Пара к тесту выше: если бы ``PRESET_SCOPES`` где-то использовался
        валидацией, заведение группы конфигом снова потребовало бы правки
        фреймворка — то есть задача была бы отменена, оставаясь зелёной.
        """
        assert "КОНВЕЙЕР" not in PRESET_SCOPES
        manager = _manager(
            tmp_path,
            КОНВЕЙЕР=LoggerScopeSchema(channels=["цех"]),
        )
        try:
            manager.log("КОНВЕЙЕР", LogLevel.INFO, "деталь принята", "мод")
            manager.flush()
        finally:
            manager.shutdown()
        assert (tmp_path / "цех.log").read_text(encoding="utf-8").count("деталь принята") == 1


class TestOneSpelling:
    """Ключ конфига == константа == значение в записи (Р-2.4-А)."""

    def test_record_carries_the_config_key_spelling(self) -> None:
        """До Ф2.4 здесь ехало бы ``perf`` — второе написание того же имени."""
        record = LogRecord(
            timestamp=0.0,
            level=LogLevel.INFO,
            scope=LogScope.PERFORMANCE,
            message="м",
            module="мод",
            extra={},
        )
        assert record.to_dict()["scope"] == "PERFORMANCE"

    def test_lowercase_config_key_lands_on_the_canonical_one(self) -> None:
        """Ключ из YAML строчными НЕ ложится рядом с каноничным, а совпадает с ним.

        Это и есть тихий отказ, ради которого приведение стоит на границе:
        второй ключ был бы недостижим (``log()`` спрашивает канон), а оператор
        видел бы свою настройку в конфиге и не понимал, почему она не действует.
        """
        cfg = LoggerManagerConfig(default_level="DEBUG", scopes={"system": {"channels": ["первый"]}})
        assert list(cfg.scopes) == ["SYSTEM"]
        # Содержимое сверяется тоже: без этого тест зелен и у реализации, которая
        # ключ канонизировала, а значение потеряла. Ф8.1 — у скоупа одно поле.
        assert cfg.scopes["SYSTEM"].channels == ["первый"]

    def test_observability_layer_key_is_normalized_too(self) -> None:
        """Вторая граница конфига — слои наблюдаемости.

        Копия правила у ``LoggerManagerConfig`` эту границу не покрывает: слои
        мержатся между собой ДО того, как доедут до менеджера, и два написания
        дали бы два ключа, из которых до менеджера доехали бы ОБА.
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            ObservabilityConfig,
        )

        cfg = ObservabilityConfig(scopes={"business": {}})
        assert list(cfg.scopes) == ["BUSINESS"]


class TestUnknownScopeIsAudible:
    """Р-2.4-Б: запасная ветка была всегда — теперь она слышна."""

    def test_unknown_scope_is_delivered_and_announced_once(self, logger: Any, caplog) -> None:
        """Пара «доставлено И слышно», и сигнал ровно один на имя.

        Уровни РАЗНЫЕ намеренно. Три одинаковые записи проверяли бы не тот
        механизм: ключ кэша маршрута — тройка «скоуп-уровень-источник», и на
        одинаковых записях детектор зовётся ровно один раз сам по себе.
        Однократность выглядела бы доказанной, а сторожил бы её кэш. Поймано
        слом-инъекцией И-5 (снять дедупликацию — тест остался зелёным).
        """
        with caplog.at_level(logging.WARNING):
            for level in (LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR):
                logger.log("АУДИТОРИЯ", level, "запись", "мод")
            logger.flush()

        complaints = [r for r in caplog.records if "АУДИТОРИЯ" in r.getMessage()]
        assert len(complaints) == 1, [r.getMessage() for r in complaints]
        assert "первый" in complaints[0].getMessage(), "жалоба обязана назвать, КУДА запись ушла"
        assert logger.unknown_scopes() == ["АУДИТОРИЯ"]

    def test_a_name_rule_deciding_everything_does_not_blind_the_detector(self, tmp_path, caplog) -> None:
        """Правило имени, забравшее ОБЕ оси, не имеет права заглушить сигнал.

        Дефект первой редакции 2.4, найденный тестом readback'а: сигнал стоял в
        запасной ветке ``_scope_schema``, а она при выигравшем правиле имени не
        зовётся вовсе. На конфиге прототипа (правила задают приёмники двум
        источникам) детектор молчал бы уже сегодня, а после 2.3b, где корневое
        правило появится у всех, — везде.
        """
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="scope24rule",
                log_directory=str(tmp_path),
                enable_batching=False,
                channels={
                    "первый": LoggerChannelSchema(type="file", enabled=True, file_path="первый.log", rotate=False),
                    "цех": LoggerChannelSchema(type="file", enabled=True, file_path="цех.log", rotate=False),
                },
                # Корневое правило решает и порог, и приёмники — скоуп не спрашивают.
                scopes={"SYSTEM": LoggerScopeSchema(channels=["первый"])},
                loggers={"": {"level": "DEBUG", "channels": ["цех"]}},
            )
        )
        try:
            with caplog.at_level(logging.WARNING):
                manager.log("АУДИТОРИЯ", LogLevel.ERROR, "запись", "мод")
                manager.flush()

            assert manager.unknown_scopes() == ["АУДИТОРИЯ"]
            complaints = [r for r in caplog.records if "АУДИТОРИЯ" in r.getMessage()]
            assert len(complaints) == 1
            assert "цех" in complaints[0].getMessage(), "маршрут в жалобе — фактический, а не запасной"
        finally:
            manager.shutdown()

    def test_declared_scope_keeps_the_detector_silent(self, logger: Any, caplog) -> None:
        """Вторая половина пары: молчащий детектор, не показанный красным, ничего не доказывает."""
        with caplog.at_level(logging.WARNING):
            logger.log(LogScope.SYSTEM, LogLevel.INFO, "запись", "мод")
            logger.flush()

        assert [r.getMessage() for r in caplog.records if "не объявлен" in r.getMessage()] == []
        assert logger.unknown_scopes() == []

    def test_unknown_scope_record_is_not_counted_as_a_loss(self, logger: Any) -> None:
        """Запись доставлена, просто не туда, куда думал автор.

        Пятый класс рядом с четырьмя («не дошла») размыл бы их: они лечатся
        разным, и правило заведено ещё в Ф0.4.
        """
        logger.log("АУДИТОРИЯ", LogLevel.INFO, "запись", "мод")
        logger.flush()

        stats = logger.get_stats()
        assert stats["unresolved_channel_records"] == 0
        assert stats["records_without_channels"] == 0


class TestUnknownScopeDetectorIsBounded:
    """Ф2.х (Н5): детектор насыщаем — поимённый учёт не растёт без предела.

    Проба ревью Ф2: после 2.4 скоуп — произвольная строка с call-site, и
    динамическое имя (f-string с id задачи) давало 3000 имён в списке при
    O(n)-скане под локом — класс Ф0.3/F6, «рост без предела по оси имён».
    """

    def test_the_detector_saturates_with_one_final_complaint(self, logger: Any, caplog) -> None:
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            _UNKNOWN_SCOPES_CEILING,
        )

        лишних = 10
        with caplog.at_level(logging.WARNING):
            for i in range(_UNKNOWN_SCOPES_CEILING + лишних):
                logger.log(f"ЗАДАЧА_{i}", LogLevel.INFO, "запись", "мод")
            logger.flush()

        имена = logger.unknown_scopes()
        assert len(имена) == _UNKNOWN_SCOPES_CEILING, "поимённый учёт упирается в потолок"
        assert f"ЗАДАЧА_{_UNKNOWN_SCOPES_CEILING}" not in имена, "имя за потолком не записывается"
        насыщение = [r.getMessage() for r in caplog.records if "насыщен" in r.getMessage()]
        assert len(насыщение) == 1, "жалоба на насыщение — ровно одна, а не по разу на имя"

    def test_below_the_ceiling_every_name_is_still_recorded(self, logger: Any) -> None:
        """Пара: потолок не съедает обычный случай — считанные опечатки видны все."""
        for name in ("ОПЕЧАТКА_А", "ОПЕЧАТКА_Б"):
            logger.log(name, LogLevel.INFO, "запись", "мод")
        logger.flush()

        assert logger.unknown_scopes() == ["ОПЕЧАТКА_А", "ОПЕЧАТКА_Б"]


class TestPresetsWithoutConfigKeepBehaving:
    """Характеризация: ``AUDIT``/``SECURITY`` не объявлены в дефолтах С САМОГО НАЧАЛА.

    Они и до Ф2.4 уходили по запасной ветке — на порог ``default_level`` и в
    первый по счёту канал. Менять это задача не собиралась: «незнакомый = SYSTEM»
    выглядит аккуратнее, но задушил бы их молча (``SYSTEM`` в дефолтах стоит на
    ``WARNING``). Здесь закреплено, что поведение осталось прежним, а изменилась
    только его видимость.
    """

    def test_default_config_declares_four_scopes_of_six_presets(self) -> None:
        declared = set(LoggerManagerConfig().scopes)
        assert declared == {"SYSTEM", "BUSINESS", "PERFORMANCE", "DEBUG"}
        assert {LogScope.AUDIT, LogScope.SECURITY} - declared == {"AUDIT", "SECURITY"}

    def test_audit_still_goes_to_the_first_channel_at_default_level(self, logger: Any) -> None:
        assert logger.config.default_level == "INFO"
        assert logger.should_log(LogScope.AUDIT, LogLevel.INFO, "мод") is True
        assert logger._route(LogScope.AUDIT, LogLevel.INFO, "мод") == ["первый"]
