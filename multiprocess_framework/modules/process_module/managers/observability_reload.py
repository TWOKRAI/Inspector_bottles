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
from ..configs.observability_audit import ACTION_REBUILD
from ..configs.observability_config import expand_observability
from ..configs.observability_layers import (
    LAYER_APP,
    LAYER_RECIPE,
    TELEMETRY_KEY,
    TELEMETRY_LAYERED_SUBSECTION,
    layer_merge,
)

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

    **Граница правила Г3 проходит ЗДЕСЬ, и вот по какому критерию (корзина 2.2).**
    Правило «ключ есть → владею, включая ``{}``» действует между слоями L1/L2/L3 и
    их до-слоевыми источниками, но НЕ над этой базой. Критерий не «где удобнее», а
    **восстановима ли нижняя сторона, если верхняя заберёт её во владение**: здесь
    лежат невосстановимые машинные факты — абсолютные пути файлов, которых нет ни
    в одном слое. ``channels: {}`` как владение увело бы логи в никуда, и вернуть
    их было бы нечем. Там, где нижняя сторона — всего лишь дефолты (загрузочная
    секция метрик в :func:`_apply_telemetry_from_layers`), владение безопасно, и
    правило Г3 действует.

    **Названное расхождение (старше корзины 2.1, воспроизведено ревью).** Слой,
    объявивший ``channels: {}``, получает в ``provenance`` владение веткой, а
    действующие каналы при этом приезжают отсюда: ``resolve`` отдаёт ``{}``,
    ``merge_managers`` возвращает ``console``/``messages_file``/``system_file``.
    Поведение правильное (пути терять нельзя) — врёт объяснение. Решение по форме
    «выключено» для каналов не принято и НЕ подменяется побочным смыслом пустого
    словаря: это отдельный разговор с владельцем, а не следствие мержа.
    """
    from ..configs.managers_config import (
        ManagersConfig,
        managers_from_log_dir,
        managers_payload_for_proc,
    )

    return managers_payload_for_proc(managers_from_log_dir(resolve_base_log_dir(log_dir), model_cls=ManagersConfig))


def _level_profile_scopes(level: str) -> Dict[str, Dict[str, Any]]:
    """Профиль уровня — **вид на общую функцию**, а не вторая её реализация (Ф2.3a).

    Тело переехало в :func:`..configs.managers_config.level_profile_scopes`,
    туда же, где живёт стартовая сборка. Пока копий было две, одна и та же
    величина значила разное: старт опускал один скоуп из четырёх, пересборка —
    все четыре. Имя оставлено здесь ради вызывающего внутри модуля; знание —
    в одном месте.

    Импорт ленивый: ``managers_config`` тянет конфиги всех менеджеров, а этот
    модуль грузится на пути пересборки, где лишний импорт на старте не нужен
    (та же причина, что у ``base_managers_payload``).
    """
    from ..configs.managers_config import level_profile_scopes

    return level_profile_scopes(level)


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
        # Ф2.6: таблица правил по имени источника. Раньше наружу не выходила вовсе —
        # `effective_*` жили в коде с 2.2, а посмотреть на них было нечем, и живой
        # прогон проверялся размерами файлов на глаз. Пустой словарь отдаётся, а не
        # опускается: «правил нет» — это ответ, и его отсутствие отправило бы искать
        # поломку доставки там, где просто ничего не настроено.
        rules_fn = getattr(logger, "rules_table", None)
        if callable(rules_fn):
            section["loggers"] = rules_fn()
        # Ф2.5: ярлыки как их ОБЪЯВИЛИ, рядом с раскрытой таблицей выше.
        # Расхождение между ними и есть «ярлык написан, а не действует»: член,
        # у которого нашлось собственное правило, в раскрытии не появится.
        groups_fn = getattr(logger, "logger_groups", None)
        if callable(groups_fn):
            section["groups"] = groups_fn()
        # Ф2.7: каталог объявленных источников — что МОЖЕТ писать, в отличие от
        # `sources` (что уже писало). Источник, у которого всё гасится порогом, в
        # журнале не появится вовсе, а разбирают обычно именно его.
        from ...log_declarations import declared_sources

        section["declared_sources"] = declared_sources()
        # Ф2.6, шаг 4: какие имена источников вообще писали. Разбор `resolve` требует
        # знать имя заранее, а на стенде вопрос обратный — и до сих пор ответом был
        # только греп по файлу лога, то есть лишь про тех, чьи записи куда-то доехали.
        sources_fn = getattr(logger, "seen_sources", None)
        if callable(sources_fn):
            section["sources"] = sources_fn()
        # Ф2.4: имена групп, в которые ПИСАЛИ, но которых в конфиге нет. Соседний
        # `scopes` выше показывает объявленные — то есть ровно то множество, в
        # котором незаведённой группы нет по определению. Пустой список отдаётся,
        # а не опускается: «таких нет» — это ответ.
        unknown_fn = getattr(logger, "unknown_scopes", None)
        if callable(unknown_fn):
            section["unknown_scopes"] = unknown_fn()
        section.update(_sink_readback(logger))
        section.update(_idle_sinks(logger))
        out["logger"] = section
    if error is not None and getattr(error, "config", None) is not None:
        out["error"] = {
            "default_level": getattr(error.config, "default_level", None),
            **_sink_readback(error),
            **_idle_sinks(error),
        }
    if stats is not None and getattr(stats, "config", None) is not None:
        sc = stats.config
        out["stats"] = {
            "enable_logging": getattr(sc, "enable_logging", None),
            "aggregation_interval": getattr(sc, "aggregation_interval", None),
            **_sink_readback(stats),
            **_idle_sinks(stats),
        }
    return out


def observability_verified(requested: Any, effective: Dict[str, Any]) -> Dict[str, Any]:
    """Сравнить ЗАПРОШЕННОЕ с ДЕЙСТВУЮЩИМ и назвать расхождения поимённо (Task 5.7).

    До этого ``config.reload`` возвращал ``effective`` (readback уже был в ответе)
    и ставил ``success: True`` по факту «применение не упало». Запроси ключ,
    перебитый вышестоящим слоем, или **опечатку** — ответ был тем же успехом.
    Данные для суждения лежали в ответе, суждения не было.

    Три различимых исхода, а не два — потому что «не проверено» и «проверено и
    сошлось» смешивать нельзя:

    * ``mismatches`` — путь есть в readback и значение НЕ совпало. Настоящий провал;
    * ``unknown_keys`` — ключ не выжил в round-trip через схему, то есть его нет в
      контракте вовсе (``log_levl`` вместо ``log_level``, ``errors.lvl``). Сегодня
      такой ключ проглатывался молча;
    * ``unverifiable`` — запрос изменил путь, которого readback не отдаёт
      (``observability_effective`` показывает подмножество полей). Зачесть его в
      успех значило бы объявить проверенным то, что не проверялось.

    **Вердикт трёхзначный, а не булев** — ``confirmed`` | ``failed`` |
    ``unverifiable``. Первая редакция отдавала ``verified: true`` при
    ``checked: 0``, то есть «подтверждено» там, где не проверено ничего: запрос
    менял только пути, которых readback не отдаёт. Булево поле здесь врало бы в
    обе стороны — ``true`` читалось бы подтверждением, ``false`` провалом, а
    правда третья. Урок проекта («полуудача — отдельным полем, вердикт по одному
    маркеру врёт») применён буквально.

    Незнакомые ключи ловятся round-trip'ом через ту же схему, из которой считается
    раскладка, а не отдельной таблицей соответствий: вторая таблица разошлась бы
    с первой на первом же новом поле. По той же причине ожидаемое считается
    ``expand_observability`` — единственной точкой раскладки (якорь ADR-CRM-006), —
    а не своим переводом «ключ конфига → поле менеджера». Перевод здесь неочевиден:
    ``log_level`` действует как ``logger.default_level``, и своя копия этого знания
    была бы вторым местом, где оно живёт.
    """
    from ..configs.observability_config import ObservabilityConfig, expand_observability
    from ..configs.observability_layers import flatten_section

    section = requested if isinstance(requested, dict) else {}
    flat_request = flatten_section(section)

    # Неизвестные ключи = не выжившие в round-trip через схему. Ключ, заданный
    # значением по умолчанию, выживает — поэтому «совпал с дефолтом» и «опечатка»
    # не путаются.
    try:
        survived = ObservabilityConfig.model_validate(section).model_dump(exclude_unset=True)
    except Exception:  # noqa: BLE001 — невалидную секцию судит применение, не вердикт
        survived = section
    unknown = sorted(set(flat_request) - set(flatten_section(survived)))

    baseline = flatten_section(expand_observability({}))
    expected = flatten_section(expand_observability(survived))
    flat_effective = flatten_section(effective if isinstance(effective, dict) else {})

    mismatches: list = []
    unverifiable: list = []
    checked = 0
    for path, want in expected.items():
        if baseline.get(path) == want:
            continue  # запрос этот путь не менял
        if path not in flat_effective:
            unverifiable.append(path)
            continue
        checked += 1
        got = flat_effective[path]
        if got != want:
            mismatches.append({"key": path, "expected": want, "actual": got})

    if mismatches or unknown:
        verdict = "failed"
    elif checked:
        verdict = "confirmed"
    else:
        # Ни расхождений, ни проверенных путей: подтверждать нечем. Сюда попадает
        # и запрос, не изменивший ничего вовсе, и запрос, изменивший только
        # непроверяемое readback'ом.
        verdict = "unverifiable"
    return {
        "verdict": verdict,
        "checked": checked,
        "mismatches": mismatches,
        "unknown_keys": unknown,
        "unverifiable": sorted(unverifiable),
    }


def _idle_sinks(manager: Any) -> Dict[str, Any]:
    """Ф2.6: приёмники, объявленные и не принявшие ничего.

    Отдаётся у ВСЕХ трёх плоскостей, а не только у логгера: детектор живёт в общей
    базе менеджеров, и молчащий приёмник ошибок — такой же симптом, как молчащий
    файл логов. Ключ присутствует всегда, пустой список — законный ответ «все
    приёмники что-то приняли».
    """
    fn = getattr(manager, "idle_sinks", None)
    return {"idle_sinks": fn()} if callable(fn) else {}


def _sink_readback(manager: Any) -> Dict[str, Any]:
    """Активные приёмники плоскости и то, что снял оператор.

    Task 5.10 (живая находка прогона): до неё эти два поля отдавались ТОЛЬКО
    логгером, и на плоскостях ошибок и статистики оператор не мог ни увидеть
    состав приёмников, ни отличить «я это выключил» от «канал не поднялся» —
    а это разные диагнозы с разными действиями. Живьём выглядело так: команда
    ответила `session_key: errors.channels.errors_file.enabled`, а readback
    показывал `sinks_disabled_by_operator: []`, то есть противоречил ей.

    Симметрия здесь не косметика: сама задача про то, что ответ одной команды
    не должен зависеть от плоскости, к которой её адресовали.
    """
    out: Dict[str, Any] = {}
    registry = getattr(manager, "_channel_registry", None)
    names = getattr(registry, "names", None)
    if callable(names):
        try:
            out["channels_active"] = sorted(names())
        except Exception:  # noqa: BLE001 — readback best-effort
            pass
    disabled = getattr(manager, "_sinks_disabled_by_operator", None)
    if isinstance(disabled, set):
        out["sinks_disabled_by_operator"] = sorted(disabled)
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
    # ``messages_batched`` здесь БЫЛ и удалён (Ф7.х, хвост Ф7.4): счётчика больше
    # нет ни у одного менеджера — батчинг записи снят целиком. Довод тот же, что
    # у снятого ``flush_failed`` абзацем ниже: заведомо недостижимое имя в списке,
    # объявленном «точкой забывания», подтачивает доверие ко всему списку.
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
    # Ф4.1 — цепочка процессоров. Поглощение записи процессором ЗАКОННО
    # (ради него заводится сэмплинг Ф7.1), но невидимым быть не вправе:
    # иначе «уровень включён, а записей нет» неотличимо от сломанного
    # маршрута. Отказ процессора — рядом и отдельно: «поглотил намеренно» и
    # «сломался» лечатся разным.
    "records_dropped_by_processor",
    "processor_failures",
    # Ф4.5 — редакция секретов. «Ни одного секрета не было» и «редактор не
    # звался вовсе» дают одинаковые логи, поэтому факт работы обязан быть
    # спрашиваемым у живого процесса. Отказ рядом и отдельно: он означает
    # запись с маркером вместо содержимого (fail-closed) — потерю текста,
    # молчать о которой нельзя.
    "records_redacted",
    "redaction_failures",
    # Ф7.1 — дроссель повторяющихся записей. Подавление законно, но «уровень
    # включён, а записей нет» обязано иметь ответ у живого процесса. Ключи
    # ключей отдельно: насыщенная карта означает «дроссель включён и НЕ
    # работает», и по одному лишь числу подавленных это неотличимо от тишины.
    "records_sampled_out",
    "sampler_keys_tracked",
    "sampler_keys_saturated",
    # Ф7.х — карта ключей дышит: подметённые протухшие. Пара к предыдущему ключу:
    # растёт expired — потолок работает как задумано; стоит expired при растущем
    # saturated — карта забита горячими ключами, дроссель по повторяемости против
    # такого шторма бессилен по построению, лечится счётчиком вместо записи.
    "sampler_keys_expired",
    # Task 5.6 — ДОСТАВКА. Все счётчики выше считают потери, и «потерь ноль»
    # одинаково означает здоровую систему и систему, из которой ничего не
    # выходит. Без этих ключей «включён» неотличимо от «доставляет».
    #
    # Темпа среди них нет намеренно: наружу едут счётчик и момент снимка
    # (`observed_at`), частное берёт потребитель. Готовое число требовало бы одной
    # базы отсчёта на всех, и два потребителя (панель GUI + backend_ctl) портили
    # бы показания друг другу — см. OBSERVED_AT_KEY в channel_routing_manager.
    "channel_written_records",
    "channel_written_by_channel",
    "observed_at",
    # Ф0.7 — чистка каталога логов: сколько удалено/сжато и сколько НЕ удалось.
    "retention_files_deleted",
    "retention_files_compressed",
    "retention_delete_failures",
    "retention_compress_failures",
    "retention_bytes_freed",
    # R2 → Ф7.2 — обратное давление стока: запись отброшена по пределу ожидания.
    "sink_writes_dropped",
    "sink_slow_writes",
    # Ф7.х B-2 — два пункта приёмки Ф7.2, невыполненные при закрытой задаче
    # (найдено сквозным ревью). ``sink_degraded`` отвечает на вопрос, которого
    # число потерь не покрывает: сток теряет СЕЙЧАС или перестал час назад.
    # Разбивка по имени отвечает на «чьи именно» — у трёх соседних классов
    # потерь она есть с Ф0.4, у лесенки не было.
    "sink_degraded",
    "sink_degraded_channels",
    "sink_writes_dropped_by_channel",
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

    Буфер плоскости отдаётся под ключом ``buffer`` — потребителю не должно быть
    нужно знать, какой менеджер он спрашивает.

    **Ф7.х (хвост Ф7.4):** здесь нормализовалось ещё и второе имя —
    ``batch_stats`` логгера. Буфера записи больше нет ни у логгера, ни у ошибок
    (``BatchBuffer`` снят вместе с батчингом), поэтому ключ убран: он мог
    подхватиться только у фальшивки в тесте, а в проде отвечал ``None`` и
    выглядел живой нормализацией. Буфер остался у статистики (окно агрегации) —
    его и читаем.
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
    buffer = raw.get("buffer")
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
    hub: Any = None,
    flush: bool = False,
) -> Dict[str, Any]:
    """Потери и глубина буферов трёх плоскостей — «сколько наблюдаемости не доехало».

    Отвечает на вопросы, которые до Ф0.3 нельзя было задать живому процессу
    снаружи вообще: ``get_stats()`` менеджеров не читал никто, кроме тестов.

      * ``buffer.pending`` растёт, ``buffer.dropped_by_channel`` непустой —
        сток тормозит и записи уже теряются, с именем канала-виновника;
      * ``errors_to_floor`` > 0 — ошибка не дошла ни до одного канала и легла
        в пол (``error_floor.path``); штатный маршрут ошибок сломан.

    ``flush`` — дожать буферы ПЕРЕД снимком, то есть сделать снимок КОГЕРЕНТНЫМ:
    «записано» включит всё, что уже эмитировано к этому моменту. Нужен ровно
    тому, кто судит по дельте ДВУХ снимков (Task 5.7).

    **Историческая справка (Ф7.4).** Нужда в ``flush`` родилась от батчинга:
    счётчик считал записи в момент записи, а пачка сдвигала его на такт сброса —
    один вызов ``introspect.observability`` на DEBUG стоил ~5.1 записи, и окно,
    открытое без ``flush``, наследовало записи самой команды. Батчинг снят,
    отставания этого рода больше нет; параметр оставлен, потому что он часть
    контракта команды и дожимает буферы плоскостей, у которых они ещё есть
    (статистика — окно агрегации).

    Кроме ``flush`` команда не мутирует ничего: только чтение живых менеджеров.
    """
    if flush:
        for manager in (logger, error, stats):
            flush_fn = getattr(manager, "flush", None)
            if callable(flush_fn):
                try:
                    flush_fn()
                except Exception:  # noqa: BLE001, S110 — диагностика не роняет команду
                    # Молча: отказ flush'а виден в самих счётчиках
                    # (`buffer.flush_failed` / `buffer.pending` едут этим же
                    # ответом), и дублировать его исключением значило бы
                    # потерять весь снимок из-за одной несжатой плоскости.
                    pass
    out: Dict[str, Any] = {}
    for name, manager in (("logger", logger), ("error", error), ("stats", stats)):
        section = _plane_counters(manager)
        if section is not None:
            out[name] = section
    # Ф7.2, припаркованный долг ревью 2026-08-03: hub считал потери
    # (`ObservabilityHub.dropped` по kind) и наружу их не отдавал никто —
    # ровно тот класс, что весь план вычищает: потеря есть, спросить о ней
    # у живого процесса нельзя.
    dropped = getattr(hub, "dropped", None)
    if isinstance(dropped, dict):
        out["hub"] = {"dropped": dict(dropped), "dropped_total": sum(int(v or 0) for v in dropped.values())}
    return out


def apply_observability_layers(
    layers: "ObservabilityLayers",
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    log_dir: Optional[str] = None,
    log_info: Optional[Callable[[str], None]] = None,
    heartbeat: Any = None,
    telemetry_boot: Optional[Dict[str, Any]] = None,
    store_throttle: Any = None,
    boot_rules: Optional[Dict[str, Any]] = None,
    origin: str,
    record_rebuild: bool = True,
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

    Task 5.10.f — **четвёртая плоскость в том же стеке.** ``heartbeat`` /
    ``heartbeat`` / ``telemetry_boot`` необязательны ровно так же, как
    менеджеры: нет получателя — плоскость пропускается. ``telemetry_boot`` — это
    L0 телеметрии (секция, с которой процесс поднялся); слои говорят ПОВЕРХ неё,
    и именно поэтому истечение срока у ключа ``telemetry.*`` возвращает гейт к
    загрузочному состоянию, а не оставляет его в последней правке.

    Task 5.9 — ``origin`` обязателен: пересборка есть момент, когда правка
    ВСТУПАЕТ В СИЛУ, и запись о ней без указания механизма ответила бы «конфиг
    поменялся сам». Провал пересборки пишется тем же путём с ``ok=false``:
    молчащий отказ здесь — задокументированный на этом проекте класс «следствие
    без причины».

    ``record_rebuild=False`` — ровно ОДИН законный вызывающий: такт подметальщика
    (:mod:`.observability_ttl`). Он пишет за весь такт одну запись ``expire``,
    которая уже несёт исход пересборки (``ok`` / ``error`` / ``log_level``), и
    вторая, generic, дублировала бы её. Замечание 4 ревью 5.9: на залипшем отказе
    такт повторяется каждые ~5с, и две записи вместо одной выедали бы кольцо
    вдвое быстрее — вытесняя как раз то, что нужно в инциденте («кто поставил
    ключ»). Флаг назван узко и намеренно: «не пиши в аудит вообще» здесь нет.

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
    try:
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
                heartbeat=heartbeat,
                telemetry_boot=telemetry_boot,
                store_throttle=store_throttle,
                boot_rules=boot_rules,
            )
            # Task 5.8: пересборка удалась — долг подметальщика погашен, КЕМ БЫ она ни
            # была вызвана. Иначе после неудачного возврата и последующего успешного
            # `config.reload` такт делал бы лишнюю «повторную» пересборку и клал в
            # кольцо аудита запись о возврате, которого не было (advisory ревью 5.8).
            layers.rebuild_pending = False
            # Замечание 3 ревью 5.9, воспроизведено: содержимое записи снимается
            # ПОД ЛОКОМ. Считанное после его снятия захватывало бы правку
            # писателя, выигравшего гонку в этом окне, — и запись утверждала бы,
            # что пересборка применила ключ, которого менеджеры не видели.
            # Наружу выносится только сама запись: она делает файловое I/O.
            snapshot_keys = layers.session_keys()
            snapshot_level = applied.get("logger", {}).get("default_level")
    except BaseException as exc:
        # Запись, а не подавление: исключение уходит вызывающему ровно как раньше
        # (подметальщик на нём ставит `rebuild_pending`). Аудит здесь лишь
        # перестаёт быть слепым к самому опасному исходу — «правка принята, а
        # конфиг остался прежним». Пишем УЖЕ ВНЕ лока: запись кладёт строку в
        # журнал, и держать на время файлового I/O лок, которого ждут все четыре
        # писателя, незачем — тем более на пути отказа.
        if record_rebuild:
            layers.audit.record(ACTION_REBUILD, origin=origin, ok=False, error=repr(exc))
        raise
    if record_rebuild:
        layers.audit.record(ACTION_REBUILD, origin=origin, log_level=snapshot_level, keys=snapshot_keys)
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
    heartbeat: Any = None,
    telemetry_boot: Optional[Dict[str, Any]] = None,
    store_throttle: Any = None,
    boot_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Тело пересборки (вызывается под локом стека — см. вызывающего)."""
    resolved = layers.resolve()
    # Task 5.10.f: телеметрия живёт в ТОМ ЖЕ плоском namespace под своим
    # префиксом, но раскладке в manager-конфиги не подлежит — у неё свои
    # получатели. Снимаем её до `expand_observability`, иначе `ObservabilityConfig`
    # отверг бы незнакомый ключ, и слой оказался бы невыразим.
    telemetry_layered = resolved.pop(TELEMETRY_KEY, None)
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

    telemetry_applied = _apply_telemetry_from_layers(
        telemetry_layered,
        layers=layers,
        boot=telemetry_boot,
        heartbeat=heartbeat,
        store_throttle=store_throttle,
        boot_rules=boot_rules,
        log_info=log_info,
    )
    if telemetry_applied is not None:
        expanded[TELEMETRY_KEY] = telemetry_applied

    if log_info is not None:
        held = ", ".join(layers.session_keys()) or "—"
        log_info(
            f"[observability] пересобран из слоёв "
            f"(log_level={expanded['logger'].get('default_level')}; держится сессией: {held})"
        )
    return expanded


