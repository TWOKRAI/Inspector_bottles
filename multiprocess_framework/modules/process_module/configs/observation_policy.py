# -*- coding: utf-8 -*-
"""Политика публикации порта наблюдений — правила по ПУТИ дерева (Ф4, задача 4.1).

Соседний :mod:`.telemetry_publish_config` решает «поедет ли метрика» по ИМЕНИ
ЛИСТА (суффиксу): правило ``metrics.fps`` действует на любой ``fps``, где бы он
ни лежал. Пока листья плагинов лежали рядом с агрегатом фреймворка, различать их
было нечем; Ф1 развела их по путям (``processes.<P>.state.fps`` против
``processes.<P>.state.plugins.<писатель>.fps``), и адресовать одну плоскость, не
задев другую, стало ВЫРАЗИМО — но только на языке путей. Этот модуль и есть тот
язык: glob-выражение по дереву, движок — публичный матчер стора
(``state_store_module.match_pattern`` / ``split_pattern``), второго не заводится.

**Где живут ключи.** В секции ``observability`` (поле
:class:`~.observability_config.ObservabilityConfig.observation`), в тех же
четырёх слоях L0→L1→L2→L3, что и логи. Пятая дверь конфига не открывается
(решение владельца, зафиксировано в ``DECISIONS.md``, ADR-PM-041).

**Четыре источника решения, три из них называет оператор** (вариант «в»
развилки умолчания, решение владельца 2026-08-25):

* :data:`SOURCE_RULE` — явное правило оператора (``observation.rules``);
* :data:`SOURCE_SUBTREE_DEFAULT` — дефолтное правило поддерева порта
  (:data:`PORT_SUBTREE_PATTERN`) с ЯВНОЙ частотой значением
  (``observation.subtree_interval_sec``), а не подразумеваемой;
* :data:`SOURCE_WHITELIST` — легаси-секция ``telemetry.publish``: её белый список
  ``metrics.<имя>`` и её же умолчание ``default_enabled``. Она читается ТОЙ ЖЕ
  сборкой как ИМЕНОВАННЫЙ источник, а не второй дверью, и провенанс называет её
  вслух (:data:`LEGACY_SOURCE_NAME`);
* :data:`SOURCE_UNGATED` — легаси-секции нет вовсе. Паритет с сегодняшним
  ``ProcessHeartbeat._build_telemetry_gate`` → ``None``: вне поддерева порта
  гейта нет, метрика едет каждый тик.

**Порядок разрешения — ЯВНОСТЬ, затем longest-prefix** (ред. 2026-08-25, решение
владельца по блокеру Б1 ревью Ф4). Старший разряд ключа — ступень явности
источника (:func:`resolution_key`), и только внутри одной ступени спор решает
специфичность паттерна:

1. :data:`TIER_RULE` — явное правило оператора по пути (``observation.rules``);
2. :data:`TIER_LEGACY_ENTRY` — ЯВНАЯ запись легаси-белого-списка
   (``telemetry.publish.metrics.<имя>``): оператор написал это имя намеренно;
3. :data:`TIER_SUBTREE_DEFAULT` — дефолтное правило поддерева порта;
4. :data:`TIER_UMBRELLA` — зонтичные умолчания (``default_enabled`` легаси-секции,
   а также «легаси-секции нет вовсе»).

**Почему явность выше специфичности.** Владелец согласился на «два умолчания в
одной секции», но НЕ на «умолчание перебивает явное заявление оператора».
Воспроизведение до правки (ревью Ф4): при ``{"default_enabled": false,
"metrics": {"fps": {"enabled": false}}}`` — то есть оператор ЗАПРЕТИЛ ``fps`` —
путь ``processes.cam1.state.plugins.capture.fps`` резолвился в ``enabled=True``
источником ``subtree_default``, потому что у дефолта поддерева (3 литерала,
5 сегментов) специфичность выше, чем у суффиксной формы ``**.fps`` (1 литерал,
2 сегмента). Живое следствие: чекбокс и частота ПЛАГИННЫХ строк пульта не делали
ничего, а команда отвечала ``success``.

Критерий М1 при этом цел и сторожится тестом: у НОВОЙ метрики записи в
``metrics`` нет вовсе, поэтому легаси отвечает зонтиком
(:data:`TIER_UMBRELLA`), и дефолт поддерева его перекрывает — новая метрика
плагина по-прежнему едет при нулевых правках конфига.

Внутри :data:`TIER_RULE` порядок прежний и ОТЛИЧАЕТСЯ от соседа
``telemetry_reload._central_rule_for_metric`` (тот берёт СТРОЖАЙШИЙ интервал).
Расхождение намеренное, довод — в ``DECISIONS.md`` (ADR-PM-042): у соседа
предохранитель IPC, где строжайший ответ безопасен, а здесь — заявка оператора,
где выигрывать обязан ТОЧНЕЕ АДРЕСОВАННЫЙ, иначе широкое правило поддерева
навсегда перебивало бы точечное.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Dict, Iterable, Optional, Tuple

from pydantic import Field, field_validator

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...state_store_module import match_pattern, split_pattern
from .telemetry_publish_config import MetricRule, TelemetryPublishConfig

#: Адрес поддерева порта наблюдений в дереве состояния. Константа, а не ручка:
#: адрес поддерева — следствие конструкции Ф1 («владение = путь»), а не настройка.
#: Понадобится другой адрес — он выражается обычным правилом в ``rules``.
PORT_SUBTREE_PATTERN = "processes.*.state.plugins.**"

#: Умолчание частоты дефолтного правила поддерева, сек. ЗНАЧЕНИЕ, а не
#: подразумевание: предохранитель, который нельзя измерить, предохранителем не
#: является (прямое условие владельца, перенесённое в вариант «в» без ослабления).
DEFAULT_SUBTREE_INTERVAL_SEC = 1.0

#: Литералы источника решения — они же значения поля ``source`` в провенансе.
SOURCE_RULE = "rule"
SOURCE_SUBTREE_DEFAULT = "subtree_default"
SOURCE_WHITELIST = "whitelist"
SOURCE_UNGATED = "ungated"

#: Имя легаси-источника в провенансе — адрес, по которому оператор его грепнет.
LEGACY_SOURCE_NAME = "telemetry.publish"

#: **Ступени ЯВНОСТИ — старший разряд ключа разрешения** (:func:`resolution_key`).
#: Числа сравниваются, а не перечисляются по месту: порядок обязан быть один на
#: все ветки :meth:`ObservationPolicy.resolve`, иначе он превращается в набор
#: частных случаев, разъезжающихся при первой же правке.
TIER_RULE = 3  #: явное правило оператора по пути (`observation.rules`)
TIER_LEGACY_ENTRY = 2  #: явная запись `telemetry.publish.metrics.<имя>`
TIER_SUBTREE_DEFAULT = 1  #: дефолтное правило поддерева порта
TIER_UMBRELLA = 0  #: зонтик: `default_enabled` либо «легаси-секции нет вовсе»

#: Плейсхолдер имени процесса, когда гейт собран без него (прямая конструкция в
#: тесте). Один сегмент, поэтому ``processes.*.…`` продолжает совпадать, а
#: адресное ``processes.cam1.…`` — нет, и это честно: имени нам не сообщили.
PROCESS_UNKNOWN = "-"

#: Ключ под-секции внутри разрешённых слоёв ``observability``.
OBSERVATION_SECTION_KEY = "observation"

#: Путь набора правил в плоском namespace слоёв. Набор — НЕПРОЗРАЧНЫЙ лист
#: (см. ``observability_layers.OPAQUE_LAYER_PATHS``): ключи здесь — glob-паттерны,
#: а в них есть точки, и per-ключевая бухгалтерия слоёв резала бы паттерн на
#: сегменты пути — тот же слом, который уже разобран у ``telemetry.throttle``.
OBSERVATION_RULES_PATH = f"{OBSERVATION_SECTION_KEY}.rules"


@register_schema("ObservationPolicyConfig")
class ObservationPolicyConfig(SchemaBase):
    """Секция ``observability.observation`` — политика порта наблюдений.

    - ``subtree_enabled`` / ``subtree_interval_sec`` — дефолтное правило поддерева
      порта (:data:`PORT_SUBTREE_PATTERN`). Живёт отдельными полями, а не записью
      внутри ``rules``, по прозаичной причине: Pydantic заменяет словарь целиком,
      и первый же операторский ``rules: {…}`` снёс бы дефолт вместе с
      предохранителем. Разрешается оно в ТОМ ЖЕ glob-множестве и тем же ключом
      (:func:`resolution_key`, см. :meth:`ObservationPolicy.resolve`) —
      операторское правило перекрывает его ПОРЯДКОМ (ступень явности), а не
      особым случаем в коде;
    - ``rules`` — правила оператора: ``{glob-путь: {enabled, interval_sec}}``.
      Значение правила — тот же :class:`MetricRule`, что у легаси-секции: две
      схемы для одной формы разошлись бы на первом же новом поле.
    """

    subtree_enabled: Annotated[
        bool,
        FieldMeta(
            "Действует ли дефолтное правило поддерева порта",
            info=f"Поддерево — {PORT_SUBTREE_PATTERN}. False возвращает поддерево "
            "под общее умолчание секции telemetry.publish (deny-by-default с белым списком).",
        ),
    ] = True
    subtree_interval_sec: Annotated[
        float,
        FieldMeta("Частота дефолтного правила поддерева порта, сек", min=0.0),
    ] = DEFAULT_SUBTREE_INTERVAL_SEC
    rules: Annotated[
        Dict[str, MetricRule],
        FieldMeta("Правила по glob-пути дерева: {'processes.*.state.plugins.*.fps': {interval_sec: 1.0}}"),
    ] = Field(default_factory=dict)

    @field_validator("rules", mode="before")
    @classmethod
    def _reject_malformed_patterns(cls, value: Any) -> Any:
        """Отвергнуть паттерн, который не может совпасть ни с чем.

        Пустая строка и пустой сегмент (``a..b``, ``.a``) — это не «правило про
        экзотику», а опечатка: матчер режет паттерн по точкам, и пустой сегмент
        не совпадёт ни с одним сегментом пути НИКОГДА. Молчаливое принятие такого
        ключа дало бы ``success=true`` у правки, которая не делает ничего, —
        класс дефекта, названный в этом проекте «молчащий детектор наоборот».

        Опечатка в ИМЕНИ сегмента (``procesess`` вместо ``processes``) здесь не
        ловится и пойматься не может: имя процесса — прикладное, фреймворк его
        каталога не знает. Её голос — счётчик ``matched_nothing`` в readback'е
        (:meth:`ObservationPolicy.rules_matched_nothing`).
        """
        if not isinstance(value, dict):
            return value
        bad = sorted(str(key) for key in value if not str(key).strip() or any(seg == "" for seg in str(key).split(".")))
        if bad:
            raise ValueError(
                "observation.rules: пустой сегмент в glob-пути "
                f"({', '.join(repr(b) for b in bad)}) — такой паттерн не совпадёт ни с одним путём"
            )
        return value

    def to_dict(self) -> Dict[str, Any]:
        """Сериализовать в dict (Dict at Boundary — уходит в IPC/конфиг)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Any) -> "ObservationPolicyConfig":
        """Собрать из dict (граница процесса). ``None``/частичный → дефолты."""
        return cls.model_validate(data or {})


