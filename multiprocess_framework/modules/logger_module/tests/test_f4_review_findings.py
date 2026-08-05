# -*- coding: utf-8 -*-
"""Регресс-стражи по находкам РЕВЬЮ ФАЗЫ Ф4 (2026-08-05), все три воспроизведены.

Общего механизма у находок нет — общая у них цена ошибки: каждая выглядит как
работающая защита и молчит.

  1. [Б-1] **``critical()`` тянул за собой хвост снятого механизма.** Ф2.6
     (`8f9a9c83`) снесла ``enable_module_logging``/``disable_module_logging``, но
     закрывающий вызов ``self._on_channels_changed()`` из последнего остался в
     файле и был поглощён телом стоящего выше ``critical()`` — вместе с
     осиротевшим заголовком секции, уехавшим на отступ метода. Симптом: КАЖДАЯ
     запись уровня CRITICAL чистит обе карты решений, обнуляет
     :meth:`seen_sources` и объявляет устаревшими все связанные виды. То есть
     разбор аварии начинается с того, что пульт забывает, кто вообще писал, —
     ровно в момент, когда это спрашивают. Из Ф4 находка не родом; фаза её не
     заметила, потому что характеризация мерила ``log()``, а не удобные методы.
  2. [Б-2] **``redis://:пароль@host``** — пустое имя пользователя штатно у Redis
     и AMQP, а URL-шаблон требовал у имени хотя бы один символ, и пароль уезжал
     в лог целиком.
  3. [Б-3] **``Authorization: Bearer <токен>``** — маскировалось слово
     ``Bearer``, токен уцелевал. Хуже голой утечки: строка ``Bearer ***``
     выглядит как отработавшая редакция, и на неё не смотрят второй раз.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_core import OBSERVABILITY_EPOCH
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.redaction import MASK, SecretRedactor


def _record(message: str) -> dict:
    """Запись минимальной формы. Своя, а не импорт из соседнего файла: каталог
    тестов не пакет, и относительный импорт здесь не разрешается."""
    return {
        "timestamp": 0.0,
        "level": "INFO",
        "scope": "business",
        "message": message,
        "module": "probe",
        "extra": {},
        "seq": 1,
    }


def _config(directory: Path) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="f4_review",
        log_directory=str(directory),
        enable_batching=False,
        channels={
            "main": LoggerChannelSchema(name="main", type="file", enabled=True, file_path="main.log", rotate=False),
        },
        scopes={
            "BUSINESS": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["main"]),
            "SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["main"]),
        },
    )


@pytest.fixture()
def logger(tmp_path: Path):
    mgr = LoggerManager(config=_config(tmp_path))
    yield mgr
    mgr.shutdown()


class TestCriticalIsNotAControlPlaneEvent:
    """Б-1. Авария — это ЗАПИСЬ, а не смена состава каналов.

    Три свойства проверяются порознь, потому что порознь и ломаются: хвост
    трогал три разных вида состояния, и починка «на одном пути из трёх» здесь
    была бы особенно правдоподобной.
    """

    def test_route_cache_survives_a_critical_record(self, logger) -> None:
        """Карта маршрутов после аварии не пуста — иначе следующая запись платит резолв заново."""
        logger.info("раз", module="alpha")
        logger.warning("два", module="beta")
        before = dict(logger._route_cache)
        assert len(before) >= 2, "кэш не наполнился — тест проверял бы не то"

        logger.critical("авария", module="gamma")

        for key in before:
            assert key in logger._route_cache, f"ключ {key} исчез после CRITICAL"

    def test_seen_sources_survives_a_critical_record(self, logger) -> None:
        """Readback пульта не врёт после аварии — а именно тогда его и читают."""
        logger.info("раз", module="alpha")
        logger.warning("два", module="beta")
        before = set(logger.seen_sources())
        assert before, "источники не накопились — тест проверял бы не то"

        logger.critical("авария", module="gamma")

        assert before <= set(logger.seen_sources()), "имена источников стёрты записью CRITICAL"

    def test_bound_views_are_not_invalidated_by_a_critical_record(self, logger) -> None:
        """Эпоха наблюдаемости не двигается: связка вида не устарела от того, что кто-то упал."""
        before = OBSERVABILITY_EPOCH[0]

        logger.critical("авария", module="gamma")

        assert OBSERVABILITY_EPOCH[0] == before, "CRITICAL объявил все связанные виды устаревшими"


class TestUrlCredentialsWithoutUser:
    """Б-2. Пустое имя пользователя — штатная форма, а не вырожденный случай."""

    @pytest.mark.parametrize(
        "url",
        [
            "redis://:hunter2@cache:6379/0",
            "amqp://:hunter2@broker:5672/",
            "postgres://user:hunter2@db/app",
        ],
    )
    def test_password_is_masked_with_and_without_a_user(self, url: str) -> None:
        redactor = SecretRedactor()
        out = redactor("business", LogLevel.INFO, _record(f"подключение упало: dsn={url}"))
        text = out["message"]
        assert "hunter2" not in text, f"пароль уцелел в URL: {text}"
        assert f":{MASK}@" in text, f"маска встала не на место: {text}"

    def test_a_url_without_credentials_is_left_alone(self) -> None:
        """Порт — не пароль. ``host:6379`` без ``@`` маскировать нечего."""
        redactor = SecretRedactor()
        out = redactor("business", LogLevel.INFO, _record("подключение: redis://cache:6379/0"))
        assert out["message"] == "подключение: redis://cache:6379/0"
        assert redactor.records_redacted == 0


class TestSchemePrefixedToken:
    """Б-3. Маскируется ТОКЕН, а не имя схемы аутентификации.

    Схема остаётся видимой намеренно: по ``Bearer`` против ``Basic`` разбирают
    инцидент, а секрета в самом слове нет.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "заголовок: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "заголовок: authorization=Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "заголовок: Authorization: Basic eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "заголовок: token: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        ],
    )
    def test_the_token_after_the_scheme_is_masked(self, text: str) -> None:
        redactor = SecretRedactor()
        out = redactor("business", LogLevel.INFO, _record(text))
        masked = out["message"]
        assert "eyJhbGciOiJIUzI1NiJ9" not in masked, f"токен уцелел за именем схемы: {masked}"
        assert MASK in masked, f"редакция не сработала вовсе: {masked}"

    def test_the_scheme_name_stays_readable(self) -> None:
        redactor = SecretRedactor()
        out = redactor("business", LogLevel.INFO, _record("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.p.s"))
        assert "Bearer" in out["message"], f"имя схемы съедено маской: {out['message']}"

    def test_the_quoted_form_is_masked_whole(self) -> None:
        """``"Authorization": "Bearer …"`` — значение в кавычках уходит целиком, и это не регресс."""
        redactor = SecretRedactor()
        out = redactor("business", LogLevel.INFO, _record('{"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.p.s"}'))
        assert "eyJhbGciOiJIUzI1NiJ9" not in out["message"]
        assert f'"Authorization": "{MASK}"' in out["message"], out["message"]