def telemetry_targets(svc: Any) -> Dict[str, Any]:
    """Получатель publish-плоскости и её L0 — одним резолвом для ВСЕХ пересборок.

    Task 5.10.f. Тремя разными местами (``config.reload``, ``telemetry.reconfigure``,
    такт подметальщика) достаётся одно и то же; разойдись они хоть в одном
    аргументе — и возврат по сроку применялся бы не туда, куда правка.

    ``telemetry_boot`` читается ТЕМ ЖЕ способом, что и на старте
    (``ProcessHeartbeat._build_telemetry_gate`` → ``get_config("telemetry")``):
    L0 обязан совпадать с тем, из чего собран загрузочный гейт, иначе «вернуть
    как было» вернёт не то, что было.

    Центрального троттла здесь нет намеренно — см. ``TELEMETRY_LAYERED_SUBSECTION``.
    """
    from .telemetry_reload import resolve_store_throttle

    get_config = getattr(svc, "get_config", None)
    raw = get_config(TELEMETRY_KEY, None) if callable(get_config) else None
    rules = get_config("state_throttle_rules", None) if callable(get_config) else None
    return {
        "heartbeat": getattr(svc, "_heartbeat", None),
        "telemetry_boot": dict(raw) if isinstance(raw, dict) else None,
        # Task 5.10.g: получатель дельты троттла и её L0. Загрузочные правила
        # лежат ОТДЕЛЬНЫМ ключом (`state_throttle_rules`) — тем же, что читает
        # boot; без него истечение срока дельты снесло бы вообще все правила
        # вместо возврата к загрузочным.
        "store_throttle": resolve_store_throttle(svc),
        "boot_rules": dict(rules) if isinstance(rules, dict) else None,
    }


