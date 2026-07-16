# -*- coding: utf-8 -*-
"""Telemetry hot-reload: единая идемпотентная точка применения секции ``telemetry`` (PC 3.1).

По образцу :func:`observability_reload.apply_observability_reconfigure` — раскладывает
секцию ``telemetry`` на ДВЕ плоскости управления (план ``telemetry-publish-control``)
и применяет их к живым получателям БЕЗ рестарта процесса:

  - ``publish``  → publisher-gate процесса (``ProcessHeartbeat.reconfigure_telemetry``):
    что процесс вообще СЧИТАЕТ/публикует и как часто (главный рычаг, PC 1.2);
  - ``throttle`` → центральный store-троттл оркестратора (``ThrottleMiddleware.set_rules``
    через ``StateStoreManager.get_middleware("throttle")``, PC 0.1/2.1): rate-limit
    записи в дерево/IPC (вторая плоскость, IPC-страховка).

ЕДИНСТВЕННОЕ место применения telemetry-секции: и IPC-команда ``telemetry.reconfigure``,
и расширенный ``config.reload`` (``data["telemetry"]``), и файловый watcher оркестратора
(через :func:`make_telemetry_on_reload`) зовут именно эту функцию — один идемпотентный
путь, как у observability (гарантия неконфликта источников).

**Граница Task 3.1 vs 3.2:** функция применяет к получателям ОДНОГО процесса-адресата.
Fan-out на ВСЕХ детей (broadcast ``process=all``) — Task 3.2, здесь НЕ делается.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from ...config_module.core.config import Config

# Task 1.1: маркер удаления правила в throttle-дельте (``mode="merge"``). Значение
# ``None`` у паттерна → ``remove_rule(pattern)``. ``0`` остаётся ВАЛИДНЫМ правилом
# «полная блокировка», поэтому не может служить маркером — только ``None`` (JSON null,
# Dict-at-Boundary дружелюбно) однозначно означает «снять правило».
THROTTLE_REMOVE: Any = None


def apply_telemetry_reconfigure(
    section: Any,
    *,
    mode: str = "replace",
    heartbeat: Any = None,
    store_throttle: Any = None,
    log_info: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Применить секцию ``telemetry`` к publisher-gate и/или центральному троттлу.

    Применяются ТОЛЬКО те под-секции, чьи ключи ПРИСУТСТВУЮТ в ``section`` (наличие
    ключа, не истинность значения) — так можно менять только одну плоскость, не трогая
    другую:

      - ``"publish" in section`` → ``heartbeat.reconfigure_telemetry(section["publish"],
        mode=mode)`` (значение dict → пересобрать/смержить gate; ``None`` → выключить gate
        — все метрики каждый тик, backward-compat);
      - ``"throttle" in section`` → центральный ``ThrottleMiddleware`` (см. ниже).

    Режим ``mode`` (Task 1.1) — общий для ОБЕИХ плоскостей:
      - ``"replace"`` (дефолт, backward-compat) — полное применение секции целиком
        (publisher-gate пересобирается из секции; throttle → ``set_rules`` заменяет ВЕСЬ
        набор правил, ``{}`` → снять все);
      - ``"merge"`` — дельта поверх ЖИВОГО состояния: publisher-gate строится из
        ``deep_merge(current_effective, delta)``; throttle применяется ПО-ПРАВИЛУ через
        ``update_rule``/``remove_rule`` (значение :data:`THROTTLE_REMOVE`/``None`` у
        паттерна → удалить правило). «Точечная» правка не стирает остальные правила/метрики.

    Отсутствующая под-секция НЕ трогается. None-получатель (процесс без heartbeat /
    без StateStoreManager) → под-секция помечается как НЕ применённая — для диагностики
    «нет приёмника» (визуализация в introspect — Task 3.2).

    Args:
        section: dict с опциональными ключами ``publish`` / ``throttle``.
        mode: ``"replace"`` (полное применение) или ``"merge"`` (дельта поверх живого).
        heartbeat: ``ProcessHeartbeat`` процесса-адресата (или None — нет приёмника).
        store_throttle: живой ``ThrottleMiddleware`` оркестратора (или None — процесс
            не держит StateStoreManager, троттл ему не адресуется).
        log_info: колбэк логирования (опционально).

    Returns:
        ``{"publish": bool, "throttle": bool}`` — по ключу для КАЖДОЙ ЗАПРОШЕННОЙ
        (присутствующей в ``section``) под-секции: ``True`` — применена, ``False`` —
        получателя не было. Незапрошенные под-секции в результат не попадают.
    """
    section = section or {}
    applied: Dict[str, Any] = {}

    if "publish" in section:
        if heartbeat is not None and hasattr(heartbeat, "reconfigure_telemetry"):
            heartbeat.reconfigure_telemetry(section["publish"], mode=mode)
            applied["publish"] = True
        else:
            applied["publish"] = False  # нет приёмника: процесс без heartbeat

    if "throttle" in section:
        if _throttle_applicable(store_throttle, mode):
            _apply_throttle(store_throttle, section["throttle"], mode)
            applied["throttle"] = True
        else:
            applied["throttle"] = False  # процесс не держит StateStoreManager/throttle

    if log_info is not None and applied:
        log_info(f"[telemetry] reconfigure применён (mode={mode}): {applied}")
    return applied


