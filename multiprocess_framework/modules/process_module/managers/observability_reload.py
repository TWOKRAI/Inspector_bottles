# -*- coding: utf-8 -*-
"""
Observability hot-reload: ConfigFileWatcher → reconfigure(Logger/Error/Stats).

Связывает готовые компоненты (reuse-first, нового watcher-кода нет):
  ConfigFileWatcher (config_module) следит за файлом конфига → при изменении читает
  секцию ``observability`` → зовёт ``reconfigure()`` у CRM-менеджеров (Phase 1).

Размещение (ADR observability P3.3): один watcher живёт в оркестраторе
(ProcessManagerProcess) и перестраивает ЕГО менеджеры. Cross-process распространение —
через IPC ``config.reload`` (Phase 4): watcher остаётся здесь, дети получат IPC-хендлер.

Итерация 1: full-rebuild каналов в потоке watchdog. Правки конфига редки и дебаунсятся,
поэтому отдельная синхронизация reconfigure ↔ конкурентного логирования не вводится
(задел следующей итерации).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ...config_module.core.config import Config
from ..configs.observability_config import expand_observability
from ..configs.observability_layers import LAYER_APP, LAYER_RECIPE

if TYPE_CHECKING:
    from ...config_module.tools.watcher import ConfigFileWatcher
    from ..configs.observability_layers import ObservabilityLayers


def resolve_base_log_dir(explicit: Optional[str] = None) -> str:
    """Каталог логов как МАШИННЫЙ контекст пересборки (Task 5.12).

    Тот же резолв, что на boot (``ProcessLaunchConfig._resolve_log_dir``): явный
    аргумент → ``INSPECTOR_LOG_DIR`` → ``MULTIPROCESS_LOG_DIR`` → ``logs``.

    Живой конфиг логгера здесь СОЗНАТЕЛЬНО не читается. Он выглядит соблазнительно
    («там же уже лежит резолвнутый путь»), но тогда удаление ``log_directory`` из
    слоя перестало бы работать: пересборка подхватывала бы прежнее значение из
    самой себя, и ровно у одного ключа наследование замолчало бы навсегда.
    """
    if explicit:
        return str(explicit)
    return os.environ.get("INSPECTOR_LOG_DIR") or os.environ.get("MULTIPROCESS_LOG_DIR") or "logs"


def base_managers_payload(log_dir: Optional[str] = None) -> Dict[str, Any]:
    """Слой L0 в машинном контексте — та же база, из которой собирается boot.

    ``managers_from_log_dir`` — единственный источник абсолютных путей файлов
    (``messages.log``, ``errors.log``, ``critical.log``…). Пересборка стартует
    ИМЕННО отсюда, поэтому частичная секция не может увести логи в чужой каталог
    (живая находка 2026-07-22): каталог приходит не из применяемой секции, а из
    машинного контекста, и переопределить его может только явный
    ``log_directory`` слоя.
    """
    from ..configs.managers_config import (
        ManagersConfig,
        managers_from_log_dir,
        managers_payload_for_proc,
    )

    return managers_payload_for_proc(managers_from_log_dir(resolve_base_log_dir(log_dir), model_cls=ManagersConfig))


def _level_profile_scopes(level: str) -> Dict[str, Dict[str, Any]]:
    """Scopes-профиль под глобальный ``log_level`` (иначе уровень — мёртвый параметр).

    ``default_level`` сам по себе НЕ фильтрует: решение принимает ``min_level``
    КАЖДОГО скоупа, а все стандартные скоупы всегда присутствуют в конфиге —
    поэтому смена уровня обязана переписывать их пороги:

      - ``INFO``  — штатный настроенный профиль (дефолты LoggerManagerConfig:
        SYSTEM=WARNING на консоль, BUSINESS/PERFORMANCE=INFO, DEBUG-scope выключен);
      - ``DEBUG`` — все скоупы на DEBUG + DEBUG-scope включается (firehose осознанно);
      - ``WARNING``/``ERROR``/``CRITICAL`` — пороги всех скоупов поднимаются до уровня
        (DEBUG-scope остаётся выключенным).
    """
    from ...logger_module.configs.logger_manager_config import LoggerManagerConfig

    lvl = str(level).upper()
    scopes: Dict[str, Dict[str, Any]] = {}
    for name, sc in LoggerManagerConfig().scopes.items():
        d = sc.model_dump()
        if lvl == "DEBUG":
            d["min_level"] = "DEBUG"
            d["enabled"] = True
        elif lvl != "INFO":
            d["min_level"] = lvl
        scopes[name] = d
    return scopes


def observability_effective(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
) -> Dict[str, Any]:
    """Фактическое (readback) состояние менеджеров наблюдаемости — не эхо запроса.

    Читается из ЖИВЫХ менеджеров ПОСЛЕ применения: пороги скоупов логгера,
    каталог логов, активные каналы (реестр каналов — он отражает и runtime
    ``logger.sink.enable/disable``, чего конфиг не видит), уровень ошибок,
    включённость статистики.
    """
    out: Dict[str, Any] = {}
    if logger is not None and getattr(logger, "config", None) is not None:
        lc = logger.config
        section: Dict[str, Any] = {
            "default_level": getattr(lc, "default_level", None),
            "log_directory": getattr(lc, "log_directory", None),
        }
        scopes = getattr(lc, "scopes", None)
        if isinstance(scopes, dict):
            section["scopes"] = {
                str(k): {
                    "enabled": bool(getattr(v, "enabled", True)),
                    "min_level": getattr(v, "min_level", None),
                }
                for k, v in scopes.items()
            }
        registry = getattr(logger, "_channel_registry", None)
        names = getattr(registry, "names", None)
        if callable(names):
            try:
                section["channels_active"] = sorted(names())
            except Exception:  # noqa: BLE001 — readback best-effort
                pass
        # 2.8: «снят оператором» — ОТДЕЛЬНОЕ поле, а не вывод из отсутствия в
        # `channels_active`. Без него оператор не отличит «я это выключил» от
        # «канал не поднялся» — а это разные диагнозы с разными действиями.
        disabled = getattr(logger, "_sinks_disabled_by_operator", None)
        if isinstance(disabled, set):
            section["sinks_disabled_by_operator"] = sorted(disabled)
        out["logger"] = section
    if error is not None and getattr(error, "config", None) is not None:
        out["error"] = {"default_level": getattr(error.config, "default_level", None)}
    if stats is not None and getattr(stats, "config", None) is not None:
        sc = stats.config
        out["stats"] = {
            "enable_logging": getattr(sc, "enable_logging", None),
            "aggregation_interval": getattr(sc, "aggregation_interval", None),
        }
    return out


def observability_provenance(layers: "ObservabilityLayers", *, logger: Any = None) -> Dict[str, Any]:
    """Кто владеет каждым действующим ключом: ``{ключ: {layer, source}}``.

    Имена каналов и скоупов берутся из ЖИВОГО конфига логгера, а не из раскладки
    слоёв. Разница существенна: пока ни один слой не тронул ``console``/``file``,
    ``expand_observability`` каналов не эмитит вовсе — объяснять было бы нечего,
    хотя каналы работают. Провенанс обязан покрывать то, что действует, а не то,
    что кто-то написал.

    Сам ответ считается по СЫРЫМ секциям слоёв (см. ``ObservabilityLayers.provenance``):
    после раскладки ключ из L0 неотличим от заданного явно.
    """
    view: Dict[str, Any] = {}
    cfg = getattr(logger, "config", None)
    if cfg is not None:
        channels = getattr(cfg, "channels", None)
        if isinstance(channels, dict):
            view["channels"] = {
                str(name): {
                    "enabled": bool(getattr(ch, "enabled", True)),
                    "type": str(getattr(ch, "type", "")),
                }
                for name, ch in channels.items()
            }
        # Каналы, порождённые секцией `modules` (``module_camera`` и соседи), в
        # `config.channels` не лежат — а работают. Ревью 5.12 (замечание 4): их не
        # было в ответе вовсе, то есть на девять живых каналов из двенадцати
        # provenance молчал, притом что приёмка требует «каждый действующий ключ».
        # Берём их из ЖИВОГО реестра — он и есть перечень действующих.
        registry = getattr(logger, "_channel_registry", None)
        names = getattr(registry, "names", None)
        if callable(names):
            try:
                active = sorted(str(n) for n in names())
            except Exception:  # noqa: BLE001 — readback best-effort
                active = []
            known = view.setdefault("channels", {})
            for name in active:
                # `type` намеренно пуст: тип module-канала не управляется оптовыми
                # тогглами console/file, и приписывать ему их владельца было бы
                # враньём — такой ключ честнее объяснить дефолтом фреймворка.
                known.setdefault(name, {"enabled": True, "type": ""})
        scopes = getattr(cfg, "scopes", None)
        if isinstance(scopes, dict):
            view["scopes"] = {
                str(name): {
                    "enabled": bool(getattr(sc, "enabled", True)),
                    "min_level": getattr(sc, "min_level", None),
                }
                for name, sc in scopes.items()
            }
    return layers.provenance(view)


# Что пересылается из get_stats() менеджера наружу в introspect.observability.
# Список ЖЁСТКИЙ намеренно (get_stats несёт и конфиг, и имена — наружу нужны
# только счётчики), но именно поэтому он и есть отдельная точка забывания:
# новый счётчик, добавленный в get_stats и НЕ добавленный сюда, существует и
# при этом невидим. Ровно этот класс уже стрелял в Ф0.3.
#
# Страж — `test_every_manager_counter_is_published_or_declared_unpublished`
# в logger_module/tests/test_counters_visible_path.py: сверяет ЭТОТ список с
# живым `manager.stats`. Прежняя редакция комментария называла стражем два
# файла, «сверяющие список с живым словарём», — такого сравнения там не было ни
# одного, проверялись отдельные счётчики поимённо. Ложная ссылка на стража хуже
# её отсутствия: на неё ссылаются, решая, нужен ли новый тест. Найдено
# слом-инъекцией Ф4.2 (снять публикацию нового счётчика → не покраснело ничего).
PLANE_COUNTER_KEYS: tuple = (
    "messages_processed",
    "messages_skipped",
    "messages_batched",
    "errors_to_floor",
    "errors_floor_write_failures",
    "error_floor",
    "metrics_count",
    "errors",
    # ``flush_failed`` здесь БЫЛ и удалён (F5, вердикт по Ф0.3): верхним уровнем
    # его не публикует ни один менеджер — единственный публикатор
    # ``batch_buffer.stats``, и наружу он уже едет внутри ``buffer``. Мёртвая
    # запись безвредна (``if key in raw``), но она подтачивает доверие к списку,
    # который сам объявлен «точкой забывания»: страж, содержащий заведомо
    # недостижимое имя, перестаёт читаться как перечень достижимых.
    # Ф0.4 — потери на стыке «имя канала → объект канала».
    "unresolved_channel_records",
    "unresolved_channels",
    "channel_write_errors",
    "channel_write_errors_by_channel",
    "channel_refused_records",
    "channel_refused_by_channel",
    # Ф4.2 — приёмников у записи не было вовсе (четвёртый класс потери).
    "records_without_channels",
    # Ф0.7 — чистка каталога логов: сколько удалено/сжато и сколько НЕ удалось.
    "retention_files_deleted",
    "retention_files_compressed",
    "retention_delete_failures",
    "retention_compress_failures",
    "retention_bytes_freed",
    # R2 — обратное давление консоли: запись отброшена по пределу ожидания.
    "console_writes_dropped",
    "console_slow_writes",
    # P2 (найдено LIVE-прогоном Ф1) — карта «уровень → канал» плоскости ошибок.
    # Не счётчик, но ровно тот же класс невидимости: резидуал P2 научил её
    # перестраиваться на снятие приёмника, план назвал её «публичным
    # level_routes», а наружу она не ехала вовсе — оператор не мог спросить у
    # живого процесса, куда сейчас идёт ERROR. Проверять «маршрут сломан» было
    # нечем именно там, где это спрашивают.
    "level_routes",
    # Ф1.4 — отложенное сообщение не собралось (callable бросил / __str__ упал).
    # Запись при этом СОХРАНЕНА с видимым следом сбоя вместо текста, поэтому
    # это не класс потери; но подмена текста обязана быть видна снаружи, иначе
    # оператор читает «<сборка сообщения упала: ...>» и не может спросить,
    # сколько таких было.
    "message_build_failures",
)


def _plane_counters(manager: Any) -> Optional[Dict[str, Any]]:
    """Счётчики одной плоскости наблюдаемости из её ``get_stats()``.

    Нормализует расхождение имён между менеджерами: буфер логгера лежит под
    ключом ``batch_stats`` (``LoggerCore.get_stats`` собирает словарь сам),
    буфер статистики — под ``buffer`` (``ChannelRoutingManager.get_stats``).
    Наружу отдаётся один ключ ``buffer`` — потребителю не должно быть нужно
    знать, какой из двух менеджеров он спрашивает.
    """
    if manager is None or not hasattr(manager, "get_stats"):
        return None
    try:
        raw = manager.get_stats()
    except Exception as exc:  # noqa: BLE001 — наблюдаемость не имеет права ронять команду
        # НЕ None: «менеджер сломан» и «менеджера нет» — разные факты, и
        # диагностическая команда не имеет права прятать отказ диагностируемого
        # (проглоченный сбой — задокументированный класс отказа этого проекта).
        return {"error": repr(exc)}
    if not isinstance(raw, dict):
        return {"error": f"get_stats вернул {type(raw).__name__}, ожидался dict"}

    out: Dict[str, Any] = {}
    buffer = raw.get("batch_stats", raw.get("buffer"))
    if isinstance(buffer, dict):
        out["buffer"] = buffer
    for key in PLANE_COUNTER_KEYS:
        if key in raw:
            out[key] = raw[key]
    return out


def observability_counters(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
) -> Dict[str, Any]:
    """Потери и глубина буферов трёх плоскостей — «сколько наблюдаемости не доехало».

    Отвечает на вопросы, которые до Ф0.3 нельзя было задать живому процессу
    снаружи вообще: ``get_stats()`` менеджеров не читал никто, кроме тестов.

      * ``buffer.pending`` растёт, ``buffer.dropped_by_channel`` непустой —
        сток тормозит и записи уже теряются, с именем канала-виновника;
      * ``errors_to_floor`` > 0 — ошибка не дошла ни до одного канала и легла
        в пол (``error_floor.path``); штатный маршрут ошибок сломан.

    Команда не мутирует ничего: только чтение живых менеджеров.
    """
    out: Dict[str, Any] = {}
    for name, manager in (("logger", logger), ("error", error), ("stats", stats)):
        section = _plane_counters(manager)
        if section is not None:
            out[name] = section
    return out


def apply_observability_layers(
    layers: "ObservabilityLayers",
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    log_dir: Optional[str] = None,
    log_info: Optional[Callable[[str], None]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Пересобрать конфиги менеджеров ИЗ СЛОЁВ и применить (Task 5.12).

    ЕДИНСТВЕННОЕ место, где секция раскладывается (``expand_observability``) и
    применяется (``reconfigure``). И hot-reload watcher (см.
    :func:`make_observability_on_reload`), и IPC-команда ``config.reload`` зовут
    именно её — поэтому файловый и IPC-пути НЕ конфликтуют.

    **Семантика — ПЕРЕСБОРКА ИЗ ИСТОЧНИКОВ, и это разворот** прежней «дельты
    поверх живого» (``deep_merge(живой конфиг, раскрытая секция)``). Причина
    структурная, а не вкусовая: дельта **принципиально не умеет** выразить
    «ключ удалён из слоя → вернись к нижнему» — удаления в дельте не существует.
    Пока конфигом владел один источник, это было незаметно; с четырьмя слоями
    «вернуть как было» стало основной операцией, и дельта её не поддерживает.

    Порядок сборки::

        base = managers_from_log_dir(машинный каталог логов)   # L0 + контекст машины
        target = merge(base, expand(layers.resolve()))          # L1 → L2 → L3
        профиль уровня, если log_level задан хоть одним слоем
        точечные scopes-переопределения слоёв — последними

    Находка 2026-07-22 («частичный reload уводил файлы логов в чужой каталог»)
    держится теперь не merge'ем, а базой: ``log_directory`` приходит из машинного
    контекста и переопределяется ТОЛЬКО явным ключом слоя. Пара на это — в
    ``test_observability_reload_merge.py``.

    None-менеджеры пропускаются (например error/stats отключены).

    Returns:
        Применённый конфиг ``{"logger": …, "error": …, "stats": …, "command": …}``.
        Фактическое состояние менеджеров — :func:`observability_effective`.
    """
    from ...data_schema_module import deep_merge
    from ..configs.managers_config import merge_managers

    # Task 5.8: пересборка идёт ПОД ЛОКОМ СТЕКА целиком. Писателей стало четыре
    # (два watcher'а, поток команд, такт heartbeat), а между «прочитал слои» и
    # «применил результат» два шага: без лока последней могла бы примениться
    # пересборка, прочитавшая слои РАНЬШЕ, то есть отменить более свежую правку.
    # RLock — потому что `_remark_operator_disabled_sinks` читает слои изнутри.
    with layers.lock:
        applied = _rebuild_and_apply(
            layers,
            logger=logger,
            error=error,
            stats=stats,
            log_dir=log_dir,
            log_info=log_info,
            deep_merge=deep_merge,
            merge_managers=merge_managers,
        )
        # Task 5.8: пересборка удалась — долг подметальщика погашен, КЕМ БЫ она ни
        # была вызвана. Иначе после неудачного возврата и последующего успешного
        # `config.reload` такт делал бы лишнюю «повторную» пересборку и клал в
        # кольцо аудита запись о возврате, которого не было (advisory ревью 5.8).
        layers.rebuild_pending = False
        return applied