def apply_telemetry_layers(
    layers: "ObservabilityLayers",
    *,
    heartbeat: Any = None,
    telemetry_boot: Optional[Dict[str, Any]] = None,
    store_throttle: Any = None,
    boot_rules: Optional[Dict[str, Any]] = None,
    log_info: Optional[Callable[[str], None]] = None,
    origin: str,
) -> Optional[Dict[str, Any]]:
    """Пересобрать ТОЛЬКО плоскость телеметрии из слоёв (Task 5.10.f).

    Отдельный вход, а не «позвать полную пересборку»: ``reconfigure`` менеджеров
    закрывает и заново открывает файлы логов, и телеметрийная правка,
    приходящая пачками, перетряхивала бы файловые приёмники ни за чем. Тело
    применения — то же самое, что внутри :func:`apply_observability_layers`,
    поэтому двух путей применения телеметрии не заводится.
    """
    try:
        with layers.lock:
            applied = _apply_telemetry_from_layers(
                layers.resolve().get(TELEMETRY_KEY),
                layers=layers,
                boot=telemetry_boot,
                heartbeat=heartbeat,
                store_throttle=store_throttle,
                boot_rules=boot_rules,
                log_info=log_info,
            )
    except BaseException as exc:
        layers.audit.record(ACTION_REBUILD, origin=origin, ok=False, error=repr(exc), plane=TELEMETRY_KEY)
        raise
    # Task 5.9: плоскость названа в записи. Без неё «пересобрали» у телеметрии и
    # «пересобрали» у логов выглядели бы одинаково, а трогают они разное — и
    # оператор, ищущий, отчего перетряхнуло файлы логов, шёл бы не туда.
    layers.audit.record(ACTION_REBUILD, origin=origin, plane=TELEMETRY_KEY, applied=applied)
    return applied