@dataclass(frozen=True)
class PolicyDecision:
    """Решение политики по ОДНОМУ пути дерева.

    Attributes:
        enabled: публиковать ли лист вообще.
        interval_sec: минимальный интервал публикации, сек.
        source: КТО решил — один из :data:`SOURCE_RULE` /
            :data:`SOURCE_SUBTREE_DEFAULT` / :data:`SOURCE_WHITELIST` /
            :data:`SOURCE_UNGATED`. Без этого поля оператор не отличает
            «разрешено дефолтом» от «разрешено руками», а в секции с ДВУМЯ
            разными умолчаниями (цена варианта «в») это единственный способ
            увидеть переворот с пульта.
        pattern: паттерн победившего правила (у легаси — суффиксная форма
            ``**.<имя>`` либо ``**`` у общего умолчания).
    """

    enabled: bool
    interval_sec: float
    source: str
    pattern: str


def pattern_specificity(pattern: str) -> Tuple[int, int, str]:
    """Ключ сортировки «longest-prefix» для glob-паттерна: больше — точнее.

    Три ступени, и третья не украшение:

    1. число ЛИТЕРАЛЬНЫХ сегментов (не ``*``/``**``) — сколько паттерн реально
       зафиксировал. Именно она делает ``…plugins.capture.fps`` точнее
       ``…plugins.*.fps``, а того — точнее ``…plugins.**``;
    2. общее число сегментов — при равном числе литералов длиннее значит уже;
    3. сам паттерн строкой — детерминизм. Без него два одинаково специфичных
       правила разрешались бы порядком словаря, то есть порядком строк в YAML,
       и «одинаковый конфиг — одинаковое поведение» перестало бы выполняться
       молча. Правило пары зафиксировано тестом с двумя пересекающимися
       правилами и литеральным ожиданием.
    """
    segments = split_pattern(pattern)
    literals = sum(1 for seg in segments if seg not in ("*", "**"))
    return (literals, len(segments), pattern)