def _rebuild_and_apply(
    layers: "ObservabilityLayers",
    *,
    logger: Any,
    error: Any,
    stats: Any,
    log_dir: Optional[str],
    log_info: Optional[Callable[[str], None]],
    deep_merge: Callable[..., Any],
    merge_managers: Callable[..., Any],
) -> Dict[str, Dict[str, Any]]:
    """Тело пересборки (вызывается под локом стека — см. вызывающего)."""
    resolved = layers.resolve()
    expanded = expand_observability(resolved)
    base = base_managers_payload(log_dir)

    explicit_level = resolved.get("log_level")
    # scopes слоёв достаём ДО merge: профиль уровня переписывает набор целиком,
    # и адресная правка обязана лечь ПОВЕРХ него, а не быть им стёртой.
    scope_overrides = expanded["logger"].pop("scopes", None)

    logger_cfg = merge_managers(base.get("logger", {}), expanded["logger"])
    if explicit_level is not None:
        logger_cfg["scopes"] = _level_profile_scopes(explicit_level)
        logger_cfg["default_level"] = str(explicit_level).upper()
    if scope_overrides:
        logger_cfg["scopes"] = deep_merge(logger_cfg.get("scopes") or {}, scope_overrides)
    expanded["logger"] = logger_cfg
    expanded["error"] = merge_managers(base.get("error", {}), expanded["error"])
    expanded["stats"] = merge_managers(base.get("stats", {}), expanded["stats"])

    if logger is not None:
        logger.reconfigure(expanded["logger"])
        _remark_operator_disabled_sinks(logger, layers, ("channels",))
    if error is not None:
        error.reconfigure(expanded["error"])
        _remark_operator_disabled_sinks(error, layers, ("errors", "channels"))
    if stats is not None:
        stats.reconfigure(expanded["stats"])
        _remark_operator_disabled_sinks(stats, layers, ("stats", "channels"))
    if log_info is not None:
        held = ", ".join(layers.session_keys()) or "—"
        log_info(
            f"[observability] пересобран из слоёв "
            f"(log_level={expanded['logger'].get('default_level')}; держится сессией: {held})"
        )
    return expanded