def _throttle_applicable(store_throttle: Any, mode: str) -> bool:
    """Есть ли у троттла нужный для режима API (иначе «нет приёмника»).

    ``replace`` требует ``set_rules`` (полная замена), ``merge`` — per-правило
    ``update_rule``/``remove_rule`` (Task 1.1: оживает мёртвый API PC 0.1).
    """
    if store_throttle is None:
        return False
    if mode == "merge":
        return hasattr(store_throttle, "update_rule") and hasattr(store_throttle, "remove_rule")
    return hasattr(store_throttle, "set_rules")


def _apply_throttle(store_throttle: Any, throttle_section: Any, mode: str) -> None:
    """Применить throttle-под-секцию к живому ``ThrottleMiddleware``.

    ``replace`` — ``set_rules(section or {})`` заменяет ВЕСЬ набор (``{}`` → снять все).
    ``merge`` — пройти дельту по правилам: ``None``-значение (:data:`THROTTLE_REMOVE`) →
    ``remove_rule(pattern)``, иначе ``update_rule(pattern, interval)``. Остальные (не
    упомянутые в дельте) правила не трогаются — это и есть «точечная» правка.
    """
    if mode == "merge":
        for pattern, interval in (throttle_section or {}).items():
            if interval is THROTTLE_REMOVE:
                store_throttle.remove_rule(pattern)
            else:
                store_throttle.update_rule(pattern, interval)
        return
    store_throttle.set_rules(throttle_section or {})


def resolve_store_throttle(holder: Any) -> Any:
    """Достать живой ``ThrottleMiddleware`` через ``_state_store_manager`` держателя.

    ЕДИНАЯ точка резолва центрального троттла (устраняет дубль): и адресный
    ``telemetry.reconfigure`` (``BuiltinCommands._resolve_store_throttle`` — держатель
    = процесс-адресат), и fan-out ``telemetry.broadcast`` (PM — держатель = сам
    оркестратор) достают троттл одинаково.

    ``holder`` — любой объект с атрибутом ``_state_store_manager`` (процесс-оркестратор
    ``GenericProcessManagerApp``). StateStoreManager держит ТОЛЬКО оркестратор → у
    обычных процессов атрибута нет / он ``None`` → возвращаем ``None`` (троттл-плоскость
    молча пропускается, её единственный адресат — оркестратор).

    Returns:
        Живой ``ThrottleMiddleware`` (по имени ``"throttle"``) либо ``None``.
    """
    store_manager = getattr(holder, "_state_store_manager", None)
    if store_manager is None or not hasattr(store_manager, "get_middleware"):
        return None
    return store_manager.get_middleware("throttle")


def make_telemetry_on_reload(
    *,
    store_throttle: Any = None,
    section_key: str = "telemetry",
    log_info: Optional[Callable[[str], None]] = None,
) -> Callable[["Config"], None]:
    """Собрать ``on_reload(config)`` для файлового watcher'а: секция ``telemetry`` → троттл.

    Используется оркестратором как ``on_reload_extra`` рядом с observability-watcher'ом
    (тот же файл, та же правка → и observability-менеджеры, и центральный троттл без
    рестарта).

    **ВАЖНО (граница Task 3.1 vs 3.2):** watcher живёт в оркестраторе и применяет ТОЛЬКО
    ``throttle`` (центральный store-троттл, доступный в ТОМ ЖЕ процессе). Publisher-gate
    ДЕТЕЙ через файл не перестраивается — для этого нужен fan-out по процессам
    (broadcast), это Task 3.2. Поэтому ``heartbeat`` тут не передаётся: применяется лишь
    throttle-плоскость (даже если в файле есть ``publish`` — он помечается «нет приёмника»
    и никого не трогает).
    """

    def _on_reload(config: "Config") -> None:
        section = config.get(section_key, {}) or {}
        apply_telemetry_reconfigure(
            section,
            heartbeat=None,  # publisher-gate детей — fan-out Task 3.2, не через файл
            store_throttle=store_throttle,
            log_info=log_info,
        )

    return _on_reload


__all__ = [
    "THROTTLE_REMOVE",
    "apply_telemetry_reconfigure",
    "make_telemetry_on_reload",
    "resolve_store_throttle",
]
