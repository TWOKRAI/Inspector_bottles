# -*- coding: utf-8 -*-
"""
Слоистое владение конфигом наблюдаемости (Task 5.12).

Четыре источника одной секции ``observability``, от общего к частному:

===== ==================================== =========================================
Слой  Где живёт                            На какой вопрос отвечает
===== ==================================== =========================================
L0    код — :class:`ObservabilityConfig`   «как правильно вообще»
L1    ``system.yaml observability:``       «что верно на ЭТОЙ машине при любом рецепте»
L2    рецепт (+ спутник) ``observability:`` «что верно для ЭТОГО конвейера»
L3    память процесса                      «что кручу руками прямо сейчас»
===== ==================================== =========================================

Отсутствие ключа на слое = наследование снизу. Резолв — ``L1 → L2 → L3``;
L0 подставляется НЕ здесь, а :func:`~.observability_config.expand_observability`
(валидация Pydantic-дефолтами). Это намеренно: единственная точка раскладки —
якорь ADR-CRM-006, и резолвер стоит **над** expand, а не внутри и не рядом.

**Provenance считается по СЫРЫМ секциям слоёв — до expand.** После раскладки
ключ из L0 неотличим от заданного явно: ``_toggled_logger_channels`` и профиль
уровня материализуют дефолты в полноценные словари. Спросить «почему у меня
INFO» у раскрытого конфига уже нельзя — поэтому ответ вычисляется один раз,
здесь, пока слои ещё различимы.

Форма L2 в рецепте (``defaults`` + per-process, per-process побеждает)::

    observability:
      defaults:
        log_level: INFO
        scopes: {DEBUG: {enabled: false}}
      processes:
        camera_0:
          channels: {module_trace: {enabled: false}}

**L3 временный по построению (Task 5.8).** Каждая запись сессии несёт срок
(``session_ttl_sec``, дефолт 300с); по истечении ключ УДАЛЯЕТСЯ — и действующее
значение уезжает за нижним слоем, как при явном сбросе. Второй политики нет:
сделать правку постоянной можно ровно одним способом — ``observability.persist``
(она переезжает в L2, а файл вечен по построению). Причина в резидуале R1 задачи
5.12: до слоёв «включил DEBUG и забыл» стиралось любым ``config.reload``, а после
5.12 ручка переживает reload — то есть живой инцидент «messages.log 645 МБ» стал
ВЕРОЯТНЕЕ, а не менее вероятен.

Сам возврат исполняет такт heartbeat (:mod:`..managers.observability_ttl`) —
здесь только бухгалтерия сроков.
"""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from ...data_schema_module import deep_merge
from .observability_audit import (
    ACTION_CLEAR,
    ACTION_EXPIRE,
    ACTION_LAYER,
    ACTION_RESET,
    ACTION_SET,
    ACTION_TOUCH,
    ObservabilityAudit,
    make_audit_log,
)

# Имена слоёв — они же значения поля ``source`` в ответе introspect.observability.
LAYER_FRAMEWORK = "framework"
LAYER_APP = "app"
LAYER_RECIPE = "recipe"
LAYER_SESSION = "session"

#: Порядок применения: каждый следующий побеждает предыдущий.
LAYER_ORDER: Tuple[str, ...] = (LAYER_FRAMEWORK, LAYER_APP, LAYER_RECIPE, LAYER_SESSION)

#: Ключ, под которым сырая L2-дельта процесса едет в ``proc_dict["config"]``
#: (точный аналог ``telemetry_override``, см. assembler прототипа).
OVERRIDE_CONFIG_KEY = "observability_override"

#: Ключ сырой L1-секции в ``proc_dict["config"]``. Нужен ДО первого reload:
#: без него процесс не знает, какие ключи пришли из ``system.yaml``, и
#: provenance приписал бы их фреймворку — то есть соврал бы.
APP_CONFIG_KEY = "observability_app"

#: Ключ с путём к активному рецепту — адрес слоя L2 (рецепт + спутник рядом).
RECIPE_PATH_CONFIG_KEY = "observability_recipe_path"

#: Имя процесса-оркестратора — единственный литерал в цепочке «спавн + слои»
#: (Task 5.13). До 5.13 их было три, и они расходились: спавнер писал имя дважды
#: (в ``args`` и в ``name=``), третьим был дефолт конструктора
#: ``ProcessManagerProcess``. При этом имя уже входило в дисковый контракт —
#: ``observability.persist`` пишет спутник по ``svc.name``.
#:
#: Живёт здесь, в самом нижнем модуле, которому это имя нужно, а спавнер и
#: остальные импортируют его отсюда. Обратное направление (константа у спавнера)
#: дало бы цикл: ``process_module`` ниже ``process_manager_module``.
#:
#: **Литералом ``"ProcessManager"`` система не исчерпывается**, и утверждать
#: обратное было бы неправдой: имя остаётся адресом по умолчанию у ``StateProxy``,
#: ``RouterManager.relay_hub``, GUI-моста и сборщиков команд — там это контракт
#: АДРЕСАЦИИ, отдельный от контракта сборки, и сводить их одной константой значило
#: бы связать два независимых решения. Консолидация этих мест в задачу не входила.
ORCHESTRATOR_PROCESS_NAME = "ProcessManager"

#: Атрибут, под которым стек живёт на объекте процесса.
LAYERS_ATTR = "_observability_layers"

#: Предел срока L3, сек — тот же, что объявляет поле схемы ``session_ttl_sec``.
#: Сутки: дольше живущая «временная» правка — это уже решение уровня рецепта.
MAX_SESSION_TTL_SEC = 86400.0

#: Ключ политики срока жизни L3 в секции ``observability`` (Task 5.8).
#: Живёт в тех же слоях, что и всё остальное: L1 задаёт машинную политику,
#: L2 — политику конвейера. ``0`` = сроков нет (осознанный отказ от защиты).
SESSION_TTL_KEY = "session_ttl_sec"

#: Четвёртая плоскость в ТОМ ЖЕ плоском namespace слоёв (Task 5.10.f).
#: Телеметрия получает владение и срок жизни наравне с логами, но не переезжает
#: в ``ObservabilityConfig`` отдельной секцией: второй набор слоёв рядом с первым
#: был бы вторым механизмом там, где хватает построенного. Раскладке в
#: manager-конфиги ключ не подлежит — его снимают до ``expand_observability``.
TELEMETRY_KEY = "telemetry"

#: Под-секция телеметрии, которая раскладывается в слоях ПО КЛЮЧАМ.
#:
#: ``publish`` — per-process рычаг «что считаем и как часто», ровно тот, чей
#: забытый включённый режим и есть инцидент 645 МБ на плоскости метрик. У него
#: имена метрик без точек, поэтому per-key слой ему подходит: свой срок и свой
#: провенанс у каждого ключа.
#:
#: ``throttle`` тоже живёт в слоях (Task 5.10.g), но ОДНИМ непрозрачным листом —
#: см. :data:`OPAQUE_LAYER_PATHS`. Разведены они не по важности, а по форме
#: имён: паттерны троттла содержат точки, и per-key разложение для них сломано
#: по построению.
TELEMETRY_LAYERED_SUBSECTION = "publish"

#: Имя второй под-секции. Литерал ``"throttle"`` был написан в этом файле
#: ОДИН раз (внутри :data:`TELEMETRY_THROTTLE_PATH`), а сверяться с ним
#: понадобилось валидатору Task 2.1 — вытащено в имя, чтобы у одной под-секции
#: не завелось двух написаний.
TELEMETRY_THROTTLE_SUBSECTION = "throttle"

#: Под-секции телеметрии, которые существуют. Список ЗАКРЫТ — довод в
#: :func:`validate_telemetry_section`.
TELEMETRY_SUBSECTIONS = (TELEMETRY_LAYERED_SUBSECTION, TELEMETRY_THROTTLE_SUBSECTION)

#: Путь дельты центрального троттла в слое сессии (Task 5.10.g).
TELEMETRY_THROTTLE_PATH = f"{TELEMETRY_KEY}.{TELEMETRY_THROTTLE_SUBSECTION}"

#: Пути, ниже которых бухгалтерия слоёв НЕ спускается: значение целиком — лист.
#:
#: Заведено под дельту троттла, и не из вкуса, а потому что per-rule ключ там
#: **сломан по построению** — воспроизведено:
#:
#:   session_set("telemetry.throttle.processes.**.state.fps", 2.0)
#:     → в слое появляются ДВЕ записи: настоящее правило
#:       {"processes.**.state.fps": 2.0} и вложенное дерево
#:       {"processes": {"**": {"state": {"fps": 2.0}}}}, потому что путь режется
#:       по точкам, а точки — часть ИМЕНИ паттерна;
#:   session_reset_keys(того же пути)
#:     → снимает вложенную ветку, рапортует успех, а само правило остаётся жить.
#:
#: То есть учёт сроков объявлял бы возврат, которого не было, — «следствие без
#: причины» по построению. Атомарный лист снимает это целиком: слои видят одно
#: непрозрачное значение, а удаление правила остаётся ВНУТРИ дельты её родным
#: маркером ``THROTTLE_REMOVE`` (контракт задач 1.1/1.2 не тронут ни строкой).
#: Цена названа: per-rule срок и per-rule провенанс недоступны — срок один на
#: всю операторскую дельту.
OPAQUE_LAYER_PATHS = frozenset({TELEMETRY_THROTTLE_PATH})

#: Кольца возвратов больше нет (Task 5.9): возвраты — это записи аудита с
#: ``action="expire"``, а ``session_reverts`` стал выборкой из него. Глубину
#: задаёт ``observability_audit.AUDIT_HISTORY`` — одна на все виды смен.


def recipe_defaults_apply_to(process_name: str) -> bool:
    """Действует ли ОПТОВЫЙ ключ рецепта (``defaults`` и короткая форма) на процесс.

    Единственное место, где живёт решение Р1 (Task 5.13). И правило резолва, и
    признак в readback читают отсюда: разведи их — и оператору показывали бы
    одно, а применялось бы другое, причём расхождение обнаружилось бы только
    сравнением двух файлов кода.

    Оркестратор исключён: рецепт описывает конвейер, а PM — машина, на которой
    конвейер исполняется. Заглушить его можно, но лишь назвав поимённо в
    ``processes``.
    """
    return process_name != ORCHESTRATOR_PROCESS_NAME