def _remark_operator_disabled_sinks(
    manager: Any,
    layers: "ObservabilityLayers",
    path: tuple[str, ...],
) -> None:
    """Вернуть отметку «снято оператором» тем приёмникам, которые держит L3.

    ``reconfigure`` чистит множество целиком, и это правильно (блокер ревью 2.9:
    отметка, пережившая пересборку, вычитала из маршрута ЖИВОЙ приёмник — тихая
    потеря). Но приёмка 2.8 обещает отличать «я это выключил» от «канал не
    поднялся», а после пересборки поле опустело бы при выключенном канале — то
    есть ответ стал бы «канал не поднялся» на вопрос, где верно «я его снял».

    Task 5.10.b: зовётся для КАЖДОЙ из трёх плоскостей, ``path`` — путь до её
    секции каналов в слое сессии. Раньше отметка возвращалась только логгеру, и
    после пересборки ответ про снятый ``errors_file`` менял смысл на противоположный.

    Task 5.10.c закрыла прежнее исключение: ``module_*``-каналы теперь гасятся
    тем же ключом ``channels.<имя>.enabled`` (см. ``LoggerCore._setup_channels``),
    поэтому после пересборки их в реестре нет — как и у остальных, и отметка
    описывает то же самое состояние, а не прикрывает живой канал.
    """
    marks = getattr(manager, "_sinks_disabled_by_operator", None)
    if not isinstance(marks, set):
        return
    node: Any = layers.session or {}
    for step in path:
        if not isinstance(node, dict):
            return
        node = node.get(step)
    if not isinstance(node, dict):
        return
    for name, body in node.items():
        if isinstance(body, dict) and body.get("enabled") is False:
            marks.add(str(name))


