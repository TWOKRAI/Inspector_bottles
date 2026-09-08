# -*- coding: utf-8 -*-
"""OtelExportConfig — ЕДИНСТВЕННОЕ объявление параметров экспортёра.

Регистры плагина (`Plugins/io/otel_export/registers.py`) — тонкая производная от
этого класса, а не вторая таблица полей: слои `framework -> Services -> Plugins`
запрещают `Services` импортировать `Plugins`, поэтому источник полей обязан жить
здесь (ADR-OTEL-003). Прецедент `telemetry_sink` кладёт поля в регистры — там
сервиса-владельца просто нет.

`FieldMeta` рядом с полем нужен именно здесь: GUI-панель и `set_config` читают
метаданные с класса регистров, а он их наследует.

Dict at Boundary: наружу процесса едет `to_dict()`, обратно — `from_dict()`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import ConfigDict, ValidationError, field_validator, model_validator

from multiprocess_framework.modules.channel_routing_module.levels import normalize_level_name
from multiprocess_framework.modules.process_module.plugins import FieldMeta, SchemaBase

__all__ = ["ENV_PLACEHOLDER_RE", "OtelExportConfig", "format_validation_error"]


#: Единственная допустимая форма значения заголовка: подстановка переменной
#: окружения целиком. Литерал в YAML запрещён правилом «секреты в env» — а не
#: только маскировкой в readback: замаскированный в выдаче секрет всё равно
#: лежал бы в git-истории рецепта.
ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def format_validation_error(error: ValidationError) -> str:
    """Компактный текст отказа схемы для ЖУРНАЛА — `loc: msg`, без шума.

    **Это форматтер читаемости, а НЕ предохранитель.** Предохранитель —
    `hide_input_in_errors=True` в `model_config` ниже: он снимает входные
    значения на всех дорогах построения модели, включая те, куда эта функция
    не дотягивается (сборка топологии `generic_process_config.from_plugins`
    строит регистр без `try` вовсе, а `RegistersManager.set_field_value`
    форматирует исключение сам — `manager.py:165`, `str(exc)`).

    Историю ошибки не переписываю: до флага `str(exc)` у pydantic 2.13 печатал
    вход целиком (`input_value={'authorization': 'Bearer …'}`), и эта функция
    была объявлена «единственным безопасным способом» — формулировка оказалась
    шире факта, потому что звать её мог только хост. Замер трёх дорог и разбор,
    почему `hidden=True` не работает (`can_modify` смотрит только `readonly`),
    — в ADR-OTEL-005.

    Хосту (Ф2.1) она по-прежнему полезна: `str(exc)` со скрытым входом остаётся
    многострочным, а здесь одна строка `endpoint: <msg>; headers: <msg>`.
    """
    parts: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        loc = ".".join(str(p) for p in item["loc"]) or "<конфиг>"
        parts.append(f"{loc}: {item['msg']}")
    return "; ".join(parts)


class OtelExportConfig(SchemaBase):
    """Параметры OTLP-экспортёра: адрес, уровень, транспорт, батчер, пул Resource.

    Все значения-потолки живут ЗДЕСЬ и видны в `readback()` — правило трека
    «ни одного нового литерала-потолка внутри механизма».
    """

    #: Предохранитель против утечки секрета через текст ValidationError (ADR-OTEL-005).
    #: pydantic 2.13 по умолчанию печатает `input_value` целиком в `str(exc)` —
    #: отвергнутый (и потому чаще всего настоящий) заголовок утёк бы в лог первой
    #: же естественной строкой `log_error(f"... {exc}")`. `hide_input_in_errors`
    #: закрывает это на ВСЕХ трёх дорогах построения (конструктор, `model_validate`,
    #: `set_field_value`/`validate_assignment`) — в том числе на `from_plugins`
    #: (`reg_cls(**reg_fields)`, без `try`), до которой не дотягивается ни плагин,
    #: ни `format_validation_error`. Цена: вход скрывается для ВСЕХ полей схемы,
    #: включая числовые — сообщения валидаторов называют значения сами, где нужно.
    #: `SchemaBase.model_config` (validate_assignment, populate_by_name) не
    #: перетирается: pydantic v2 мёржит `model_config` по MRO, а не заменяет
    #: (проверено прогоном — см. отчёт Task 0.5).
    model_config = ConfigDict(hide_input_in_errors=True)

    endpoint: Annotated[
        str,
        FieldMeta(
            "Endpoint",
            info=(
                "Адрес приёмника OTLP/HTTP ВМЕСТЕ С ПУТЁМ СИГНАЛА, "
                "напр. http://127.0.0.1:4318/v1/logs — SDK шлёт по нему дословно, "
                "адрес без пути даёт 404. Обязателен: dev-адрес годится только стенду, "
                "на Jetson/Raspberry коллектор стоит на другой машине"
            ),
        ),
    ]
    """Обязателен и БЕЗ дефолта: тихий дефолт `127.0.0.1:4318` увёл бы записи в
    никуда на устройстве, где коллектор живёт на другом хосте. Фрагмент топологии
    без этого ключа обязан оставлять плагин в состоянии `error` (Task 3.1)."""

    level: Annotated[
        str,
        FieldMeta(
            "Level",
            info="Уровень подписки на хвост наблюдаемости: DEBUG | INFO | WARNING | ERROR | CRITICAL",
        ),
    ] = "INFO"
    """Дефолт INFO — главный рычаг объёма (Р-4). DEBUG включают на время сверки
    словаря, не насовсем."""

    compression: Annotated[
        Literal["gzip", "deflate", "none"],
        FieldMeta(
            "Compression",
            info="Сжатие тела OTLP/HTTP. gzip режет трафик на Wi-Fi/4G ценой копеек CPU",
        ),
    ] = "gzip"
    """Множество значений повторяет `opentelemetry.exporter.otlp.proto.http.Compression`
    (сверено на установленном 1.44.0: none | deflate | gzip). Дефолт `gzip` стоит
    пока на ДОВОДЕ, а не на замере: замер CPU на Pi — критерий Task 2.4."""

    headers: Annotated[
        dict[str, str],
        FieldMeta(
            "Headers",
            info="Заголовки OTLP (токены облачных приёмников). Значения — только ${ENV_VAR}",
        ),
    ] = {}
    """Значение-литерал отвергается валидатором. `readback()` отдаёт `***`."""

    service_namespace: Annotated[
        str,
        FieldMeta(
            "Service namespace",
            info=(
                "semconv service.namespace — различает ДВА приложения на одном "
                "коллекторе. Пусто = подставляется имя приложения из app.yaml"
            ),
        ),
    ] = ""

    max_queue_size: Annotated[
        int,
        FieldMeta("Max queue size", info="Ёмкость очереди BatchLogRecordProcessor", min=1),
    ] = 2048

    schedule_delay_ms: Annotated[
        int,
        FieldMeta("Schedule delay", info="Период выгрузки батча", unit="ms", min=1),
    ] = 1000
    """Дефолт **1000**, а не 5000: сверено с исходником установленного SDK 1.44.0
    (`_DEFAULT_SCHEDULE_DELAY_MILLIS`). Редакция 4 плана называла 5000 — ошибка плана."""

    max_export_batch_size: Annotated[
        int,
        FieldMeta("Max export batch size", info="Сколько записей уходит одним запросом", min=1),
    ] = 512

    export_timeout_ms: Annotated[
        int,
        FieldMeta("Export timeout", info="Таймаут ОТПРАВКИ — уходит в OTLPLogExporter(timeout=)", unit="ms", min=1),
    ] = 30000
    """**Действует не там, где кажется.** У `BatchLogRecordProcessor` одноимённый
    параметр SDK игнорирует — в исходнике 1.44.0 над ним стоит комментарий
    `# Not used. No way currently to pass timeout to export.`, а
    `BatchProcessor.force_flush` несёт `TODO: Fix force flush so the timeout is
    used` (issue 4568). Реальный таймаут отправки — аргумент `timeout` (секунды)
    конструктора `OTLPLogExporter`. Поэтому `readback()` показывает это значение
    отдельным ключом `export_timeout_sec` — там, где оно правда действует."""

    flush_timeout_ms: Annotated[
        int,
        FieldMeta("Flush timeout", info="Дедлайн дожатия очереди — команда flush и останов", unit="ms", min=1),
    ] = 3000
    """**Дедлайн держит очередь хоста, а не SDK** (Task 2.4). `export_timeout_ms`
    потолком вызова не является: замер CTO — при «потолке» 3000 мс вызов жил
    4.08 с, на чёрной дыре при 30 с — 42.08 с, потому что это дедлайн расписания
    ретраев. Единственное, чем дожатие ограничивается на самом деле, —
    `BatchDrainWorker.flush(timeout)`: работу делает поток дренажа, а вызывающий
    ждёт прогресса до этого числа и уходит.

    Дефолт **3000**, а не 5000, хотя бюджет останова у фреймворка именно 5 с
    (`process_registry.stop_all(timeout=5.0)`): плагин на останове не один —
    после него ещё снимается намерение подписки и останавливается логгер
    процесса. Забрав весь бюджет себе, он вернул бы ровно тот исход, ради
    которого Task 2.2 дожатие и отменила: процесс убивают снаружи, финальные
    строки не пишутся. Два секунды запаса — это и есть цена того, чтобы строка
    исхода доехала."""

    resource_pool_size: Annotated[
        int,
        FieldMeta("Resource pool size", info="Предел пула Resource; вытеснение LRU считается", min=1),
    ] = 64
    """64 = порядок «8 процессов сегодня (20 после closure 4.8) × несколько
    инкарнаций»: ключ пула включает `incarnation`, то есть каждый рестарт
    источника добавляет запись. Не бесконечность — иначе долгий прогон течёт."""

    # ------------------------------------------------------------------ #
    # Валидация границы
    # ------------------------------------------------------------------ #

    @field_validator("endpoint")
    @classmethod
    def _endpoint_not_blank(cls, value: str) -> str:
        """Пустая строка — это не «значение по умолчанию», а не заполненный ключ."""
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "endpoint пуст: адрес приёмника OTLP обязателен "
                "(напр. http://127.0.0.1:4318/v1/logs). Тихого дефолта здесь нет"
            )
        return stripped

    @field_validator("endpoint")
    @classmethod
    def _endpoint_carries_signal_path(cls, value: str) -> str:
        """Адрес обязан нести путь сигнала — SDK шлёт по нему **дословно**.

        **Замер, из-за которого валидатор появился (2026-09-07, Task 2.3).** Против
        настоящего `otelcol` 0.158.0 с включённым конвейером логов:

        | POST | ответ |
        |---|---|
        | ``http://127.0.0.1:4318`` | **404** |
        | ``http://127.0.0.1:4318/v1/logs`` | **200** |
        | ``http://127.0.0.1:4318/v1/traces`` | 404 (контроль: дело в пути, не в теле) |

        Причина в SDK и она односторонняя: явный аргумент уходит без изменений
        (``_log_exporter/__init__.py:91`` — ``self._endpoint = endpoint or ...``), а
        путь дописывается ТОЛЬКО на дороге переменной окружения
        ``OTEL_EXPORTER_OTLP_ENDPOINT``. То есть наше поле по смыслу равно
        ``OTEL_EXPORTER_OTLP_LOGS_ENDPOINT``, у которого путь входит в значение.

        **Почему отказ, а не дописывание пути.** Прямой прецедент — вердикт CTO о
        форме ``${ENV_VAR}``: не заводить свой разворачиватель для того, что SDK уже
        определил. Дописывание пути «когда его нет» тихо переписало бы адрес и тому,
        кто целил в шлюз на корне, а цена ошибки здесь несимметрична: отказ виден на
        старте одной строкой, а тихо неверный адрес выглядит как отказ сети — и до
        сегодня выглядел им 28 раз подряд.

        **Чем это скрывалось.** Заглушка стенда Task 2.2 принимала POST по любому
        пути и отвечала 200, поэтому ``exported`` рос, а до настоящего приёмника не
        доезжало ничего. Ровно правило проекта «фейковая оснастка доказывает
        оснастку»: приёмка обязана хоть раз пройти через настоящего потребителя.
        """
        parsed = urlparse(value)
        # Разбирается АДРЕС ЦЕЛИКОМ, а не одно поле.
        #
        # Первая редакция смотрела только на `path` — и была зелёной по неверной
        # причине (находка ревью, воспроизведена): у адреса без схемы `urlparse`
        # читает номер порта как путь, поэтому `localhost:4318` давал
        # `scheme='localhost'`, `path='4318'` и ПРОХОДИЛ сторож именно потому, что
        # пути у него нет. Сквозной прогон такого адреса: схема приняла, доставка
        # `accepted=0 failed=1` — то есть ровно тот дефект, который задача закрывает,
        # только вошедший другой дверью.
        missing: list[str] = []
        if parsed.scheme not in {"http", "https"}:
            missing.append("схема http:// или https://")
        if not parsed.netloc:
            missing.append("хост с портом")
        if not parsed.path.strip("/"):
            missing.append("путь сигнала (для логов — /v1/logs)")
        if missing:
            raise ValueError(
                f"endpoint {value!r} неполон, не хватает: {', '.join(missing)}. SDK шлёт по адресу "
                "ДОСЛОВНО, и настоящий приёмник отвечает 404 (замерено на otelcol 0.158.0). "
                "Полная форма: http://127.0.0.1:4318/v1/logs"
            )
        return value

    @field_validator("level")
    @classmethod
    def _level_is_known(cls, value: str) -> str:
        """Имя уровня — только из шкалы фреймворка; алиасы WARN/FATAL раскрываются.

        Свой список имён здесь не заводится: единственный владелец шкалы —
        `channel_routing_module/levels.py`. Незнакомое имя отвергается, а не
        подменяется мягким дефолтом: подписка «на всякий случай DEBUG» дороже
        отказа на старте.
        """
        canonical = normalize_level_name(value)
        if canonical is None:
            raise ValueError(
                f"неизвестный уровень {value!r}: допустимы "
                "DEBUG | INFO | WARNING | ERROR | CRITICAL (алиасы WARN, FATAL)"
            )
        return canonical

    @field_validator("headers")
    @classmethod
    def _headers_only_env_placeholders(cls, value: dict[str, str]) -> dict[str, str]:
        """Значение заголовка — только `${ENV_VAR}` целиком.

        В тексте ошибки называется КЛЮЧ и требуемая форма, но НИКОГДА само
        значение: сообщение об отвергнутом секрете уезжает в журнал, и печать
        значения превратила бы валидатор в утечку.
        """
        for name, raw in value.items():
            if not isinstance(raw, str) or not ENV_PLACEHOLDER_RE.match(raw):
                raise ValueError(
                    f"заголовок {name!r}: значение обязано быть подстановкой "
                    "окружения вида ${ENV_VAR} целиком; литерал в конфиге запрещён "
                    "(секреты в env). Само значение здесь не печатается намеренно"
                )
        return value

    @model_validator(mode="after")
    def _batch_fits_queue(self) -> "OtelExportConfig":
        """Батч не больше очереди — иначе SDK откажет уже при построении.

        Правило не наше: `BatchLogRecordProcessor._validate_arguments` (SDK 1.44.0)
        бросает ValueError на `max_export_batch_size > max_queue_size`. Ловим на
        границе конфига, чтобы адрес ошибки назывался нашим ключом, а не всплывал
        из чужого конструктора внутри `configure()`.
        """
        if self.max_export_batch_size > self.max_queue_size:
            raise ValueError(
                f"max_export_batch_size ({self.max_export_batch_size}) больше "
                f"max_queue_size ({self.max_queue_size}) — SDK такой батчер не построит"
            )
        return self

    # ------------------------------------------------------------------ #
    # Dict at Boundary
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в `dict` для передачи между процессами."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OtelExportConfig":
        """Собрать из `dict` (посторонние ключи игнорируются `SchemaBase`)."""
        return cls.model_validate(dict(data))

    # ------------------------------------------------------------------ #
    # Эффективные значения
    # ------------------------------------------------------------------ #

    def readback(self) -> dict[str, Any]:
        """Эффективные значения наружу: то, что реально уйдёт в SDK.

        Отличается от `model_dump()` (сконфигурированного) двумя вещами:

        * `headers` — значения заменены на `***`. Маскируется ЛЮБОЕ значение,
          а не только похожее на секрет: разбор «этот заголовок безопасный»
          и есть та развилка, на которой утекают токены;
        * добавлен `export_timeout_sec` — тот самый таймаут в секундах, каким
          он уйдёт в `OTLPLogExporter(timeout=...)`. Ключ `export_timeout_ms`
          остаётся, но сам по себе он вводит в заблуждение: одноимённый
          параметр `BatchLogRecordProcessor` SDK 1.44.0 игнорирует.

        На стадии `contract` это значения, которые БУДУТ переданы SDK. После Ф2
        плагин обязан снимать их с построенных объектов — иначе readback станет
        эхом конфигурации, а не показанием.
        """
        data = self.model_dump()
        data["headers"] = {name: "***" for name in self.headers}
        data["export_timeout_sec"] = self.export_timeout_ms / 1000.0
        # Дедлайны переводятся в секунды ЗДЕСЬ и только здесь: деление на 1000,
        # разъехавшееся по двум местам, даёт таймаут в тысячу раз длиннее нужного
        # и не даёт об этом ни одного признака (тот же довод, что у
        # `export_timeout_sec` выше).
        data["flush_timeout_sec"] = self.flush_timeout_ms / 1000.0
        return data
