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

#: Имя процесса-оркестратора — ЕДИНСТВЕННЫЙ литерал в системе (Task 5.13).
#:
#: Живёт здесь, в самом нижнем модуле, которому это имя нужно, а спавнер и
#: остальные импортируют его отсюда. Обратное направление (константа у спавнера)
#: дало бы цикл: ``process_module`` ниже ``process_manager_module``.
#: До 5.13 имя было тремя расходящимися литералами — у спавнера (дважды) и
#: дефолтом конструктора ``ProcessManagerProcess``; при этом оно уже входило в
#: дисковый контракт (``observability.persist`` пишет спутник по ``svc.name``).
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

#: Путь дельты центрального троттла в слое сессии (Task 5.10.g).
TELEMETRY_THROTTLE_PATH = f"{TELEMETRY_KEY}.throttle"

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


def resolve_recipe_section(
    section: Any,
    process_name: str,
    *,
    include_defaults: Optional[bool] = None,
) -> Dict[str, Any]:
    """Сырая L2-дельта КОНКРЕТНОГО процесса из секции рецепта.

    ``defaults`` применяется всем процессам рецепта, ``processes[<имя>]``
    мержится поверх. Процесс, не названный в ``processes``, получает только
    ``defaults`` — и правка соседа его не задевает.

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

    Исключение решается ЗДЕСЬ, а не параметром у вызывающих: call-sites пять
    (два ассемблера, конверт switch, спутник, L2-watcher), три из них
    исполняются внутри самого процесса. Правило, которое каждый обязан не
    забыть передать, дало бы ``effective`` PM, зависящий от того, какой путь
    стрелял последним.

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
        include_defaults = process_name != ORCHESTRATOR_PROCESS_NAME
    if not include_defaults:
        return dict(per_process)
    declared = section.get("defaults")
    declared = declared if isinstance(declared, dict) else {}
    # Всё, что не служебные ключи — тоже defaults (короткая форма, возможно
    # смешанная со структурной после merge).
    inline = {k: v for k, v in section.items() if k not in ("defaults", "processes")}
    defaults = deep_merge(inline, declared) if inline else declared
    return deep_merge(defaults, per_process)


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
        """Сырая секция ``observability`` после наложения L1 → L2 → L3."""
        with self._lock:
            merged = deep_merge(self.app or {}, self.recipe or {})
            return deep_merge(merged, self.session or {})

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
                вместо тихого «значит, навсегда».
        """
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
        self.audit.record(ACTION_SET, origin=origin, key=path, value=value, ttl_sec=left)
        return left

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
            # Task 5.10.g: непрозрачный путь — сам себе лист, и перечислять его
            # содержимое нельзя: имена внутри (паттерны троттла) содержат точки,
            # и отчёт назвал бы ключи, которых в namespace не существует.
            if path in OPAQUE_LAYER_PATHS:
                leaves: tuple = ()
            else:
                leaves = tuple(sorted(flatten_section(self._node_at(path)).keys())) if self._node_at(path) else ()
            removed = tuple(f"{path}.{leaf}" for leaf in leaves) if leaves else (path,)
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
        """
        body = dict(section) if isinstance(section, dict) else {}
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
        self.audit.record(ACTION_LAYER, origin=origin, key=layer, keys=keys, source=source or "")
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
        explicit: Dict[str, Tuple[str, str]] = {}
        for layer, section, source in self.raw_layers():
            for key in flatten_section(section):
                explicit[key] = (layer, source or layer)

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


def _channel_toggle(channel_type: str) -> str:
    """Какая оптовая ручка секции управляет ``enabled`` канала этого типа."""
    if channel_type == "console":
        return "console"
    if channel_type == "file":
        return "file"
    return ""


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
        if isinstance(value, dict) and value and path not in OPAQUE_LAYER_PATHS:
            out.update(flatten_section(value, prefix=f"{path}."))
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
