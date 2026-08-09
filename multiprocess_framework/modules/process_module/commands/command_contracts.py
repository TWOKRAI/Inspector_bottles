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

import typing
from typing import Any, Dict, List, Optional, Type

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


class ObservabilityIntrospectParams(BaseModel):
    """Параметры ``introspect.observability`` (Task 5.9).

    Команда была ``NoParams``; аудит добавил ровно одну ручку — глубину хвоста.
    Объявить её обязательно: ``extra="forbid"`` означает, что незадекларированный
    параметр помечается ``unexpected`` warn-мидлварью, а в ``FW_CONTRACTS_STRICT``
    сообщение дропается целиком — ручка была бы мертва при зелёных тестах.
    """

    model_config = ConfigDict(extra="forbid")

    #: Сколько последних записей аудита вернуть (дефолт 20; 0 — не возвращать).
    audit_limit: Optional[int] = None


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
    """Параметры ``observability.tail.subscribe`` (Ф5.20b)."""

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None


class ObservabilityTailUnsubscribeParams(BaseModel):
    """Параметры ``observability.tail.unsubscribe`` (F1: per-subscriber отписка).

    Форвардер наблюдаемости — per-subscriber (несколько подписчиков сосуществуют на
    одном процессе: GUI + backend_ctl). ``subscriber`` снимает форвардер ТОЛЬКО этого
    подписчика; ``None`` (legacy/teardown) — снять форвардеры всех подписчиков.
    """

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None


class ObservabilityTailBrokerParams(BaseModel):
    """Параметры ``observability.tail.subscribe_all`` / ``.unsubscribe_all`` (Task 5.11).

    Команды брокера живут на ОРКЕСТРАТОРЕ, но контракт объявляется здесь, вместе
    со всеми остальными: два реестра имён одной плоскости однажды разойдутся, и
    тогда через одно написание пройдёт то, что другое отвергает (урок 5.10.e).
    Схема одна на обе команды — параметр у них ровно один и тот же.
    """

    model_config = ConfigDict(extra="forbid")

    subscriber: Optional[str] = None


class HealthReportParams(BaseModel):
    """Параметры ``health.report`` (диагностический впрыск health-события, Ф2 Task 2.1)."""

    model_config = ConfigDict(extra="forbid")

    context: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None


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
    "LogTailSubscribeParams",
    "LogTailUnsubscribeParams",
    "ObservabilityTailSubscribeParams",
    "ObservabilityTailBrokerParams",
    "HealthReportParams",
    "BUILTIN_COMMAND_CONTRACTS",
    "params_schema_of",
]