def resolution_key(tier: int, pattern: str) -> Tuple[int, int, int, str]:
    """Полный ключ разрешения кандидата: **явность, затем longest-prefix**.

    Старший разряд — ступень явности источника (``TIER_*``), младшие три —
    :func:`pattern_specificity`. Порядок живёт ЗДЕСЬ, одной функцией, а не
    ветками в :meth:`ObservationPolicy.resolve`: правило «явное заявление
    оператора не проигрывает умолчанию» — свойство ПОРЯДКА, и спрятанное в
    ветку оно перестаёт быть проверяемым одним местом.

    Почему явность старше специфичности — в докстринге модуля (воспроизведение
    блокера Б1: дефолт поддерева перебивал операторский запрет ``metrics.fps``).
    """
    literals, segments, text = pattern_specificity(pattern)
    return (int(tier), literals, segments, text)


class ObservationPolicy:
    """Разрешение «поедет ли ЭТОТ путь и как часто» — одним glob-множеством.

    Тотальна по построению: у любого пути есть ответ, потому что легаси-источник
    (или его отсутствие) замыкает список кандидатов паттерном ``**``.

    Потокобезопасность: объект НЕИЗМЕНЯЕМ после сборки (правки прилетают новым
    объектом и атомарной подменой ссылки — тот же приём, что у
    ``ProcessHeartbeat._telemetry_gate``). Единственное изменяемое состояние —
    счётчик попаданий :attr:`_hits`, и его НАБОР КЛЮЧЕЙ фиксирован конструктором:
    поток такта только увеличивает значения, поэтому читатель ``introspect``
    обходит словарь, чей размер не меняется.
    """

    def __init__(
        self,
        config: Optional[ObservationPolicyConfig] = None,
        legacy: Optional[TelemetryPublishConfig] = None,
        *,
        hits: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Args:
            config: секция ``observability.observation`` (``None`` → дефолты L0,
                то есть дефолтное правило поддерева включено).
            legacy: секция ``telemetry.publish`` как ИМЕНОВАННЫЙ источник
                (``None`` → гейта вне поддерева порта нет вовсе).
            hits: счёт попаданий ПРЕДЫДУЩЕЙ политики (``{паттерн: сколько раз}``).
                Переносятся только те паттерны, которые есть и в новом наборе:
                правило с тем же текстом — то же правило, а переписанное
                оператором начинается с нуля честно.

                **Зачем перенос** (находка З3 ревью Ф4): политику пересобирает
                КАЖДАЯ соседняя правка (``telemetry.reconfigure``, любое движение
                пульта — ``_make_gate`` собирает новый объект). Без переноса
                чужая правка обнуляла бы счёт, и работающее правило возвращалось
                бы в ``rules_matched_nothing``, то есть единственный голос про
                опечатку в пути кричал бы на здоровые правила.
        """
        self._config = config if config is not None else ObservationPolicyConfig()
        self._legacy = legacy
        self._rules: Dict[str, MetricRule] = dict(self._config.rules)
        # Ключи фиксированы здесь и больше не меняются — см. докстринг класса.
        carried = hits or {}
        self._hits: Dict[str, int] = {pattern: int(carried.get(pattern, 0)) for pattern in self._rules}

    # ------------------------------------------------------------------ чтение

    @property
    def config(self) -> ObservationPolicyConfig:
        """Секция, из которой политика собрана (источник readback'а)."""
        return self._config

    @property
    def legacy(self) -> Optional[TelemetryPublishConfig]:
        """Легаси-секция ``telemetry.publish``, если она есть."""
        return self._legacy

    def resolve(self, path: str, *, count: bool = True) -> PolicyDecision:
        """Решение по полному пути дерева (``processes.cam1.state.plugins.a.fps``).

        Кандидаты собираются ВСЕ, победитель — старший по :func:`resolution_key`:
        сначала ступень ЯВНОСТИ (``TIER_*``), внутри неё — специфичность
        паттерна. Явное правило оператора и дефолт поддерева живут в одном
        множестве: если оператор написал ровно :data:`PORT_SUBTREE_PATTERN`, его
        запись вытесняет дефолт СТУПЕНЬЮ (правило явное, дефолт — нет), поэтому
        дефолт добавляется лишь когда такого паттерна нет в ``rules``.

        Args:
            path: полный путь листа в дереве состояния.
            count: считать ли попадания правил (``rules_matched_nothing``).
                ``False`` — для ДИАГНОСТИЧЕСКОГО чтения (:meth:`provenance_for`).
                Собственный докстринг соседа ``TelemetryGate.decide`` объявляет
                этот принцип дословно — «опрос состояния, меняющий состояние, это
                наблюдатель, который врёт о том, что наблюдает», — и до находки
                З3 ревью Ф4 нарушался ровно здесь: два подряд
                ``introspect.observability`` без единого такта процесса между
                ними убирали работающее правило из списка «не совпало ни с чем».
        """
        segments = tuple(str(path).split("."))
        best_key: Optional[Tuple[int, int, int, str]] = None
        best: Optional[PolicyDecision] = None

        def _offer(pattern: str, enabled: bool, interval: float, source: str, tier: int) -> None:
            nonlocal best_key, best
            key = resolution_key(tier, pattern)
            if best_key is None or key > best_key:
                best_key = key
                best = PolicyDecision(
                    enabled=bool(enabled), interval_sec=float(interval), source=source, pattern=pattern
                )

        default_interval = self._legacy.default_interval_sec if self._legacy is not None else 0.0

        for pattern, rule in self._rules.items():
            if match_pattern(split_pattern(pattern), segments):
                if count:
                    self._hits[pattern] = self._hits.get(pattern, 0) + 1
                interval = rule.interval_sec if rule.interval_sec is not None else default_interval
                _offer(pattern, rule.enabled, interval, SOURCE_RULE, TIER_RULE)

        cfg = self._config
        if (
            cfg.subtree_enabled
            and PORT_SUBTREE_PATTERN not in self._rules
            and match_pattern(split_pattern(PORT_SUBTREE_PATTERN), segments)
        ):
            _offer(
                PORT_SUBTREE_PATTERN,
                True,
                cfg.subtree_interval_sec,
                SOURCE_SUBTREE_DEFAULT,
                TIER_SUBTREE_DEFAULT,
            )

        if self._legacy is None:
            # Легаси-секции нет — гейта нет: паритет с `_build_telemetry_gate` → None.
            # Зонтик: это НЕ заявление про имя, а отсутствие механизма.
            _offer("**", True, 0.0, SOURCE_UNGATED, TIER_UMBRELLA)
        else:
            leaf = segments[-1] if segments else ""
            rule = self._legacy.metrics.get(leaf)
            if rule is not None:
                interval = rule.interval_sec if rule.interval_sec is not None else default_interval
                # Суффиксное правило `имя` ≡ `**.имя` — старые правила валидны буквально.
                # Ступень ЯВНАЯ: оператор написал это имя руками (блокер Б1).
                _offer(f"**.{leaf}", rule.enabled, interval, SOURCE_WHITELIST, TIER_LEGACY_ENTRY)
            else:
                # `default_enabled` — зонтик над ВСЕМИ именами, а не заявление про
                # это. Поэтому дефолт поддерева порта его перекрывает, и критерий
                # М1 («новая метрика — ноль правок конфига») цел.
                _offer("**", self._legacy.default_enabled, default_interval, SOURCE_WHITELIST, TIER_UMBRELLA)

        # `best` не может остаться None: последняя ветка всегда предлагает `**`.
        assert best is not None  # noqa: S101 — инвариант тотальности, а не проверка ввода
        return best

    # ------------------------------------------------------------- диагностика

    def rules_matched_nothing(self) -> list[str]:
        """Правила оператора, которые за жизнь политики не совпали ни с чем.

        **Единственный голос про опечатку в ПУТИ правила.** Соседний сверщик
        секций (``observability_layers._telemetry_publish_problems``) намеренно
        не судит имена под ``metrics`` («незнакомое имя метрики законно»), и это
        решение верное для ИМЁН — но правило по ПУТИ судить некому вовсе:
        ``procesess.*.state.fps`` (опечатка в первом сегменте) проходит схему,
        ложится в слой под срок, отвечает ``success=true`` и не делает НИЧЕГО.
        Здесь оно становится видимым числом, а не выводом из отсутствия эффекта.

        Показание НАКОПИТЕЛЬНОЕ и читается «ни разу с момента применения
        политики»: правило, чей писатель ещё не появился, будет здесь до его
        первой публикации — это не ложная тревога, а честное «пока не совпало».
        Счёт ПЕРЕЖИВАЕТ пересборку политики соседней правкой (см. ``hits=`` у
        конструктора) и не растёт от диагностического чтения
        (:meth:`provenance_for` резолвит с ``count=False``) — обе половины
        находки З3 ревью Ф4.
        """
        return sorted(pattern for pattern, hits in self._hits.items() if hits == 0)

    def rule_hits(self) -> Dict[str, int]:
        """``{паттерн: сколько путей он рассудил}`` — счёт, а не «ноль/не ноль».

        Выбрано вместо булева ответа осознанно (открытый вопрос З3 ревью Ф4):
        «ноль» отличает опечатку от здорового правила, но НЕ отличает правило,
        совпадающее раз в час, от совпадающего каждый такт. Оператор с числом
        видит и то, и другое; цена — одно поле в readback'е.
        """
        return dict(self._hits)

    def rules_view(self) -> Dict[str, Dict[str, Any]]:
        """Правила оператора в НОРМАЛИЗОВАННОЙ форме — для readback'а и сверки.

        Нормализация одна на оба берега (запрошенное и действующее), иначе
        частичная запись ``{"interval_sec": 1.0}`` не сошлась бы с полной формой
        живого объекта и вердикт ``config_reload_verified`` объявлял бы провал
        там, где всё применилось.
        """
        return {pattern: rule.model_dump() for pattern, rule in self._rules.items()}

    def effective_view(self) -> Dict[str, Any]:
        """Действующая политика целиком — ответ на «что действует» (М4, пункт а)."""
        return {
            "subtree": PORT_SUBTREE_PATTERN,
            "subtree_enabled": self._config.subtree_enabled,
            "subtree_interval_sec": self._config.subtree_interval_sec,
            "rules": self.rules_view(),
            "legacy_source": LEGACY_SOURCE_NAME if self._legacy is not None else None,
        }

    def provenance_for(self, paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """``{путь: {source, pattern, enabled, interval_sec}}`` — кто решил по каждому.

        Считается ТЕМ ЖЕ :meth:`resolve`, которым решение и принимается: свой
        пересчёт «по смыслу» показывал бы согласие всегда, в том числе когда
        живой гейт решает иначе. Но ``count=False``: диагностика не имеет права
        менять то, что показывает (находка З3 ревью Ф4 — воспроизведение в
        докстринге :meth:`resolve`).
        """
        out: Dict[str, Dict[str, Any]] = {}
        for path in paths:
            decision = self.resolve(str(path), count=False)
            out[str(path)] = {
                "source": decision.source,
                "pattern": decision.pattern,
                "enabled": decision.enabled,
                "interval_sec": decision.interval_sec,
            }
        return out


def cap_candidates(view: Any) -> Dict[str, Dict[str, Any]]:
    """Правила, чью частоту обязаны сверять с потолками, — ВКЛЮЧАЯ дефолт поддерева.

    Один сборщик на обоих сверщиков (:func:`~..heartbeat.telemetry.capped_metrics`
    и :func:`~..managers.telemetry_reload.detect_throttle_caps`). До находки З1
    ревью Ф4 их охват РАЗЛИЧАЛСЯ: первый учитывал дефолт поддерева, второй
    получал только ``rules`` и о нём не знал вовсе — два отчёта о потолках,
    расходящихся в охвате, при том что дефолт поддерева и есть НАЗНАЧЕННЫЙ
    предохранитель варианта «в».

    Args:
        view: :meth:`ObservationPolicy.effective_view` (или любой dict той же
            формы: ``subtree`` / ``subtree_enabled`` / ``subtree_interval_sec`` /
            ``rules``).

    Returns:
        ``{паттерн: {"enabled": bool, "interval_sec": float|None}}``. Дефолт
        поддерева не добавляется, если оператор написал такой паттерн сам, —
        та же оговорка, что в :meth:`ObservationPolicy.resolve`.
    """
    if not isinstance(view, dict):
        return {}
    rules = view.get("rules")
    out: Dict[str, Dict[str, Any]] = {
        str(pattern): dict(rule) for pattern, rule in (rules or {}).items() if isinstance(rule, dict)
    }
    subtree = str(view.get("subtree") or PORT_SUBTREE_PATTERN)
    if view.get("subtree_enabled") and subtree not in out:
        out[subtree] = {"enabled": True, "interval_sec": view.get("subtree_interval_sec")}
    return out


def normalized_observation_section(section: Any) -> Dict[str, Any]:
    """Плоские ключи запрошенной секции ``observation`` — для ``observability_verified``.

    Форма ключей ДОСЛОВНО совпадает с тем, что даёт ``flatten_section`` над
    readback'ом той же секции (``observation.rules`` — непрозрачный лист, см.
    :data:`OBSERVATION_RULES_PATH`). Совпадение здесь не косметика: расходись
    берега формой ключа — и каждая правка порта отвечала бы ``unverifiable`` при
    ``checked=0``, то есть «никто не смотрел», ровно та ловушка, которую задача
    обязана сторожить.
    """
    if not isinstance(section, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in section.items():
        if key == "rules":
            rules = value if isinstance(value, dict) else {}
            out[OBSERVATION_RULES_PATH] = {
                str(name): MetricRule.model_validate(rule or {}).model_dump() for name, rule in rules.items()
            }
        else:
            out[f"{OBSERVATION_SECTION_KEY}.{key}"] = value
    return out


__all__ = [
    "DEFAULT_SUBTREE_INTERVAL_SEC",
    "LEGACY_SOURCE_NAME",
    "OBSERVATION_RULES_PATH",
    "OBSERVATION_SECTION_KEY",
    "PORT_SUBTREE_PATTERN",
    "PROCESS_UNKNOWN",
    "SOURCE_RULE",
    "SOURCE_SUBTREE_DEFAULT",
    "SOURCE_UNGATED",
    "SOURCE_WHITELIST",
    "TIER_LEGACY_ENTRY",
    "TIER_RULE",
    "TIER_SUBTREE_DEFAULT",
    "TIER_UMBRELLA",
    "ObservationPolicy",
    "ObservationPolicyConfig",
    "PolicyDecision",
    "cap_candidates",
    "normalized_observation_section",
    "pattern_specificity",
    "resolution_key",
]