def resolve_recipe_section(
    section: Any,
    process_name: str,
    *,
    include_defaults: Optional[bool] = None,
) -> Dict[str, Any]:
    """Сырая L2-дельта КОНКРЕТНОГО процесса из секции рецепта.

    ``defaults`` применяется всем процессам рецепта **кроме оркестратора**
    (решение владельца Р1, подробности ниже), ``processes[<имя>]`` мержится
    поверх. Процесс, не названный в ``processes``, получает только ``defaults``
    — и правка соседа его не задевает.

    Короткая форма (ключи прямо в секции, без ``defaults``) — это тоже
    ``defaults``, и **она остаётся ими даже в присутствии ``processes``**.
    Прежняя редакция переключалась на структурную ветку по наличию любого из
    двух служебных ключей и молча выбрасывала верхнеуровневые. Ломалось это не
    руками человека, а машиной: спутник ВСЕГДА пишется в форме ``processes:``,
    и первый же ``observability.persist`` домерживал этот ключ в секцию рецепта
    короткой формы — после чего её собственные настройки исчезали у ВСЕХ
    процессов, а у соседей сохранившего — исчезало всё. Триггер несвязанный,
    симптом нулевой. Найдено ревью 5.12 (Fable), блокер 1.

    **Исключение оркестратора (Task 5.13, решение владельца Р1).** Оптовый ключ
    рецепта — ``defaults`` И короткая форма — на :data:`ORCHESTRATOR_PROCESS_NAME`
    НЕ действует: он берёт только то, что названо его именем в ``processes``.
    Рецепт описывает конвейер, а оркестратор — машина, на которой конвейер
    исполняется; ``defaults: {log_level: ERROR}`` иначе гасил бы строки
    нормального хода самого PM (охваты рассылок брокера, охват reset-рассылки,
    дисковый след аудита смен) — то есть узнавалось бы это по отсутствию строк,
    позже всего. Заглушить оркестратора можно, но лишь назвав его поимённо.

    Исключение решается ЗДЕСЬ, а не параметром у вызывающих: call-sites СЕМЬ —
    два ассемблера (generic ``app_module.builder`` и прикладной), конверт switch,
    спутник, L2-watcher, ``orchestrator_observability_config`` и сам PM, — и
    четыре из них исполняются внутри процесса-получателя. Правило, которое каждый
    обязан не забыть передать, дало бы ``effective`` PM, зависящий от того, какой
    путь стрелял последним. (Ревью корзины 2: здесь стояло «пять», перечень отстал
    от кода на две дороги — счёт сверен по вызовам, а не по памяти.)

    Внимание: исключение накрывает **весь** ``defaults``, включая
    не-глушащие ключи (``session_ttl_sec``, ``telemetry``). Это принятая цена
    решения Р1, а не упущение: список «глушащих ключей» был бы вторым реестром
    рядом с теми, что Ф8.1 собирается схлопывать.

    Args:
        section: секция ``observability`` рецепта или спутника (сырая).
        process_name: имя процесса-адресата.
        include_defaults: явный override правила выше. ``None`` — правило
            действует (оркестратор без ``defaults``, остальные с ним). Нужен
            тестам, чтобы проверять обе ветки, не подменяя имя процесса.

    Returns:
        Сырой dict (возможно пустой) — форма секции ``observability`` процесса.
    """
    if not isinstance(section, dict) or not section:
        return {}
    per_process = (section.get("processes") or {}).get(process_name) or {}
    if not isinstance(per_process, dict):
        per_process = {}
    if include_defaults is None:
        include_defaults = recipe_defaults_apply_to(process_name)
    if not include_defaults:
        return dict(per_process)
    declared = section.get("defaults")
    declared = declared if isinstance(declared, dict) else {}
    # Всё, что не служебные ключи — тоже defaults (короткая форма, возможно
    # смешанная со структурной после merge).
    inline = {k: v for k, v in section.items() if k not in ("defaults", "processes")}
    # `inline` и `declared` — ОДИН уровень (оба «defaults» этой секции), поэтому
    # здесь канонический мерж: владение — отношение между РАЗНЫМИ этажами, а внутри
    # одного этажа объявлять «моё» не у кого. А вот ниже этажи разные.
    defaults = deep_merge(inline, declared) if inline else declared
    # Правило Г3 (корзина 2.1): `processes[<имя>]` — ЧАСТНОЕ поверх ОБЩЕГО, ровно то
    # же отношение, что между слоями. Канонический `deep_merge` здесь означал, что
    # «заглушить у одного процесса» (`scopes: {}` при непустом `defaults`) не
    # работало: ключи defaults воскресали, а команда молчала об этом.
    return layer_merge(defaults, per_process)


def orchestrator_observability_config(
    *,
    app_section: Any = None,
    recipe_section: Any = None,
    app_config_path: str = "",
    recipe_path: str = "",
) -> Dict[str, Any]:
    """Ключи наблюдаемости оркестратора для ``orchestrator_config`` (Task 5.13).

    Оркестратор спавнится мимо ассемблера proc_dict'ов, поэтому слои приезжают к
    нему теми же ключами, но другим конвертом. Функция **одна на обе дороги** —
    прототип (``backend/launch.py``) и generic (``app_module.SystemBuilder``):
    третья копия правила раскладки разошлась бы с первыми двумя, а те две уже
    разошлись однажды (ветка ``if resolved:`` есть в одной и нет в другой).

    Секция ``managers`` здесь НЕ собирается — и это не пропуск. Её пересобирает
    сам процесс на старте (``ProcessModule._apply_boot_observability_layers``) из
    тех же слоёв и с базой из машинного каталога логов. Собрать её ещё и тут
    значило бы завести второе место, где живёт одна и та же сборка, — то есть
    ровно то, из-за чего этот дефект и появился.

    Долька рецепта резолвится тем же :func:`resolve_recipe_section`, а значит
    автоматически подчиняется решению Р1: оптовый ключ (``defaults`` и короткая
    форма) до оркестратора не доходит, только названное его именем.

    Args:
        app_section: сырая секция ``observability`` приложения (слой L1).
        recipe_section: сырая секция ``observability`` РЕЦЕПТА (база слоя L2).
            Спутник сюда не мержится (ФР-3) — его кладёт поверх уже разрешённой
            дольки ``observability_companion.compose_over_base``, и делает это
            последним. Прежний контракт требовал «уже смерженную со спутником»
            секцию, и прикладная дорога его исполняла: снятый из спутника ключ
            оставался в базе конфига навсегда, тогда как generic-дорога (она
            спутника не мержила) честно возвращалась к рецепту.
        app_config_path: путь к файлу L1 — адрес слоя для ``provenance``.
        recipe_path: путь к активному рецепту — адрес слоя L2, он же цель
            ``observability.persist``.

    Returns:
        Ключи для ``orchestrator_config``. Пустые не кладутся: отсутствие ключа
        и ключ с пустым значением различаются в ``provenance``.
    """
    out: Dict[str, Any] = {}
    if isinstance(app_section, dict) and app_section:
        out[APP_CONFIG_KEY] = dict(app_section)
    own_slice = resolve_recipe_section(recipe_section, ORCHESTRATOR_PROCESS_NAME)
    if own_slice:
        out[OVERRIDE_CONFIG_KEY] = own_slice
    if app_config_path:
        out["observability_config_path"] = str(app_config_path)
    if recipe_path:
        out[RECIPE_PATH_CONFIG_KEY] = str(recipe_path)
    return out