def _apply_telemetry_from_layers(
    layered: Any,
    *,
    layers: "ObservabilityLayers",
    boot: Optional[Dict[str, Any]],
    heartbeat: Any,
    store_throttle: Any,
    boot_rules: Optional[Dict[str, Any]],
    log_info: Optional[Callable[[str], None]],
) -> Optional[Dict[str, Any]]:
    """Собрать секцию ``telemetry`` из L0+слоёв и применить к её получателям.

    Task 5.10.f. Возвращает применённое или ``None``, если применять нечего.

    Почему ``mode="replace"``, а не ``"merge"``: слои УЖЕ слиты — это и есть
    результат, а не дельта. Merge поверх живого гейта вернул бы ровно ту
    неспособность, ради устранения которой 5.12 развернула семантику: удаление
    ключа из слоя не выразимо дельтой, и истёкшая правка телеметрии осталась бы
    в гейте навсегда.

    **Названная цена (семантика ``telemetry.reconfigure mode="replace"``
    изменилась).** Раньше ``replace`` строил гейт из присланной секции ОДНОЙ, в
    обход загрузочной. Теперь присланное — слой поверх L0, и метрики, которых
    оператор не упомянул, продолжают жить по загрузочной настройке. Взамен
    появилось то, чего не было: правка переживает ``config.reload`` и
    возвращается по сроку. Заменить L0 целиком по-прежнему можно — правкой
    файла, то есть слоем, который для этого и предназначен.

    **Различение «ключа нет» ↔ «явный ``publish: null``» (A-A1-1).** ``.get(sub)``
    отдавал ``None`` в обоих случаях, и слоистый путь расходился с прямым: прямой
    ``telemetry.reconfigure`` при ``publish=None`` честно шлёт ``(None,'replace')``
    (снимает гейт), а слоистый делал ``deep_merge(boot, None) == boot`` — то есть
    пересобирал к загрузочному ВМЕСТО выключения. Теперь владение и значение
    берутся по ПРИСУТСТВИЮ ключа (``sub in layered``), а не по «значение не None»:

    * ключ ЕСТЬ → слои владеют плоскостью, что бы в нём ни лежало (правило Г3
      «ключ есть → владею»). ``publish: null`` — это явное «гейта нет», и он
      уезжает получателю как ``None`` (снятие гейта), совпадая с прямым путём;
      непустой словарь ложится слоем поверх ``boot``;
    * ключа НЕТ, но плоскость уже во владении (липкий ``telemetry_owned`` после
      прошлой правки или её истечения) → возврат к загрузочному ``boot``. Именно
      это отличает «оператор снял ключ» (вернись к boot) от «оператор выключил
      явным null» (сними гейт) — два разных исхода, которые ``.get`` сливал.
    """
    applied: Dict[str, Any] = {}
    throttle_applied = _apply_throttle_from_layers(
        layered,
        layers=layers,
        boot_rules=boot_rules,
        store_throttle=store_throttle,
        log_info=log_info,
    )
    if throttle_applied is not None:
        applied.update(throttle_applied)

    if heartbeat is None:
        return applied or None
    sub = TELEMETRY_LAYERED_SUBSECTION
    # Владение — по ПРИСУТСТВИЮ ключа, а не по «значение не None»: явный
    # `publish: null` присутствует и означает «выключить», а не «слои молчат».
    has_sub = isinstance(layered, dict) and sub in layered
    layered_sub = layered.get(sub) if isinstance(layered, dict) else None
    if has_sub:
        layers.telemetry_owned = True
    if not layers.telemetry_owned:
        # Слои о publish-плоскости не сказали ни разу — не наша, не трогаем.
        # Иначе пересборка наблюдаемости клобберила бы гейт, собранный на старте
        # самим heartbeat'ом, и делала бы это на каждый reload.
        return applied or None

    boot_sub = (boot or {}).get(sub)
    if has_sub:
        # Слои владеют publish. `null` = явное «гейта нет» → уедет как None
        # (снятие), НЕПУСТОЙ словарь — слоем поверх загрузочного boot.
        #
        # Корзина 2.1, шов, не названный ревью: слово «непустой» тут появилось не
        # ради стиля. `deep_merge(boot_sub, {})` возвращал boot — то есть
        # `publish: {}` («считать нечего, и это моё решение») читалось как
        # «слои промолчали», и загрузочный набор метрик оживал. Ключ ЕСТЬ —
        # значит слои владеют, что бы в нём ни лежало: правило Г3, ровно то же,
        # которым эта функция уже различает `null` и отсутствие (A-A1-1 выше).
        # Мерж непустого — `layer_merge`: вложенное `{"metrics": {}}` обязано
        # владеть по той же причине, что и верхнее.
        if layered_sub is None:
            merged_sub: Any = None
        elif isinstance(boot_sub, dict) and isinstance(layered_sub, dict) and layered_sub:
            merged_sub = layer_merge(boot_sub, layered_sub, prefix=f"{TELEMETRY_KEY}.{sub}.")
        else:
            merged_sub = layered_sub
    else:
        # Ключа в слоях нет, но плоскость owned (истекла правка / липкий флаг):
        # вернуть к загрузочному. ``None`` boot тоже законен — «гейта не было».
        merged_sub = boot_sub
    section: Dict[str, Any] = {sub: merged_sub}

    from .telemetry_reload import apply_telemetry_reconfigure

    applied.update(
        apply_telemetry_reconfigure(
            section,
            mode="replace",
            heartbeat=heartbeat,
            # Троттл применён выше, СВОИМ путём: он входит в слои одним
            # непрозрачным листом, а не под-секцией (OPAQUE_LAYER_PATHS).
            store_throttle=None,
            log_info=log_info,
        )
    )
    return applied


