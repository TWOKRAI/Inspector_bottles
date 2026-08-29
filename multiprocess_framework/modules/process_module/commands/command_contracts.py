# -*- coding: utf-8 -*-
"""Контракты параметров встроенных команд (Ф4.2 шаг 6 + NEW-3, ADR-MSG-008).

Декларативное наполнение `MessageContractRegistry` для built-in команд: связывает
имя команды с Pydantic-схемой её ПАРАМЕТРОВ. Даёт три вещи:

  - `introspect.capabilities` v1 отдаёт `params_schema` (имена/типы/обязательность
    полей) — агент/оператор видит форму команды без чтения исходников;
  - warn-middleware (дефолт) ловит опечатку в имени параметра — `extra="forbid"`
    даёт `unexpected` в diff вместо тихого игнора лишнего ключа;
  - `FW_CONTRACTS_STRICT=1` (раскатка) дропает control-plane сообщение с кривым
    `data` вместо тихого прохода — целевой режим ADR-MSG-008.

**NEW-3 (2026-07-11):** все схемы — `extra="forbid"`. Поля намеренно ``Optional``
(документирующий контракт параметров, не строгий envelope): большинство built-in
команд принимают набор опциональных полей с рантайм-проверкой обязательности внутри
хендлера (например ``worker_name`` для worker.*), контракт лишь фиксирует ФОРМУ —
что это за поля и какого типа, не дублируя рантайм-проверку missing/optional. Live-
аудит звонков (grep по репозиторию на 2026-07-11, см. отчёт задачи NEW-3) не нашёл
НИ ОДНОГО живого вызова, слающего поле вне списка ниже — раскатка warn→strict для
built-in команд безопасна без allow-исключений.

Регистрируются per-process в ``BuiltinCommands._register_message_guards``; команды,
которых в процессе нет, просто не попадут в его карточку (capabilities итерирует
реальные регистрации CommandManager).
"""

from __future__ import annotations

import functools
import typing
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, ConfigDict


class NoParams(BaseModel):
    """Команда без параметров (диагностика/интроспекция) — любой ключ в ``data`` лишний."""

    model_config = ConfigDict(extra="forbid")


class WireConfigureParams(BaseModel):
    """Параметры ``wire.configure`` (runtime-настройка SHM-канала)."""

    model_config = ConfigDict(extra="forbid")

    wire_key: Optional[str] = None
    role: Optional[str] = None  # "sender" | "receiver"
    shm_name: Optional[str] = None
    shm_owner: Optional[str] = None
    buffer_slots: Optional[int] = None


class WireDeconfigureParams(BaseModel):
    """Параметры ``wire.deconfigure`` (снять wire-middleware)."""

    model_config = ConfigDict(extra="forbid")

    wire_key: Optional[str] = None


class RoutingProbeParams(BaseModel):
    """Параметры ``routing.probe`` (диагностика peer→peer доставки, Ф3.1)."""

    model_config = ConfigDict(extra="forbid")

    target: Optional[str] = None
    inner: Optional[Dict[str, Any]] = None


class RoutingRefreshParams(BaseModel):
    """Параметры ``routing.refresh`` (авторитетный снимок routing-epoch, Ф3.1)."""

    model_config = ConfigDict(extra="forbid")

    epoch: Optional[int] = None
    hub: Optional[str] = None
    reason: Optional[str] = None
    processes: Optional[Dict[str, Any]] = None
    ts: Optional[float] = None


class RouterRelayParams(BaseModel):
    """Параметры ``router.relay`` (хаб-релей недоставляемого билета, Ф1.7)."""

    model_config = ConfigDict(extra="forbid")

    ticket: Optional[Dict[str, Any]] = None


class WorkerNameParams(BaseModel):
    """Параметры команд, адресующих воркер по имени (remove/restart/start/stop)."""

    model_config = ConfigDict(extra="forbid")

    worker_name: Optional[str] = None


class WorkerCreateParams(BaseModel):
    """Параметры ``worker.create`` / ``worker.update`` (CRUD воркера)."""

    model_config = ConfigDict(extra="forbid")

    worker_name: Optional[str] = None
    priority: Optional[str] = None
    execution_mode: Optional[str] = None
    target_interval_ms: Optional[int] = None
    worker_class: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    restart_on_failure: Optional[bool] = None
    max_restarts: Optional[int] = None
    worker_type: Optional[str] = None