@dataclass
class ObservabilityLayers:
    """Стек сырых секций наблюдаемости одного процесса.

    Хранит ИСТОЧНИКИ, а не результат: резолв (:meth:`resolve`) и объяснение
    (:meth:`provenance`) вычисляются от них каждый раз. Именно это делает
    возможной пересборку конфига вместо дельты поверх живого — удаление ключа
    из слоя в дельте невыразимо, а в пересборке выражается само собой.

    Attributes:
        app: L1 — секция ``observability`` из ``system.yaml`` (сырая).
        recipe: L2 — уже разрешённая для ЭТОГО процесса дельта рецепта
            (см. :func:`resolve_recipe_section`).
        session: L3 — рантайм-правки оператора (``logger.sink.disable``,
            ``config.reload`` с ``persist=False``).
        app_source / recipe_source: файлы, давшие L1/L2 — наружу отдаётся
            КОНКРЕТНЫЙ файл, а не абстрактное имя слоя (иначе при паре
            «рецепт + спутник» оператор не знает, какой из двух править).
        session_expiry: Task 5.8 — ``{ключ L3: монотонный дедлайн}``. Ключа нет =
            срока нет (правка объявлена бессрочной явно).
        audit: Task 5.9 — кольцо смен наблюдаемости, ЕДИНСТВЕННЫЙ писатель.
            Прежнее кольцо возвратов ``session_reverts`` стало выборкой из него
            (см. одноимённое свойство): два кольца, хранящие пересекающиеся
            факты, немедленно порождают вопрос «почему в одном есть, а в другом
            нет».
        rebuild_pending: пересборка после истечения срока не удалась — повторить
            на следующем такте. Без флага ключ уже удалён из L3, а менеджеры
            остались на старом конфиге, и расхождение было бы вечным и немым.
        clock: монотонные часы КАК ЗАВИСИМОСТЬ ОБЪЕКТА. Глобальный патч
            ``time.monotonic`` в тестах доедают чужие потоки — на этом проекте
            уже ловили флейк в невиновном тесте.
    """

    app: Dict[str, Any] = field(default_factory=dict)
    recipe: Dict[str, Any] = field(default_factory=dict)
    session: Dict[str, Any] = field(default_factory=dict)
    app_source: str = ""
    recipe_source: str = ""
    session_expiry: Dict[str, float] = field(default_factory=dict)
    audit: ObservabilityAudit = field(default_factory=ObservabilityAudit)
    rebuild_pending: bool = False
    # Task 5.10.f: взяли ли слои плоскость телеметрии под своё владение. Липкий,
    # и это его смысл: истечение срока УДАЛЯЕТ ключ `telemetry.*` из L3, и без
    # памяти о том, что слои им владели, пересборка перестала бы трогать гейт
    # ровно в тот момент, когда его надо вернуть к загрузочному состоянию.
    # Пока ни один слой о телеметрии не сказал, плоскость не трогается вовсе —
    # иначе пересборка наблюдаемости клобберила бы применённое её собственным
    # watcher'ом (`make_telemetry_on_reload` идёт ПОСЛЕ неё на оркестраторе).
    telemetry_owned: bool = False
    # Task 5.10.g: то же липкое владение для дельты центрального троттла. Раздельно
    # с `telemetry_owned`: у плоскостей разные получатели (гейт процесса против
    # одного middleware оркестратора), и общий флаг заставлял бы пересборку трогать
    # чужое ровно тогда, когда слои сказали только про соседа.
    throttle_owned: bool = False
    clock: Callable[[], float] = time.monotonic
    # Писателей у L3 стало ЧЕТЫРЕ: watcher L1, watcher L2, поток команд и (Task 5.8)
    # такт heartbeat. Три первых были резидуалом R2 «не воспроизведено»; четвёртый
    # ходит по тем же вложенным словарям регулярно и сам по себе, поэтому лок
    # заводится здесь, а не откладывается: `session_set` создаёт ветку, `session_reset`
    # её же подчищает — интерливинг этих двух обходов теряет запись молча.
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    @property
    def lock(self) -> Any:
        """Лок стека — держится и на время пересборки (см. ``apply_observability_layers``).

        Одного лока на мутации мало: пересборка читает слои и применяет результат
        двумя шагами, и две пересборки внахлёст могут закончиться тем, что последней
        применится СТАРШАЯ по времени чтения — то есть отменит более свежую правку.
        """
        return self._lock

    def __getstate__(self) -> Dict[str, Any]:
        """Лок непиклим, а стек живёт на объекте процесса — снимаем его из снимка."""
        state = dict(self.__dict__)
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = threading.RLock()

    def resolve(self) -> Dict[str, Any]:
        """Сырая секция ``observability`` после наложения L1 → L2 → L3.

        Наложение — :func:`layer_merge`, а не канонический ``deep_merge``: пустой
        словарь верхнего слоя ВЛАДЕЕТ (решение владельца Г3), а не сливается в
        no-op. Это же правило различения использует :meth:`provenance` — resolve и
        объяснение не могут разойтись, потому что делят один примитив.
        """
        with self._lock:
            merged = layer_merge(self.app or {}, self.recipe or {})
            return layer_merge(merged, self.session or {})

    def raw_layers(self) -> Tuple[Tuple[str, Dict[str, Any], str], ...]:
        """``(имя слоя, сырая секция, источник)`` в порядке применения."""
        return (
            (LAYER_APP, self.app or {}, self.app_source),
            (LAYER_RECIPE, self.recipe or {}, self.recipe_source),
            (LAYER_SESSION, self.session or {}, LAYER_SESSION),
        )

    # ---------------------------------------------------------------- L3

    def session_set(self, path: str, value: Any, ttl: Optional[float] = None, *, origin: str) -> Optional[float]:
        """Записать ключ в L3 (``"channels.messages_file.enabled"``) со сроком.

        Args:
            ttl: срок в секундах. ``None`` — взять действующую политику слоёв
                (:meth:`effective_session_ttl`, дефолт 300с), а НЕ «навсегда»:
                оператор, который забыл про DEBUG, забыл бы и про ``ttl``, и
                опциональный срок не закрыл бы инцидент, ради которого заведён.
                ``0`` — бессрочно, и это осознанное заявление вызывающего.
            origin: Task 5.9 — механизм смены для аудита. **Обязателен** и не
                имеет дефолта: дефолт был бы записью «источник неизвестен», то
                есть ровно той ложью, которую аудит устраняет.

        Returns:
            Остаток срока в секундах или ``None``, если правка бессрочна.

        Raises:
            ValueError: отрицательный или нечисловой ``ttl`` — громкий отказ
                вместо тихого «значит, навсегда»; ЛИБО путь ведёт ВНУТРЬ
                непрозрачного листа (R3b, см. :func:`_reject_path_inside_opaque`);
                ЛИБО значение не проходит схему секции (B2, см.
                :func:`validate_layer_section`) — тогда в тексте адрес ключа и
                список допустимых значений.
        """
        _reject_path_inside_opaque(path)
        # B2: один ключ судится той же схемой, что целая секция, — путь
        # разворачивается обратно в дерево. Ручка оператора (`logger.sink.*`,
        # `config.reload` по одному ключу) ходит именно сюда, и без проверки
        # здесь мусор доезжал бы до L3 в обход границы секции.
        nested: Any = value
        for part in reversed(path.split(".")):
            nested = {part: nested}
        validate_layer_section(nested, layer=LAYER_SESSION)
        with self._lock:
            seconds = self.effective_session_ttl() if ttl is None else validate_ttl(ttl)
            node = self.session
            parts = path.split(".")
            for part in parts[:-1]:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
            node[parts[-1]] = value
            orphans = self._forget_expiry_of_replaced(path)
            # Срок ПЕРЕУСТАНАВЛИВАЕТСЯ каждой записью, включая бессрочную: иначе
            # повторная правка того же ключа наследовала бы дедлайн прошлой и
            # возвращалась раньше, чем оператор просил в последний раз.
            if seconds > 0:
                self.session_expiry[path] = self.clock() + seconds
                left: Optional[float] = seconds
            else:
                self.session_expiry.pop(path, None)
                left = None
        # Запись — ВНЕ лока стека: она кладёт строку в журнал, а держать лок
        # слоёв на время файлового I/O значило бы дать пересборке ждать диска.
        self.audit.record(
            ACTION_SET,
            origin=origin,
            key=path,
            value=value,
            ttl_sec=left,
            # Снятое ЭТОЙ записью названо в ТОЙ ЖЕ записи: снятие и постановка —
            # один факт для читателя, разносить их значило бы заставить его
            # сшивать журнал по времени (то же решение, что в `session_touch`).
            removed=list(orphans) or None,
        )
        return left

    def _forget_expiry_of_replaced(self, path: str) -> Tuple[str, ...]:
        """Снять сроки, которые запись по ``path`` сделала беспредметными (корзина 2.2).

        Два вида, и оба — про ЧУЖУЮ правку, а не про свою:

        * **Предки.** Срок на ``channels`` ставила команда, писавшая туда своё
          значение (например ``{}`` — владение пустотой по правилу Г3). Запись в
          ``channels.messages_file.enabled`` это значение ЗАМЕНИЛА, и прежний срок
          теперь накрывает содержимое, которого его автор не писал. Найдено
          независимым ревью корзины 2.1 и воспроизведено: правка, объявленная
          оператором БЕССРОЧНОЙ (``ttl=0``, ответ ``ttl_sec: None``), сносилась
          подметальщиком по чужому дедлайну, а аудит записывал это штатным
          авто-возвратом. Принцип «срок ставится ключам ЭТОЙ правки» (Task 5.8)
          симметричен: чужая правка не имеет права и УБИВАТЬ ключ.
        * **Потомки, переставшие существовать.** Запись листа поверх ветки
          (``scopes`` ← скаляр/``{}``) уносит ключи под ней; их сроки иначе
          пережили бы свои ключи и всплыли бы в readback'е.

        Потомок, который ПОСЛЕ записи всё ещё лист сессии, свой срок сохраняет:
        ``session_set("scopes", {"DEBUG": …})`` не отменяет собственный дедлайн
        ``scopes.DEBUG.enabled`` — ключ на месте, и обещание про него честно.

        Returns:
            Снятые ключи, отсортированные (для записи в аудит).
        """
        leaves = set(flatten_section(self.session).keys())
        doomed = set()
        parts = path.split(".")
        for depth in range(1, len(parts)):
            ancestor = ".".join(parts[:depth])
            if ancestor in self.session_expiry:
                doomed.add(ancestor)
        prefix = f"{path}."
        for key in self.session_expiry:
            if key.startswith(prefix) and key not in leaves:
                doomed.add(key)
        for key in doomed:
            self.session_expiry.pop(key, None)
        return tuple(sorted(doomed))

    def session_touch(
        self,
        paths: Iterable[str],
        ttl: Optional[float] = None,
        *,
        origin: str,
        removed: Optional[Iterable[str]] = None,
    ) -> Optional[float]:
        """Проставить срок ключам, уже лежащим в L3 (Task 5.8).

        Нужен там, где секция приезжает целиком (``config.reload`` с inline
        ``observability``) и мержится одним ``deep_merge``: пере-записывать её
        по листьям через :meth:`session_set` значило бы чуть иначе обрабатывать
        пустые под-словари, то есть завести второй, слегка отличающийся merge.

        Args:
            removed: ключи, которые вызывающий снял ТОЙ ЖЕ операцией
                (``telemetry.reconfigure mode=replace`` выбрасывает стейл-листья
                старой под-секции). Замечание 2 ревью 5.9: без них снятая ручка
                исчезала из действующей наблюдаемости, а аудит показывал только
                новые ключи — путь, меняющий состояние без следа. Одно поле в
                той же записи, а не вторая запись: снятие и постановка здесь —
                один факт, и разносить их значило бы заставить читателя сшивать
                их по времени.

        Returns:
            Проставленный срок в секундах или ``None`` (бессрочно).
        """
        with self._lock:
            seconds = self.effective_session_ttl() if ttl is None else validate_ttl(ttl)
            touched = [str(path) for path in paths]
            for path in touched:
                if seconds > 0:
                    self.session_expiry[path] = self.clock() + seconds
                else:
                    self.session_expiry.pop(path, None)
            left = seconds if seconds > 0 else None
        # Task 5.9: именно эта запись описывает inline-секцию `config.reload` —
        # она приезжает целиком и мержится одним `deep_merge`, минуя session_set,
        # поэтому без записи здесь смена секцией была бы невидима в аудите.
        self.audit.record(
            ACTION_TOUCH,
            origin=origin,
            keys=touched,
            ttl_sec=left,
            removed=sorted({str(k) for k in removed}) if removed else None,
        )
        return left

    def effective_session_ttl(self) -> float:
        """Действующая политика срока L3, сек (``0`` — сроков нет).

        Тот же резолв слоёв, что у любого другого ключа: L0 (300с) → L1 (машина)
        → L2 (конвейер) → L3. Битое значение = дефолт L0, а не «навсегда»:
        опечатка в конфиге не имеет права молча снимать защиту.
        """
        raw = self.resolve().get(SESSION_TTL_KEY)
        if raw is None:
            return _default_session_ttl()
        try:
            return validate_ttl(raw)
        except ValueError:
            return _default_session_ttl()

    def session_expires_in(self, path: str, now: Optional[float] = None) -> Optional[float]:
        """Остаток срока ключа, сек (``None`` — ключ бессрочен либо его нет)."""
        with self._lock:
            deadline = self.session_expiry.get(path)
            if deadline is None:
                return None
            return round(deadline - (self.clock() if now is None else now), 1)

    def session_has_deadline(self, path: str) -> bool:
        """Есть ли у ключа срок (согласованное с локом чтение для ответов команд)."""
        with self._lock:
            return path in self.session_expiry

    def session_ttl_view(self, now: Optional[float] = None) -> Dict[str, float]:
        """``{ключ: остаток срока, сек}`` для readback. Отрицательное = срок вышел,
        а возврат ещё не наступил (такт heartbeat не прошёл) — это ЧЕСТНЫЙ ответ,
        и он же отличает «сейчас вернётся» от «уже вернулось»."""
        with self._lock:
            moment = self.clock() if now is None else now
            return {key: round(deadline - moment, 1) for key, deadline in sorted(self.session_expiry.items())}

    def expire_due(self, now: Optional[float] = None) -> Tuple[str, ...]:
        """Удалить из L3 ключи, чей срок вышел. Возврат — что реально снято.

        Ключ, которого в L3 уже нет (сохранён в L2 или сброшен руками), из учёта
        сроков вычёркивается, но в возврат НЕ попадает: аудит обязан перечислять
        действительно изменённое, иначе оператор ищет причину у правки, которой
        не было. По той же причине истёкшая ВЕТКА перечисляется листьями
        (:meth:`_reset_keys_unrecorded`), а не своим путём.

        Task 5.9 — **единственная мутация L3, которая не пишет в аудит сама.**
        Запись за весь такт кладёт подметальщик (:meth:`note_revert`): снятие
        ключей и исход пересборки для оператора один факт, а исход известен
        только после применения.
        """
        with self._lock:
            moment = self.clock() if now is None else now
            removed: list = []
            for key in sorted(k for k, deadline in self.session_expiry.items() if deadline <= moment):
                self.session_expiry.pop(key, None)
                removed.extend(self._reset_keys_unrecorded(key))
            return tuple(removed)

    @property
    def session_reverts(self) -> Tuple[Dict[str, Any], ...]:
        """Авто-возвраты — ВЫБОРКА из аудита, а не своё кольцо (Task 5.9).

        Прежде это был отдельный deque. Два кольца, хранящие пересекающиеся
        факты, немедленно порождают вопрос «почему в одном есть, а в другом
        нет», и отвечать на него пришлось бы сравнением реализаций. Форма записи
        изменилась вместе с переездом: ``ts``/``ok`` вместо ``at``/``success``,
        плюс ``seq``, ``origin`` и ``action`` — два написания одного факта не
        заводятся даже ради совместимости поля.
        """
        return tuple(self.audit.entries(action=ACTION_EXPIRE))

    def note_revert(self, entry: Mapping[str, Any], *, origin: str) -> Dict[str, Any]:
        """Записать в аудит итог одного такта подметальщика (Task 5.8 → 5.9).

        Запись кладёт ПОДМЕТАЛЬЩИК, а не :meth:`expire_due`, и это единственное
        исключение из правила «каждая мутация L3 пишет сама»: снятие ключей и
        исход пересборки — один факт для оператора («правка больше не
        действует»), а исход становится известен только после применения. Две
        записи на такт заставляли бы читателя сшивать их по времени.
        """
        payload = dict(entry)
        return self.audit.record(
            ACTION_EXPIRE,
            origin=origin,
            keys=payload.pop("keys", ()) or (),
            ok=bool(payload.pop("success", True)),
            error=payload.pop("error", None),
            **payload,
        )

    def session_reset(self, path: str, *, origin: str) -> bool:
        """Удалить ключ из L3 — записать ОТСУТСТВИЕ, а не текущее значение.

        Присвоение значения дефолта порвало бы связь с ним навсегда: поменяется
        L0/L1 — сессия продолжит держать старое число. Поэтому сброс именно
        удаляет, и действующее значение после него едет за нижним слоем.

        Returns:
            True, если ключ был и удалён; False — если его не было.
        """
        return bool(self.session_reset_keys(path, origin=origin))

    def session_reset_keys(self, path: str, *, origin: str) -> Tuple[str, ...]:
        """То же, что :meth:`session_reset`, но возвращает СНЯТЫЕ ЛИСТЬЯ.

        Путь может указывать на ветку (``scopes``), и тогда удаляется всё под
        ней. Прежняя редакция отчитывалась запрошенным путём, а исчезали ещё и
        соседи с собственными, ненаступившими сроками: отчёт называл одно,
        происходило другое, а сроки-сироты оставались висеть в readback'е у
        правок, которых больше нет. Замечание 3 ревью 5.8, воспроизведено.
        """
        removed = self._reset_keys_unrecorded(path)
        # Пустой результат — тоже смена, о которой стоит знать: «сбросил, а там
        # ничего не было» и «сбросил, ключи ушли» — разные исходы одной команды,
        # и по молчанию аудита их не различить.
        self.audit.record(ACTION_RESET, origin=origin, key=path, keys=removed)
        return removed

    def _reset_keys_unrecorded(self, path: str) -> Tuple[str, ...]:
        """Тело сброса без записи в аудит.

        Отдельный метод, а не флаг-часовой у публичного: единственный, кому
        нужна мутация без своей записи, — :meth:`expire_due`, и запись за весь
        его такт кладёт подметальщик (см. :meth:`note_revert`). Флаг вида
        ``record=False`` был бы лазейкой, которой рано или поздно
        воспользовался бы кто-то ещё.
        """
        with self._lock:
            node = self._node_at(path)
            # Task 5.10.g: непрозрачный путь — сам себе лист, и перечислять его
            # содержимое нельзя: имена внутри (паттерны троттла) содержат точки,
            # и отчёт назвал бы ключи, которых в namespace не существует.
            #
            # A-A1-2 (воскрешение 5.10.g на развилке сброса РОДИТЕЛЯ): flatten
            # получает ПОЛНЫЙ префикс пути — иначе, спускаясь от `telemetry` к
            # `telemetry.throttle`, он не узнавал бы непрозрачный лист по его
            # абсолютному имени и разрезал бы паттерны с точками на несуществующие
            # ключи (`telemetry.throttle.processes.**.state.fps`). С префиксом лист
            # виден как один атомарный ключ на ЛЮБОЙ глубине сброса.
            if path in OPAQUE_LAYER_PATHS or not node:
                leaves: tuple = ()
            else:
                leaves = tuple(sorted(flatten_section(node, prefix=f"{path}.").keys()))
            removed = leaves if leaves else (path,)
            # Сроки снимаем ВСЕГДА и со всей ветки, даже если ключа уже не было:
            # иначе срок переживёт свой ключ и всплывёт в readback'е как срок у
            # правки, которой нет.
            self.session_expiry.pop(path, None)
            prefix = f"{path}."
            for key in [k for k in self.session_expiry if k.startswith(prefix)]:
                self.session_expiry.pop(key, None)
            return removed if self._delete_path(path) else ()

    def _node_at(self, path: str) -> Any:
        """Непустой под-словарь по пути (``None``, если там лист или ничего)."""
        node: Any = self.session
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node if isinstance(node, dict) and node else None

    def _delete_path(self, path: str) -> bool:
        """Удалить путь из L3 вместе с опустевшими родителями. True — было что удалять."""
        with self._lock:
            parts = path.split(".")
            stack = [self.session]
            node: Any = self.session
            for part in parts[:-1]:
                node = node.get(part) if isinstance(node, dict) else None
                if not isinstance(node, dict):
                    return False
                stack.append(node)
            if not isinstance(node, dict) or parts[-1] not in node:
                return False
            del node[parts[-1]]
            # Подчистить опустевшие ветки: иначе `session` перестаёт быть честным
            # ответом на «что держится сессией» — {"channels": {"a": {}}} читается
            # как «канал a чем-то управляется», хотя не управляется ничем.
            for parent, part in zip(reversed(stack[:-1]), reversed(parts[:-1])):
                child = parent.get(part)
                if isinstance(child, dict) and not child:
                    del parent[part]
                else:
                    break
            return True

    def session_keys(self) -> Tuple[str, ...]:
        """Плоский список ключей, которые сейчас держит L3 (для ответа команды).

        Под локом: обход дерева параллельно с чужой правкой — это не только
        неверный ответ, но и «dictionary changed size during iteration» из
        диагностической команды.
        """
        with self._lock:
            return tuple(sorted(flatten_section(self.session or {}).keys()))

    def session_clear(self, *, origin: str) -> Tuple[str, ...]:
        """Сбросить L3 целиком, вернув перечень сброшенных ключей."""
        with self._lock:
            keys = self.session_keys()
            self.session = {}
            # Сроки уходят вместе с ключами (switch = новая сессия). Оставленный
            # срок ничего бы не вернул — возвращать уже нечего, — но показывал бы
            # в readback'е несуществующую правку.
            self.session_expiry.clear()
        self.audit.record(ACTION_CLEAR, origin=origin, keys=keys)
        return keys

    def replace_layer(
        self,
        layer: str,
        section: Optional[Dict[str, Any]],
        *,
        source: Optional[str] = None,
        origin: str,
    ) -> Tuple[str, ...]:
        """Заменить сырую секцию слоя L1/L2 целиком (Task 5.9).

        Метод, а не присваивание ``layers.app = ...``: смена файла — такая же
        смена наблюдаемости, как команда, и до этой задачи она не оставляла
        следа вовсе. Присваиванием поля перехватить её нечем.

        Возвращает ключи НОВОЙ секции — то, что слой теперь заявляет. Разницу
        со старой аудит не считает: сравнение двух сырых секций дало бы третье
        написание того же факта, а «что действует» отвечает провенанс.

        Задача 5.4 — **незнакомые ключи файла попадают в аудит ЗДЕСЬ**, а не у
        вызывающих. Отказать файлу нельзя (опечатка в спутнике не имеет права
        валить switch рецепта), но и промолчать нельзя: ключ, которого нет в
        контракте, живёт в файле вечно и не делает ничего. Место выбрано по
        числу дорог: тело в L1/L2 кладут пять (watcher ``system.yaml``, watcher
        спутника, файловая ветка ``config.reload``, конверт switch'а, перечитка
        спутника), и запись у каждой из них была бы пятью написаниями одного
        факта — с гарантией, что одна отстанет.
        """
        body = dict(section) if isinstance(section, dict) else {}
        # B2: проверка ДО того, как тронут слой. Отвергнутая секция не имеет
        # права оставить слой ни в новом состоянии, ни в полупустом — тот же
        # порядок «сперва проверить, потом разрушать», что у CRM.reconfigure (R9).
        validate_layer_section(body, layer=layer)
        stray = unknown_section_keys(body)
        with self._lock:
            if layer == LAYER_RECIPE:
                self.recipe = body
                if source is not None:
                    self.recipe_source = source
            else:
                self.app = body
                if source is not None:
                    self.app_source = source
            keys = tuple(sorted(flatten_section(body).keys()))
        self.audit.record(
            ACTION_LAYER,
            origin=origin,
            key=layer,
            keys=keys,
            source=source or "",
            # `or None` — штатный способ сказать «поля нет»: `record` пропускает
            # None-экстры (см. её тело). Пустой список читался бы как «проверено
            # и чисто» ровно так же, как отсутствие поля, но выедал бы кольцо
            # аудита на всех здоровых дорогах.
            unknown_keys=stray or None,
        )
        return keys

    def session_forget_expiry(self, keys: Iterable[str]) -> Tuple[str, ...]:
        """Снять сроки с ключей, переехавших из L3 в L2 (``observability.persist``).

        Файл вечен по построению, и срок на нём — ложь. Возврат — с каких ключей
        срок действительно снят: «сохранил, а оно всё равно откатилось» и
        «сохранил, срок снят» обязаны различаться в ответе команды.

        Task 5.9 — в аудит НЕ пишет, и это не пропуск: метод снимает дедлайны, а
        не содержимое L3, и зовут его двое с разными намерениями (переезд в L2 и
        зачистка устаревшей под-секции при ``replace``). Записывать оба одним
        действием значило бы соврать одному из них; запись кладёт тот, кто знает
        намерение, — команда.
        """
        with self._lock:
            return tuple(sorted(key for key in keys if self.session_expiry.pop(key, None) is not None))

    # -------------------------------------------------------- provenance

    def provenance(self, expanded_logger: Optional[Mapping[str, Any]] = None) -> Dict[str, Dict[str, str]]:
        """Слой-победитель для каждого действующего ключа секции.

        Args:
            expanded_logger: секция ``logger`` из :func:`expand_observability`
                (нужна, чтобы назвать слой у МАТЕРИАЛИЗОВАННЫХ ``channels``/
                ``scopes``: их имена появляются только после раскладки).

        Returns:
            ``{ключ: {"layer": ..., "source": ...}}``. Ключи — в сыром
            namespace секции (``log_level``, ``errors.level``,
            ``channels.<имя>.enabled``), потому что править оператор будет
            именно их, а не имена полей manager-конфига.
        """
        explicit: Dict[str, Tuple[str, str]] = self._provenance_leaves()

        out: Dict[str, Dict[str, str]] = {}

        # 1. Все поля схемы: явно заданное — со своего слоя, остальное — L0.
        for key in _schema_keys():
            layer, source = explicit.get(key, (LAYER_FRAMEWORK, LAYER_FRAMEWORK))
            out[key] = {"layer": layer, "source": source}

        # 2. Явные ключи вне плоского набора схемы (channels.*/scopes.* задают
        #    произвольные имена) — их слой известен точно.
        for key, (layer, source) in explicit.items():
            out[key] = {"layer": layer, "source": source}

        # 3. Материализованные ключи: имя канала/скоупа появилось из дефолта L0,
        #    но управляет им тот слой, который тронул породившую ручку.
        if expanded_logger:
            out.update(self._materialized_provenance(expanded_logger, explicit, out))
        return out

    def _materialized_provenance(
        self,
        expanded_logger: Mapping[str, Any],
        explicit: Mapping[str, Tuple[str, str]],
        already: Mapping[str, Dict[str, str]],
    ) -> Dict[str, Dict[str, str]]:
        """Слой у ключей, которых в сырых секциях нет — их материализовал expand."""
        out: Dict[str, Dict[str, str]] = {}

        channels = expanded_logger.get("channels")
        if isinstance(channels, dict):
            for name, body in channels.items():
                if not isinstance(body, dict):
                    continue
                for field_name in body:
                    key = f"channels.{name}.{field_name}"
                    if key in explicit:
                        continue
                    # `enabled` каналов рождается оптовым тогглом console/file;
                    # остальные поля канала — чистый дефолт L0.
                    toggle = _channel_toggle(str(body.get("type", "")))
                    if field_name == "enabled" and toggle and toggle in explicit:
                        layer, source = explicit[toggle]
                    else:
                        layer, source = LAYER_FRAMEWORK, LAYER_FRAMEWORK
                    out[key] = {"layer": layer, "source": source}

        scopes = expanded_logger.get("scopes")
        if isinstance(scopes, dict):
            level_owner = explicit.get("log_level")
            for name, body in scopes.items():
                if not isinstance(body, dict):
                    continue
                for field_name in body:
                    key = f"scopes.{name}.{field_name}"
                    if key in explicit or key in out:
                        continue
                    if level_owner is not None:
                        layer, source = level_owner
                    else:
                        layer, source = LAYER_FRAMEWORK, LAYER_FRAMEWORK
                    out[key] = {"layer": layer, "source": source}

        # Уже объяснённое явными ключами не переписываем.
        return {k: v for k, v in out.items() if k not in explicit and k not in already}

    def _provenance_leaves(self) -> Dict[str, Tuple[str, str]]:
        """``{ключ: (слой, источник)}`` — владелец каждого ЯВНОГО листа слоёв.

        Считается тем же наложением, что и :meth:`resolve` (:func:`_overlay_owner`
        зеркалит :func:`layer_merge`): слой, объявивший ветку листом — пустым
        ``{}`` или скаляром, — затеняет ключи нижних слоёв под этой веткой. Прежняя
        редакция плющила каждый слой независимо (``flatten_section`` по слою) и
        верхний ``scopes: {}`` не затенял нижний ``scopes.SYSTEM.min_level``:
        provenance называл слой у ключа, которого в resolve уже нет (A-A4-1).
        """
        tree: Dict[str, Any] = {}
        for layer, section, source in self.raw_layers():
            _overlay_owner(tree, section, (layer, source or layer))
        return _flatten_owner_tree(tree)


