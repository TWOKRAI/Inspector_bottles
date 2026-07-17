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

# Маркер удаления правила в throttle-дельте (``mode="merge"``). Значение ``None`` у
# паттерна → ``remove_rule(pattern)``. ``0`` остаётся ВАЛИДНЫМ правилом «полная
# блокировка», поэтому не может служить маркером — только ``None`` (JSON null,
# Dict-at-Boundary дружелюбно) однозначно означает «снять правило».
THROTTLE_REMOVE: Any = None

# Явный маркер полной очистки набора central-правил: ``throttle: {"__clear__": true}``.
# Введён, чтобы развести две семантики пустоты (находка B): ПУСТАЯ секция
# (``{}``/``None``) означает «вернуть boot-дефолты» — так boot ≡ reload на одном YAML;
# «снять ВСЕ правила» теперь требует ЯВНОГО намерения через этот маркер, а не совпадает
# с пустым dict. Раньше ``throttle: {}`` на boot давал дефолты, а на hot-reload —
# ``set_rules({})`` (снимал всё): один и тот же файл давал разное состояние.
THROTTLE_CLEAR_MARKER: str = "__clear__"

# Task 1.2 (замечание ревьюера Task 1.1): допустимые режимы применения дельты. Неизвестный
# ``mode`` (напр. опечатка ``"mrege"``) НЕ должен молча уходить в деструктивную
# ``replace``-ветку (wipe соседних правил/метрик) — валидируем в единой точке применения.
VALID_MODES: tuple[str, ...] = ("replace", "merge")