class ConfigReloadParams(BaseModel):
    """Параметры ``config.reload`` (Ф1 Task 1.4: hot-reload observability)."""

    model_config = ConfigDict(extra="forbid")

    observability: Optional[Dict[str, Any]] = None
    # PC 3.1 — секцию telemetry команда принимает с тех пор, но в контракте её
    # не было: при extra="forbid" warn-мидлварь ругалась на КАЖДЫЙ штатный вызов.
    telemetry: Optional[Dict[str, Any]] = None
    telemetry_mode: Optional[str] = None
    # Task 5.12 — ключи, которые надо УДАЛИТЬ из слоя сессии (L3).
    observability_reset: Optional[List[str]] = None
    # switch рецепта: обнулить слой сессии целиком (инициатор не знает его состава).
    observability_session_clear: Optional[bool] = None
    # R6 (живой switch): новый слой L2 целиком — СЫРАЯ секция рецепта и его адрес.
    # Секция сырая, а не готовая долька процесса: резолв (`defaults` +
    # `processes[<имя>]`) обязан идти ТЕМ ЖЕ кодом, что и на boot, иначе switch и
    # старт разойдутся в трактовке одного файла. Пустая секция (`{}`) — законное
    # «новый рецепт про наблюдаемость молчит», и она обязана СНЯТЬ прежний слой.
    observability_recipe: Optional[Dict[str, Any]] = None
    observability_recipe_path: Optional[str] = None
    # R4 (Task 5.11.f) — «перечитай слой L2 со своего адреса»: зеркало файловой
    # ветки для L1. Секцию на проводе НЕ несёт: спутник лежит на диске, и читать
    # его обязан тот же код, что на boot, иначе перечитка и старт разойдутся.
    observability_recipe_reload: Optional[bool] = None
    # Task 5.8 — срок жизни inline-правки, сек. Не задан → политика слоёв
    # (``session_ttl_sec``, дефолт 300с); ``0`` → бессрочно, явным решением.
    ttl: Optional[float] = None
    path: Optional[str] = None
    # A1 (оракул контракт↔хендлер): ключ ЗАРЕЗЕРВИРОВАН и хендлер отвечает на него
    # адресным отказом с указанием на `observability.persist`. Объявлен он именно
    # ради этого отказа: при extra="forbid" незадекларированный ключ дропается
    # мидлварью, и защита оказывается недостижимой — оператор не увидел бы ни
    # отказа, ни подсказки, а решил бы, что правка записана навсегда.
    persist: Optional[bool] = None


class ObservabilityPersistParams(BaseModel):
    """Параметры ``observability.persist`` (Task 5.12: L3 → спутник рецепта)."""

    model_config = ConfigDict(extra="forbid")

    recipe_path: Optional[str] = None


class LoggerSinkParams(BaseModel):
    """Параметры ``observability.sink.enable`` / ``.disable`` (и алиасов ``logger.sink.*``)."""

    model_config = ConfigDict(extra="forbid")

    sink: Optional[str] = None
    name: Optional[str] = None  # алиас sink (см. _toggle_logger_sink)
    # Ф0.6: какую плоскость наблюдаемости адресуем — logger (дефолт) | error | stats.
    # Значения вне whitelist'а отвергает обработчик (роутер — транспорт, не плоскость).
    manager: Optional[str] = None
    # Task 5.8 — срок жизни снятия/возврата приёмника, сек (0 — бессрочно).
    ttl: Optional[float] = None


class LoggerSinkTailParams(BaseModel):
    """Параметры ``observability.sink.tail`` (и алиаса ``logger.sink.tail``).

    Task 2.2: команда жила в поверхности наблюдаемости **без контракта вовсе** —
    то есть её параметры не видел ни warn-мидлварь, ни карточка
    ``introspect.capabilities``, ни оракул A1. Незадекларированная команда не
    «свободна от правил», она невидима для них: судить нечем, и любой промах в
    имени или типе параметра остаётся тихим.
    """

    model_config = ConfigDict(extra="forbid")

    sink: Optional[str] = None
    name: Optional[str] = None  # алиас sink — как у LoggerSinkParams
    manager: Optional[str] = None
    #: Сколько последних записей вернуть из memory-приёмника.
    limit: Optional[int] = None