def read_process_config(svc: Any, key: str, default: Any = None) -> Any:
    """Прочитать per-process ключ конфига независимо от того, КАК он доехал.

    Оркестратор получает конфиг ПЛОСКИМ (``spawner`` мержит ``orchestrator_config``
    в корень), а дочерний процесс — ВЕСЬ ``proc_dict`` (``process_runner`` отдаёт
    ``custom["process_config"]``), поэтому его ключи лежат под ``config.``.
    Один и тот же ``get_config("ключ")`` в первом случае работает, во втором молча
    возвращает ``None``.

    Найдено ЖИВЫМ прогоном 5.12: ``observability.persist`` на дочернем процессе
    ответил «путь к рецепту неизвестен», хотя ключ лежал в его ``proc_dict``.
    Тесты этого не видели — они подают ``svc`` с плоским словарём, то есть
    доказывали фейк. Это же место объясняет, почему ``telemetry_override``
    (та же форма чтения, находка C задачи 2.2) на детях не срабатывал.

    Порядок намеренно «плоский → вложенный»: оркестратор не должен платить
    лишним обходом, а совпадений имён между корнем proc_dict
    (``class``/``queues``/``managers``) и секцией ``config`` нет.
    """
    get_config = getattr(svc, "get_config", None)
    if not callable(get_config):
        return default
    value = get_config(key, None)
    if value is None:
        value = get_config(f"config.{key}", None)
    return default if value is None else value