def apply_telemetry_reconfigure(
    section: Any,
    *,
    mode: str = "replace",
    heartbeat: Any = None,
    store_throttle: Any = None,
    default_throttle_rules: Optional[Dict[str, Any]] = None,
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
        набор правил). ПУСТАЯ throttle-под-секция (``{}``/``None``) → ``default_throttle_rules``
        (единая семантика с boot: тот же YAML даёт то же состояние при рестарте и reload,
        находка B); полная очистка — только явным :data:`THROTTLE_CLEAR_MARKER`;
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
        default_throttle_rules: boot-дефолты central-троттла (результат
            ``build_throttle_rules``). Пустая throttle-под-секция в режиме ``replace`` →
            эти правила (boot ≡ reload). ``None`` (вызов без источника дефолтов, напр.
            адресная операторская команда) → пустая секция снимает все правила, как раньше.
        log_info: колбэк логирования (опционально).

    Returns:
        ``{"publish": bool, "throttle": bool}`` — по ключу для КАЖДОЙ ЗАПРОШЕННОЙ
        (присутствующей в ``section``) под-секции: ``True`` — применена, ``False`` —
        получателя не было. Незапрошенные под-секции в результат не попадают.

        Task 1.2: неизвестный ``mode`` → ``{"error": <текст>, "mode": <mode>}`` и НИЧЕГО
        не применяется (ни одна плоскость) — явная наблюдаемая ошибка вместо молчаливого
        деструктивного ``replace`` (опечатка не должна стирать соседние правила/метрики).
    """
    if mode not in VALID_MODES:
        msg = f"неизвестный telemetry mode={mode!r} (ожидается {VALID_MODES}); секция НЕ применена"
        if log_info is not None:
            log_info(f"[telemetry] {msg}")
        return {"error": msg, "mode": mode}

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
            _apply_throttle(store_throttle, section["throttle"], mode, default_throttle_rules)
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


def _apply_throttle(
    store_throttle: Any,
    throttle_section: Any,
    mode: str,
    default_rules: Optional[Dict[str, Any]] = None,
) -> None:
    """Применить throttle-под-секцию к живому ``ThrottleMiddleware``.

    Семантика пустоты (находка B, boot ≡ reload):
      - явный :data:`THROTTLE_CLEAR_MARKER` (``{"__clear__": true}``) в ЛЮБОМ режиме →
        ``set_rules({})`` — единственный способ снять ВСЕ правила намеренно;
      - ``replace`` + пустая секция (``{}``/``None``) → ``default_rules`` (boot-дефолты);
        ``None``-дефолты (нет источника) → снять все, как раньше (backward-compat);
      - ``replace`` + непустая секция → ``set_rules(section)`` заменяет весь набор;
      - ``merge`` — пройти дельту по правилам: ``None``-значение (:data:`THROTTLE_REMOVE`)
        → ``remove_rule(pattern)``, иначе ``update_rule(pattern, interval)``. Остальные
        (не упомянутые в дельте) правила не трогаются — это и есть «точечная» правка.
    """
    section = throttle_section or {}

    # Явный clear-маркер — снять всё намеренно (перекрывает и merge, и replace). Строгая
    # проверка ``is True``: маркер срабатывает только на документированную форму
    # ``{"__clear__": true}``, а не на любое truthy-значение под этим ключом (иначе
    # гипотетический паттepн-правило с таким именем случайно снёс бы весь набор).
    if isinstance(section, dict) and section.get(THROTTLE_CLEAR_MARKER) is True:
        store_throttle.set_rules({})
        return

    if mode == "merge":
        for pattern, interval in section.items():
            if interval is THROTTLE_REMOVE:
                store_throttle.remove_rule(pattern)
            else:
                store_throttle.update_rule(pattern, interval)
        return

    # replace: пустая секция → boot-дефолты (единая семантика с рестартом), иначе — набор.
    if not section:
        store_throttle.set_rules(dict(default_rules) if default_rules else {})
        return
    store_throttle.set_rules(section)


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


def _central_rule_for_metric(metric: str, rules: Dict[str, Any]) -> Optional[float]:
    """Найти интервал central-правила для метрики по СУФФИКСУ паттерна (generic).

    Central-правила троттла авторятся как листовые глобы вида ``processes.**.state.fps``
    — последний сегмент == имя метрики publisher-контракта (``fps`` / ``latency_ms`` /
    ``effective_hz`` / ``cycle_duration_ms`` / ``shm``). Сопоставляем ПО СУФФИКСУ, а не по
    полному пути: framework не знает layout дерева прототипа (``processes.**.state.*``) —
    это app-specific. Суффикс-матч оставляет framework generic.

    Если под метрику подпадает несколько правил — берём СТРОЖАЙШЕЕ (макс. интервал; ``0``
    = полная блокировка — строже любого интервала): именно оно и станет узким местом.

    Returns:
        Интервал строжайшего правила метрики либо ``None``, если правил нет.
    """
    candidates = [
        interval
        for pattern, interval in rules.items()
        if isinstance(interval, (int, float)) and pattern.rsplit(".", 1)[-1] == metric
    ]
    if not candidates:
        return None
    # 0 (полная блокировка) — строжайшее; иначе максимальный интервал.
    if any(c == 0 for c in candidates):
        return 0.0
    return max(candidates)


def detect_throttle_caps(publish_section: Any, store_throttle: Any) -> Dict[str, Dict[str, float]]:
    """Найти метрики publish-дельты, чью частоту central-троттл молча срезал бы.

    Инвариант ADR-PM-017: **publisher-gate — единственный авторитет частоты**, central-троттл
    — лишь IPC-предохранитель от СБОЙНОГО публикатора, а не второй авторитет. Если оператор
    поднимает частоту метрики (publisher ``interval_sec``) НИЖЕ действующего central-правила
    той же метрики, троттл молча срезал бы это поднятие — недопустимо (принцип «no silent
    caps»). Вместо тихого среза возвращаем ЯВНЫЙ отчёт: инициатор (backend_ctl/GUI) ВИДИТ,
    что троттл ограничивает частоту, и может осознанно ослабить central-правило (``telemetry_set
    plane=throttle``). Троттл при этом НЕ трогается автоматически — операторская страховка
    остаётся нетронутой (auto-relax отвергнут, см. ADR-PM-017 «Rejected»).

    Сравнивается только per-метрика явный ``interval_sec`` в ``metrics.<name>`` (``None`` →
    наследование default — не флагуем, неоднозначно). Central-правило метрики ищется по
    суффиксу паттерна (:func:`_central_rule_for_metric`).

    Args:
        publish_section: publish-под-секция команды (dict с опциональным ``metrics``).
        store_throttle: живой центральный ``ThrottleMiddleware`` оркестратора (или ``None``).

    Returns:
        ``{metric: {"publisher_interval_sec": p, "throttle_interval_sec": t}}`` — только для
        метрик, где троттл строже (``t > p`` или ``t == 0`` полная блокировка). Пусто →
        поднятие частоты дойдёт до дерева без среза (страховка мягче публикатора).
    """
    if not isinstance(publish_section, dict) or store_throttle is None:
        return {}
    metrics = publish_section.get("metrics")
    if not isinstance(metrics, dict):
        return {}
    rules = getattr(store_throttle, "rules", None)
    if not isinstance(rules, dict) or not rules:
        return {}

    caps: Dict[str, Dict[str, float]] = {}
    for metric, rule in metrics.items():
        if not isinstance(rule, dict):
            continue
        pub_interval = rule.get("interval_sec")
        if not isinstance(pub_interval, (int, float)) or isinstance(pub_interval, bool):
            continue
        throttle_interval = _central_rule_for_metric(metric, rules)
        if throttle_interval is None:
            continue
        # Троттл строже: больший min-интервал (реже пропускает) ИЛИ 0 (полная блокировка).
        if throttle_interval == 0 or throttle_interval > pub_interval:
            caps[metric] = {
                "publisher_interval_sec": float(pub_interval),
                "throttle_interval_sec": float(throttle_interval),
            }
    return caps


def make_telemetry_on_reload(
    *,
    store_throttle: Any = None,
    default_throttle_rules: Optional[Dict[str, Any]] = None,
    section_key: str = "telemetry",
    log_info: Optional[Callable[[str], None]] = None,
) -> Callable[["Config"], None]:
    """Собрать ``on_reload(config)`` для файлового watcher'а: секция ``telemetry`` → троттл.

    Используется оркестратором как ``on_reload_extra`` рядом с observability-watcher'ом
    (тот же файл, та же правка → и observability-менеджеры, и центральный троттл без
    рестарта).

    **Файл — декларативный источник состояния троттла (boot ≡ reload, находка B):**
    удаление ключа ``throttle`` из файла означает «вернуть boot-дефолты», а НЕ «оставить
    stale». НО watcher срабатывает на ЛЮБОЕ изменение файла (в т.ч. несвязанное — правку
    ``observability.log_level`` в том же файле). Поэтому central-троттл трогается ТОЛЬКО
    когда throttle-объявление РЕАЛЬНО изменилось с прошлого reload: иначе runtime-дельта
    троттла (операторская правка через ``telemetry.broadcast``, ADR-PM-017) молча
    откатывалась бы к дефолтам при несвязанной перезагрузке — тихий срез страховки,
    который ADR-PM-017 запрещает («no silent caps»). ``default_throttle_rules`` — те же
    boot-правила (``build_throttle_rules``), что оркестратор кладёт в ``state_throttle_rules``.

    **Граница Task 3.1 vs 3.2:** watcher живёт в оркестраторе и применяет ТОЛЬКО
    ``throttle`` (центральный store-троттл, доступный в ТОМ ЖЕ процессе). Publisher-gate
    ДЕТЕЙ через файл не перестраивается — для этого нужен fan-out по процессам
    (broadcast), это Task 3.2. Поэтому ``heartbeat`` тут не передаётся: применяется лишь
    throttle-плоскость (даже если в файле есть ``publish`` — он помечается «нет приёмника»
    и никого не трогает).
    """
    # Маркер «throttle-объявление ещё не наблюдалось» — отличает первый reload от
    # последующих и «throttle никогда не было в файле» от «throttle удалили».
    _unseen = object()
    last_throttle: Any = _unseen

    def _on_reload(config: "Config") -> None:
        nonlocal last_throttle
        raw = config.get(section_key, None)
        if raw is None:
            # Телеметрия в файле не объявлена вовсе → центральный троттл не трогаем.
            return
        section = dict(raw or {})
        declared = section.get("throttle", _unseen)  # что файл объявляет сейчас (или его отсутствие)
        # Diff-гейт: несвязанная правка файла (throttle-объявление не изменилось) НЕ трогает
        # троттл — не откатывает runtime-дельту к дефолтам. Реальное изменение/удаление
        # throttle в файле → применяем (удаление → declared==_unseen → пустой → boot-дефолты).
        if declared == last_throttle:
            return
        last_throttle = declared
        section.setdefault("throttle", {})  # объявление изменилось; отсутствие → дефолты
        apply_telemetry_reconfigure(
            section,
            heartbeat=None,  # publisher-gate детей — fan-out Task 3.2, не через файл
            store_throttle=store_throttle,
            default_throttle_rules=default_throttle_rules,
            log_info=log_info,
        )

    return _on_reload


__all__ = [
    "THROTTLE_CLEAR_MARKER",
    "THROTTLE_REMOVE",
    "VALID_MODES",
    "apply_telemetry_reconfigure",
    "detect_throttle_caps",
    "make_telemetry_on_reload",
    "resolve_store_throttle",
]