def _apply_throttle_from_layers(
    layered: Any,
    *,
    layers: "ObservabilityLayers",
    boot_rules: Optional[Dict[str, Any]],
    store_throttle: Any,
    log_info: Optional[Callable[[str], None]],
) -> Optional[Dict[str, Any]]:
    """Применить операторскую дельту троттла из слоя поверх загрузочных правил.

    Task 5.10.g. Дельта живёт в L3 ОДНИМ листом ``telemetry.throttle`` — почему
    именно так, объяснено у :data:`OPAQUE_LAYER_PATHS` (per-rule ключ сломан по
    построению: точки внутри паттерна режутся как разделители пути).

    Собирается из источников, а не накладывается на живое: ``boot_rules``
    (та же ``state_throttle_rules``, что и на старте) + дельта, где ``None`` у
    паттерна означает «правила нет» — родной маркер ``THROTTLE_REMOVE``
    контракта задач 1.1/1.2, не тронутый ни строкой. Истечение срока снимает
    лист целиком → остаются загрузочные правила, что совпадает с семантикой
    задачи 2.1 («пустая секция → boot-дефолты») без единого исключения.

    **Асимметрия с ``publish`` — названная, а не случайная (корзина 2.2).**
    Независимое ревью заметило, что после распространения правила Г3 два соседних
    поля одной секции читают ``{}`` по-разному: ``publish: {}`` — владение (метрики
    boot сняты), ``throttle: {}`` — загрузочные правила остаются. Причина в том,
    что ЗНАЧЕНИЯ у них разной природы: у ``publish`` в слое лежит СЕКЦИЯ (полное
    описание плоскости), у ``throttle`` — ДЕЛЬТА со своим маркером снятия. Пустая
    секция и пустая дельта обязаны значить разное: первая — «плоскость пуста»,
    вторая — «я ничего не меняю». Сделать ``{}`` владением и здесь означало бы
    сломать семантику срока: истёкшая дельта возвращает boot-правила, а истёкшее
    владение пустотой возвращало бы... тоже boot — то есть срок перестал бы что-то
    значить, зато «снять всё» стало бы невыразимо иначе как перечислением.

    **Названная цена:** сказать «правил троттла нет вовсе» одной командой нельзя —
    только снять каждое своим ``THROTTLE_REMOVE``. Загрузочные правила защищают
    стор от шторма, и оптовое «снять все» пока не запрошено ни одним сценарием;
    появится — это отдельное решение, а не побочный смысл пустого словаря.
    """
    delta = layered.get("throttle") if isinstance(layered, dict) else None
    if isinstance(delta, dict):
        layers.throttle_owned = True
    if not layers.throttle_owned:
        # Слои дельты не держали ни разу — троттлом владеет файл и его watcher.
        return None
    if store_throttle is None:
        # Получателя нет (обычный процесс, а не оркестратор) — и это ОТВЕТ, а не
        # молчание: оператор, не увидевший поля, решил бы, что правило применено.
        return {"throttle": False}

    effective = dict(boot_rules or {})
    for pattern, value in (delta or {}).items():
        if value is None:  # THROTTLE_REMOVE: правило снято дельтой
            effective.pop(str(pattern), None)
        else:
            effective[str(pattern)] = value
    try:
        store_throttle.set_rules(effective)
    except Exception as exc:  # noqa: BLE001 — отчёт вызывающему, не падение пересборки
        if log_info is not None:
            log_info(f"[observability] троттл не применён из слоёв: {exc!r}")
        return {"throttle": False}
    if log_info is not None:
        log_info(f"[observability] троттл собран из слоёв: правил {len(effective)}")
    return {"throttle": True}


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
        # Task 5.9: замена слоя идёт МЕТОДОМ, а не присваиванием поля — правка
        # файла такая же смена наблюдаемости, как команда, и до этой задачи она
        # не оставляла следа вовсе. Присваиванием перехватить её нечем.
        origin = f"watcher:{layer}"
        if layer == LAYER_RECIPE:
            stack.replace_layer(LAYER_RECIPE, resolve_recipe_section(section, process_name), origin=origin)
        else:
            stack.replace_layer(LAYER_APP, section if isinstance(section, dict) else {}, origin=origin)
        apply_observability_layers(
            stack,
            logger=logger,
            error=error,
            stats=stats,
            log_info=log_info,
            origin=origin,
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
