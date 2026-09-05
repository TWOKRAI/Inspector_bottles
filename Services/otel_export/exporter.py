# -*- coding: utf-8 -*-
"""Обёртка над OpenTelemetry SDK. Сейчас — только проверка наличия SDK.

**Единственное место сервиса, которому позволено трогать `opentelemetry`,** и
только ЛЕНИВО — внутри функции. Импорт на уровне модуля запрещён (критерий E1
плана): `class_loader` фреймворка глотает `ImportError` при построении класса
(`log.error -> None`), и отказ «нет extra [otel]» стал бы молчаливым — процесс
не поднялся бы без названной причины.

Реализация экспорта (`BatchLogRecordProcessor` поверх `OTLPLogExporter`,
переполнение, `force_flush`) приходит в Ф2.2/Ф2.4 — здесь её НЕТ намеренно.
"""

from __future__ import annotations

__all__ = ["INSTALL_HINT", "SDK_DISTRIBUTIONS", "sdk_available"]


#: Текст отказа для readback регистров и голоса плагина. Литерал: на него
#: ссылается приёмочный тест и он же попадает оператору в `otel_export.status`.
INSTALL_HINT = "missing: uv pip install --inexact '.[otel]'"
#: `--inexact` обязателен: `uv sync` без него сносит всё, что не объявлено
#: в зависимостях проекта (боевой опыт владельца).

#: Дистрибутивы extra `[otel]`. Пин minor — в `pyproject.toml`: Logs SDK живёт
#: под `opentelemetry.sdk._logs` и совместимости в minor не обещает.
SDK_DISTRIBUTIONS = ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http")


def sdk_available() -> tuple[bool, str]:
    """Установлен ли SDK — факт и человекочитаемая деталь.

    Post:
        * `(True, "<версия opentelemetry-sdk>")` — оба пакета extra `[otel]`
          импортируются; версия идёт в readback ключом `sdk`;
        * `(False, INSTALL_HINT)` — не импортируются. Наружу `ImportError`
          **не выпускается**: решение «что делать с отсутствием SDK» принимает
          хост (плагин уходит в состояние `error` с этим текстом), а не импорт.

    Проверяются оба пакета, а не один: `opentelemetry-sdk` может стоять как
    транзитивная зависимость чего-то ещё, а без `exporter-otlp-proto-http`
    отправлять всё равно нечем — и отказ вылез бы позже и глуше.
    """
    try:
        # Ровно те символы, которыми пользуется Ф2: проверка «пакет ставится»
        # без проверки нужных имён — зелёный сторож над сломанной установкой.
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # noqa: F401
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs.export import (  # noqa: F401
            BatchLogRecordProcessor,
        )
    except ImportError:
        return False, INSTALL_HINT

    from importlib import metadata

    try:
        version = metadata.version("opentelemetry-sdk")
    except metadata.PackageNotFoundError:
        # Пакет импортируется, метаданных дистрибутива нет (vendoring, zip-app).
        # Говорим это прямо, а не подставляем правдоподобное число.
        return True, "версия неизвестна: метаданные дистрибутива opentelemetry-sdk не найдены"
    return True, version
