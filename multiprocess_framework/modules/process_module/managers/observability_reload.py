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
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ...config_module.core.config import Config
from ...logger_module.core.process_hooks import HOOK_COUNTER_KEYS
from ..configs.observability_audit import ACTION_REBUILD
from ..configs.observability_config import ObservabilityConfig, expand_observability
from ..configs.observability_layers import (
    LAYER_APP,
    LAYER_RECIPE,
    ORCHESTRATOR_PROCESS_NAME,
    TELEMETRY_KEY,
    TELEMETRY_LAYERED_SUBSECTION,
    flatten_section,
    layer_merge,
)
from ..configs.observation_policy import OBSERVATION_SECTION_KEY, normalized_observation_section
from .observability_flight import FLIGHT_SECTION_KEY, apply_flight_recorder
from .observability_wiring import (
    EVENTS_SECTION_KEY,
    VOICES_SECTION_KEY,
    apply_event_selector,
    apply_voices_policy,
)

#: Под-секции ``observability``, у которых путь КОНФИГА совпадает с путём
#: READBACK'а один в один — те, что идут мимо ``expand_observability`` (у них
#: нет менеджера, в поля которого их надо было бы переводить).
#:
#: **Задача 2.9 (M1, добор ревью Ф2): этот перечень БОЛЬШЕ НЕ участвует в
#: построении ``expected`` внутри ``observability_verified``.** До неё дыра
#: («секция мимо экспандера — впиши её сюда руками») закрывалась ТРИЖДЫ:
#: ``events`` (блокер Б2 ревью Ф4), ``flight`` (Ф5), ``voices`` (Task 1.4) — и
#: на четвёртой (``heartbeat_interval_sec``, скаляр, а не под-секция — этот
#: перечень его никогда и не покрывал) она открылась снова, потому что
#: ручной список сам по себе не гарантирует полноты. ``observability_verified``
#: теперь решает «потребляет ли эту секцию экспандер» ЗОНДОМ у самого
#: ``expand_observability`` (см. докстринг функции) — и добавляет в ``expected``
#: КАЖДЫЙ непотреблённый лист любой секции, а не только четырёх перечисленных
#: здесь. Дыра этого класса больше не открывается «на пятой секции»: у новой
#: секции схемы просто нет способа остаться неклассифицированной.
#:
#: Константа осталась ради ДРУГОГО стража — не про полноту вердикта, а про
#: осознанную классификацию новой под-секции схемы:
#: ``test_voices_policy_road_guards.py::TestIdentitySectionsCoverEveryUnexpandedSubsection``
#: сверяет её (плюс ``EXPANDED``/``EXEMPT`` того теста) с полным списком
#: SchemaBase-под-секций ``ObservabilityConfig`` и краснеет, если новая секция
#: не отнесена ни к одной корзине сознательно. Это второй, самостоятельный
#: класс дефекта («никто не подумал, куда её отнести»), и генерический зонд его
#: не заменяет: зонд гарантирует, что вердикт не промолчит про лист СЕГОДНЯ,
#: а этот сторож — что автор следующей под-секции осознанно записал, почему
#: она обходит экспандер (или почему нет).
#:
#: ``observation`` в перечень НЕ входит: у её ключей своя нормализация обоих
#: берегов (``normalized_observation_section``), и тождественное сравнение по
#: строкам ей не годится буквально (см. ветку ниже по файлу) — но генерический
#: зонд про неё тоже верно говорит «не потреблена экспандером», поэтому её
#: сырые пути и без этого перечня попадают в ``expected`` раньше нормализации
#: (нормализация переписывает их поверх, см. ниже).
IDENTITY_SECTION_KEYS = (EVENTS_SECTION_KEY, FLIGHT_SECTION_KEY, VOICES_SECTION_KEY, "history")

#: Ф2 (задача 2.3, M9). СКАЛЯР схемы (``float``), не под-секция — тем же родом,
#: что ``session_ttl_sec`` (``observability_layers.SESSION_TTL_KEY``): у него нет
#: своего ``SchemaBase``-класса, поэтому страж ``test_identity_sections_...``
#: (он перебирает ТОЛЬКО поля с аннотацией-подклассом ``SchemaBase``) его не
#: видит и не обязан — ``IDENTITY_SECTION_KEYS`` выше про НЕГО, не про это имя.
HEARTBEAT_INTERVAL_KEY = "heartbeat_interval_sec"

if TYPE_CHECKING:
    from ...config_module.tools.watcher import ConfigFileWatcher
    from ..configs.observability_layers import ObservabilityLayers


def resolve_base_log_dir(explicit: Optional[str] = None) -> str:
    """Каталог логов как МАШИННЫЙ контекст пересборки (Task 5.12).

    Тот же резолв, что на boot (``ProcessLaunchConfig._resolve_log_dir``): явный
    аргумент → ``MULTIPROCESS_LOG_DIR`` → ``INSPECTOR_LOG_DIR`` →
    :func:`~...logger_module.core.log_paths.default_log_base_directory`.

    **Последним рубежом стоит общая функция, а не строка ``"logs"``** (ревью
    Task 1.2, F4). Строка тут пережила задачу 3.3, которая сняла её у boot'а, и
    расхождение было ровно то, от которого 3.3 и лечила: относительная ``"logs"``
    резолвится от cwd запускающего, то есть при молчащем окружении пересборка
    уводила логи в дерево репозитория, тогда как boot тех же менеджеров клал их в
    системный temp. Один запуск — два дерева, и оба «правильные» с точки зрения
    своей половины кода. Утверждение в docstring («тот же резолв, что на boot»)
    при этом было ложным с момента 3.3 и молчало об этом.

    Живой конфиг логгера здесь СОЗНАТЕЛЬНО не читается. Он выглядит соблазнительно
    («там же уже лежит резолвнутый путь»), но тогда удаление ``log_directory`` из
    слоя перестало бы работать: пересборка подхватывала бы прежнее значение из
    самой себя, и ровно у одного ключа наследование замолчало бы навсегда.
    """
    if explicit:
        return str(explicit)
    env_dir = os.environ.get("MULTIPROCESS_LOG_DIR") or os.environ.get("INSPECTOR_LOG_DIR")
    if env_dir:
        return env_dir
    from ...logger_module.core.log_paths import default_log_base_directory

    return str(default_log_base_directory())


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


def _voice_repurposed_stats_enabled(resolved: Any) -> None:
    """Голос ADR-PM-046 (смена смысла ``stats.enabled``) — на стадии «применяю».

    Task 4.11 (вердикт CTO 2026-09-03, корень m1): голос переехал сюда ИЗ
    валидатора схемы
    (``ObservabilityStatsConfig._complain_about_repurposed_enabled`` — полная
    история диагноза в его докстринге, включая замеры «6 срабатываний на один
    reload / 18 на три подряд»). Причина переезда — не косметика: валидатор
    зовётся ТРИЖДЫ на каждое действие оператора (стадии ``config.reload``:
    проверить → применить → сверить, решение B2/Task 5.7), и окно
    (Task 2.12) дросселировало РАЗБОРЫ, а не действия — «подавлено: N» после
    трёх ``config.reload`` называло 17 вместо 2.

    **Почему именно здесь, а не внутри** :func:`~..configs.observability_config.
    expand_observability` **и не внутри модели схемы.** Эта функция —
    ЕДИНСТВЕННАЯ, что зовётся РОВНО один раз на действие оператора:

    * boot — раз на создание менеджеров процесса
      (``ProcessManagers._managers_config_for_creation``, ``process_managers.py``);
    * ``config.reload`` / hot-reload watcher — раз на стадии «применить»
      (:func:`_rebuild_and_apply`, вызванная из :func:`apply_observability_layers`).

    Стадии «проверить» и «сверить» её НЕ зовут — они читают
    ``expand_observability`` НАПРЯМУЮ (:func:`observability_verified` и
    ``unknown_section_keys``), минуя эту обёртку. Голос внутри самой
    ``expand_observability`` прозвучал бы и на стадии «сверить» тоже — то есть
    дважды на один ``config.reload`` (применить + сверить), и число снова стало
    бы не тем, которое ждёт читатель.

    Args:
        resolved: СЫРОЙ словарь секции ``observability`` (тот же, что уйдёт в
            ``ObservabilityConfig.model_validate`` внутри ``expand_observability``
            следующей строкой) — не раскладка. Секция ``stats`` может отсутствовать
            вовсе (молчащий слой) — тогда функция молчит.

    Не падает и не голосит ни на каком постороннем входе (мусор вместо словаря,
    ``stats`` не словарь, ``enabled`` не булев ``False`` буквально) — вход сюда
    приходит из разрешённых слоёв, а не напрямую от оператора, но граница
    остаётся защищённой той же дисциплиной, что была у валидатора
    (``is False``, а не ``== False``: строка ``"false"``/``0``/``None`` — не тот
    же факт, что булев ``False``).
    """
    section = resolved.get("stats") if isinstance(resolved, dict) else None
    if not isinstance(section, dict) or section.get("enabled") is not False:
        return

    from ..._fallback import FallbackLogger
    from ...logger_module.core.windowed_voice import compose_voice_text, process_voices

    voiced, suppressed = process_voices().take("stats.enabled.repurposed", None)
    if voiced:
        FallbackLogger(__name__).warning(
            compose_voice_text(
                "stats.enabled: false — с Ф2 этот ключ означает ПЛОСКОСТЬ ЧИСЕЛ: "
                "метрики не будут собираться вовсе (окно пустое, все каналы "
                "статистики молчат). Прежний смысл «не писать снапшоты в журнал» "
                "переехал в stats.log_snapshots — если вы хотели именно его, "
                "замените на 'enabled: true, log_snapshots: false' (ADR-PM-046)",
                suppressed,
            )
        )