class TelemetryReconfigureParams(BaseModel):
    """Параметры ``telemetry.reconfigure`` (PC 3.1).

    Task 2.2: второй пробел того же рода, что у :class:`LoggerSinkTailParams`, и
    более дорогой — эта команда правит publisher-gate и центральный троттл.

    ``ttl`` объявлен здесь, хотя оракул A1 его у хендлера НЕ видит: хендлер
    читает срок через общий ``_parse_ttl(args)``, а оракул судит только
    литеральные ``args.get(...)`` в теле метода — ограничение метода, названное
    в его докстринге. Пропусти мы ``ttl``, при ``extra="forbid"`` операторский
    срок помечался бы лишним полем, а в strict-режиме команда исчезала бы молча.
    """

    model_config = ConfigDict(extra="forbid")

    #: dict → пересобрать publisher-gate; ``None`` → выключить его (все метрики
    #: каждый тик). Различаются они ПРИСУТСТВИЕМ ключа, а не значением.
    publish: Optional[Dict[str, Any]] = None
    #: Дельта центрального троттла ``{glob-паттерн: интервал_сек}``.
    throttle: Optional[Dict[str, Any]] = None
    #: ``replace`` (дефолт) | ``merge`` — как правка входит в слой.
    telemetry_mode: Optional[str] = None
    #: Срок жизни правки, сек (Task 5.10.f); читается через ``_parse_ttl``.
    ttl: Optional[float] = None


class ObservabilityIntrospectParams(BaseModel):
    """Параметры ``introspect.observability`` (Task 5.9).

    Команда была ``NoParams``; аудит добавил ровно одну ручку — глубину хвоста.
    Объявить её обязательно: ``extra="forbid"`` означает, что незадекларированный
    параметр помечается ``unexpected`` warn-мидлварью, а в ``FW_CONTRACTS_STRICT``
    сообщение дропается целиком — ручка была бы мертва при зелёных тестах.

    A1: правило выше сформулировано здесь с Task 5.9, но выполнено было только
    для ``audit_limit`` — ``resolve`` (Ф2.6) и ``flush`` (Task 5.7) добавлялись
    в хендлер мимо схемы. Ровно тот случай, который докстринг описывает.
    Расхождение теперь судится оракулом ``test_command_contract_oracle.py``.
    """

    model_config = ConfigDict(extra="forbid")

    #: Сколько последних записей аудита вернуть (дефолт 20; 0 — не возвращать).
    audit_limit: Optional[int] = None
    #: Ф2.6: разобрать правило для имени источника (строка) или списка имён.
    resolve: Optional[Union[str, List[str]]] = None
    #: Task 5.7: дожать буферы перед снимком счётчиков (когерентный снимок).
    flush: Optional[bool] = None


class LogTailSubscribeParams(BaseModel):
    """Параметры ``log.tail.subscribe`` (Ф1 Task 1.5)."""

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None
    level: Optional[str] = None
    command: Optional[str] = None


class LogTailUnsubscribeParams(BaseModel):
    """Параметры ``log.tail.unsubscribe``."""

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None
    tap: Optional[str] = None


class ObservabilityTailSubscribeParams(BaseModel):
    """Параметры ``observability.tail.subscribe`` (Ф5.20b).

    A1 (Б-1б): ``level`` объявлен здесь с той же ролью, что у брата
    ``LogTailSubscribeParams``. До этого хендлер его читал, а схема запрещала:
    при ``extra="forbid"`` каждая подписка давала ``contract_violation``, а с
    ``FW_CONTRACTS_STRICT=1`` исчезала бы молча. ``None`` — «уровень не назван»,
    дефолт применяет процесс (см. ``subscribe_observability_tail``); повторять
    здесь константу ``"ERROR"`` нельзя — две позиции одного дефолта расходятся
    молча.

    Задача 5.6: ``scope`` — та же история, что у ``level``, но про НАМЕРЕНИЕ.
    ``"all"`` кладёт брокер, разворачивая оптовую подписку в адресные команды;
    процесс по нему знает, что порог, заданный прицельно, понижать нельзя (блокер
    Н2-1 переприёмки F2). Объявлено здесь потому, что ``extra="forbid"``: поле,
    которого нет в схеме, дало бы `contract_violation` на каждой оптовой раздаче,
    а под ``FW_CONTRACTS_STRICT=1`` — молча дропнутое сообщение. Отсутствие ключа
    означает прицельную подписку, то есть прежнее поведение всех вызывающих.
    """

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None
    level: Optional[str] = None
    scope: Optional[str] = None