def apply_observability_reconfigure(
    section: Any,
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    log_dir: Optional[str] = None,
    log_info: Optional[Callable[[str], None]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Голая секция ``observability`` — это стек, в котором сказал только L1.

    Тонкий фасад над :func:`apply_observability_layers`, а не второй механизм:
    вызывающие, у которых слоёв нет (одиночный процесс, тесты, внешний инструмент
    с готовой секцией), не обязаны собирать стек руками.
    """
    from ..configs.observability_layers import ObservabilityLayers

    return apply_observability_layers(
        ObservabilityLayers(app=dict(section) if isinstance(section, dict) else {}),
        logger=logger,
        error=error,
        stats=stats,
        log_dir=log_dir,
        log_info=log_info,
    )


def make_observability_on_reload(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    section_key: str = "observability",
    log_info: Optional[Callable[[str], None]] = None,
    layers: Optional["ObservabilityLayers"] = None,
    layer: str = LAYER_APP,
    process_name: str = "",
) -> Callable[[Config], None]:
    """Собрать ``on_reload(config)`` callback: файл → нужный СЛОЙ → пересборка.

    Использует ``on_reload`` ConfigFileWatcher'а напрямую (callback вызывается ПОСЛЕ
    ``Config.update``) — pub/sub по ключу не нужен (``update`` шлёт ``_notify("*")``).

    Args:
        layers: стек процесса. **Обязателен, если у процесса есть L2/L3.** Без него
            файл трактуется как весь конфиг целиком, и правка ``system.yaml`` молча
            снесла бы и дельту рецепта, и ручку оператора — то есть watcher оказался
            бы способом обойти слои, ради которых всё и делалось.
        layer: какой слой обновляет ЭТОТ файл — ``app`` (``system.yaml``) или
            ``recipe`` (рецепт/спутник).
        process_name: имя процесса для разрешения per-process секции рецепта
            (``processes[<имя>]``); для слоя ``app`` не используется.
    """
    from ..configs.observability_layers import ObservabilityLayers, resolve_recipe_section

    stack = layers if layers is not None else ObservabilityLayers()

    def _on_reload(config: Config) -> None:
        section = config.get(section_key, {}) or {}
        if layer == LAYER_RECIPE:
            stack.recipe = resolve_recipe_section(section, process_name)
        else:
            stack.app = dict(section) if isinstance(section, dict) else {}
        apply_observability_layers(
            stack,
            logger=logger,
            error=error,
            stats=stats,
            log_info=log_info,
        )

    return _on_reload


def start_observability_watcher(
    *,
    config_path: str | Path,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    section_key: str = "observability",
    debounce_seconds: float = 1.0,
    log_info: Optional[Callable[[str], None]] = None,
    log_error: Optional[Callable[[str], None]] = None,
    on_reload_extra: Optional[Callable[[Config], None]] = None,
    layers: Optional["ObservabilityLayers"] = None,
    layer: str = LAYER_APP,
    process_name: str = "",
) -> Optional["ConfigFileWatcher"]:
    """Запустить watcher файла конфига, перестраивающий менеджеры наблюдаемости.

    Args:
        config_path:  Путь к файлу конфига (например system.yaml) с секцией ``observability``.
        logger/error/stats: CRM-менеджеры с ``reconfigure(dict)`` (любой может быть None).
        section_key:  Имя секции в конфиге (по умолчанию ``observability``).
        debounce_seconds: Дебаунс watchdog (по умолчанию 1.0).
        log_info/log_error: Колбэки логирования (опционально).
        on_reload_extra: Дополнительный ``on_reload(config)``-колбэк, вызываемый ПОСЛЕ
            observability-reconfigure на том же ``Config`` (PC 3.1: оркестратор передаёт
            сюда telemetry-throttle-колбэк из ``telemetry_reload.make_telemetry_on_reload``,
            чтобы одна правка файла перестроила и observability-менеджеры, и центральный
            троттл). ``None`` → только observability (прежнее поведение). Семантически
            watcher остаётся observability-агностичным к содержимому extra-колбэка.

    Returns:
        Запущенный ``ConfigFileWatcher`` или None, если файл не найден.
    """
    from ...data_schema_module.serialization.converter import DataConverter

    path = Path(config_path)
    if not path.exists():
        if log_error is not None:
            log_error(f"[observability] hot-reload: файл не найден — {path}")
        return None

    # Ленивый импорт: watchdog — опциональная зависимость; без неё hot-reload недоступен,
    # но импорт process_module не должен падать.
    try:
        from ...config_module.tools.watcher import ConfigFileWatcher
    except ImportError:
        if log_error is not None:
            log_error("[observability] hot-reload недоступен: не установлен watchdog")
        return None

    # Начальное содержимое — текущий файл (чтобы config.get(section) был консистентен).
    try:
        initial = DataConverter.load_from_file(path)
        initial = initial if isinstance(initial, dict) else {}
    except Exception:
        initial = {}

    config = Config(initial_data=initial)
    on_reload = make_observability_on_reload(
        logger=logger,
        error=error,
        stats=stats,
        section_key=section_key,
        log_info=log_info,
        layers=layers,
        layer=layer,
        process_name=process_name,
    )
    if on_reload_extra is not None:
        # Композиция: сначала observability-reconfigure, затем extra-колбэк (PC 3.1:
        # telemetry-throttle) на том же Config. Наличие callback'а — child-side seam,
        # содержимого extra эта функция не знает (остаётся observability-агностичной).
        _base_on_reload = on_reload

        def on_reload(config: Config, _base=_base_on_reload, _extra=on_reload_extra) -> None:  # noqa: F811
            _base(config)
            _extra(config)

    watcher = ConfigFileWatcher(
        path=path,
        config=config,
        on_reload=on_reload,
        debounce_seconds=debounce_seconds,
    )
    watcher.start()
    if log_info is not None:
        log_info(f"[observability] hot-reload watcher запущен: {path}")
    return watcher