def compose_managers_payload(
    resolved: Dict[str, Any],
    *,
    log_dir: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Разрешённые слои → конфиги менеджеров. **Одна сборка на два адресата.**

    Адресаты:

    * пересборка на boot / reload (:func:`apply_observability_layers`);
    * **создание** менеджеров процесса
      (``ProcessManagers._managers_config_for_creation``).

    Почему шов, а не две ветки (Task 1.2, находка живого стенда). Создание
    собирало конфиг само — голым ``expand_observability(layers.resolve())``, без
    базы L0. А ``expand_observability`` эмитит **частичный** словарь каналов
    (только те, что назвал слой): в конфиге прототипа это ``gui_file`` /
    ``trace_file`` / ``busy_file``. Pydantic на ``LoggerManagerConfig`` заменяет
    словарь целиком — значит рождавшийся менеджер имел ТРИ канала, а ``scopes``
    у него оставались дефолтные и вели в ``system_file`` / ``messages_file``,
    которых в его реестре не было вовсе.

    Следствие измерено на стенде 2026-08-31: у ``ProcessManager`` **12 записей**
    (``{'system_file': 6, 'messages_file': 6}``) уходили в несуществующие каналы —
    ровно те, что эмитятся между ``logger.initialize()`` и пересборкой на boot
    (`LoggerManager initialized`, `RouterManager initialized`, `StatsManager`,
    порт наблюдений, `StatsAdapter.setup`). Пересборка секундой позже собирала
    конфиг ПРАВИЛЬНО (``merge_managers(base, expanded)``) — и потери
    прекращались. То есть дефекта «в логгере» не было: две дороги к одному
    конфигу расходились, и расходились молча.

    Поэтому сборка живёт здесь одна. Родиться и пересобраться теперь нельзя
    по-разному: разойтись будет нечему.

    Args:
        resolved: результат ``ObservabilityLayers.resolve()`` **без** ключа
            ``telemetry``: её снимает вызывающий, потому что у телеметрии свои
            получатели. Слова «иначе конфиг её отверг бы» здесь стояли и были
            неправдой (ревью Task 1.2, F5): ``ObservabilityConfig`` — обычная
            pydantic-модель с политикой ``extra`` по умолчанию (``ignore``), и
            незнакомый ключ она молча проглатывает. Замер 2026-08-31: с ключом
            ``telemetry`` сборка проходит и отдаёт те же четыре секции, а снятие
            ``pop`` на пути рождения не роняет ни одного теста из 3347. Ключ
            снимается ради ОДНОЙ формы аргумента у обоих вызывающих, а не ради
            защиты от отказа, которого нет.
        log_dir: каталог логов; ``None`` → машинный контекст
            (``MULTIPROCESS_LOG_DIR`` / ``INSPECTOR_LOG_DIR`` /
            ``default_log_base_directory()``).

    Returns:
        ``{"logger": …, "error": …, "stats": …, "command": …}`` — слои, наложенные
        на базу L0 машинного контекста.

    Task 4.11: эта функция — единственный адресат голоса ADR-PM-046
    (:func:`_voice_repurposed_stats_enabled`), потому что она — единственная,
    что зовётся РОВНО один раз на действие оператора (см. докстринг голоса).
    """
    from ...data_schema_module import deep_merge
    from ..configs.managers_config import merge_managers

    _voice_repurposed_stats_enabled(resolved)
    expanded = expand_observability(resolved)
    base = base_managers_payload(log_dir)

    explicit_level = resolved.get("log_level")
    logger_cfg = merge_managers(base.get("logger", {}), expanded["logger"])
    if explicit_level is not None:
        # Ф8.1: уровень кладётся ОДНИМ правилом корня и мержится с остальными
        # правилами, а не заменяет секцию. Прежде здесь стоял танец
        # «вынуть scopes до merge → положить профиль → вернуть правки поверх»:
        # он существовал ровно потому, что профиль переписывал набор целиком.
        # Причина снята — танец снят вместе с ней.
        #
        # ``deep_merge``, а не ``update``: у корня может быть и правило приёмников
        # (``loggers[""].channels``), и замена словаря целиком снесла бы его молча.
        logger_cfg["loggers"] = deep_merge(logger_cfg.get("loggers") or {}, _root_level_rule(explicit_level))
        logger_cfg["default_level"] = str(explicit_level).upper()
    expanded["logger"] = logger_cfg
    expanded["error"] = merge_managers(base.get("error", {}), expanded["error"])
    expanded["stats"] = merge_managers(base.get("stats", {}), expanded["stats"])
    return expanded


def _root_level_rule(level: str) -> Dict[str, Dict[str, Any]]:
    """Корневое правило уровня — **вид на общую функцию**, а не вторая реализация.

    Тело живёт в :func:`..configs.managers_config.root_level_rule`, там же, где
    стартовая сборка. Пока копий было две (Ф2.3a), одна и та же величина значила
    разное: старт опускал один скоуп из четырёх, пересборка — все четыре. Имя
    оставлено здесь ради вызывающего внутри модуля; знание — в одном месте.

    Ф8.1: функция сменила ФОРМУ результата — было «набор скоупов целиком», стало
    «одно правило корня». Это и есть суть задачи: пока уровень возвращал набор,
    его применение стирало всё, что оператор написал адреснее.

    Импорт ленивый: ``managers_config`` тянет конфиги всех менеджеров, а этот
    модуль грузится на пути пересборки, где лишний импорт на старте не нужен
    (та же причина, что у ``base_managers_payload``).
    """
    from ..configs.managers_config import root_level_rule

    return root_level_rule(level)


def observability_effective(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    event_selector: Any = None,
    flight_recorder: Any = None,
    heartbeat: Any = None,
    command: Any = None,
    session_ttl_sec: Optional[float] = None,
    history: Optional[Dict[str, Any]] = None,
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
            # Ф2 (задача 2.2, критерий 3): ретеншен/компрессия эмитятся
            # `expand_observability` (`logger.retention_*`/`compress_rotated`), но
            # readback их не отдавал вовсе — `config_reload_verified` отвечал
            # `unverifiable` на КАЖДУЮ правку этих четырёх ключей. Читаются у
            # ЖИВОГО конфига (`self.config` мутируется на `reconfigure`, ретеншен
            # сам читает `self.config` в момент свипа — расхождения между «что
            # сказали» и «что действует» здесь нет).
            "retention_days": getattr(lc, "retention_days", None),
            "retention_total_mb": getattr(lc, "retention_total_mb", None),
            "compress_rotated": getattr(lc, "compress_rotated", None),
            "retention_sweep_interval_sec": getattr(lc, "retention_sweep_interval_sec", None),
        }
        # Ф2 (2.2, критерий 3): адресные переопределения канала (Task 5.12,
        # `observability.channels.<имя>.enabled`) эмитятся экспандером, но
        # readback отдавал только ИМЕНА активных каналов (`channels_active`
        # ниже), не их `enabled` — правка `channels.messages_file.enabled`
        # была неподтверждаема. Путь конфига (`channels.<имя>.enabled`) и путь
        # readback'а обязаны совпадать — иначе тождественное сравнение вердикта
        # не найдёт свой путь.
        channels_cfg = getattr(lc, "channels", None)
        if isinstance(channels_cfg, dict):
            section["channels"] = {
                str(name): {"enabled": bool(getattr(ch, "enabled", True))} for name, ch in channels_cfg.items()
            }
        scopes = getattr(lc, "scopes", None)
        if isinstance(scopes, dict):
            # Ф8.1: у скоупа осталась одна ось — приёмники. Прежний readback отдавал
            # `enabled`/`min_level`, и после снятия полей они превратились бы в
            # вечные `True`/`None` — то есть пульт показывал бы ручки, которых нет.
            # Readback, расходящийся с гейтом, хуже отсутствующего: по нему решают.
            section["scopes"] = {
                str(k): {"channels": list(getattr(v, "channels", None) or ())} for k, v in scopes.items()
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
        # Ф2 (2.2, критерий 3): имя readback'а — ИМЯ СХЕМЫ (`logger_groups`), а не
        # внутреннее `groups`. Оператор правит секцию ключом `logger_groups`
        # (`ObservabilityConfig.logger_groups`), и старое имя ответа не совпадало
        # с путём запроса — тождественное сравнение вердикта не находило свой
        # путь, и `logger_groups.*` был `unverifiable` на любой правке.
        groups_fn = getattr(logger, "logger_groups", None)
        if callable(groups_fn):
            section["logger_groups"] = groups_fn()
        # Ф2.7: каталог объявленных источников — что МОЖЕТ писать, в отличие от
        # `sources` (что уже писало). Источник, у которого всё гасится порогом, в
        # журнале не появится вовсе, а разбирают обычно именно его.
        from ...observability_declarations import declared_sources

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
        # Задача 4.4: действующие параметры дросселя. Без них включение ручки на
        # живой системе давало вердикт ``unverifiable`` — «подано, подтвердить
        # нечем» (воспроизведено зондом ``probe_4_4_sampler_live``): ни один путь
        # ``logger.sampling_*`` в readback не приходил, а счётчик подавленных
        # отвечает на другой вопрос. Спрашиваем менеджер, а он — сам процессор:
        # запрошенное и действующее здесь расходятся законно (потолок обрезан
        # ошибками), и показать обязаны действующее.
        sampling_fn = getattr(logger, "sampling_readback", None)
        if callable(sampling_fn):
            section.update(sampling_fn())
        section.update(_sink_readback(logger))
        section.update(_idle_sinks(logger))
        out["logger"] = section
    if error is not None and getattr(error, "config", None) is not None:
        out["error"] = {
            "default_level": getattr(error.config, "default_level", None),
            # Ф2 (2.2, критерий 3): пара к `default_level` (тот уже подтверждался).
            # `include_stacktrace` живёт НЕ на `error.config` (он превращается в
            # `LoggerManagerConfig` внутри `ErrorManager` и теряет это поле) — а в
            # приватном `_include_stacktrace` самого менеджера
            # (`error_manager.py::_normalize_error_config`), тем же приёмом, что
            # `_sinks_disabled_by_operator` соседней строкой ниже.
            "include_stacktrace": getattr(error, "_include_stacktrace", None),
            **_sink_readback(error),
            **_idle_sinks(error),
        }
    # Ф2 (2.2, критерий 3): `observability_effective` не принимала получателя для
    # `command` вовсе — `commands.log_success` не мог попасть в readback ни при
    # каком запросе, и `config_reload_verified` отвечал `unverifiable` всегда.
    # Читаем ПРИВАТНЫЙ `_log_success_enabled`: у `CommandManager` нет отдельного
    # публичного геттера (только `set_log_success_enabled`), тем же приёмом, что
    # `include_stacktrace` строкой выше.
    if command is not None:
        log_success = getattr(command, "_log_success_enabled", None)
        if log_success is not None:
            out["command"] = {"log_success": bool(log_success)}
    # Ф2 (2.2, критерий 3): `session_ttl_sec` (Task 5.8) не раскладывается
    # `expand_observability` (получатель — бухгалтерия слоя L3, не менеджер), и
    # без этой ветки правка исчезала из вердикта ЦЕЛИКОМ — не `mismatch`, не
    # даже `unverifiable`. Читается ВЫЗЫВАЮЩИМ у `ObservabilityLayers.
    # effective_session_ttl()` и передаётся сюда готовым числом: эта функция не
    # держит ссылку на `layers`.
    if session_ttl_sec is not None:
        out["session_ttl_sec"] = float(session_ttl_sec)
    # Ф2 (2.2, критерий 1): `history` — четвёртая под-секция «своего механизма»
    # (см. IDENTITY_SECTION_KEYS). Политика приходит готовым словарём
    # (`resolve_history_policy(svc)`) — той же дорогой, что и `session_ttl_sec`
    # выше: эта функция читает менеджеров и живые объекты, а не сам процесс.
    if history is not None:
        out["history"] = dict(history)
    if stats is not None:
        # B1. Прежде ветка сторожилась `getattr(stats, "config", None) is not None`
        # и НЕ ИСПОЛНЯЛАСЬ НИ РАЗУ: `self.config` ставит `LoggerCore` (общий
        # предок логгера и ошибок), а `StatsManager` — наследник CRM напрямую, и
        # такого атрибута у него нет. Воспроизведено:
        # `observability_effective(stats=mgr)` → `{}`. Защита была недостижима,
        # то есть весь темп стат-плоскости жил в вердикте как `unverifiable`, а
        # приёмники и молчащие стоки третьей плоскости не выходили наружу вовсе.
        #
        # Спрашиваем плоскость, а не её конфиг: что действует — знает она сама
        # (темп берётся из живого окна агрегации, см. `observability_readback`).
        section: Dict[str, Any] = {}
        readback = getattr(stats, "observability_readback", None)
        if callable(readback):
            try:
                section.update(readback() or {})
            except Exception as exc:  # noqa: BLE001 — readback best-effort, но отказ назван
                section["error"] = repr(exc)
        section.update(_sink_readback(stats))
        section.update(_idle_sinks(stats))
        if section:
            out["stats"] = section
    if event_selector is not None:
        # Ф4 (4.1): отбор широких записей читается у ЖИВОГО селектора — той же
        # дорогой, что темп статистики выше. Без этой ветки ручка применялась, но
        # оставалась НЕПОДТВЕРЖДАЕМОЙ: `config_reload_verified` на всех восьми
        # процессах живого стенда отвечал `unverifiable` при `checked=0`, потому
        # что сравнивать запрошенное было не с чем (замер 2026-08-16). Ручка,
        # которую нельзя подтвердить, неотличима от неприменённой — тот же урок
        # 3.4, что и у предела строки снапшота.
        knobs = getattr(event_selector, "knobs", None)
        if isinstance(knobs, tuple) and len(knobs) == 2:
            out["events"] = {"first_n": int(knobs[0]), "every_mth": int(knobs[1])}
    if flight_recorder is not None:
        # Ф5 (5.1): ручки дампа — той же дорогой и по тому же уроку, что
        # `events` строкой выше. Ручка, которую нельзя подтвердить, неотличима
        # от неприменённой: `config_reload_verified` отвечал бы `unverifiable`
        # при `checked=0`, и правка «включить flight recorder» уходила бы к
        # оператору без вердикта.
        from .observability_flight import flight_effective  # локально: только этой ветке

        section = flight_effective(flight_recorder)
        if section is not None:
            out[FLIGHT_SECTION_KEY] = section
    if heartbeat is not None:
        # Ф4 плана «порт наблюдений» (4.1): действующая политика порта — той же
        # дорогой и по тому же уроку, что `events`/`flight`. Ручка, которую
        # нельзя подтвердить, неотличима от неприменённой: без этой ветки КАЖДАЯ
        # правка политики отвечала бы `unverifiable` при `checked=0`, то есть
        # «никто не смотрел», и AC задачи прямо требует сторожить эту ловушку.
        #
        # Читается ЖИВОЙ гейт (`current_observation_policy`), а не разрешённые
        # слои: пересчёт из того же источника показывал бы согласие всегда — в
        # том числе когда правка до гейта не доехала.
        policy_fn = getattr(heartbeat, "current_observation_policy", None)
        if callable(policy_fn):
            section = policy_fn()
            if section is not None:
                out[OBSERVATION_SECTION_KEY] = section
        # Task 2.9 (M1): ``heartbeat_interval_sec`` — скаляр верхнего уровня,
        # который `expand_observability` не раскладывает (получатель не
        # менеджер, а этот же живой `heartbeat`, см. докстринг поля схемы).
        # Без этой ветки правка была неотличима от отсутствия правки: вход
        # `observability_verified({"heartbeat_interval_sec": 1.0}, eff)` и
        # `observability_verified({}, eff)` давали ПОБАЙТНО одинаковый ответ
        # (воспроизведено ревью, M1) — путь никогда не появлялся ни в
        # `mismatches`, ни в `unverifiable`. Читаем ЖИВОЙ такт (`_interval`,
        # тот же приватный атрибут, что мутирует `apply_heartbeat_interval`),
        # а не пересчитываем из конфига — пересчёт показывал бы согласие
        # всегда, в том числе когда правка до такта не доехала. Публичного
        # геттера у `_interval` нет (только сеттер `apply_heartbeat_interval`),
        # тем же приёмом читаем приватный атрибут, что `include_stacktrace` и
        # `_log_success_enabled` парой экранов выше.
        interval = getattr(heartbeat, "_interval", None)
        if isinstance(interval, (int, float)) and not isinstance(interval, bool):
            out[HEARTBEAT_INTERVAL_KEY] = float(interval)
    # Ф1.4 (M17): окна голоса — БЕЗУСЛОВНО и без параметра, в отличие от соседей
    # выше. У этой секции нет живого объекта, который надо было бы прокинуть
    # сюда вызывающему: механизм процессный, политика существует в любом
    # процессе с первой секунды, и «получателя не передали» здесь не бывает.
    #
    # Читается ДЕЙСТВУЮЩАЯ политика механизма, а не разрешённые слои — по тому
    # же доводу, что у `events`/`flight`/`observation`: пересчёт из того же
    # источника показывал бы согласие всегда, в том числе когда правка до
    # механизма не доехала. Без этой ветки КАЖДАЯ правка `observability.voices`
    # отвечала бы `unverifiable` при `checked=0` — воспроизведено ревью Task 1.4
    # на живом стенде, и это ровно тот же блокер Б2, что уже был у `events`.
    #
    # Имена ключей — из СХЕМЫ (`ObservabilityVoicesConfig`), а не внутренние
    # имена политики: путь конфига обязан совпасть с путём readback'а один в
    # один, иначе тождественное сравнение ниже не найдёт свой путь.
    #
    # Task 2.7 (добор ревью Ф1): бывшие литералы MAX_TRACKED_KEYS/_STALE_WINDOWS
    # читаются той же безусловной дорогой, что и окно/эскалация выше — они
    # такая же ДЕЙСТВУЮЩАЯ политика механизма, а не параметр менеджера.
    from ...logger_module.core.windowed_voice import (
        default_window_sec,
        escalate_after_repeats,
        max_tracked_keys,
        stale_windows,
    )

    out[VOICES_SECTION_KEY] = {
        "default_window_sec": float(default_window_sec()),
        "escalate_after_repeats": int(escalate_after_repeats()),
        "max_tracked_keys": int(max_tracked_keys()),
        "stale_windows": int(stale_windows()),
    }
    return out


#: Часовой «значение отсутствует» для сравнения двух раскладок. ``None`` тут не
#: годится: ``None`` — законное ЗНАЧЕНИЕ листа раскладки, и «пути нет» слилось бы
#: с «путь есть и в нём null».
_ABSENT = object()

#: Пробное значение для строк. Канонический уровень, а не ``"<строка>__probe"``:
#: ровно пять строковых полей схемы (``log_level``, ``errors.level``,
#: ``stats.log_level``, ``sampling_max_level``, ``history.level``) провалидированы
#: ``canonical_level_or_raise``, и произвольная строка уронила бы зонд именно на
#: них — то есть на самых нагруженных ручках. Для НЕ-уровневых строк (пути к
#: файлам, имена стоков, dotted-путь фабрики) канонический уровень — такая же
#: годная «другая строка», как любая иная.
_PROBE_STR = "DEBUG"
_PROBE_STR_ALT = "ERROR"


@lru_cache(maxsize=8)
def _schema_leaf_paths(model_cls: type) -> frozenset:
    """Листовые пути схемы: спуск ТОЛЬКО в под-``SchemaBase``.

    ``Dict[str, Any]``-поле (``channels``, ``scopes``, ``loggers``,
    ``observation.rules``) — ЛИСТ, хотя его значение и словарь: за его формой
    стоит не под-схема, а свободная карта, и «управляет ли им экспандер» — вопрос
    про поле целиком, а не про каждое имя внутри. Та же рекурсия по
    ``issubclass(annotation, SchemaBase)``, что у стражей задач 2.2/2.9 — правило
    здесь атрибут схемы, а не решение автора, поэтому копии разойтись неоткуда.
    """
    from ...data_schema_module import SchemaBase

    out = set()
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, SchemaBase):
            out.update((name, *rest) for rest in _schema_leaf_paths(ann))
        else:
            out.add((name,))
    return frozenset(out)


def _requested_leaves(section: Any, leaf_paths: frozenset, prefix: tuple = ()) -> list:
    """Листья ЗАПРОСА как ``(кортеж-путь, значение)`` — с резом по границе СХЕМЫ.

    Кортеж, а не строка ``"a.b.c"``: имена внутри свободных карт содержат точки
    (``loggers``: ``some.prefix``), и восстановить вложенную форму из плоской
    строки однозначно нельзя. Зонду ниже нужна именно вложенная форма.

    Ключ, которого в схеме нет вовсе (секция не прошла валидацию, и ``survived``
    остался сырым), листом всё равно становится — его назовёт отдельный сверщик
    ``unknown_section_keys``, а молча потерять его здесь нельзя.
    """
    out: list = []
    if not isinstance(section, dict):
        return out
    for key, value in section.items():
        path = prefix + (str(key),)
        if path in leaf_paths or not isinstance(value, dict) or not value:
            out.append((path, value))
        else:
            out.extend(_requested_leaves(value, leaf_paths, path))
    return out


def _other_value(value: Any) -> Any:
    """Заведомо ДРУГОЕ значение того же рода — второй полюс зонда.

    Про пустоту отдельно, потому что оба случая неочевидны:

    * ``None`` — это «ключ есть, значения нет» (``log_directory``,
      ``documents.factory``). Другим полюсом берём строку: почти все
      ``Optional``-листья схемы строковые, а валидации на пути зонда нет вовсе
      (см. :func:`_with_leaf`), поэтому промах по типу максимум даст неотличимые
      раскладки — то есть безопасный исход «лист назван», а не тихий пропуск;
    * пустой словарь ``{}`` — это «слой владеет пустотой» (правило Г3), законное
      значение ``channels``/``scopes``. Другим полюсом берём непустую карту:
      экспандер смотрит такие поля через ``if cfg.channels:``, и разница
      «пусто/непусто» — ровно та ось, которой лист и управляет.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return _PROBE_STR_ALT if value == _PROBE_STR else _PROBE_STR
    if value is None:
        return _PROBE_STR
    if isinstance(value, (list, tuple)):
        return [] if value else [_PROBE_STR]
    if isinstance(value, dict):
        return {k: _other_value(v) for k, v in value.items()} if value else {_PROBE_STR: {}}
    return _PROBE_STR


def _with_leaf(cfg: Any, path: tuple, value: Any) -> Any:
    """Копия конфига с ОДНИМ подменённым листом — БЕЗ повторной валидации.

    ``model_copy(update=...)``, а не сборка словаря и ``model_validate``, и это
    не микро-оптимизация. У схемы есть валидаторы с ПОБОЧНЫМ ДЕЙСТВИЕМ: у
    ``stats`` стоит ``mode="before"``, который на ``enabled: false`` пишет
    оператору предупреждение «метрики не будут собираться вовсе» (ADR-PM-046).
    Зонд подставляет второй полюс сам — и через словарь он вписывал бы это
    предупреждение оператору, попросившему ровно ОБРАТНОЕ (``enabled: true``).
    Ложный голос о выключенной плоскости дороже отсутствующего: его читают.
    Воспроизведено: ``expand_observability({"stats": {"enabled": False}})`` даёт
    запись ``WARNING observability_config``, тот же вход через ``model_copy`` —
    ноль записей.

    Второе следствие того же выбора: мутант не может быть отвергнут схемой, то
    есть ветка «зонд ослеп из-за собственного пробного значения» закрыта не
    обработкой исключения, а построением. ``expand_observability`` при этом
    остаётся защищённым ``try`` у вызывающего — он читает поля сам и на
    бессмысленном значении может упасть.
    """
    if not path:
        return value
    head = path[0]
    if len(path) == 1:
        return cfg.model_copy(update={head: value})
    node = getattr(cfg, head, None)
    if not hasattr(node, "model_copy"):
        raise TypeError(f"{head}: не под-схема, спускаться некуда")
    return cfg.model_copy(update={head: _with_leaf(node, path[1:], value)})


def _controlled_layout_paths(path: tuple, value: Any, layout: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Пути раскладки, которыми управляет ОДИН лист запроса, со значениями из ``layout``.

    Возвращает:

    * ``None`` — раскладка от значения этого листа не зависит ВООБЩЕ (два полюса
      дали побайтно одно и то же). Экспандер лист не смотрит: его получатель —
      живой механизм процесса, а не конфиг менеджера. Вызывающий кладёт такой
      лист в ``expected`` под СХЕМНЫМ именем;
    * словарь — лист потреблён, и это его отпечаток: пути, которыми полюса
      расходятся, пересечённые с ПОЛНОЙ раскладкой запроса. Значение берётся из
      полной раскладки, а не из изолированной: ключи взаимодействуют
      (``loggers`` объявленных модулей мержится с ``loggers`` запроса), и
      изолированный полюс тут соврал бы значением;
    * ПУСТОЙ словарь — лист потреблён, но при ЭТОМ значении экспандер молчит и
      отдаёт решение дефолту ниже (``console: true`` не эмитит ``channels``
      вовсе — их подставит ``LoggerManagerConfig``). Проверять нечего: значения,
      которое надо сравнить с readback'ом, в раскладке просто нет.

    Пустой словарь в самой раскладке (``error: {}`` при ``errors.enabled:
    false``) в отпечаток НЕ берётся: это не поле, а погашенная СЕКЦИЯ раскладки,
    и readback такого пути не отдаёт никогда. Без этого реза вердикт называл бы
    оператору внутреннее имя ``error``, которого нет ни в его конфиге, ни в
    ответе (находка Д3 ревью).
    """
    base = ObservabilityConfig()
    try:
        here = flatten_section(expand_observability(_with_leaf(base, path, value)))
        there = flatten_section(expand_observability(_with_leaf(base, path, _other_value(value))))
    except Exception:  # noqa: BLE001 — зонд ослеп: назвать лист, а не проглотить
        return None
    if here == there:
        return None
    owned: Dict[str, Any] = {}
    # ПЕРЕСЕЧЕНИЕ, а не объединение: утверждаем разницу по ЗНАЧЕНИЮ, разницу по
    # НАЛИЧИЮ только называем. Объединение давало ложную тревогу, воспроизведённую
    # на живом стенде: `errors.enabled` переключением ГАСИТ секцию `error`
    # целиком, поэтому в отпечаток падали все её пути, а значения им доставались
    # из раскладки запроса, где несмежные соседи стоят на схемных дефолтах.
    # Оператор спрашивал про ОДИН ключ и получал `failed` с двумя чужими
    # (`error.default_level`, `error.include_stacktrace`), выставленными им же
    # секундой раньше. Ложная тревога дороже отсутствующей: на неё полагаются.
    # Побочно тот же рез снял и ПРЕДСУЩЕСТВУЮЩИЙ шум: `console: false` называл 56
    # путей стола каналов (на базе `f84817cf` — 47), теперь называет себя одного.
    # Цена названа вслух: `console`/`file` теряют единственную сверку
    # (`logger.channels.<имя>.enabled`) и становятся `unverifiable` — сверка
    # приезжала в комплекте с 56 ложными именами и риском ложного mismatch на
    # чужом стоке. Честное «не проверил» дешевле проверки, которую не отличить
    # от вранья; настоящую дорогу этим ключам даст реестр описателей (Task 4.9).
    for probe_path in set(here) & set(there):
        if here.get(probe_path, _ABSENT) == there.get(probe_path, _ABSENT):
            continue
        got = layout.get(probe_path, _ABSENT)
        if got is _ABSENT or (isinstance(got, dict) and not got):
            continue
        owned[probe_path] = got
    return owned


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

    **«Потреблён ли лист» решает ЗОНД, а не ручной список особых случаев**
    (задача 2.9, M1/M2). До неё лист, не попавший ни в
    ``expand_observability(survived)``, ни в ``IDENTITY_SECTION_KEYS``, исчезал
    из вердикта ЦЕЛИКОМ: запрос, подавший ``heartbeat_interval_sec`` или
    ``stats.enabled``, отвечал побайтно тем же, что и ПУСТОЙ запрос.

    **Зонд спрашивает про РАЗНИЦУ ДВУХ значений, а не про одно** (добор ревью
    2.9). Первая редакция сравнивала раскладку ``{ключ: значение}`` с раскладкой
    пустого запроса — и путала «ключ не просили» с «значение запроса совпало со
    схемным дефолтом». Совпадение с дефолтом законно (оператор, написавший
    ``console: true`` поверх выключенной консоли, сказал ровно то, что хотел), а
    цена ошибки была двойной: 24 листа схемы получали в ``unverifiable`` СЫРОЕ
    схемное имя, которого readback не отдаёт никогда, и ещё 7 не получали
    ничего. Ложное имя хуже отсутствующего: отличить его от честного
    ``documents.factory`` оператору нечем.

    Разница двух значений от значения не зависит — на этом и стоит починка. Для
    каждого ЛИСТА СХЕМЫ, приехавшего в ``survived``, зонд строит два полюса
    (``значение`` и :func:`_other_value`), раскладывает ОБА и берёт пути, в
    которых они расходятся: это ровно те пути раскладки, которыми лист
    управляет. Полюса собираются ``model_copy`` поверх чистого
    ``ObservabilityConfig()`` — без повторной валидации, см. :func:`_with_leaf`.
    Значение для ``expected`` берётся из ПОЛНОЙ раскладки ``expand(survived)``.

    Три исхода зонда и что вердикт с ними делает — в докстринге
    :func:`_controlled_layout_paths`. Здесь важны следствия:

    * отдельного пропуска «запрос этот путь не менял» больше НЕТ и он не нужен:
      в ``expected`` попадают ТОЛЬКО пути, которыми запрос управляет, а не вся
      раскладка. Пропуск сравнивал со схемными дефолтами и глушил ровно те
      правки, где оператор просит значение, равное дефолту (``stats.enabled:
      true`` подтверждался только на выключение);
    * лист, чей отпечаток раскладка при этом значении не материализовала
      (``console: true`` — экспандер молчит и отдаёт решение дефолту ниже),
      проверяемого пути не даёт и потому НАЗЫВАЕТСЯ схемным именем — всегда, а
      не только когда весь запрос состоит из таких листьев. Названность —
      свойство ЛИСТА: первая редакция ставила её «последним рубежом» при пустом
      ``expected``, и один и тот же ``console: true`` назывался в одиночку и
      молчал рядом с проверяемым ключом;
    * отпечаток берётся по ПЕРЕСЕЧЕНИЮ путей двух полюсов, а не по объединению:
      разницу по ЗНАЧЕНИЮ утверждаем, разницу по НАЛИЧИЮ только называем.
      Объединение давало ложную тревогу — переключатель, гасящий секцию
      раскладки (``errors.enabled``), забирал в отпечаток всю её, и вердикт
      требовал схемный дефолт от соседних ключей, которых оператор не писал
      (воспроизведено ревью на живом стенде). Цена реза: ``console``/``file``
      теряют единственную сверку и становятся ``unverifiable`` — она приезжала
      в комплекте с 56 ложными именами стола каналов;
    * раскладка не обязана быть инъективной: если два значения листа дают
      побайтно одну раскладку (клампинг, насыщение), отпечаток пуст и лист
      уходит в ``unverifiable`` под схемным именем. Шумно, но честно —
      сегодняшних примеров в схеме нет, а появится такой лист — вердикт скажет
      «не проверил», а не «сошлось».

    ``observation`` — секция непотреблённого рода, но её собственная нормализация
    (``normalized_observation_section``, glob-пути с точками внутри имени)
    обязана применяться ПОСЛЕ зонда: без этого порядка в ``expected`` лёг бы
    СЫРОЙ ``rules``-словарь (без достроенных дефолтов ``MetricRule``), и он бы
    никогда не совпал с тем, что отдаёт readback. Здесь и только здесь более
    специфичная запись обязана победить более общую.
    """
    from ..configs.observability_layers import unknown_section_keys

    section = requested if isinstance(requested, dict) else {}

    # Неизвестные ключи считает ОБЩИЙ сверщик (задача 5.4): та же функция стоит
    # на границе записи в слой сессии, где отвечает отказом. Пока расчёт был
    # написан ЗДЕСЬ, он и жил только здесь — то есть имя ключа судил вердикт
    # ПОСЛЕ того, как ключ уже лёг в L3 со сроком (находки Н-C/Н-D приёмки F2).
    # Две копии разошлись бы на первом же новом поле схемы, а «неизвестный ключ»
    # значило бы разное на двух дорогах одной команды.
    unknown = unknown_section_keys(section)
    try:
        survived = ObservabilityConfig.model_validate(section).model_dump(exclude_unset=True)
    except Exception:  # noqa: BLE001 — невалидную секцию судит применение, не вердикт
        survived = section

    # Раскладка ПОЛНОГО запроса — источник ЗНАЧЕНИЙ (какие пути кому
    # принадлежат, решает зонд по каждому листу отдельно).
    layout = flatten_section(expand_observability(survived))
    leaves = _requested_leaves(survived, _schema_leaf_paths(ObservabilityConfig))
    expected: Dict[str, Any] = {}
    for leaf_path, leaf_value in leaves:
        owned = _controlled_layout_paths(leaf_path, leaf_value, layout)
        if not owned:
            # ``None`` — раскладка от листа не зависит вовсе (зонд молчит на обоих
            # полюсах): лист идёт мимо экспандера, его схемный путь и есть путь
            # readback'а. Пустой словарь — лист УПРАВЛЯЕТ путями раскладки, но при
            # ЭТОМ значении раскладка их не материализовала (`console: true` —
            # схемный дефолт, экспандер молчит; `errors.enabled: false` гасит
            # секцию целиком). Сверять нечего ни там, ни там — и оба случая
            # обязаны быть НАЗВАНЫ схемным именем.
            #
            # Одной веткой, а не «последним рубежом при пустом `expected`»:
            # рубеж делал названность зависимой от СОСЕДЕЙ по запросу — один и тот
            # же `console: true` назывался в одиночку и молчал рядом с проверяемым
            # ключом. Свойство «либо сверен, либо назван, но никогда нигде»
            # принадлежит ЛИСТУ, а не запросу целиком.
            expected[".".join(leaf_path)] = leaf_value
        else:
            expected.update(owned)
    # `observation` — секция того же непотреблённого рода, но с СОБСТВЕННОЙ
    # нормализацией путей (glob-паттерны содержат точки, и голая запись выше
    # кладёт СЫРОЙ словарь `rules` без достроенных дефолтов `MetricRule`).
    # Обязана идти ПОСЛЕ зонда: её ключи заменяют только что положенные сырые,
    # а не соседствуют с ними (см. докстринг функции).
    if isinstance(survived.get(OBSERVATION_SECTION_KEY), dict):
        expected.update(normalized_observation_section(survived[OBSERVATION_SECTION_KEY]))
    flat_effective = flatten_section(effective if isinstance(effective, dict) else {})

    mismatches: list = []
    unverifiable: list = []
    checked = 0
    for path, want in expected.items():
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
            # Ф8.1: одна ось — приёмники (см. соседний readback выше).
            view["scopes"] = {
                str(name): {"channels": list(getattr(sc, "channels", None) or ())} for name, sc in scopes.items()
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
    # 2.2 — потолок кардинальности. В ``LOSS_COUNTER_KEYS`` эти счётчики НЕ
    # входят (решение Р2.2-8: те пять классов описывают стык «менеджер →
    # канал» и общие для трёх плоскостей, а кардинальность — потеря на ВХОДЕ и
    # существует только у статистики; в общем кортеже она объявила бы вечный
    # ноль у логгера и у ошибок). Но «не в том реестре» не значит «невидима»:
    # видимость обеспечивается ЗДЕСЬ, и именно это требовалось проверить
    # поимённо. Имена опущенных серий едут рядом со счётчиками, потому что
    # «порог-сумма прячет слепоту» — по одному числу нельзя понять, ЧТО
    # перестало наблюдаться.
    # Серии и эмиссии — РАЗНЫЕ величины и оба публикуются: «сколько серий не
    # пущено» отвечает за арифметику снапшота, «сколько эмиссий отвергнуто» —
    # за темп. Признак ``*_is_lower_bound`` едет РЯДОМ со своим числом: оценка,
    # опубликованная без пометки, читается как точное число.
    "series_dropped",
    "observations_dropped",
    "series_dropped_is_lower_bound",
    "dropped_series",
    # У окна публикуются ДВЕ величины из четырёх, и это решение, а не забывчивость:
    # `series` и признак оценки снизу у стража окна живут до ближайшего
    # `take_report()`, а `observations` и имена — за срок процесса. Одноимённая
    # четвёрка с разными периодами читается неверно молча (пробовали — откатили,
    # см. `StatsManager.get_stats`). «Сколько серий опущено за окно» едет в самой
    # записи снапшота, где период однозначен.
    "window_observations_dropped",
    "window_dropped_series",
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
    # D1 — запись НЕ роздана в tap'ы, потому что раздача уже шла в этом потоке
    # (tap, который сам эмитит из write()). Подавление законно — иначе лавина до
    # предела рекурсии, — но невидимым быть не вправе: «хвост тихий» и «хвост
    # глушит сам себя» лечатся разным, а выглядят одинаково.
    "tap_reentrant_suppressed",
    # Ф5, ревью-блокер B3 — tap хвоста бросил при записи; глушится (эмитент не
    # роняется), но не молчит счётчиком.
    "tap_write_errors",
    # Ф5, ревью-блокер B2 — числа плоскости stats, ушедшие МИМО порта наблюдений
    # (attach_observation_port не вызывался/не удался). В боевой сборке обязан
    # быть пустым словарём; словарь по МЕТОДУ (record_metric/gauge/…), а не
    # единое число — см. ``StatsManager.observation_bypasses``.
    "observation_bypasses",
    # Ф5, ревью-блокер B3 — собственные счётчики порта наблюдений (только у
    # ``ObservationManager``, три соседние плоскости их не заводят вовсе):
    # сколько чисел реально ушло в раздачу tap'ам, сколько потеряно отказом
    # приёмника и сколько подавлено реентерабельностью. Без них «обходов
    # ноль» (``observation_bypasses == {}``) неотличимо от «портом никто не
    # пользовался» — см. ``ObservationManager.get_stats``.
    "numbers_delivered",
    # Ф5-добор, блокер Б1 — раздача состоялась и не дошла НИ ДО КОГО.
    # Пара к ``numbers_delivered``: сам по себе он рос одинаково при живом
    # приёмнике и при нуле приёмников, то есть различитель живой и мёртвой
    # плоскости чисел — только ПАРА (delivered > 0 И no_sink == 0). Без этого
    # ключа спросить у ЖИВОГО процесса нечем: он есть только здесь.
    "numbers_dropped_no_sink",
    "numbers_dropped_by_sink_error",
    "numbers_suppressed_reentrant",
    # Ф2, задача 2.1 — числа, НЕ собранные по решению политики. Это потеря на
    # ВХОДЕ (как кардинальность), и она обязана быть спрашиваемой у живого
    # процесса: без неё «метрики нет в окне» одинаково выглядит и при работающем
    # правиле оператора, и при сломанном писателе, а лечатся они разным.
    # Пара к тишине: `stats.enabled: false` без растущего счётчика неотличим от
    # «никто не писал» — ровно это требует критерий 3 приёмки задачи.
    # Два ключа, а не сумма: «запрещено правилом» лечится правилом,
    # «придержано interval_sec» — частотой (см. `StatsManager.numbers_policy_dropped`).
    "numbers_policy_dropped",
    "numbers_policy_throttled",
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
    # Ф1.4 (M17) — окна голоса на ключ. Родственник дросселя выше, но не он:
    # тот подавляет по ТЕКСТУ записи, этот — по явному ключу события, и число
    # подавленных называется в тексте следующего голоса. Пара ключей по тому же
    # правилу, что у дросселя: «сколько подавлено» и «сколько счётчиков потеряно
    # вместе с выброшенным по потолку ключом» — второе делает первое честным.
    "windowed_suppressed",
    "windowed_keys_evicted",
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
    # Ф1.1 (C3) — три счётчика процессных хуков приезжают ИМПОРТОМ константы, а
    # не переписанными строками. Список выше сам объявлен «точкой забывания», и
    # четвёртая копия трёх имён (реестр, объявление в ErrorManager, документ,
    # здесь) разошлась бы молча — расхождение видно только тому, кто сверяет
    # руками. Кортеж склеивается, а не распаковывается внутрь, чтобы имена
    # оставались там, где они определены.
) + HOOK_COUNTER_KEYS


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
    observation: Any = None,
    hub: Any = None,
    flush: bool = False,
) -> Dict[str, Any]:
    """Потери и глубина буферов ЧЕТЫРЁХ плоскостей — «сколько наблюдаемости не доехало».

    ``observation`` — Ф5, ревью-блокер S2. До этой правки кортеж называл только
    ``logger``/``error``/``stats``: секция ``observation`` в ответе
    ``introspect.observability`` существовала (``observation_plane_report``), но
    отвечала ТОЛЬКО за гейт УРОВНЕЙ (``writers``/``publications``) — счётчиков
    ЧИСЕЛ порта (``numbers_delivered`` и соседи, B3; ``observation_bypasses``
    менеджера stats, B2) в ответе не было вовсе, и «один писатель» проверялся
    только тестами: спросить у ЖИВОГО процесса было нечем.

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
    for name, manager in (("logger", logger), ("error", error), ("stats", stats), ("observation", observation)):
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
    event_selector: Any = None,
    flight_recorder: Any = None,
    command: Any = None,
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

    Task 2.2 (критерий 3): ``command`` — седьмая плоскость на тех же правах,
    что ``event_selector``/``flight_recorder``: ручка ``observability.commands.
    log_success`` раскладывалась ``expand_observability`` и НИКОГДА не
    доставлялась до живого ``CommandManager`` — правка лежала в слое, была
    видна в провенансе и не действовала. ``None`` — не отказ (процесс без
    ``CommandManager`` пропускает ветку).

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

    Ф4 (4.1) — **пятая плоскость в том же стеке.** ``event_selector`` необязателен
    ровно так же, как менеджеры: нет получателя — ручки отбора широких записей
    пропускаются. Селектор создаётся сшивкой на старте и живёт весь процесс,
    поэтому здесь он ПЕРЕНАСТРАИВАЕТСЯ, а не пересоздаётся: счёт по родам обязан
    пережить правку конфига (тот же довод, что у ``RateSampler.configure``).

    Ф5 (5.1) — **шестая плоскость, дословно на тех же правах.** ``flight_recorder``
    необязателен, перенастраивается, а не пересоздаётся, и обязан быть передан
    на ВСЕХ дорогах пересборки. Находка №1 задачи 4.1 была ровно про это: ручка
    действовала через ``config.reload`` и НЕ действовала через правку файла, а
    обе дороги отвечали «применено».

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
                heartbeat=heartbeat,
                telemetry_boot=telemetry_boot,
                store_throttle=store_throttle,
                boot_rules=boot_rules,
                event_selector=event_selector,
                flight_recorder=flight_recorder,
                command=command,
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
    heartbeat: Any = None,
    telemetry_boot: Optional[Dict[str, Any]] = None,
    store_throttle: Any = None,
    boot_rules: Optional[Dict[str, Any]] = None,
    event_selector: Any = None,
    flight_recorder: Any = None,
    command: Any = None,
) -> Dict[str, Dict[str, Any]]:
    """Тело пересборки (вызывается под локом стека — см. вызывающего)."""
    resolved = layers.resolve()
    # Task 5.10.f: телеметрия живёт в ТОМ ЖЕ плоском namespace под своим
    # префиксом, но раскладке в manager-конфиги не подлежит — у неё свои
    # получатели. Снимаем её до `expand_observability`, иначе `ObservabilityConfig`
    # отверг бы незнакомый ключ, и слой оказался бы невыразим.
    telemetry_layered = resolved.pop(TELEMETRY_KEY, None)
    expanded = compose_managers_payload(resolved, log_dir=log_dir)

    if logger is not None:
        logger.reconfigure(expanded["logger"])
        _remark_operator_disabled_sinks(logger, layers, ("channels",))
    if error is not None:
        error.reconfigure(expanded["error"])
        _remark_operator_disabled_sinks(error, layers, ("errors", "channels"))
    if stats is not None:
        stats.reconfigure(expanded["stats"])
        _remark_operator_disabled_sinks(stats, layers, ("stats", "channels"))

    # Ф2 (задача 2.2, критерий 3): третья точка дороги `observability.commands.
    # log_success`. `expanded["command"]` УЖЕ считается `compose_managers_payload`
    # выше, но раньше его не забирал никто — правка легла бы в слой, была бы
    # видна в провенансе (`_schema_keys()` генерик её видит) и НЕ действовала.
    # Получатель — ЖИВОЙ `CommandManager` (`set_log_success_enabled`), а не
    # пересоздание: гейт у ИСТОЧНИКА (командный hot-path не должен терять счёт
    # ради правки конфига).
    if command is not None:
        set_log_success_fn = getattr(command, "set_log_success_enabled", None)
        if callable(set_log_success_fn):
            set_log_success_fn(bool(expanded["command"].get("log_success", False)))

    # Ф4 (4.1), третья точка дороги ручки: живой селектор перенастраивается ИЗ
    # ТЕХ ЖЕ разрешённых слоёв, что прочитала сшивка на старте. Без этой ветки
    # `config.reload` менял бы слой и не менял поведение — правка была бы видна в
    # провенансе и не действовала бы, ровно тот класс, который лечит правило
    # трёх точек. Секция `events` при этом остаётся в `resolved` (в отличие от
    # `telemetry`, которую снимают выше): `ObservabilityConfig` её знает, а
    # `expand_observability` не раскладывает — как `documents` и `session_ttl_sec`.
    events_applied = apply_event_selector(event_selector, resolved.get(EVENTS_SECTION_KEY))
    if events_applied is not None:
        expanded[EVENTS_SECTION_KEY] = events_applied

    # Ф5 (5.1), та же третья точка у соседней под-секции. Секция `flight`
    # остаётся в `resolved` по той же причине, что `events`: `ObservabilityConfig`
    # её знает, а `expand_observability` не раскладывает.
    flight_applied = apply_flight_recorder(flight_recorder, resolved.get(FLIGHT_SECTION_KEY))
    if flight_applied is not None:
        expanded[FLIGHT_SECTION_KEY] = flight_applied

    # Ф1.4 (M17), та же третья точка у окон голоса. Отличие от соседей: живой
    # объект перенастраивать не надо — механизм процессный, и применение это
    # смена политики, которую все держатели окон читают на следующем голосе.
    voices_applied = apply_voices_policy(resolved.get(VOICES_SECTION_KEY))
    if voices_applied is not None:
        expanded[VOICES_SECTION_KEY] = voices_applied

    # Ф4 плана «порт наблюдений» (4.1), та же третья точка у политики порта.
    # Секция `observation` остаётся в `resolved` по тому же доводу, что `events`
    # и `flight`. Получатель — живой гейт heartbeat'а: без этой ветки правка
    # легла бы в слой, была бы видна в провенансе и НЕ действовала.
    # Отчёт о потолках IPC здесь НЕ считается (Ф3, задача 3.0a, находка Н1
    # ревью): он читает такт и publish-секцию, а обе величины правят СОСЕДНИЕ
    # стадии ниже. Считается он в конце ленты — `observation_throttle_report`.
    observation_applied = apply_observation_policy(
        heartbeat,
        resolved.get(OBSERVATION_SECTION_KEY),
    )
    if observation_applied is not None:
        expanded[OBSERVATION_SECTION_KEY] = observation_applied

    # Ф2 (задача 2.3, M9), седьмая плоскость на тех же правах. Скаляр, а не
    # под-секция (как `observation`/`voices`/`events`/`flight` выше), поэтому в
    # `resolved` лежит ПРЯМО под своим именем (как `log_level` в
    # `compose_managers_payload`), а не под ключом-конвертом. Получатель — ЖИВОЙ
    # `ProcessHeartbeat`: без этой ветки правка легла бы в слой, была бы видна в
    # провенансе (`_schema_keys()` генерик её уже видит) и НЕ действовала бы —
    # ровно тот класс, ради которого «третья точка дороги» здесь и заведена.
    heartbeat_interval_applied = apply_heartbeat_interval(heartbeat, resolved.get(HEARTBEAT_INTERVAL_KEY))
    if heartbeat_interval_applied is not None:
        expanded[HEARTBEAT_INTERVAL_KEY] = heartbeat_interval_applied

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

    # Ф3, задача 3.0a (находка Н1 ревью): отчёт о потолках IPC — ПОСЛЕДНЯЯ
    # строка ленты применений, потому что он целиком считается по readback'у
    # состояния, которое правят обе стадии выше (такт — `apply_heartbeat_interval`,
    # `tick_sec`/`default_interval_sec` — телеметрийная). Стоя раньше, он отвечал
    # по состоянию ДО правки, и два ОДИНАКОВЫХ `config.reload` подряд давали
    # РАЗНЫЕ ответы: первый утверждал «потолков нет» там, где потолок уже был.
    if observation_applied is not None:
        observation_applied.update(observation_throttle_report(heartbeat, observation_applied, store_throttle))

    if log_info is not None:
        held = ", ".join(layers.session_keys()) or "—"
        log_info(
            f"[observability] пересобран из слоёв "
            f"(log_level={expanded['logger'].get('default_level')}; держится сессией: {held})"
        )
    return expanded


def apply_observation_policy(heartbeat: Any, section: Any, *, store_throttle: Any = None) -> Optional[Dict[str, Any]]:
    """Донести политику порта до ЖИВОГО гейта и вернуть применённое (Ф4, 4.1).

    ``None`` на входе (``heartbeat`` не поднят) — не отказ: пересборка идёт и на
    процессах, где телеметрию никто не публикует. Секция при этом ВСЕГДА
    непустая по смыслу, даже когда слои о ней молчат: дефолтное правило поддерева
    порта — это решение владельца (вариант «в»), а не «механизма нет». Поэтому
    применяем и при ``section is None`` — иначе снятие ключа из слоя оставляло бы
    гейт на прошлой правке, ровно та невыразимость, ради устранения которой 5.12
    развернула семантику на «пересборку из источников».

    **Голос про потолок IPC — здесь, а не только у соседней плоскости.**
    Половина сверщика, работающая с ``publish_section``, судит правила
    ``telemetry.publish`` по ИМЕНИ и правила по ПУТИ не видит вовсе (её и зовёт
    оптовый ``telemetry.broadcast``); без этой ветки обещание проекта «no
    silent caps» (ADR-PM-017) стало бы неправдой ровно для тех правил, ради
    которых фаза делалась: оператор просит частоту выше центрального потолка,
    получает ``success=true`` и молча срезанный темп. Отчёт кладётся в ответ, а
    троттл НЕ трогается — операторская страховка остаётся нетронутой (auto-relax
    отвергнут тем же ADR).

    ``throttle_checked=False`` означает «сверять было не с чем» (у процесса нет
    центрального троттла — он живёт только на оркестраторе), и это НЕ то же
    самое, что «потолков нет»: пустой отчёт без этого признака читался бы как
    подтверждение, которого никто не давал.

    **``capped_by_throttle_unjudged`` — третье показание того же сверщика** (Ф3,
    задача 3.0, находка F2 вердикта CTO по Ф2, 2026-09-03). ``throttle_checked``
    отвечает за ВЫЗОВ, а не за ОХВАТ: сверщик мог быть позван и всё же не
    рассудить часть кандидатов (заявки нет И такта нет — heartbeat выключен).
    До правки такие кандидаты пропускались молча, и пустой ``capped_by_throttle``
    рядом с ``throttle_checked: true`` был неотличим от «потолков нет». Ключ
    кладётся ТОЛЬКО при непустом списке: пустой словарь завёл бы в ответе
    показание «не судили никого», которого читатель не просил, и его пришлось
    бы отличать от отсутствия механизма.

    **Возвращённое читается снаружи** (``config.reload`` → ключ
    ``observation_applied``). До находки Б2 ревью Ф4 отчёт вычислялся и
    выбрасывался: за пределами тестов его не потреблял никто, а единственный
    сторож смотрел во внутренний ``expanded`` — то есть доказывал харнесс.

    **Охват сверки — ``cap_candidates``, а не ``rules``** (находка З1 того же
    ревью): дефолт правила поддерева в ``rules`` не лежит, и назначенный
    предохранитель варианта «в» не судился вовсе, при том что соседний
    ``capped_metrics`` его учитывал — два отчёта о потолках расходились в охвате.
    """
    apply = getattr(heartbeat, "apply_observation_policy", None)
    if not callable(apply):
        return None
    applied = dict(apply(section) or {})
    applied.update(observation_throttle_report(heartbeat, applied, store_throttle))
    return applied


def observation_throttle_report(heartbeat: Any, applied: Dict[str, Any], store_throttle: Any) -> Dict[str, Any]:
    """Отчёт о потолках IPC по СНЯТОМУ СЕЙЧАС состоянию процесса (Ф3, задача 3.0a, Н1).

    Отделено от :func:`apply_observation_policy` не ради красоты, а потому что
    отчёт и применение обязаны стоять в РАЗНЫХ точках ленты команды. Отчёт
    целиком считается по двум readback'ам — ``current_telemetry_tick()`` и
    ``current_telemetry_publish()``, — а обе величины меняют СОСЕДНИЕ стадии
    того же ``config.reload``: такт правит ``apply_heartbeat_interval``
    (``observability.heartbeat_interval_sec``), а ``tick_sec`` и
    ``default_interval_sec`` — телеметрийная стадия
    (``_apply_telemetry_from_layers``). Пока отчёт считался внутри применения
    политики порта, он читал состояние ДО этих стадий, и один и тот же вызов
    отвечал по-разному в зависимости от того, каким он был по счёту.

    Воспроизведение (находка Н1 ревью, два ОДИНАКОВЫХ ``config.reload`` подряд,
    троттл ``{'processes.*.state.plugins.**': 0.5}``, такт харнесса 1.0)::

        reload#1 {"heartbeat_interval_sec": 0.2} -> capped_by_throttle={}
        reload#2 тот же вход                     -> {'processes.*.state.plugins.**':
                                                     {'publisher_interval_sec': 0.2,
                                                      'throttle_interval_sec': 0.5}}

    То есть первый ответ утверждал «потолков нет» там, где потолок уже был. Та же
    болезнь достижима и без ``heartbeat_interval_sec`` — через ``telemetry.publish.tick_sec``
    в той же команде, — поэтому ``apply_observability_layers`` зовёт отчёт ПОСЛЕ
    ОБЕИХ стадий, а не только после такта.

    Почему не переехало само применение политики: ``reconfigure_telemetry``
    (телеметрийная стадия) внутри себя зовёт ``_warn_capped_metrics`` — соседний
    голос о потолках, который считает по ЖИВОЙ политике порта. Переставь стадии
    местами — и этот голос заговорит по политике ПРОШЛОЙ правки. Порядок
    применений остаётся прежним, переехал только отчёт.

    Args:
        heartbeat: ``ProcessHeartbeat`` процесса (источник обоих readback'ов).
        applied: применённая политика порта — из неё собираются кандидаты
            (:func:`~..configs.observation_policy.cap_candidates`).
        store_throttle: живой центральный троттл оркестратора либо ``None``.

    Returns:
        Ключи для ответа: ``throttle_checked`` всегда; ``capped_by_throttle`` —
        когда троттл есть; ``capped_by_throttle_unjudged`` — только непустым.
    """
    report: Dict[str, Any] = {"throttle_checked": store_throttle is not None}
    if store_throttle is None:
        return report

    from ..configs.observation_policy import cap_candidates
    from .telemetry_reload import judge_throttle_caps

    # ЖИВОЕ значение гейта, а не константа: правило без явного `interval_sec`
    # унаследует именно его, и сверять надо то, что попросит публикатор.
    # Второй проход ревью итерации 2: здесь стоял `None`, поэтому сверщик
    # никогда не видел `default_interval_sec` процесса и судил по литералу —
    # при 0.5 против троттла 0.8 срез был реален, а отчёт отдавал пустой
    # список рядом с `throttle_checked: true`.
    live_publish = None
    current = getattr(heartbeat, "current_telemetry_publish", None)
    if callable(current):
        try:
            live_publish = current()
        except Exception:  # noqa: BLE001 — readback не смеет ронять применение политики
            live_publish = None
    inherited = None
    if isinstance(live_publish, dict):
        raw = live_publish.get("default_interval_sec")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            inherited = float(raw)
    # Ф2 (задача 2.11, Р-11): дефолт поддерева (`cap_candidates(applied)`)
    # заявляет `interval_sec=0.0` на каждой пересборке — `judge_throttle_caps`
    # обязан судить его по РЕАЛЬНОМУ ask, а не по голому нулю; Ф3 (задача 3.0,
    # F1) обобщила это до «такт — нижняя граница ЛЮБОЙ заявки» (см. её
    # докстринг). Тот же осторожный приём, что уже стоит выше для
    # `current_telemetry_publish`: readback не смеет ронять применение политики.
    effective_tick = None
    current_tick = getattr(heartbeat, "current_telemetry_tick", None)
    if callable(current_tick):
        try:
            raw_tick = current_tick()
        except Exception:  # noqa: BLE001 — readback не смеет ронять применение политики
            raw_tick = None
        if isinstance(raw_tick, (int, float)) and not isinstance(raw_tick, bool):
            effective_tick = float(raw_tick)
    caps, unjudged = judge_throttle_caps(
        None,
        store_throttle,
        observation_rules=cap_candidates(applied),
        default_interval_sec=inherited,
        effective_tick=effective_tick,
    )
    report["capped_by_throttle"] = caps
    # Ф3, задача 3.0 (находка F2 вердикта CTO по Ф2): ключ появляется ТОЛЬКО
    # когда есть что назвать. Пустой словарь рядом с `throttle_checked: true`
    # читался бы как «сверщик посмотрел и не судил ничего» — третье показание
    # там, где показаний два; отсутствие ключа означает «судить было чем всех».
    if unjudged:
        report["capped_by_throttle_unjudged"] = unjudged
    return report


def apply_heartbeat_interval(heartbeat: Any, value: Any) -> Optional[float]:
    """Донести ``observability.heartbeat_interval_sec`` до ЖИВОГО такта (Ф2, 2.3, M9).

    Тонкая обёртка — тем же приёмом, что :func:`apply_observation_policy` для
    соседней плоскости: тело мутации живёт НА ``ProcessHeartbeat``
    (:meth:`~..heartbeat.process_heartbeat.ProcessHeartbeat.apply_heartbeat_interval`),
    здесь — только достать получателя и не уронить пересборку, если его нет.

    ``heartbeat is None`` (такт не поднят — паритет с соседями выше) → ``None``,
    и это НЕ отказ: пересборка идёт и на процессах без heartbeat'а.

    Returns:
        Применённое значение (для readback в ответе ``config.reload``) либо
        ``None``, если применять было некому.
    """
    apply = getattr(heartbeat, "apply_heartbeat_interval", None)
    if not callable(apply):
        return None
    return apply(value)


def telemetry_targets(svc: Any) -> Dict[str, Any]:
    """Получатель publish-плоскости и её L0 — одним резолвом для ВСЕХ пересборок.

    Task 5.10.f. Тремя разными местами (``config.reload``, ``telemetry.reconfigure``,
    такт подметальщика) достаётся одно и то же; разойдись они хоть в одном
    аргументе — и возврат по сроку применялся бы не туда, куда правка.

    ``telemetry_boot`` читается ТЕМ ЖЕ способом, что и на старте
    (``ProcessHeartbeat._build_telemetry_gate`` → :func:`read_process_config`):
    L0 обязан совпадать с тем, из чего собран загрузочный гейт, иначе «вернуть
    как было» вернёт не то, что было.

    **Ред. 2026-08-18.** Здесь стоял голый ``get_config(TELEMETRY_KEY, None)`` — тот
    же плоский читатель, что и в загрузочном гейте, и обещание выше выполнялось
    буквально: оба ОДИНАКОВО не видели вложенный адрес ``config.telemetry``, под
    которым ключ приезжает дочернему процессу (весь ``proc_dict`` идёт конфигом).
    Обе точки переведены на :func:`read_process_config` ОДНОВРЕМЕННО и намеренно:
    почини одну — и обещание рвётся молча, а возврат по сроку отдаст не тот L0, из
    которого собран гейт. Живое измерение дефекта — докстринг
    ``ProcessHeartbeat._build_telemetry_gate``.

    ``state_throttle_rules`` остаётся ПЛОСКИМ читателем сознательно: это ключ
    оркестратора (``orchestrator_config``, ``backend/launch.py``), у детей его нет.

    Центрального троттла здесь нет намеренно — см. ``TELEMETRY_LAYERED_SUBSECTION``.
    """
    from ..configs.observability_layers import read_process_config
    from .telemetry_reload import resolve_store_throttle

    get_config = getattr(svc, "get_config", None)
    raw = read_process_config(svc, TELEMETRY_KEY) if callable(get_config) else None
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


#: Адрес исполнителя каждой под-секции ``telemetry`` — текстом, пригодным для
#: ответа оператору. Task 3.1: «нет получателя» обязано называть, КУДА слать, а
#: не только «здесь нельзя»: без адреса оператор узнаёт о промахе по отсутствию
#: эффекта, то есть позже всего.
#:
#: Имя оркестратора берётся из :data:`ORCHESTRATOR_PROCESS_NAME`, а не пишется
#: строкой второй раз: переименуй его — и зашитый литерал остался бы врать
#: оператору, а тест приёмки (``assert "ProcessManager" in reason``) остался бы
#: зелёным, потому что сверял бы литерал с литералом.
TELEMETRY_SUBSECTION_ADDRESS: Dict[str, str] = {
    "throttle": (
        "центральный store-троттл живёт только на оркестраторе — "
        f"адресуйте под-секцию процессу {ORCHESTRATOR_PROCESS_NAME}"
    ),
    "publish": (
        "publisher-gate собирает ProcessHeartbeat, а у этого процесса heartbeat не поднят — применять publish некому"
    ),
}


def telemetry_unaddressable(svc: Any, section: Any) -> list[str]:
    """Под-секции ``telemetry``, у которых на ЭТОМ процессе нет исполнителя.

    Task 3.1. Резолв получателей — ТОТ ЖЕ :func:`telemetry_targets`, которым
    пользуется применение: разойдись они хоть в одном аргументе, и дверь
    отказывала бы там, где применение справилось (или наоборот — пропускала
    туда, где применить некому, ровно тот дефект, который задача закрывает).

    Судится ПРИСУТСТВИЕ ключа, а не истинность значения: ``publish: null`` —
    законная команда «снять гейт», и снимать его тоже некому, если heartbeat'а
    нет. Тем же правилом Г3 («ключ есть → владею») здесь уже живут
    :func:`_apply_telemetry_from_layers` и ``_cmd_telemetry_reconfigure``.

    Возвращает имена под-секций в стабильном порядке (``throttle`` перед
    ``publish``) — ответ команды не должен менять текст от порядка ключей во
    входном словаре.
    """
    if not isinstance(section, dict):
        return []
    targets = telemetry_targets(svc)
    receivers = {"throttle": targets.get("store_throttle"), "publish": targets.get("heartbeat")}
    return [sub for sub in ("throttle", "publish") if sub in section and receivers[sub] is None]


def format_telemetry_unaddressable(svc: Any, missing: list[str]) -> str:
    """Собрать причину отказа/голоса по списку под-секций без исполнителя."""
    where = getattr(svc, "name", "?")
    return "; ".join(
        f"telemetry.{sub} не применяется на процессе {where!r}: {TELEMETRY_SUBSECTION_ADDRESS[sub]}" for sub in missing
    )


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
    has_delta = isinstance(delta, dict)
    if not (has_delta or layers.throttle_owned):
        # Слои дельты не держали ни разу — троттлом владеет файл и его watcher.
        # Проверка стоит ПЕРВОЙ намеренно: процесс без получателя И без дельты
        # обязан молчать, а не отчитываться `throttle: False` на каждый reload.
        return None
    if store_throttle is None:
        # Получателя нет (обычный процесс, а не оркестратор) — и это ОТВЕТ, а не
        # молчание: оператор, не увидевший поля, решил бы, что правило применено.
        #
        # Task 3.1: возврат стоит ДО присвоения `throttle_owned`, и это несущий
        # порядок, а не стиль. Прежде владение захватывалось по одному факту
        # «в слое лежит dict», то есть РАНЬШЕ, чем выяснялось, что применять
        # некому: плоскость оказывалась во владении слоёв навсегда (флаг
        # липкий), хотя ни одна дельта никогда не доезжала до исполнителя. Ответ
        # при этом можно было сделать честным одним текстом — и слот всё равно
        # остался бы занятым. Владеет тот, кто применил; неприменённая дельта не
        # владеет ничем.
        return {"throttle": False}
    if has_delta:
        layers.throttle_owned = True

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
    event_selector: Any = None,
    flight_recorder: Any = None,
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
            # Ф4 (4.1): селектор — такой же получатель пересборки, как менеджеры.
            # Без него правка ФАЙЛА меняла бы слой и не меняла отбор широких
            # записей, тогда как та же правка через `config.reload` действовала бы —
            # то есть одна ручка вела бы себя по-разному на двух дорогах, и
            # разошлись бы они молча. Найдено инъекцией по дорогам (2026-08-16),
            # у соседней ручки `stats` этого дефекта нет по построению.
            event_selector=event_selector,
            # Ф5 (5.1): рекордер дампов — такой же получатель правки ФАЙЛА.
            # Пропусти мы его здесь, и `observability.flight.enabled`,
            # выставленный в system.yaml/спутнике, действовал бы только через
            # `config.reload` — то есть ручка вела бы себя по-разному на двух
            # дорогах, и разошлись бы они молча (находка 1 задачи 4.1).
            flight_recorder=flight_recorder,
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
    event_selector: Any = None,
    flight_recorder: Any = None,
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
        event_selector=event_selector,
        flight_recorder=flight_recorder,
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