def layers_are_silent(layers: ObservabilityLayers) -> bool:
    """Слои ничего не объявили → накладывать НЕЧЕГО, и это не то же самое, что «наложить пустое».

    Правило одно, продакшн-адресатов **два**: общий шов раскладки в слои
    (`apply_layers_to_proc_dict`, обслуживает обе дороги сборки) и пересборка на
    boot (`process_module`). До ревью 5.13 правило жило тремя разными редакциями:
    generic-дорога проверяла, прикладная — нет, boot — нет; сведение двух дорог
    сборки в один шов и сделало из трёх адресатов два. Расхождение было латентным
    ровно до первого процесса с молчащими слоями.

    (Число сверено с кодом 2026-08-02, корзина 2 п.11: прежняя редакция говорила
    «адресатов три» уже после того, как дороги свелись.)

    Почему пустое накладывать нельзя: ``expand_observability({})`` — это не пустой
    словарь, а ПОЛНЫЙ набор дефолтов L0. Наложенный на готовую секцию менеджеров,
    он затирает то, что пришло другим путём и слоями не описано, — уровень из
    ``MULTIPROCESS_LOG_LEVEL`` (``managers_from_log_dir``) или конфиг, собранный
    встройщиком фреймворка программно. Молчание слоёв означает «решает нижний»,
    а не «сбросить к дефолтам».
    """
    return not layers.resolve()


def apply_layers_to_proc_dict(proc_dict: Dict[str, Any], layers: ObservabilityLayers) -> None:
    """Наложить слои на ``proc_dict["managers"]`` НА МЕСТЕ. Слои молчат → proc_dict не тронут.

    Единственная раскладка «слои → менеджеры» для обеих дорог сборки (generic
    ``assemble_proc_dicts`` и прикладной ``BlueprintAssembler``). До ревью 5.13
    это были две копии, и они уже разошлись: generic проверяла молчание слоёв,
    прикладная накладывала безусловно — то есть у процесса с молчащими слоями
    появлялся ключ ``managers``, целиком собранный из дефолтов L0.

    «Не тронут» здесь буквально: словарь не мутируется вовсе. В реальной сборке
    секция ``managers`` к этому моменту УЖЕ существует и заполнена
    (``managers_from_log_dir``: каталог логов, пути файлов, уровень из
    ``MULTIPROCESS_LOG_LEVEL``) — поэтому цена наложения пустого не «появится лишний
    ключ», а «уровень из окружения молча вернётся к дефолту L0». Именно это
    расхождение и было латентным между двумя дорогами.
    """
    if layers_are_silent(layers):
        return
    from .managers_config import merge_managers
    from .observability_config import expand_observability

    proc_dict["managers"] = merge_managers(
        proc_dict.get("managers", {}),
        expand_observability(layers.resolve()),
    )