class ObservabilityTailUnsubscribeParams(BaseModel):
    """Параметры ``observability.tail.unsubscribe`` (F1: per-subscriber отписка).

    Задача 5.6 добавила ``scope`` — зеркало подписки: ``"all"`` кладёт брокер,
    разворачивая ОПТОВОЕ снятие, и по нему процесс знает, что прицельную подписку
    трогать нельзя (находка Н2-2: `unwatch()` глушил хвост, которого не создавал).
    Объявлено здесь, потому что ``extra="forbid"``.

    Форвардер наблюдаемости — per-subscriber (несколько подписчиков сосуществуют на
    одном процессе: GUI + backend_ctl). ``subscriber`` снимает форвардер ТОЛЬКО этого
    подписчика; ``None`` (legacy/teardown) — снять форвардеры всех подписчиков.
    """

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None
    scope: Optional[str] = None


class ObservabilityTailBrokerParams(BaseModel):
    """Параметры ``observability.tail.subscribe_all`` / ``.unsubscribe_all`` (Task 5.11).

    Команды брокера живут на ОРКЕСТРАТОРЕ, но контракт объявляется здесь, вместе
    со всеми остальными: два реестра имён одной плоскости однажды разойдутся, и
    тогда через одно написание пройдёт то, что другое отвергает (урок 5.10.e).
    Схема одна на обе команды — параметр ``subscriber`` у них общий.
    """

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None
    #: A1: порог, который брокер кладёт в намерение и разворачивает в
    #: ``observability.tail.subscribe`` — включая переподписку свежей инкарнации.
    #: Осмыслен только у ``subscribe_all``; у ``unsubscribe_all`` игнорируется
    #: (общая схема — сознательный выбор, см. докстринг: два реестра имён одной
    #: плоскости однажды разойдутся).
    level: Optional[str] = None


class HealthReportParams(BaseModel):
    """Параметры ``health.report`` (диагностический впрыск health-события, Ф2 Task 2.1)."""

    model_config = ConfigDict(extra="forbid")

    context: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None
    #: A1: уровень сопутствующей лог-записи. Хендлер читает его и на неизвестном
    #: имени отвечает адресным отказом — но необъявленный ключ до этой проверки
    #: не доезжает, то есть проверка была недостижима (см. ConfigReloadParams.persist).
    level: Optional[str] = None


class DiagThreadRaiseParams(BaseModel):
    """Параметры ``diag.thread_raise`` (впрыск исключения потока, Ф1.1 / C3)."""

    model_config = ConfigDict(extra="forbid")

    message: Optional[str] = None
    #: Имя потока. Объявлено, а не «додумывается из message»: имя приезжает в
    #: ``extra.context.thread`` записи плоскости ошибок, то есть служит АДРЕСОМ
    #: события, по которому его потом ищут среди соседних проверок.
    thread_name: Optional[str] = None


class DiagWarnParams(BaseModel):
    """Параметры ``diag.warn`` (впрыск ``warnings.warn``, Ф1.1 / C3)."""

    model_config = ConfigDict(extra="forbid")

    message: Optional[str] = None
    #: Имя класса-предупреждения из ``builtins`` (``UserWarning`` по умолчанию).
    #: Хендлер отвечает адресным отказом на неизвестное имя — но необъявленный
    #: ключ до этой проверки не доехал бы (тот же довод, что у
    #: ``HealthReportParams.level``).
    category: Optional[str] = None


