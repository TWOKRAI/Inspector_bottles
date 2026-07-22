# -*- coding: utf-8 -*-
"""feature_flags — единый реестр булевых маркеров движка (``FW_*``).

Purpose:
    Все ``FW_*``-флаги движка задекларированы в ОДНОМ месте (имя / default / doc /
    requires / aliases) вместо строковых литералов, разбросанных по модулям-
    читателям. Опечатка в имени → громкий ``KeyError``, а не тихий ``default=False``.
    Приоритет ``ctor-arg > env > default`` сохранён — на нём держится откат
    dark-launch «бит-в-бит» (env ``NAME=0`` перекрывает любой default).

    Реестр НЕ через ConfigStore (решение владельца 2026-07-14): ``Config`` — это
    прикладной Pydantic-конфиг (правила проекта 1/5), а флаги — глобальные
    process-toggles движка; смешивать нельзя. Реестр читается на старте процесса
    (в ctor менеджеров / на import), НЕ на hot-path — ноль оверхеда на кадр.

    Разграничение с наблюдаемостью: логи/статистика/ошибки НЕ являются ``FW_*``-
    флагами. Их тумблеры живут в секции ``observability`` app.yaml с hot-reload
    (ADR-CRM-006); ошибки включены всегда (ErrorManager создаётся всегда). Этот
    модуль — только про маркеры движка (seqlock, zero-copy, QoS, …).

Public API:
    - FeatureFlag — декларация одного флага (name/default/doc/requires/aliases)
    - FlagState — снимок значения флага (value + source) для приёмки и /dev
    - FLAGS — реестр ``{имя: FeatureFlag}``, единственный источник правды
    - resolve — разрешить булево значение флага (ctor > env > default)
    - is_enabled — короткая форма ``resolve(name)`` без ctor-override
    - state_of — снимок одного флага (FlagState)
    - list_flags — снимок всех флагов (для introspect / приёмки G.7)
    - validate — advisory-проверка requires-графа (список нарушений, не бросает)

Stability: lite
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .tools.env import env_truthy

__all__ = [
    "FeatureFlag",
    "FlagState",
    "FLAGS",
    "resolve",
    "is_enabled",
    "state_of",
    "list_flags",
    "validate",
]


@dataclass(frozen=True)
class FeatureFlag:
    """Декларация одного булева маркера движка.

    Invariants:
      - ``name`` уникально в ``FLAGS`` (проверяется при сборке реестра)
      - каждый элемент ``requires`` и каждый ``alias`` — не сам ``name``
    """

    name: str
    default: bool
    doc: str
    requires: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FlagState:
    """Снимок разрешённого значения флага с источником.

    ``source`` ∈ {``"ctor"``, ``"env"``, ``"alias"``, ``"default"``} — откуда
    взято значение (для приёмки G.7 и вкладки /dev: видно, что именно активно
    и почему).
    """

    name: str
    value: bool
    source: str
    default: bool
    doc: str
    requires: Tuple[str, ...] = ()


# ── Реестр флагов ────────────────────────────────────────────────────────────
# Порядок = логические группы (SHM hot-path → data-plane → GC → супервизор →
# контракты). default отражает ПРЕЖНЕЕ поведение читателя (откат = флаг off/on
# как было). requires — декларативный граф зависимостей (enforcement остаётся у
# владельца ресурса; здесь — для advisory-validate и наглядности приёмки).

_FLAG_LIST: Tuple[FeatureFlag, ...] = (
    # — SHM кадровый тракт (Ф7 G.3–G.5, dark-launch, откат бит-в-бит) —
    FeatureFlag(
        "FW_SHM_SEQLOCK",
        default=False,
        doc="Seqlock слота SHM: чётность generation → нет torn-frame (ADR-SRM-011).",
    ),
    FeatureFlag(
        "FW_SHM_OWNER_INCARNATION",
        default=False,
        doc="Имена сегментов {slot}_{owner}_{pid}_{inc}: читатели следуют за "
        "рестартом писателя, мультикамера без коллизий (обязателен на POSIX-мультикамере).",
    ),
    FeatureFlag(
        "FW_SHM_HANDLE_CACHE",
        default=False,
        doc="Кэш mmap-хэндлов reader'а: снятие open/mmap/close на кадр.",
        requires=("FW_SHM_OWNER_INCARNATION",),
    ),
    FeatureFlag(
        "FW_SHM_ZERO_COPY",
        default=False,
        doc="View вместо копии на data-plane (GUI остаётся copy-out). "
        "Enforcement жёсткого требования — во FrameShmMiddleware.",
        requires=("FW_SHM_HANDLE_CACHE", "FW_SHM_OWNER_INCARNATION"),
    ),
    FeatureFlag(
        "FW_SHM_LOAN_PROTOCOL",
        default=False,
        doc="Owner-mediated loan/release слотов (refcount): медленный потребитель "
        "не блокирует камеру, kill-9 читателя → reclaim.",
        requires=("FW_SHM_ZERO_COPY",),
    ),
    FeatureFlag(
        "FW_SHM_PREFIX_CLEANUP",
        default=False,
        doc="Startup-cleanup осиротевших SHM-сегментов по префиксу (POSIX; на Windows no-op).",
    ),
    FeatureFlag(
        "FW_QOS_PROFILES",
        default=False,
        doc="QoS-профили kind + боевые кольца RingBuffer per-camera (data drop_oldest "
        "со счётчиком, system никогда молча).",
    ),
    # — Data-plane / перф —
    FeatureFlag(
        "FW_DATA_PLANE_DICTS",
        default=False,
        doc="Data-plane dict вместо Message/Pydantic: нет пересборки конверта на кадр.",
    ),
    FeatureFlag(
        "FW_PERF_PROBES",
        default=False,
        doc="Перф-пробы цикла (p50/p99, FPS) через get_cycle_metrics.",
    ),
    # — GC-дисциплина (Ф7 G.9) —
    FeatureFlag(
        "FW_GC_FREEZE",
        default=False,
        doc="gc.freeze() после старта: долгоживущие объекты вне сборки, паузы ↓.",
    ),
    FeatureFlag(
        "FW_GC_SCHEDULED",
        default=False,
        doc="GC по расписанию вместо порогов (measurement-gated: включать, только если "
        "после FW_GC_FREEZE остались p99-выбросы от GC).",
        requires=("FW_GC_FREEZE",),
    ),
    # — Доставка / каналы (Ф7 G.2) —
    FeatureFlag(
        "FW_USE_KIND_CHANNELS",
        default=False,
        doc="Kind-каналы доставки (G.2): очереди по kind сообщения. "
        "Историческое не-FW имя MULTIPROCESS_USE_KIND_CHANNELS поддержано как alias.",
        aliases=("MULTIPROCESS_USE_KIND_CHANNELS",),
    ),
    FeatureFlag(
        "FW_STATE_COALESCE",
        default=False,
        doc="Межвызовное коалесцирование state-дельт (гашение gui-шторма): буфер "
        "дельт per-subscriber + daemon-flusher (тик ~120мс, cap ~200) шлёт один "
        "state.changed на тик вместо одного на каждую мутацию. Приёмник (StateProxy) "
        "не меняется — конверт уже несёт first_revision/revision. OFF → путь бит-в-бит.",
    ),
    FeatureFlag(
        "FW_STATE_QUEUE",
        default=False,
        doc="Отдельная очередь класса 'state' для state.changed (гашение gui-шторма): "
        "дельты идут в {proc}_state (drop_oldest, QoS-профиль _STATE) вместо never-drop "
        "system-очереди, поэтому burst state.set не топит system-почту команд. Приёмный "
        "system-тред дренирует ['system','state']; переполнение → data_evicted, не "
        "system_evict_blocked; клиент делает resync по разрыву revision. OFF → 'system' как раньше.",
    ),
    # — Контракты сообщений / плагинов (Ф4) —
    FeatureFlag(
        "FW_CONTRACTS_STRICT",
        default=False,
        doc="Строгая валидация контрактов сообщений (extra=forbid на data команд).",
    ),
    FeatureFlag(
        "FW_PORT_VALIDATE",
        default=False,
        doc="Валидация портов плагина при сборке цепочки.",
    ),
    # — Супервизор / живучесть (default ON — прежнее поведение) —
    FeatureFlag(
        "FW_AUTORESTART",
        default=True,
        doc="Авто-рестарт упавших дочерних процессов супервизором. Default ON.",
    ),
    FeatureFlag(
        "FW_ROUTING_REFRESH",
        default=True,
        doc="Refresh routing-epoch при изменении топологии. Default ON.",
    ),
    FeatureFlag(
        "FW_FENCE",
        default=True,
        doc="Fencing-токены сообщений (защита от stale после switch). Default ON.",
    ),
    FeatureFlag(
        "FW_STATE_TOPOLOGY_GATE",
        default=True,
        doc=(
            "Гейт записей в processes.<name>.* по текущей топологии (защита от "
            "воскрешения узла снятого процесса поздним state.set). Default ON."
        ),
    ),
    FeatureFlag(
        "FW_HEALTH_RESTART",
        default=False,
        doc="Рестарт процесса по деградации health-статуса (опц., поверх авто-рестарта).",
    ),
)

#: Реестр: имя флага → декларация. Единственный источник правды.
FLAGS: Dict[str, FeatureFlag] = {}
_ALIAS_INDEX: Dict[str, str] = {}


def _build_registry() -> None:
    """Собрать ``FLAGS`` и индекс алиасов, отвергнув дубли/самоссылки.

    Pre:
      - имена флагов и алиасов попарно уникальны в ``_FLAG_LIST``
    Post:
      - ``FLAGS[name].name == name`` для каждого флага
      - каждый alias резолвится в ровно один канонический ``name``
    """
    for flag in _FLAG_LIST:
        if flag.name in FLAGS:
            raise ValueError(f"Дубль флага в реестре: {flag.name!r}")
        if flag.name in flag.requires or flag.name in flag.aliases:
            raise ValueError(f"Флаг {flag.name!r} ссылается сам на себя")
        FLAGS[flag.name] = flag
    for flag in _FLAG_LIST:
        for req in flag.requires:
            if req not in FLAGS:
                raise ValueError(f"Флаг {flag.name!r} требует неизвестный {req!r}")
        for alias in flag.aliases:
            if alias in FLAGS:
                raise ValueError(f"Alias {alias!r} совпадает с именем флага")
            if alias in _ALIAS_INDEX:
                raise ValueError(f"Дубль алиаса: {alias!r}")
            _ALIAS_INDEX[alias] = flag.name


_build_registry()


def _spec(name: str) -> FeatureFlag:
    """Достать декларацию флага; неизвестное имя → громкий ``KeyError``.

    Pre:
      - ``name`` зарегистрирован в ``FLAGS`` (канон, НЕ alias)
    Post:
      - вернулась декларация с ``.name == name``
    """
    try:
        return FLAGS[name]
    except KeyError:
        known = ", ".join(sorted(FLAGS))
        raise KeyError(f"Неизвестный feature-флаг {name!r}. Зарегистрированные: {known}") from None


def _env_lookup(spec: FeatureFlag) -> Optional[Tuple[bool, str]]:
    """Явно заданное env-значение флага (канон, затем алиасы) или ``None``.

    «Задано» = переменная присутствует и не пуста (после strip). Пустая/
    отсутствующая → ``None`` (падаем на default). Парсинг — канонический
    ``env_truthy`` (решение F9): ``1/true/yes/on`` истинны, всё прочее ложно,
    в т.ч. явный ``NAME=0`` возвращает ``(False, "env")`` и перекрывает default.
    """
    raw = os.environ.get(spec.name)
    if raw is not None and raw.strip() != "":
        return env_truthy(raw), "env"
    for alias in spec.aliases:
        raw = os.environ.get(alias)
        if raw is not None and raw.strip() != "":
            return env_truthy(raw), "alias"
    return None


def resolve(name: str, explicit: Optional[bool] = None) -> bool:
    """Разрешить булев маркер по приоритету ``ctor > env > default``.

    Pre:
      - ``name`` зарегистрирован в ``FLAGS`` (иначе ``KeyError`` — ловит опечатку)
    Post:
      - если ``explicit is not None`` → ``bool(explicit)`` (ctor побеждает всё)
      - иначе если env задан (канон или alias) → значение из env (``=0`` = False)
      - иначе → ``FLAGS[name].default``
    """
    spec = _spec(name)
    if explicit is not None:
        return bool(explicit)
    env = _env_lookup(spec)
    if env is not None:
        return env[0]
    return spec.default


def is_enabled(name: str) -> bool:
    """Короткая форма ``resolve(name)`` без ctor-override (env > default).

    Pre:
      - ``name`` зарегистрирован
    Post:
      - эквивалентно ``resolve(name, None)``
    """
    return resolve(name, None)


def state_of(name: str, explicit: Optional[bool] = None) -> FlagState:
    """Снимок флага: разрешённое значение + источник.

    Pre:
      - ``name`` зарегистрирован
    Post:
      - ``.value == resolve(name, explicit)``
      - ``.source`` отражает победивший уровень приоритета
    """
    spec = _spec(name)
    if explicit is not None:
        return FlagState(name, bool(explicit), "ctor", spec.default, spec.doc, spec.requires)
    env = _env_lookup(spec)
    if env is not None:
        return FlagState(name, env[0], env[1], spec.default, spec.doc, spec.requires)
    return FlagState(name, spec.default, "default", spec.default, spec.doc, spec.requires)


def list_flags() -> List[FlagState]:
    """Снимок ВСЕХ флагов (без ctor-override) — для introspect и приёмки G.7.

    Post:
      - длина == ``len(FLAGS)``; порядок совпадает с реестром
      - каждый элемент — ``state_of(name)``
    """
    return [state_of(name) for name in FLAGS]


def validate(states: Optional[Dict[str, bool]] = None) -> List[str]:
    """Advisory-проверка requires-графа: список человекочитаемых нарушений.

    НЕ бросает и НЕ меняет рантайм — только сообщает (оркестратор логирует их
    на старте, чтобы misconfig был виден). Жёсткое enforcement остаётся у
    владельца ресурса (напр. FrameShmMiddleware для zero-copy).

    Pre:
      - ключи ``states`` (если переданы) — зарегистрированные имена
    Post:
      - для каждого включённого флага каждый его ``requires`` тоже включён —
        иначе строка-нарушение в результате
      - пустой список ⇔ граф зависимостей согласован
    """
    if states is None:
        states = {s.name: s.value for s in list_flags()}
    problems: List[str] = []
    for name, on in states.items():
        _spec(name)  # валидируем имя (ловит опечатку в переданном снимке)
        if not on:
            continue
        for req in FLAGS[name].requires:
            req_on = states.get(req)
            if req_on is None:
                req_on = is_enabled(req)
            if not req_on:
                problems.append(f"{name} включён, но требует {req} (сейчас выключен)")
    return problems