def process_observability_layers(svc: Any) -> ObservabilityLayers:
    """Стек слоёв ЭТОГО процесса — один на процесс, создаётся лениво.

    L1/L2 приезжают в ``proc_dict["config"]`` (ассемблер), L3 рождается пустым и
    живёт до конца процесса. Кэш на объекте процесса, а не пересборка на каждый
    вызов: L3 — это состояние, и пересоздавать его значило бы терять ручку
    оператора при каждой команде.

    Процесс без обоих ключей (тесты, одиночный запуск) получает пустой стек —
    работоспособный, просто без объяснимого происхождения ключей.
    """
    existing = getattr(svc, LAYERS_ATTR, None)
    if isinstance(existing, ObservabilityLayers):
        return existing

    app = read_process_config(svc, APP_CONFIG_KEY) or {}
    recipe = read_process_config(svc, OVERRIDE_CONFIG_KEY) or {}
    app_source = str(read_process_config(svc, "observability_config_path") or "")
    recipe_source = str(read_process_config(svc, RECIPE_PATH_CONFIG_KEY) or "")
    layers = ObservabilityLayers(
        app=dict(app) if isinstance(app, dict) else {},
        recipe=dict(recipe) if isinstance(recipe, dict) else {},
        app_source=app_source,
        recipe_source=recipe_source,
    )
    # Task 5.9: долговечный след аудита — журнал ЭТОГО процесса. Своего файла не
    # заводится: журнал уже долговечен, уже ротируется и уже единственный писатель
    # на диск. Процесс без журнала получает работающее кольцо без долговечности —
    # и это видно по отсутствию строк, а не по молчанию поля.
    layers.audit.log = make_audit_log(svc)
    try:
        setattr(svc, LAYERS_ATTR, layers)
    except Exception:  # noqa: BLE001 — объект без сеттеров: работаем без кэша, но работаем
        pass
    return layers


def validate_ttl(raw: Any) -> float:
    """``raw`` → секунды. Отрицательное/нечисловое — ``ValueError``, не «навсегда».

    Тихое приведение мусора к «бессрочно» дало бы худшую из возможных ошибок:
    опечатка оператора выглядела бы как успех и снимала бы ровно ту защиту, ради
    которой параметр введён.
    """
    if isinstance(raw, bool):  # bool — подкласс int, но `ttl=True` это не «1 секунда»
        raise ValueError(f"ttl={raw!r} — не число секунд")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"ttl={raw!r} — не число секунд") from None
    if value != value or value == float("inf"):  # NaN / inf
        raise ValueError(f"ttl={raw!r} — не конечное число секунд")
    if value < 0:
        raise ValueError(f"ttl={raw!r} — срок не может быть отрицательным (0 = бессрочно)")
    if value > MAX_SESSION_TTL_SEC:
        # Поле схемы объявляет max=86400, но параметр команды и сырой ключ слоя
        # шли мимо этой проверки: `ttl=10**9` принимался и означал «вечно» под
        # видом срока. Advisory ревью 5.8 — граница одна на оба входа.
        raise ValueError(f"ttl={raw!r} — больше предела {MAX_SESSION_TTL_SEC:.0f}с (0 = бессрочно явно)")
    return value


_DEFAULT_TTL_CACHE: Optional[float] = None


def _default_session_ttl() -> float:
    """Дефолт L0 — берётся из схемы, а не из литерала здесь.

    Второй литерал стал бы вторым источником истины: поменяли бы поле схемы, а
    ручка продолжила бы жить по старому числу.
    """
    global _DEFAULT_TTL_CACHE
    if _DEFAULT_TTL_CACHE is None:
        from .observability_config import ObservabilityConfig

        _DEFAULT_TTL_CACHE = float(ObservabilityConfig().session_ttl_sec)
    return _DEFAULT_TTL_CACHE


def _reject_path_inside_opaque(path: str) -> None:
    """Запрет на дотированный путь ВНУТРЬ непрозрачного листа (R3b, A-A1-2).

    Непрозрачный лист (``telemetry.throttle``) хранит правила ПЛОСКИМ словарём, где
    имена-паттерны сами содержат точки. Путь вида
    ``telemetry.throttle.processes.**.state.fps``, разрезанный :meth:`session_set`
    по точкам, завёл бы в слое вложенное дерево РЯДОМ с настоящим правилом — ровно
    тот дефект, ради которого лист и объявлен непрозрачным
    (:data:`OPAQUE_LAYER_PATHS`). Владеть таким листом можно ТОЛЬКО целиком:
    ``session_set("telemetry.throttle", {...})``.

    Production-вызывающих такого пути нет (операторские команды кладут дельту
    троттла листом целиком), но грабля латентна — закрываем громким отказом на
    входе, а не тихой порчей структуры слоя. Строгое ``startswith(opaque + ".")``:
    сам путь ``telemetry.throttle`` разрешён (владение листом), запрещён только
    спуск ГЛУБЖЕ него.
    """
    for opaque in OPAQUE_LAYER_PATHS:
        if path.startswith(f"{opaque}."):
            raise ValueError(
                f"путь {path!r} ведёт ВНУТРЬ непрозрачного листа {opaque!r}: "
                f"владеть им можно только целиком — session_set({opaque!r}, {{...}})"
            )


def unknown_section_keys(section: Any) -> list[str]:
    """Пути секции, которых НЕТ в контракте наблюдаемости (задача 5.4).

    Механизм — round-trip через ТУ ЖЕ схему, из которой считается раскладка:
    ключ, не выживший в ``model_validate → model_dump(exclude_unset=True)``,
    схеме неизвестен (``extra`` у Pydantic — ``ignore``, лишнее отбрасывается
    молча). Второй таблицы «известных имён» здесь нет намеренно: она разошлась
    бы с первой на первом же новом поле, и тогда «неизвестный ключ» значило бы
    разное на двух дорогах одной команды.

    Ключ, заданный значением ПО УМОЛЧАНИЮ, выживает (``model_fields_set``),
    поэтому «совпал с дефолтом» и «опечатка» не путаются.

    Две границы механизма — обе найдены разведкой ДО правки, обе стали бы
    ложными ОТКАЗАМИ, если бы сверка пошла по сырым путям:

    * **``telemetry``** снимается до сверки. Схема наблюдаемости про эту
      плоскость не знает вовсе (её ключи разбирает
      :func:`validate_telemetry_section`, а раскладка снимает ключ в
      ``_rebuild_and_apply``), и round-trip объявлял незнакомым КАЖДЫЙ путь
      законной телеметрийной правки (``telemetry.publish.tick_sec``);
    * **регистр имени скоупа** приводится :func:`~.observability_config.canonical_scope_keys`
      — тем же правилом, которым его приводит схема. Иначе законное
      ``scopes.system`` не совпадало бы с выжившим ``scopes.SYSTEM``.

    Значение, отвергнутое схемой, даёт ПУСТОЙ ответ: судить имена там нечем, и
    об этом входе говорит :func:`validate_layer_section` — своим отказом, с
    адресом ключа. Иначе один и тот же мусор получил бы два разных объяснения.

    Returns:
        Отсортированные ПУТИ (``logger.default_level``, ``errors.lvl``), а не
        голые имена: оператор правит текст, и «где именно» ему нужнее.
    """
    if not isinstance(section, dict) or not section:
        return []
    from .observability_config import ObservabilityConfig, canonical_scope_keys

    body = {key: value for key, value in section.items() if key != TELEMETRY_KEY}
    if not body:
        return []
    if "scopes" in body:
        body = {**body, "scopes": canonical_scope_keys(body["scopes"])}
    try:
        survived = ObservabilityConfig.model_validate(body).model_dump(exclude_unset=True)
    except Exception:  # noqa: BLE001 — негодное ЗНАЧЕНИЕ судит validate_layer_section
        return []
    return sorted(set(flatten_section(body)) - set(flatten_section(survived)))


def format_unknown_keys(keys: Iterable[str], *, layer: str, source: Optional[str] = None) -> str:
    """Одна формулировка отказа и громкой строки — задача 5.4.

    Текст называет ПОСЛЕДСТВИЕ («ключ есть, эффекта нет»), а не только факт: из-за
    него опечатку и не замечают. Подсказка о похожих именах считается по полям
    схемы через ``difflib``, а не по своему списку: список разошёлся бы со схемой.
    Ровно этот класс и дал находку — оператор подал ``logger.default_level``
    (машинную форму, которой на этой границе нет) и получил «успех».
    """
    from difflib import get_close_matches

    from .observability_config import ObservabilityConfig

    paths = sorted(str(key) for key in keys)
    known = list(ObservabilityConfig.model_fields)
    hints: list[str] = []
    for path in paths:
        segments = path.split(".")
        # Ищем похожее и по КОРНЮ пути, и по его листу. Одного корня мало ровно на
        # том входе, который дал находку: у `logger.default_level` корень похож на
        # `loggers`/`logger_groups`, а нужное имя — `log_level`, и оно похоже на
        # ЛИСТ (`default_level`). Подсказка, не называющая человеческую форму
        # машинной, оставила бы оператора там же, где он стоял.
        for probe in {segments[0], segments[-1]}:
            hints.extend(get_close_matches(probe, known, n=2, cutoff=0.6))
    where = f" ({source})" if source else ""
    tail = f"; возможно, имелось в виду: {', '.join(sorted(set(hints)))}" if hints else ""
    return (
        f"слой {layer} отвергнут{where} — ключей нет в контракте наблюдаемости "
        f"(ключ есть, эффекта нет): {', '.join(paths)}{tail}"
    )