#: Реестр контрактов built-in команд: имя команды → Pydantic-схема параметров.
#: Наполняется в BuiltinCommands._register_message_guards.
BUILTIN_COMMAND_CONTRACTS: Dict[str, Type[BaseModel]] = {
    # worker.* — CRUD/lifecycle воркеров процесса
    "worker.pause_all": NoParams,
    "worker.resume_all": NoParams,
    "worker.create": WorkerCreateParams,
    "worker.remove": WorkerNameParams,
    "worker.update": WorkerCreateParams,
    "worker.restart": WorkerNameParams,
    "worker.start": WorkerNameParams,
    "worker.stop": WorkerNameParams,
    # introspect.* — диагностика без параметров
    "introspect.handlers": NoParams,
    "introspect.registers": NoParams,
    "introspect.status": NoParams,
    "introspect.router_stats": NoParams,
    "introspect.queues": NoParams,
    "introspect.memory": NoParams,
    "introspect.capabilities": NoParams,
    "introspect.plugins": NoParams,
    "introspect.observability": ObservabilityIntrospectParams,
    # observability control plane (Ф1 Task 1.4/1.5, Ф5.20b)
    "config.reload": ConfigReloadParams,
    "observability.persist": ObservabilityPersistParams,
    # Task 5.10.e: каноническое имя и алиас судятся ОДНИМ контрактом. Разные
    # схемы у двух имён одной команды означали бы, что через алиас проходит то,
    # что канон отвергает — то есть контракт обходится сменой написания.
    "observability.sink.enable": LoggerSinkParams,
    "observability.sink.disable": LoggerSinkParams,
    "logger.sink.enable": LoggerSinkParams,
    "logger.sink.disable": LoggerSinkParams,
    # Task 2.2: три команды поверхности наблюдаемости жили без контракта вовсе —
    # их не судили ни мидлварь, ни оракул A1, и в карточке процесса они значились
    # командами без параметров. «Контракта нет» читалось как «нарушать нечего».
    "observability.sink.tail": LoggerSinkTailParams,
    "logger.sink.tail": LoggerSinkTailParams,
    "telemetry.reconfigure": TelemetryReconfigureParams,
    "log.tail.subscribe": LogTailSubscribeParams,
    "log.tail.unsubscribe": LogTailUnsubscribeParams,
    "observability.tail.subscribe": ObservabilityTailSubscribeParams,
    "observability.tail.unsubscribe": ObservabilityTailUnsubscribeParams,
    # Task 5.11 — брокер подписки (обрабатывает оркестратор, судится общим реестром)
    "observability.tail.subscribe_all": ObservabilityTailBrokerParams,
    "observability.tail.unsubscribe_all": ObservabilityTailBrokerParams,
    # health (Ф2 Task 2.1)
    "health.report": HealthReportParams,
    "health.status": NoParams,
    # diag (Ф1.1 / C3) — впрыск НАСТОЯЩЕГО события в процессные хуки
    "diag.thread_raise": DiagThreadRaiseParams,
    "diag.warn": DiagWarnParams,
    # wire (runtime SHM-канал)
    "wire.configure": WireConfigureParams,
    "wire.deconfigure": WireDeconfigureParams,
    # relay/routing (Ф1.7, Ф3.1)
    "router.relay": RouterRelayParams,
    "routing.probe": RoutingProbeParams,
    "routing.refresh": RoutingRefreshParams,
}


def _type_str(ann: Any) -> str:
    """Читаемое имя типа поля; ``Optional[X]`` разворачивается в ``X``."""
    origin = typing.get_origin(ann)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return _type_str(non_none[0])
        return " | ".join(_type_str(a) for a in non_none)
    return getattr(ann, "__name__", None) or str(ann).replace("typing.", "")


@functools.lru_cache(maxsize=256)
def _adapter_for(schema: Type[BaseModel], field: str) -> Any:
    """``TypeAdapter`` одного поля схемы — по полю, а не по модели целиком.

    Модель целиком дала бы одну общую ошибку и потеряла бы соседей: оператор,
    промахнувшийся дважды, чинил бы вход по одной строке за команду. Кэш —
    потому что судить приходится на КАЖДОМ вызове команды наблюдаемости, а
    сборка адаптера дороже самой проверки.
    """
    from pydantic import TypeAdapter

    return TypeAdapter(schema.model_fields[field].annotation)


