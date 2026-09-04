# -*- coding: utf-8 -*-
"""Telemetry hot-reload: единая идемпотентная точка применения секции ``telemetry`` (PC 3.1).

По образцу :func:`observability_reload.apply_observability_layers` — раскладывает
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

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from ...state_store_module import split_pattern

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


#: Правило на адресе ЕСТЬ, но его интервал не число (Ф3, задача 3.0a, находка Н3).
#: Отдельно от ``None`` («правила нет») потому, что это РАЗНЫЕ факты и разная
#: судьба записи в живом троттле: непокрытый путь пропускается без ограничений,
#: а нечисловое правило ломает ``ThrottleMiddleware`` со ВТОРОГО вызова.
_UNREADABLE_RULE: Any = object()


def _narrow_rule(matched: list) -> Any:
    """Строжайшее из отобранных правил, либо ``None``, либо :data:`_UNREADABLE_RULE`.

    Общая половина обоих матчеров: они по-разному РЕШАЮТ, какие правила
    адресуют кандидата (суффикс имени против пересечения глобов), но одинаково
    выбирают из отобранного — иначе на одном входе получились бы две дисциплины.

    **``bool`` — валидное правило, а не мусор** (Ф3, задача 3.0a, находка Н2).
    Половина по ПУТИ исключала его, половина по ИМЕНИ принимала; замер на живом
    ``ThrottleMiddleware`` (три ``before_set`` подряд) снял вопрос — троттл
    исполняет оба значения::

        {'…fps': True}  -> [(True,0), (False,1), (False,2)]   # как интервал 1.0
        {'…fps': 0.05}  -> [(True,0), (False,1), (False,2)]   # так же
        {'…fps': False} -> полная блокировка (ветка `interval == 0`)

    Раз троттл правило исполняет — сверщик обязан его видеть, иначе РАБОТАЮЩЕЕ
    правило падало бы в «судили, потолка нет».

    **Нечисловой интервал — не «правила нет»** (находка Н3). Замер на том же
    стенде::

        {'…fps': '0.05'} -> [(True,0), TypeError("unsupported operand type(s) for /: 'float' and 'str'"), …]

    То есть строка не троттлит, а ЛОМАЕТ троттл со второго вызова, и молчание
    сверщика скрыло бы не потолок, а сломанное правило.

    Названный потолок: если адрес покрыт И читаемым, и нечитаемым правилом,
    судим по читаемым, а сломанное молчит — сузить это до «называть оба» нельзя,
    не заведя второй список в ответе.
    """
    if not matched:
        return None
    readable = [float(interval) for interval in matched if isinstance(interval, (int, float))]
    if not readable:
        return _UNREADABLE_RULE
    # 0 (полная блокировка) — строжайшее; иначе максимальный интервал.
    if any(c == 0 for c in readable):
        return 0.0
    return max(readable)


def _central_rule_for_metric(metric: str, rules: Dict[str, Any]) -> Any:
    """Найти интервал central-правила для метрики по СУФФИКСУ паттерна (generic).

    Central-правила троттла авторятся как листовые глобы вида ``processes.**.state.fps``
    — последний сегмент == имя метрики publisher-контракта (``fps`` / ``latency_ms`` /
    ``effective_hz`` / ``cycle_duration_ms`` / ``shm``). Сопоставляем ПО СУФФИКСУ, а не по
    полному пути: framework не знает layout дерева прототипа (``processes.**.state.*``) —
    это app-specific. Суффикс-матч оставляет framework generic.

    Если под метрику подпадает несколько правил — берём СТРОЖАЙШЕЕ (макс. интервал; ``0``
    = полная блокировка — строже любого интервала): именно оно и станет узким местом.

    **Оговорка после Ф1 «порта наблюдений» (Task 1.4).** У одного имени метрики форм
    адреса стало ДВЕ: агрегат фреймворка плоско (``processes.**.state.fps``) и метрика
    плагина в поддереве писателя (``processes.**.state.plugins.*.drops``). Последний
    сегмент у обеих — имя метрики, поэтому посылка функции цела и правка ей не нужна.
    Названный потолок: функция НЕ проверяет, матчит ли выбранный паттерн живое дерево, —
    если формы разойдутся по интервалу, строжайшей может оказаться та, по адресу которой
    не пишет никто, и оператору отрапортуется несуществующий потолок. Прототип держит обе
    формы на одном интервале намеренно (``manager_setup.py``, там же комментарий), и
    сторож этого равенства стоит в
    ``multiprocess_prototype/backend/state/tests/test_throttle_rules_cover_plugin_paths.py``.

    Returns:
        Интервал строжайшего правила метрики; ``None``, если ни одно правило не
        адресует метрику; :data:`_UNREADABLE_RULE`, если правило есть, а его
        интервал не число (Ф3, задача 3.0a, находка Н3 — см. :func:`_narrow_rule`).
    """
    matched = [interval for pattern, interval in rules.items() if pattern.rsplit(".", 1)[-1] == metric]
    return _narrow_rule(matched)


def _globs_intersect(a: Tuple[str, ...], b: Tuple[str, ...]) -> bool:
    """Существует ли путь, который матчат ОБА паттерна (пересечение непусто).

    Нужно там, где сравниваются два ГЛОБА, а не глоб и путь: правило порта по
    пути против central-правила троттла. Суффиксное сравнение (сосед
    :func:`_central_rule_for_metric`) на такой паре слепо, и слепота была не
    частной: ``…plugins.capture.*``, ``…plugins.**`` и дефолтное правило
    поддерева ``processes.*.state.plugins.**`` возвращали ПУСТО молча — то есть
    «no silent caps» не действовало ровно для назначенного предохранителя
    (находка З1 ревью Ф4).

    Семантика сегментов — та же, что у матчера стора
    (``state_store_module.match_pattern``): ``*`` — ровно один любой сегмент,
    ``**`` — ноль и больше. Частичных wildcard'ов (``f*``) движок не знает: такой
    сегмент — обычный литерал, и здесь он сравнивается литералом же.

    Returns:
        ``True``, если пересечение множеств путей непусто.
    """
    if not a and not b:
        return True
    if not a or not b:
        # Хвост из одних `**` поглощает пустоту — иначе пересечения нет.
        return all(seg == "**" for seg in (a or b))
    head_a, head_b = a[0], b[0]
    if head_a == "**":
        return _globs_intersect(a[1:], b) or _globs_intersect(a, b[1:])
    if head_b == "**":
        return _globs_intersect(a, b[1:]) or _globs_intersect(a[1:], b)
    if head_a == "*" or head_b == "*" or head_a == head_b:
        return _globs_intersect(a[1:], b[1:])
    return False


def _central_rule_for_path_pattern(pattern: str, rules: Dict[str, Any]) -> Any:
    """Строжайшее central-правило, чьи пути ПЕРЕСЕКАЮТСЯ с правилом порта.

    Отличается от :func:`_central_rule_for_metric` не капризом, а входом: там
    ключ — ИМЯ метрики (``metrics.fps``), и что это имя значит в дереве, знает
    только прикладной слой, поэтому framework обязан остаться на суффиксе. Здесь
    ключ — сам ПУТЬ, выраженный на языке того же матчера, что и central-правила;
    сравнивать их напрямую не только можно, но и единственно честно.

    Строжайшее (макс. интервал, ``0`` = полная блокировка) — по тому же доводу,
    что у соседа: узкое место оператору называется то, которое реально сработает.
    Выбор из отобранного и обе особые формы значения (``bool``, нечисло) — общие
    с соседом, см. :func:`_narrow_rule`: раньше эта половина исключала ``bool``,
    а соседняя принимала, и на одном входе жили две дисциплины (находка Н2).
    """
    matched = [
        interval
        for throttle_pattern, interval in rules.items()
        if _globs_intersect(split_pattern(str(pattern)), split_pattern(str(throttle_pattern)))
    ]
    return _narrow_rule(matched)


def judge_throttle_caps(
    publish_section: Any,
    store_throttle: Any,
    *,
    observation_rules: Optional[Dict[str, Any]] = None,
    default_interval_sec: Optional[float] = None,
    effective_tick: Optional[float] = None,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, str]]:
    """Рассудить кандидатов на молчаливый потолок central-троттла — ОДНИМ проходом.

    Инвариант ADR-PM-017: **publisher-gate — единственный авторитет частоты**, central-троттл
    — лишь IPC-предохранитель от СБОЙНОГО публикатора, а не второй авторитет. Если оператор
    поднимает частоту метрики (publisher ``interval_sec``) НИЖЕ действующего central-правила
    той же метрики, троттл молча срезал бы это поднятие — недопустимо (принцип «no silent
    caps»). Вместо тихого среза возвращаем ЯВНЫЙ отчёт: инициатор (backend_ctl/GUI) ВИДИТ,
    что троттл ограничивает частоту, и может осознанно ослабить central-правило (``telemetry_set
    plane=throttle``). Троттл при этом НЕ трогается автоматически — операторская страховка
    остаётся нетронутой (auto-relax отвергнут, см. ADR-PM-017 «Rejected»).

    Половин у прохода две, и они судятся РАЗНЫМ сопоставлением, потому что у них разный
    ВХОД: ключ ``metrics.<имя>`` — это ИМЯ, и что оно значит в дереве, знает только
    прикладной слой (framework обязан остаться generic), поэтому central-правило метрики
    ищется пересечением по суффиксу (:func:`_central_rule_for_metric`); ключ правила порта —
    сам ПУТЬ на языке того же матчера, что и central-правила, поэтому судится пересечением
    глобов (:func:`_central_rule_for_path_pattern`). Довод целиком — ADR-PM-042.

    **Почему ответ — ПАРА, а не только потолки (Ф3, задача 3.0, находка F2 вердикта CTO
    по Ф2, 2026-09-03).** Кандидат, которого рассудить нечем (заявки нет И такта нет),
    до этой правки пропускался МОЛЧА, и пустой ``capped_by_throttle`` был неотличим от
    «потолков нет» — ровно класс «``checked`` отвечает за вызов, а не за охват»: ответ
    ``throttle_checked: true`` с пустым списком читается как подтверждение, которого
    никто не давал. Теперь такой кандидат называется вслух — во второй половине ответа,
    с причиной-литералом (``"no_tick"``). Молчание осталось ровно там, где ответ
    ОПРЕДЕЛЁН и без ask'а: если ни одно central-правило на адрес кандидата не
    пересекается, потолку неоткуда взяться при ЛЮБОМ ask'е, и такой кандидат — не
    «не судили», а «судили, потолка нет».

    **Ред. по находке З1 ревью Ф4: правила по пути судятся ПЕРЕСЕЧЕНИЕМ ГЛОБОВ**
    (:func:`_central_rule_for_path_pattern`), а не по последнему сегменту.
    Прежняя редакция брала ``pattern.rsplit(".", 1)[-1]``, и это молча не судило
    целые классы: ``…plugins.capture.*``, ``…plugins.**``, ``…plugins.*.f*`` —
    и, главное, ДЕФОЛТНОЕ ПРАВИЛО ПОДДЕРЕВА, то есть назначенный предохранитель
    варианта «в». Измерено на прежней редакции: ``…plugins.*.fps`` судилось,
    три перечисленных формы возвращали ``{}``. Названный потолок «отчёт назовёт
    потолок, которого на этом пути нет» СУЗИЛСЯ, но не исчез: пересечение
    считается в языке ПАТТЕРНОВ, а не по живому дереву. Воспроизведение (ревью
    Ф4, итерация 2): ``processes.*.state.plugins.**`` против central-правила
    ``**.state.actual_fps`` пересекаются свидетелем
    ``processes.cam1.state.plugins.capture.state.actual_fps`` — путём, которого в
    дереве нет, — и отчёт назовёт потолок. Ошибка в безопасную сторону (лишнее
    предупреждение, не молчание), поэтому оставлена, а не спрятана.

    **Ред. по итерации 2 ревью:** правило БЕЗ явного ``interval_sec`` судится по
    унаследованному ``default_interval_sec`` — как у соседа. До правки оно
    пропускалось, и ответ утверждал «сверено, потолков нет» при живом срезе.

    Args:
        publish_section: publish-под-секция команды (dict с опциональным ``metrics``).
        store_throttle: живой центральный ``ThrottleMiddleware`` оркестратора (или ``None``).
        observation_rules: правила порта по пути ``{glob: {enabled, interval_sec}}``
            — ожидается :func:`~..configs.observation_policy.cap_candidates`
            (правила оператора ПЛЮС дефолт поддерева) либо ``None``.
        default_interval_sec: ЖИВОЕ значение гейта, которое унаследует правило порта
            без явного ``interval_sec``.
        effective_tick: эффективный телеметрийный тик воркера, сек
            (``ProcessHeartbeat.current_telemetry_tick()``). При пригодном значении
            (``> 0``) — НИЖНЯЯ ГРАНИЦА ask'а публикатора (см. ``_publisher_ask``).
            ``None`` либо непригодный (``<= 0`` — heartbeat отключён или значение слоя
            отрицательное) → такт в расчёте не участвует.

    Returns:
        Пару ``(caps, unjudged)``:

        * ``caps`` — ``{метрика-или-паттерн: {"publisher_interval_sec": p,
          "throttle_interval_sec": t}}``, только там, где троттл строже (``t > p``
          или ``t == 0`` полная блокировка). ``p`` — РЕАЛЬНЫЙ ask публикатора
          (``max(заявка, такт)``), не сырое заявленное значение конфига: печатать
          рядом с «троттл строже» частоту, которой публикатор не попросит, было бы
          противоречием по смыслу для читателя отчёта;
        * ``unjudged`` — ``{ключ: причина}`` для кандидатов, которых рассудить нечем.
          Причина — литерал, их два: ``"no_tick"`` (нет ни заявки, ни такта) и
          ``"unreadable_rule"`` (правило на адресе есть, а его интервал не число —
          Ф3, задача 3.0a, находка Н3; см. :func:`_narrow_rule`).

        Оба словаря пусты → поднятие частоты дойдёт до дерева без среза, и это
        УТВЕРЖДЕНИЕ, а не молчание.
    """
    caps: Dict[str, Dict[str, float]] = {}
    unjudged: Dict[str, str] = {}
    if store_throttle is None:
        return caps, unjudged
    rules = getattr(store_throttle, "rules", None)
    if not isinstance(rules, dict) or not rules:
        return caps, unjudged

    def _usable_tick() -> Optional[float]:
        """Такт, пригодный для расчёта, либо ``None``.

        Непригодны: отсутствие (``None``), нечисло, ``bool`` (в Python ``True``
        это ``1`` — сравнение прошло бы молча), ``NaN`` (``nan > 0`` ложно) и
        вырожденное значение (``<= 0``: heartbeat отключён либо значение слоя
        отрицательное).
        """
        if not isinstance(effective_tick, (int, float)) or isinstance(effective_tick, bool):
            return None
        tick = float(effective_tick)
        return tick if tick > 0.0 else None

    def _inherited_interval() -> float:
        """Частота, которую унаследует правило без явного ``interval_sec``.

        Источник — ЖИВОЕ значение гейта, переданное вызывающим
        (``default_interval_sec``), затем секция запроса, и только потом ``0.0``.

        **Почему не схемный литерал 1.0** (ред. по второму проходу ревью
        итерации 2). Первая редакция этой правки брала 1.0 «схемным дефолтом» —
        и была неверна дважды. Во-первых, боевой вызывающий передавал сюда
        ``None`` вместо секции, поэтому живое число не доходило НИКОГДА и
        сверщик судил по константе: при ``default_interval_sec: 0.5`` и троттле
        0.8 реальный срез существовал, а отчёт отдавал пустой список — тот же
        утвердительный ноль, ради которого пункт и был блокером. Во-вторых,
        сосед (``capped_metrics``, ``heartbeat/telemetry.py``) и само решение
        (``ObservationPolicy.resolve``) откатываются к ``0.0``, а не к 1.0:
        «частоты нет» значит «каждый тик», и любой троттл тогда строже.
        Разойтись с ними значило бы завести третью дисциплину на том же входе.
        """
        if isinstance(default_interval_sec, (int, float)) and not isinstance(default_interval_sec, bool):
            return float(default_interval_sec)
        if isinstance(publish_section, dict):
            raw = publish_section.get("default_interval_sec")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)
        return 0.0

    def _publisher_ask(pub_interval: float) -> Optional[float]:
        """Частота, которую публикатор РЕАЛЬНО запросит у хранилища.

        **Такт — НИЖНЯЯ ГРАНИЦА ask'а, а не замена нулю** (Ф3, задача 3.0,
        находка F1 вердикта CTO по Ф2, 2026-09-03). Публикатор физически не
        публикует чаще такта heartbeat'а: между двумя тактами он не просыпается,
        и заявка «раз в 1.0 с» при такте 5.0 с даёт обращения к хранилищу раз в
        5.0 с. Поэтому при пригодном такте ask = ``max(заявка, такт)``.

        Замер F1 (вход → вывод), на котором находка и стоит:
        ``interval_sec=1.0``, ``effective_tick=5.0``, central-правило ``2.0``.
        До правки: ask ``1.0`` → ``2.0 > 1.0`` → отчёт называл потолок, которого
        нет — публикатор попросит ``5.0``, и правило ``2.0`` его не режет.
        После: ask ``max(1.0, 5.0) = 5.0`` → ``2.0 > 5.0`` ложно → потолок не
        называется. Второй половиной пары: тот же вход при правиле ``6.0`` →
        потолок назван, и ``publisher_interval_sec`` в нём ``5.0`` (реальный
        ask), а не заявленная ``1.0``.

        Task 2.11 (Ф2, Р-11) замещала тактом только НОЛЬ; правка 3.0 обобщает
        замещение до нижней границы, и прежний случай остаётся её частным:
        ``max(0.0, такт) == такт``.

        Без пригодного такта поведение прежнее — регресса нет: ``pub_interval >
        0`` — заявка есть, она и есть ask; ``pub_interval <= 0`` — заявки нет
        тоже, сравнивать не с чем, ``None`` читается вызывающим как «не судили»
        (причина ``"no_tick"``).

        **«Такта нет» — это НЕ только ``None``** (находка ревью Task 2.11,
        2026-09-03). Вырожденный такт (``0.0`` или отрицательный) сюда доезжает
        и достижим не гипотетически: ``ObservabilityConfig.heartbeat_interval_sec``
        объявлен с ``min=0.0``, а ``ProcessHeartbeat.apply_heartbeat_interval``
        отбивает только НЕЧИСЛО (``try/except`` на ``float()``), поэтому
        ``current_telemetry_tick()`` возвращает ``0.0`` при выключенном
        heartbeat'е и отрицательное при отрицательном значении слоя. Замер
        ревьюера на боевых правилах троттла: при ``effective_tick=0.0``
        замещение давало ``{'processes.*.state.plugins.**':
        {'publisher_interval_sec': 0.0, 'throttle_interval_sec': 0.05}}`` —
        ДОСЛОВНО тот отчёт, ради снятия которого добор и делался, только
        вернувшийся через чёрный ход. Ноль здесь не «публикуй бесконечно часто»,
        а «такта нет вовсе» (``heartbeat_interval <= 0`` в этом фреймворке
        означает «heartbeat отключён» — см. примечание ``introspect.telemetry``).

        Правку намеренно сделали ЗДЕСЬ, а не в ``apply_heartbeat_interval``:
        ноль там — законное значение («heartbeat отключён»), и переписывать его
        в схемный дефолт значило бы отменить операторское выключение. Долг
        соседа (докстринг ``apply_heartbeat_interval`` обещает откат к дефолту
        для ОТРИЦАТЕЛЬНОГО, а кода такой ветки нет) назван в плане Task 2.11
        отдельно и этой правкой не закрывается.
        """
        # Заявка берётся ТОЛЬКО положительная: так `NaN` (у которого `> 0` ложно)
        # читается как «заявки нет», а не подставляется в `max`, откуда вышел бы
        # `NaN` в отчёте о потолке.
        claim = float(pub_interval) if pub_interval > 0.0 else None
        tick = _usable_tick()
        if tick is None:
            return claim
        if claim is None:
            return tick
        return max(claim, tick)

    def _judge(key: str, pub_interval: Any, throttle_interval: Any) -> None:
        """Одна развилка на ОБЕ половины: капнут / потолка нет / не судили.

        Порядок проверок — не косметика. Central-правило смотрится ПЕРВЫМ:
        если на адрес кандидата не пересекается ни одно правило, потолку
        неоткуда взяться при любом ask'е, и такой кандидат определён без такта —
        в ``unjudged`` он не идёт, иначе веер «не судил» заполнился бы всем
        деревом и перестал бы что-либо значить.

        Нечитаемое правило (:data:`_UNREADABLE_RULE`) — третий исход того же
        вопроса и вторая причина веера (Ф3, задача 3.0a, находка Н3): правило на
        адресе ЕСТЬ, но интервал не число, и это НЕ «правила нет». Замер живого
        троттла — в докстринге :func:`_narrow_rule`: строка не троттлит, а
        роняет ``ThrottleMiddleware`` со второго вызова, поэтому молчание здесь
        скрывало бы сломанное правило, а не отсутствие потолка.
        """
        if throttle_interval is _UNREADABLE_RULE:
            unjudged[key] = "unreadable_rule"
            return
        if throttle_interval is None:
            return
        if not isinstance(pub_interval, (int, float)) or isinstance(pub_interval, bool):
            # `interval_sec: None` в publish-дельте — «наследуй default», а не
            # «частоты нет»: неоднозначно, не флагуем (поведение до Ф3).
            return
        asked = _publisher_ask(float(pub_interval))
        if asked is None:
            # Единственная сейчас причина «не судили» — литерал контракта ответа
            # `config.reload` (`capped_by_throttle_unjudged`).
            unjudged[key] = "no_tick"
            return
        # Троттл строже: больший min-интервал (реже пропускает) ИЛИ 0 (полная блокировка).
        if throttle_interval == 0 or throttle_interval > asked:
            caps[key] = {
                "publisher_interval_sec": asked,
                "throttle_interval_sec": float(throttle_interval),
            }

    metrics = publish_section.get("metrics") if isinstance(publish_section, dict) else None
    if isinstance(metrics, dict):
        for metric, rule in metrics.items():
            if isinstance(rule, dict):
                name = str(metric)
                _judge(name, rule.get("interval_sec"), _central_rule_for_metric(name, rules))

    if isinstance(observation_rules, dict):
        # Унаследованная частота судится ТАК ЖЕ, как у соседа (`capped_metrics`,
        # `heartbeat/telemetry.py`): `interval_sec: None` — не «неизвестно», а
        # «возьми `default_interval_sec`», и публикатор именно её и попросит.
        # Находка ревью Ф4, итерация 2: прежняя редакция делала здесь `continue`,
        # и правило вида `{"enabled": true}` (обычный способ переоткрыть лист при
        # `subtree_enabled: false`) уходило из-под сверки. Отчёт при этом отвечал
        # `throttle_checked: true` с ПУСТЫМ списком — то есть утверждал «сверено,
        # потолков нет» там, где троттл резал 0.05 с до 2.0 с, в сорок раз.
        # Подтверждающий ноль без контроля — худшая форма молчания: его читают
        # как факт.
        default_interval = _inherited_interval()
        for pattern, rule in observation_rules.items():
            if not isinstance(rule, dict) or rule.get("enabled") is False:
                continue
            pub_interval = rule.get("interval_sec")
            if not isinstance(pub_interval, (int, float)) or isinstance(pub_interval, bool):
                pub_interval = default_interval
            key = str(pattern)
            _judge(key, pub_interval, _central_rule_for_path_pattern(key, rules))

    # Ключ у половин разный по природе (ИМЯ метрики против ПУТИ-паттерна), но
    # строковое совпадение возможно — и тогда один и тот же ключ утверждал бы в
    # одном ответе и «потолок вот такой», и «рассудить было нечем». Утверждение
    # сильнее: рассуждённое побеждает.
    #
    # Развязка ОДНОСТОРОННЯЯ намеренно (Ф3, задача 3.0a, находка Н4 ревью): пара
    # «не судил» ↔ «судил, потолка нет» ею не разводится, потому что второе
    # показание вообще не имеет записи в ответе — разводить нечего. Достижимость
    # столкновения сегодня НУЛЕВАЯ ни на одной живой дороге: `apply_observation_policy`
    # шлёт `publish_section=None`, а оптовый `telemetry.broadcast`
    # (`process_manager_process.py`) не шлёт `observation_rules` — две половины
    # никогда не заполняются одновременно. Строка стоит как страж на день, когда
    # дороги сойдутся (Task 4.12), а не как лечение живого дефекта.
    for judged_key in caps:
        unjudged.pop(judged_key, None)

    return caps, unjudged


def detect_throttle_caps(
    publish_section: Any,
    store_throttle: Any,
    *,
    observation_rules: Optional[Dict[str, Any]] = None,
    default_interval_sec: Optional[float] = None,
    effective_tick: Optional[float] = None,
) -> Dict[str, Dict[str, float]]:
    """Найти метрики и правила порта, чью частоту central-троттл молча срезал бы.

    Тонкая обёртка над :func:`judge_throttle_caps`: тот же проход, но из пары
    ``(caps, unjudged)`` наружу отдаётся только ПЕРВАЯ половина. Разделение
    сделано Ф3 (задача 3.0) ради вызывающих, которым веер «не судил» не нужен:
    сигнатура и тип ответа здесь прежние, поэтому правка F2 их не коснулась.
    Полный разбор механизма — в докстринге :func:`judge_throttle_caps`; замер
    находки F1 (реальный ask публикатора) — в докстринге ``_publisher_ask``
    внутри неё.

    Кто хочет отличать «потолков нет» от «рассудить было нечем» — обязан звать
    :func:`judge_throttle_caps` напрямую: здесь эти два случая по-прежнему
    неотличимы, и это ОСОЗНАННАЯ цена узкого контракта, а не недосмотр.

    Returns:
        ``{метрика-или-паттерн: {"publisher_interval_sec": p, "throttle_interval_sec": t}}``.
        Пусто → либо среза нет, либо судить было нечем (см. выше).
    """
    caps, _unjudged = judge_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        default_interval_sec=default_interval_sec,
        effective_tick=effective_tick,
    )
    return caps


# Внутренние маркеры diff-гейта watcher'а (см. make_telemetry_on_reload).
_THROTTLE_UNSEEN: Any = object()  # throttle в файле не объявлен (отсутствует)
_THROTTLE_SKIP: Any = object()  # файл сейчас нечитаем (частичная запись) — пропустить reload


def _read_throttle_declaration(config_path: Any, section_key: str) -> Any:
    """Свежая throttle-декларация ПРЯМО ИЗ ФАЙЛА (не из merge-аккумулированного Config).

    Ключ находки: watcher-``Config`` аддитивен (``Config.update`` = ``deep_merge``) —
    удалённый/опустошённый в файле ``throttle`` в нём остаётся stale, поэтому сравнивать
    надо со свежей загрузкой файла (ровно как ручной ``config.reload``), иначе «файл —
    источник истины» не работает для удаления/сброса throttle.

    Returns:
        - dict — throttle-под-секция как объявлена в файле;
        - :data:`_THROTTLE_UNSEEN` — секция telemetry есть, но throttle отсутствует, ЛИБО
          telemetry не объявлена вовсе (в обоих случаях throttle «не задан» → дефолты);
        - :data:`_THROTTLE_SKIP` — файл нечитаем/битый прямо сейчас (не трогать троттл).
    """
    if not config_path:
        return _THROTTLE_UNSEEN
    try:
        from ...data_schema_module.serialization.converter import DataConverter

        data = DataConverter.load_from_file(config_path)
    except Exception:  # noqa: BLE001 — частично записанный файл: пропустить этот reload
        return _THROTTLE_SKIP
    if not isinstance(data, dict):
        return _THROTTLE_SKIP
    section = data.get(section_key)
    if not isinstance(section, dict):
        return _THROTTLE_UNSEEN  # телеметрия в файле не объявлена
    return section.get("throttle", _THROTTLE_UNSEEN)


def make_telemetry_on_reload(
    *,
    store_throttle: Any = None,
    default_throttle_rules: Optional[Dict[str, Any]] = None,
    config_path: Any = None,
    section_key: str = "telemetry",
    log_info: Optional[Callable[[str], None]] = None,
) -> Callable[["Config"], None]:
    """Собрать ``on_reload(config)`` для файлового watcher'а: секция ``telemetry`` → троттл.

    Используется оркестратором как ``on_reload_extra`` рядом с observability-watcher'ом
    (тот же файл, та же правка → и observability-менеджеры, и центральный троттл без
    рестарта).

    **Файл — декларативный источник состояния троттла (boot ≡ reload, находка B):** throttle
    читается СВЕЖЕЙ загрузкой ``config_path`` (не из merge-аккумулированного ``Config`` —
    тот аддитивен, удалённый throttle в нём остаётся stale). Central-троттл трогается ТОЛЬКО
    когда throttle-декларация файла РЕАЛЬНО изменилась с прошлого reload (diff-гейт):
    несвязанная правка (``observability.log_level``) не откатывает runtime-дельту троттла
    (операторская правка через ``telemetry.broadcast``, ADR-PM-017 «no silent caps»).
    ``last_throttle`` сидируется ФАКТИЧЕСКОЙ boot-декларацией из файла — иначе первый reload
    при сконфигурированном throttle принял бы «_unseen → {файл}» за изменение и снёс бы
    runtime-дельту. Пустая/отсутствующая throttle-декларация → ``default_throttle_rules``
    (те же boot-правила ``build_throttle_rules``, что оркестратор кладёт в ``state_throttle_rules``).

    **Граница Task 3.1 vs 3.2:** watcher живёт в оркестраторе и применяет ТОЛЬКО
    ``throttle`` (центральный store-троттл, доступный в ТОМ ЖЕ процессе). Publisher-gate
    ДЕТЕЙ через файл не перестраивается — для этого нужен fan-out по процессам
    (broadcast), это Task 3.2.
    """
    # Сид: фактическая boot-декларация throttle из файла (фикс silent-cap на 1-м reload).
    last_throttle: Any = _read_throttle_declaration(config_path, section_key)
    if last_throttle is _THROTTLE_SKIP:
        last_throttle = _THROTTLE_UNSEEN

    def _on_reload(_config: "Config") -> None:
        nonlocal last_throttle
        declared = _read_throttle_declaration(config_path, section_key)
        if declared is _THROTTLE_SKIP:
            return  # файл нечитаем прямо сейчас — не трогаем троттл
        # Diff-гейт: throttle-декларация файла не изменилась → не трогаем (сохраняем
        # runtime-дельту). Изменение/удаление → применяем (удаление → _unseen → пустой →
        # default_throttle_rules, boot ≡ reload).
        if declared == last_throttle:
            return
        last_throttle = declared
        throttle_section = {} if declared is _THROTTLE_UNSEEN else declared
        apply_telemetry_reconfigure(
            {"throttle": throttle_section},
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
    "judge_throttle_caps",
    "make_telemetry_on_reload",
    "resolve_store_throttle",
]