def validate_layer_section(section: Any, *, layer: str) -> None:
    """Проверить секцию наблюдаемости ДО записи в слой (B2, major-8).

    Проверка имени уровня жила ТОЛЬКО на резолве — в ``LoggerManagerConfig``,
    то есть срабатывала уже после того, как значение записано в слой.
    Воспроизведено до правки: ``config.reload {"log_level": "БОЛТОВНЯ"}`` →
    ``success: true``, мусор лёг в L3 со сроком, применение откатилось,
    действовал прежний уровень. «Успех» означал «команда не упала», а оператор
    читает его как «значение действует».

    Стоит на ГРАНИЦЕ записи и одна на все слои: L1 и L2 (:meth:`replace_layer`),
    L3 целой секцией (``config.reload`` inline) и L3 одним ключом
    (:meth:`session_set`). Persist наследует гарантию через ``replace_layer``.
    Проверка в одном из четырёх мест воскресала бы на трёх соседних.

    **Пятое место — телеметрия, и до задачи 2.1 его здесь не было.** Ревью
    приёмки (Н-4) назвало докстринг враньём, и по делу: ``_merge_telemetry_layer``
    пишет ``layers.session`` ПРЯМЫМ присваиванием, а ключ ``telemetry`` эта
    функция не знала вовсе — секция ``ObservabilityConfig`` принимает лишние
    ключи молча, поэтому мусор в ``publish``/``throttle`` проезжал границу без
    единого возражения. Теперь ключ разбирает :func:`validate_telemetry_section`
    — то же правило, а не вторая его реализация; мест применения по-прежнему
    столько, сколько дверей в слой.

    **ИМЕНА ключей — с задачи 5.4, и только у слоя сессии.** Прежняя редакция
    отдавала имена вердикту ``config.reload`` (``unknown_keys`` →
    ``verdict=failed``) с доводом «второй предохранитель на то же место сделал
    бы неизвестным, который из них держит». Приёмка F2 (находки Н-C/Н-D)
    показала цену: незнакомый ключ — включая машинную форму
    ``logger.default_level``, которой на этой границе нет, — отвечал
    ``success=true``, оседал в L3 со сроком и не действовал, а честный
    ``verdict="failed"`` лежал в ТОМ ЖЕ ответе и противоречил ``success``.
    Оператор читает ``success``. Мерило 2 плана требует буквально: «мусор любого
    рода (значение, тип, **ключ**) — адресный отказ».

    Разведены не по важности, а **по двери**, и это не второй предохранитель на
    то же место:

    * ``session`` (ручка оператора: ``config.reload`` inline, ``session_set``) →
      **отказ ДО записи**. Имя написано руками сейчас, и узнать об опечатке
      через час по отсутствию логов дороже;
    * ``framework``/``app``/``recipe`` (файл, спутник, конверт switch'а) →
      молчание здесь и громкая строка у вызывающего. Отказ означал бы, что
      опечатка в спутнике валит switch рецепта или старт процесса. Та же
      политика и по той же причине, что у ссылок без приёмника
      (:mod:`.observability_refs`), — одна на два соседних класса опечаток.

    Вердикт при этом НЕ становится мёртвым слоем: ``unknown_keys`` по-прежнему
    единственный ответ на файловой дороге, где отказа нет.

    Raises:
        ValueError: значение не годится (текст несёт адрес ключа и список
            допустимых значений) ЛИБО — у слоя сессии — ключа нет в контракте
            (текст несёт путь и похожие известные имена).
    """
    if not isinstance(section, dict) or not section:
        return
    from pydantic import ValidationError

    from .observability_config import ObservabilityConfig

    if TELEMETRY_KEY in section:
        # Ключ снимается ДО схемы наблюдаемости: она про него не знает и,
        # принимая лишнее молча, вернула бы «годится» на любое содержимое.
        validate_telemetry_section(section[TELEMETRY_KEY], layer=layer)
        section = {k: v for k, v in section.items() if k != TELEMETRY_KEY}
        if not section:
            return

    try:
        ObservabilityConfig.model_validate(section)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            address = ".".join(str(part) for part in err.get("loc", ())) or "<секция>"
            problems.append(f"{address}: {err.get('msg', '')}")
        raise ValueError(f"слой {layer} отвергнут — " + "; ".join(problems)) from exc

    # Задача 5.4: имена — после значений и только у ручки оператора (см. докстринг).
    # Порядок именно такой: негодное ЗНАЧЕНИЕ известного ключа обязано получить
    # свой текст со списком допустимых, а не общий «ключа нет в контракте».
    if layer == LAYER_SESSION:
        unknown = unknown_section_keys(section)
        if unknown:
            raise ValueError(format_unknown_keys(unknown, layer=layer))


def validate_telemetry_section(section: Any, *, layer: str) -> None:
    """Проверить секцию ``telemetry`` ДО записи в слой (Task 2.1, находка Н-4).

    Плоскость телеметрии живёт в тех же слоях, что и логи, но её содержимое до
    этой задачи не судил никто. Воспроизведено на харнессе ``test_telemetry_*``:

    * ``telemetry.reconfigure {"publish": {"default_interval_sec": "быстро"}}``
      → ``success=false`` (мусор ловит Pydantic уже У ПОЛУЧАТЕЛЯ), но в слое L3
      к этому моменту ЛЕЖИТ ``telemetry.publish.default_interval_sec: "быстро"``.
      Дальше отравленный слой ломает **соседа**: следующий, совершенно законный
      ``config.reload {"observability": {"log_level": "DEBUG"}}`` того же процесса
      отвечает ``reconfigure failed: … TelemetryPublishConfig``. Оператор, который
      телеметрию не трогал, не может сменить уровень логов ближайшие 300 секунд —
      до истечения срока правки, которой ему официально отказали;
    * ``telemetry.reconfigure {"throttle": {"processes.**.state.fps": "часто"}}``
      → ``success=true``, правило доехало до живого ``ThrottleMiddleware``, и на
      ВТОРОЙ записи по этому пути стор падает с ``TypeError: unsupported operand
      type(s) for /: 'float' and 'str'``. Следствие Н-4 числилось гипотезой —
      теперь оно с репро;
    * опечатка в имени под-секции (``pubish``) вела себя ПО-РАЗНОМУ на двух
      дверях: без секции ``observability`` рядом — тихий no-op, вместе с ней —
      ключ ``telemetry.pubish.tick_sec`` ложился в L3 под срок и попадал в
      ``session_keys``. Один и тот же ввод, два ответа, оба неверные.

    Список под-секций ЗАКРЫТ (:data:`TELEMETRY_SUBSECTIONS`). Незнакомое имя —
    это опечатка оператора, а не расширение протокола: своей секции у неё нет,
    применить её некому, и единственное, что она может, — занять место в слое и
    съесть срок. Цена решения названа честно: рецепт с под-секцией из БУДУЩЕЙ
    версии фреймворка будет отвергнут этой, а не принят наполовину.

    Args:
        section: значение ключа ``telemetry`` (``None`` — «слой про телеметрию
            молчит», законно).
        layer: имя слоя для текста отказа — тем же словом, что у соседа.

    Raises:
        ValueError: содержимое не годится; текст несёт адрес КАЖДОГО негодного
            ключа (все проблемы разом, а не первая попавшаяся).
    """
    if section is None:
        return
    if not isinstance(section, dict):
        raise ValueError(
            f"слой {layer} отвергнут — {TELEMETRY_KEY}: ожидается словарь под-секций "
            f"({'/'.join(TELEMETRY_SUBSECTIONS)}), получено {type(section).__name__}"
        )

    problems: list[str] = []
    unknown = [str(key) for key in section if key not in TELEMETRY_SUBSECTIONS]
    for key in sorted(unknown):
        problems.append(
            f"{TELEMETRY_KEY}.{key}: неизвестная под-секция телеметрии (известны: {', '.join(TELEMETRY_SUBSECTIONS)})"
        )

    if TELEMETRY_LAYERED_SUBSECTION in section:
        problems.extend(_telemetry_publish_problems(section[TELEMETRY_LAYERED_SUBSECTION]))
    if TELEMETRY_THROTTLE_SUBSECTION in section:
        problems.extend(_telemetry_throttle_problems(section[TELEMETRY_THROTTLE_SUBSECTION]))

    if problems:
        raise ValueError(f"слой {layer} отвергнут — " + "; ".join(problems))


def _telemetry_publish_problems(publish: Any) -> list[str]:
    """Негодные ключи ``telemetry.publish`` — судит СВОЯ схема плоскости.

    ``None`` — законная команда «выключить гейт» (все метрики каждый тик), и
    отвергать её было бы отказом в существующей операции. Всё остальное едет в
    :class:`~.telemetry_publish_config.TelemetryPublishConfig` — ту же схему, из
    которой получатель собирает гейт. Второй копии правил здесь нет: разъедься
    они, слой принимал бы то, чего получатель не умеет, — ровно сегодняшний
    дефект, только с другой стороны.
    """
    if publish is None:
        return []
    from pydantic import ValidationError

    from .telemetry_publish_config import MetricRule, TelemetryPublishConfig

    base = f"{TELEMETRY_KEY}.{TELEMETRY_LAYERED_SUBSECTION}"
    try:
        TelemetryPublishConfig.model_validate(publish)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            tail = ".".join(str(part) for part in err.get("loc", ()))
            problems.append(f"{base}.{tail}: {err.get('msg', '')}" if tail else f"{base}: {err.get('msg', '')}")
        return problems

    # Задача 5.7 (блокер Н2-4 переприёмки раунда 2). Значения проверены выше, а
    # ИМЕНА — нет: схема принимает лишние ключи молча, и `publish: {нет_такой_ручки:
    # …}` отвечал `success=true`, ложился в L3 со сроком 254 с, не имел readback'а и
    # ПОПУТНО включал гейт публикации. Задача 5.4 закрыла тот же класс у соседних
    # плоскостей и передала ключ `telemetry` сюда — а здесь судились только имена
    # ПОД-СЕКЦИЙ. Классический «фасад — белый список»: поле в схеме менеджера не
    # делает ручку управляемой, и делегирование соседу не делает её проверенной.
    #
    # Метрики НЕ трогаем: имя под `metrics` — это имя метрики, и незнакомое имя там
    # законно (конфиг сужает, а не объявляет белый список). Их судит существующий
    # `unknown_metrics` — голосом, а не отказом.
    if isinstance(publish, dict):
        known = set(TelemetryPublishConfig.model_fields)
        problems = [
            f"{base}.{key}: неизвестное поле секции публикации (известны: {', '.join(sorted(known))}); "
            f"правила метрик живут под 'metrics'"
            for key in sorted(str(k) for k in publish)
            if str(key) not in known
        ]
        rules = publish.get("metrics")
        if isinstance(rules, dict):
            rule_fields = set(MetricRule.model_fields)
            for name, rule in sorted(rules.items()):
                if not isinstance(rule, dict):
                    continue
                problems.extend(
                    f"{base}.metrics.{name}.{key}: неизвестное поле правила метрики "
                    f"(известны: {', '.join(sorted(rule_fields))})"
                    for key in sorted(str(k) for k in rule)
                    if str(key) not in rule_fields
                )
        if problems:
            return problems
    return []