def validated_params(command: str, params: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Проверить ТИПЫ объявленных параметров команды и вернуть приведённые значения.

    Task 2.2 (находка Н-5, решение владельца Р-3а). Контракт объявляет тип, но
    до этой задачи его читала только warn-мидлварь: она писала предупреждение и
    ПРОПУСКАЛА сообщение к хендлеру. Хендлер получал мусор и падал на нём уже
    своим способом — воспроизведено:

    * ``introspect.observability {"resolve": true}`` → ``list(True)`` →
      ``Dispatch failed: 'bool' object is not iterable``;
    * ``config.reload {"observability_reset": true}`` → тот же ``TypeError``,
      второе место того же класса;
    * ``config.reload {"observability_session_clear": "net"}`` → ``bool("net")``
      истинно → **весь слой L3 стёрт**, включая правку оператора со сроком 600 с.
      Слово «нет» означало «да, снеси всё».

    Судятся ТОЛЬКО типы объявленных полей, и только тех, что ПРИСУТСТВУЮТ во
    входе. Три следствия, каждое намеренное:

    * **отсутствующее поле не материализуется.** Вернуть ``model_dump()`` целиком
      значило бы подставить ``None`` вместо «ключа нет», а половина команд
      наблюдаемости различает эти случаи присутствием ключа
      (``publish: null`` — «выключить гейт», отсутствие — «слои молчат»);
    * **лишние ключи не судятся здесь.** Их считает warn-мидлварь
      (``unexpected``) и вердикт ``config.reload``; второй предохранитель на то
      же место сделал бы неизвестным, который из них держит;
    * **приведение — часть договора, а не побочный эффект.** ``audit_limit="20"``
      доедет до хендлера как ``20``, а ``observability_session_clear="no"`` — как
      ``False``, то есть как и просил оператор.

    Returns:
        ``(параметры с приведёнными значениями, список проблем)``. Проблемы —
        готовые строки с адресом поля, ожидаемым типом и полученным значением.
    """
    from pydantic import ValidationError

    schema = BUILTIN_COMMAND_CONTRACTS.get(command)
    if schema is None:
        return params, []

    coerced = dict(params)
    problems: List[str] = []
    for field, info in schema.model_fields.items():
        if field not in params:
            continue
        value = params[field]
        bad = isinstance(value, bool) and not _admits_bool(info.annotation)
        if not bad:
            try:
                coerced[field] = _adapter_for(schema, field).validate_python(value)
                continue
            except ValidationError:
                bad = True
        if bad:
            problems.append(
                f"параметр {field}: ожидается {_type_str(info.annotation)}, получено {type(value).__name__} ({value!r})"
            )
    return (params if problems else coerced), problems


def _admits_bool(ann: Any) -> bool:
    """Объявлен ли ``bool`` среди допустимых типов поля.

    Отдельная ветка нужна потому, что Pydantic в мягком режиме принимает ``True``
    как число: ``bool`` — подкласс ``int``. Без неё эта проверка **ослабила бы**
    существующую защиту, а не усилила: ``ttl=True`` до задачи 2.2 отвергался
    (``validate_ttl``: «ttl=True — не число секунд»), а с приведением к ``1.0``
    доехал бы до хендлера годным сроком в одну секунду — и приёмник был бы снят.
    Поймано прогоном полной сьюты, а не рассуждением: тест
    ``test_bad_ttl_is_refused_and_the_sink_is_untouched[True]`` покраснел.

    Тот же довод, что у :func:`~..configs.observability_layers.validate_ttl` и у
    правил троттла (2.1). Это третья ТОЧКА одного правила, а не третья его
    редакция: там судят значение, дошедшее из файла или слоя, здесь — параметр
    команды, и границ действительно три.
    """
    if typing.get_origin(ann) is typing.Union:
        return any(_admits_bool(arg) for arg in typing.get_args(ann))
    return ann is bool


def params_schema_of(schema: Type[BaseModel]) -> list[dict[str, Any]]:
    """Детерминированная форма схемы для карточки: [{name, type, required}] по имени.

    Только контракт (имена/типы/обязательность), без runtime-значений — как
    ``registers`` в capability-манифесте. Тип рендерится читаемой строкой.
    """
    out: list[dict[str, Any]] = []
    for name, info in schema.model_fields.items():
        out.append({"name": name, "type": _type_str(info.annotation), "required": bool(info.is_required())})
    return sorted(out, key=lambda f: f["name"])


__all__ = [
    "NoParams",
    "WireConfigureParams",
    "WireDeconfigureParams",
    "RoutingProbeParams",
    "RoutingRefreshParams",
    "RouterRelayParams",
    "WorkerNameParams",
    "WorkerCreateParams",
    "ConfigReloadParams",
    "LoggerSinkParams",
    "LoggerSinkTailParams",
    "TelemetryReconfigureParams",
    "ObservabilityIntrospectParams",
    "ObservabilityPersistParams",
    "LogTailSubscribeParams",
    "LogTailUnsubscribeParams",
    "ObservabilityTailSubscribeParams",
    "ObservabilityTailBrokerParams",
    "HealthReportParams",
    "BUILTIN_COMMAND_CONTRACTS",
    "params_schema_of",
]