def _telemetry_throttle_problems(throttle: Any) -> list[str]:
    """Негодные правила ``telemetry.throttle`` — схемы у плоскости нет, правила здесь.

    Дельта троттла — ПЛОСКИЙ словарь ``{glob-паттерн: интервал}``, и Pydantic-модели
    у неё нет по построению (ключи — произвольные имена путей). Поэтому три правила
    написаны здесь, и каждое стоит на своём репро:

    * **интервал — конечное неотрицательное число.** Строка доезжает до живого
      ``ThrottleMiddleware`` и роняет стор делением на неё (см. репро выше);
    * **``bool`` интервалом не считается.** ``True`` — подкласс ``int``, то есть
      «раз в секунду» под видом «включить»; тот же довод, по которому его
      отвергает :func:`validate_ttl`;
    * **``__clear__`` — только ``true``.** Применение сверяет маркер строго
      (``is True``), и ``__clear__: "yes"`` не очистит набор, а заведёт ПРАВИЛО с
      таким именем и строковым интервалом — то есть тихо сделает не то, о чём
      просили, да ещё и на горячем пути.

    ``None`` у паттерна остаётся законным: это родной маркер
    ``THROTTLE_REMOVE`` («снять правило») в режиме ``merge``, а в ``replace`` —
    просто путь без правила.

    Адрес в тексте — ``telemetry.throttle[паттерн]``, а НЕ через точку: точки
    внутри паттерна часть имени, и точечная форма назвала бы оператору путь,
    который слои запрещают (:func:`_reject_path_inside_opaque`).
    """
    from ..managers.telemetry_reload import THROTTLE_CLEAR_MARKER

    if throttle is None:
        return []
    if not isinstance(throttle, dict):
        return [
            f"{TELEMETRY_THROTTLE_PATH}: ожидается словарь {{паттерн: интервал_сек}}, "
            f"получено {type(throttle).__name__}"
        ]

    problems: list[str] = []
    for pattern, interval in throttle.items():
        address = f"{TELEMETRY_THROTTLE_PATH}[{pattern!r}]"
        if not isinstance(pattern, str):
            problems.append(f"{address}: паттерн правила обязан быть строкой")
            continue
        if pattern == THROTTLE_CLEAR_MARKER:
            if interval is not True:
                problems.append(
                    f"{address}: маркер полной очистки принимает только true "
                    f"(получено {interval!r}); иначе это правило с таким именем, а не очистка"
                )
            continue
        if interval is None:  # THROTTLE_REMOVE — снять правило
            continue
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            problems.append(f"{address}: интервал должен быть числом секунд, получено {interval!r}")
            continue
        if interval != interval or interval in (float("inf"), float("-inf")):
            problems.append(f"{address}: интервал должен быть конечным числом секунд, получено {interval!r}")
            continue
        if interval < 0:
            problems.append(f"{address}: интервал не может быть отрицательным (0 — полная блокировка)")
    return problems


def _channel_toggle(channel_type: str) -> str:
    """Какая оптовая ручка секции управляет ``enabled`` канала этого типа."""
    if channel_type == "console":
        return "console"
    if channel_type == "file":
        return "file"
    return ""


def _is_layer_leaf(value: Any, path: str) -> bool:
    """Лист ли это для бухгалтерии слоёв — ОДНО определение на все обходы дерева.

    Листом считается всё, во что спускаться нельзя или незачем: не-словарь,
    пустой словарь (``{}`` — владение пустотой, правило Г3) и любой путь из
    :data:`OPAQUE_LAYER_PATHS`, каким бы ни было его содержимое.

    Заведено корзиной 2.2 по замечанию независимого ревью: тот же предикат стоял
    БУКВА В БУКВУ в трёх обходах (:func:`flatten_section`, :func:`layer_merge`,
    :func:`_overlay_owner`), и расхождение между ними — вопрос времени, а не
    вероятности. Расхождение ровно этого рода уже стреляло дважды: resolve против
    provenance (A-A4-1) и мерж против плющения (находка Ф-3). Второй непрозрачный
    путь — а константа объявлена ``frozenset``, то есть он предусмотрен — был бы
    третьим случаем. Обходы остаются РАЗНЫМИ (они строят разные результаты:
    слитый dict, плоскую карту, дерево владельцев), общим стало решение.
    """
    return not (isinstance(value, dict) and value and path not in OPAQUE_LAYER_PATHS)


def flatten_section(section: Any, prefix: str = "") -> Dict[str, Any]:
    """Вложенный dict → ``{"a.b.c": значение}`` по листьям.

    Пустой dict — тоже лист: ``{"scopes": {}}`` даёт ключ ``scopes``. Иначе
    «слой задал пустую карту» и «слой не сказал ничего» стали бы неотличимы.

    Пути из :data:`OPAQUE_LAYER_PATHS` — тоже листья, каким бы ни было их
    содержимое (Task 5.10.g). См. константу: там объяснено, почему.
    """
    out: Dict[str, Any] = {}
    if not isinstance(section, dict):
        return out
    for key, value in section.items():
        path = f"{prefix}{key}"
        if _is_layer_leaf(value, path):
            out[path] = value
        else:
            out.update(flatten_section(value, prefix=f"{path}."))
    return out


def layer_merge(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
    *,
    prefix: str = "",
) -> Dict[str, Any]:
    """Наложить слой ``overlay`` на ``base`` по правилу Г3 (решение владельца 2026-08-02).

    Отличие от канонического ``deep_merge`` ровно одно и намеренное: **непустой
    ключ верхнего слоя ВЛАДЕЕТ, включая пустой словарь**. Правило целиком: нет
    ключа → наследую нижний; ключ есть, что бы в нём ни лежало (скаляр, список,
    ``null``, ``{}``) → владею. Единственный способ сказать «наследую» — отсутствие
    ключа; ``{}`` остаётся за «здесь пусто, и это моё решение» (законная настройка
    «в этом рецепте приёмников нет»).

    Рекурсия — только в НЕПУСТОЙ словарь поверх словаря: тогда владение адресное,
    по-ключевое (``errors: {level: ERROR}`` не сносит ``include_stacktrace`` соседа).
    ``deep_merge`` рекурсировал и в пустой overlay-словарь, где ``if not overlay:
    return base`` возвращал нижний — из-за чего resolve отдавал значение нижнего
    слоя, а provenance (через ``flatten_section``, где ``{}`` — лист) называл
    верхний: расхождение A-A4-1. Здесь resolve и provenance пользуются ОДНИМ
    правилом различения (см. :meth:`ObservabilityLayers._provenance_leaves`).

    Верхнеуровневый пустой ``overlay`` (весь слой пуст) по-прежнему наследует —
    это «слой молчит» (:func:`layers_are_silent`), а не «слой владеет пустотой»:
    пустой namespace нельзя объявить владением, потому что владеть в нём нечем.

    **Непрозрачные пути (:data:`OPAQUE_LAYER_PATHS`) — листья и здесь.** Спуска в
    них нет: значение верхнего слоя заменяет нижнее ЦЕЛИКОМ. Без этого мерж
    расходился с двумя другими обходами того же дерева — ``flatten_section`` и
    ``_overlay_owner`` знают про непрозрачность с 5.10.g, а мерж не знал. Цена
    расхождения не теоретическая (ревью корзины 2, находка Ф-3): дельта троттла
    верхнего слоя сливалась с нижней ПО КЛЮЧАМ, то есть правило, которое оператор
    снял, продолжало действовать, — а provenance при этом называл верхний слой
    владельцем листа целиком. Два ответа об одном ключе, снова расходящиеся.

    Args:
        prefix: путь до ``base``/``overlay`` в дереве секции. Нужен только для
            сверки с :data:`OPAQUE_LAYER_PATHS`. Мержащие от КОРНЯ секции его не
            передают; единственный вызывающий, который передаёт, —
            ``_apply_telemetry_from_layers`` (``"telemetry.publish."``), и под этим
            префиксом сверка холостая: непрозрачных путей внутри ``publish`` нет
            по построению — их имена не содержат точек, ради чего разведение с
            ``throttle`` и заводилось. Передаётся он там не «на всякий случай», а
            чтобы вложенный мерж не начал считать пути от чужого корня, если
            непрозрачный путь под ``publish`` когда-нибудь появится.
            *(Ревью корзины 2.1: здесь стояло «все сегодняшние вызывающие его не
            передают» — утверждение опровергал тот же коммит.)*
    """
    result = copy.deepcopy(base)
    if not overlay:
        return result
    for key, value in overlay.items():
        path = f"{prefix}{key}"
        if not _is_layer_leaf(value, path) and isinstance(result.get(key), dict):
            result[key] = layer_merge(result[key], value, prefix=f"{path}.")
        else:
            result[key] = copy.deepcopy(value)
    return result


def _overlay_owner(
    tree: Dict[str, Any],
    section: Any,
    owner: Tuple[str, str],
    prefix: str = "",
) -> None:
    """Наложить владельца ``owner`` на дерево провенанса ТЕМ ЖЕ правилом, что :func:`layer_merge`.

    Лист (скаляр/список/``null``/``{}``/непрозрачный путь) ЗАМЕНЯЕТ поддерево нижнего
    слоя владельцем — так пустой ``scopes: {}`` наверху затеняет ``scopes.SYSTEM.*``
    снизу, в точности как это делает resolve. Без этого провенанс называл бы слой у
    ключа, которого в resolve уже нет (A-A4-1).
    """
    if not isinstance(section, dict):
        return
    for key, value in section.items():
        path = f"{prefix}{key}"
        if _is_layer_leaf(value, path):
            tree[key] = owner  # лист владеет: заменяет поддерево нижнего слоя
        else:
            node = tree.get(key)
            if not isinstance(node, dict):
                node = {}
                tree[key] = node
            _overlay_owner(node, value, owner, prefix=f"{path}.")


def _flatten_owner_tree(tree: Dict[str, Any], prefix: str = "") -> Dict[str, Tuple[str, str]]:
    """Дерево владельцев → ``{"a.b.c": (layer, source)}``. Кортеж-владелец — лист."""
    out: Dict[str, Tuple[str, str]] = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten_owner_tree(value, prefix=f"{path}."))
        else:
            out[path] = value
    return out


def _schema_keys() -> Iterable[str]:
    """Плоские ключи всех полей :class:`ObservabilityConfig` с дефолтами.

    Ленивый импорт: модуль слоёв не должен тянуть схему на импорт-тайме
    (её тянет expand, а слои стоят НАД ним).
    """
    from .observability_config import ObservabilityConfig

    dumped = ObservabilityConfig().model_dump()
    # channels/scopes у дефолта пусты: имён у них ещё нет, они появятся после
    # expand — и объясняются отдельной веткой (_materialized_provenance).
    dumped.pop("channels", None)
    dumped.pop("scopes", None)
    return flatten_section(dumped).keys()
