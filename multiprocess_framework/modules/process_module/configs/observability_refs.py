# -*- coding: utf-8 -*-
"""Ссылки секции наблюдаемости, за которыми нет приёмника (Task 5.5).

Секция адресует приёмники и скоупы **по имени**, и имя, которого нет, до этой
задачи не стоило ничего: `channels: {messages_fil: {enabled: false}}` проходил как
успех, а `scopes: {SYSTEMM: {min_level: DEBUG}}` — как **подтверждённая** смена
(вердикт 5.7 честно видел ключ в readback). Оператор уходил с уверенностью, что
приёмник погашен или диагностика включена.

**Опечатка отличается от определения тем, что за ней нет приёмника** — и это не
формальность. `LoggerScopeSchema` несёт СВОИ `channels`/`modules`, а
`LoggerChannelSchema` — `type`: значит новое имя, пришедшее с телом, законно
определяет новую сущность, и запрещать незнакомые имена нельзя. Различаем:

* ``channels.<имя>`` — имени нет среди известных **и** записи нечем себя
  определить (нет ``type``) → ссылка в пустоту;
* ``scopes.<имя>`` — имя новое **и** список ``channels`` пуст → правило, которому
  некуда писать; отдельно — скоуп (любой), чей ``channels`` называет неизвестный
  канал;
* ``processes.<имя>`` — имени нет в топологии (шаг 10 задачи 5.13). Судить может
  только сборщик: процесс знает лишь себя.

Ядро модуля чистое: ни менеджеров, ни I/O — на входе dict и известные имена, на
выходе имена-сироты. Решение, что с ними делать (отказать или сказать вслух),
принимает вызывающий: у ручки оператора и у файла рецепта эти ответы РАЗНЫЕ.

**ФР-2.** Поверх ядра лежат две функции-правила — :func:`unknown_refs_for` и
:func:`report_unknown_refs`. Они существуют потому, что «посчитать известные имена
и сказать вслух» было написано ровно в одном месте (ветка inline/файл команды
``config.reload``), а тело в слой L2 кладут ПЯТЬ дорог. Три из них — конверт
switch'а, перечитка спутника и boot — проходили мимо проверки молча, и законный
ключ на снятый канал, записанный ``observability.persist`` в спутник, въезжал на
следующем старте увековеченной опечаткой. Правило теперь одно на все дороги: где
считать известные имена и что говорить — здесь, а не у каждого вызывающего.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

#: Плоскость → путь до её словаря каналов внутри секции.
_CHANNEL_SECTIONS: tuple = (
    ("logger", ()),
    ("error", ("errors",)),
    ("stats", ("stats",)),
)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dig(section: Mapping[str, Any], path: Iterable[str]) -> Dict[str, Any]:
    node: Any = section
    for key in path:
        node = _as_mapping(node).get(key)
    return _as_mapping(node)


def known_refs_from_managers(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
) -> Dict[str, Set[str]]:
    """Известные имена ЖИВЫХ менеджеров: каналы трёх плоскостей + скоупы логгера.

    Каналы берутся как объединение **живого реестра и конфига**. Ни одного из двух
    источников по отдельности не хватает: снятый командой приёмник исчез из
    реестра, но остался в конфиге (и `{enabled: true}` про него — законный возврат,
    а не опечатка), а построенный рантаймом — наоборот. Возьми мы только реестр —
    возврат снятого канала объявлялся бы ошибкой.
    """
    known: Dict[str, Set[str]] = {"logger": set(), "error": set(), "stats": set(), "scopes": set()}
    for plane, manager in (("logger", logger), ("error", error), ("stats", stats)):
        if manager is None:
            continue
        registry = getattr(manager, "get_all_channels", None)
        if callable(registry):
            try:
                known[plane].update(str(getattr(ch, "name", "")) for ch in registry() or [])
            except Exception:  # noqa: BLE001, S110 — диагностика не роняет вызывающего
                pass
        config = getattr(manager, "config", None)
        channels = getattr(config, "channels", None)
        if isinstance(channels, Mapping):
            known[plane].update(str(name) for name in channels)
        known[plane].discard("")
    scopes = getattr(getattr(logger, "config", None), "scopes", None)
    if isinstance(scopes, Mapping):
        known["scopes"].update(str(name) for name in scopes)
    return known


def unknown_observability_refs(section: Any, known: Mapping[str, Iterable[str]]) -> Dict[str, List[str]]:
    """Имена секции, за которыми нет приёмника. Пустой dict = все ссылки разрешимы.

    Ключи ответа — ПУТИ секции (``channels.messages_fil``,
    ``scopes.SYSTEMM.channels``), а не голые имена: оператор правит текст конфига, и
    «где именно» ему нужнее, чем «что именно».
    """
    body = _as_mapping(section)
    if not body:
        return {}
    known_scopes = {str(name) for name in known.get("scopes", ())}
    out: Dict[str, List[str]] = {}

    for plane, path in _CHANNEL_SECTIONS:
        prefix = ".".join((*path, "channels")) if path else "channels"
        allowed = {str(name) for name in known.get(plane, ())}
        orphans = [
            name
            for name, body_of in sorted(_dig(body, (*path, "channels")).items())
            # `type` — способ записи определить себя. Есть он → это НОВЫЙ канал,
            # и запрещать его нельзя: конфиг имеет право добавить приёмник.
            if str(name) not in allowed and not _as_mapping(body_of).get("type")
        ]
        if orphans:
            out[prefix] = orphans

    logger_channels = {str(name) for name in known.get("logger", ())}
    declared_channels = {str(name) for name in _dig(body, ("channels",))}
    empty_scopes: List[str] = []
    dangling: List[str] = []
    for name, body_of in sorted(_dig(body, ("scopes",)).items()):
        scope = _as_mapping(body_of)
        listed = [str(ch) for ch in scope.get("channels") or []]
        if str(name) not in known_scopes and not listed:
            # Новый скоуп без каналов: правило, которое не может сработать. У
            # ИЗВЕСТНОГО скоупа пустой список законен — каналы приедут снизу
            # merge'ем, и требовать их здесь значило бы запретить `{min_level: …}`.
            empty_scopes.append(str(name))
            continue
        dangling.extend(f"{name}.{ch}" for ch in listed if ch not in logger_channels and ch not in declared_channels)
    if empty_scopes:
        out["scopes"] = empty_scopes
    if dangling:
        out["scopes.channels"] = sorted(dangling)
    return out


def unknown_recipe_processes(section: Any, known_processes: Iterable[str]) -> List[str]:
    """Имена в ``observability.processes``, которых нет в топологии (шаг 10 задачи 5.13).

    Судит только сборщик: у процесса нет списка соседей, а
    ``resolve_recipe_section`` по своему имени молча возвращает дефолты — то есть
    адресная секция для процесса с опечаткой не доезжает НИ ДО КОГО и делает это
    бесшумно.
    """
    processes = _dig(_as_mapping(section), ("processes",))
    if not processes:
        return []
    allowed = {str(name) for name in known_processes}
    return sorted(str(name) for name in processes if str(name) not in allowed)


def format_unknown_refs(refs: Mapping[str, Iterable[str]], *, source: Optional[str] = None) -> str:
    """Одна строка для лога/ответа: где именно ссылка в пустоту.

    Формулировка называет ПОСЛЕДСТВИЕ, а не только факт: «ключ есть, эффекта нет»
    — то, из-за чего опечатку и не замечают.
    """
    parts = "; ".join(f"{path}: {', '.join(sorted(names))}" for path, names in sorted(refs.items()) if names)
    where = f" ({source})" if source else ""
    return f"[observability] ссылки без приёмника{where} — ключ есть, эффекта нет: {parts}"


def unknown_refs_for(svc: Any, section: Any) -> Dict[str, List[str]]:
    """Сироты секции для ЖИВОГО процесса: каталог имён берётся с его менеджеров.

    Единственное место, где считается «что этот процесс знает». До ФР-2 расчёт
    жил внутри ветки ``config.reload``, и остальные дороги слоя L2 его просто не
    звали — то есть проверка была свойством ОДНОЙ дороги, а не свойством слоя.

    **Пустой каталог = молчание, а не «всё сироты».** Каталога нет у процесса,
    которому менеджеров не собирали вовсе (встройщик вправе так сделать, см.
    ``layers_are_silent``); сравнение с пустым множеством объявило бы опечаткой
    каждое имя подряд — самый громкий из возможных способов не сказать ничего.
    """
    if not isinstance(section, Mapping) or not section:
        return {}
    known = known_refs_from_managers(
        logger=getattr(svc, "logger_manager", None),
        error=getattr(svc, "error_manager", None),
        stats=getattr(svc, "stats_manager", None),
    )
    if not any(known.values()):
        return {}
    return unknown_observability_refs(section, known)


def report_unknown_refs(svc: Any, section: Any, *, source: str = "") -> Dict[str, List[str]]:
    """Громкая половина правила: посчитать сироты и НАЗВАТЬ их в журнале.

    Политика «сказать, но не отказать» — та же, что у файловой дороги L1, и по той
    же причине: отказ означал бы, что опечатка в спутнике валит switch рецепта или
    старт процесса. Тихий ключ дешевле упавшей системы, но только если он тихий
    ровно в конфиге, а не в журнале.

    Отказывает ровно одна дорога — inline-ручка оператора; она зовёт
    :func:`unknown_refs_for` напрямую и решает сама.

    Returns:
        Те же сироты, что и :func:`unknown_refs_for`, — вызывающий кладёт их в
        свой ответ. Журнал видит оператор процесса, ответ — инициатор команды, и
        это разные люди в разное время.
    """
    refs = unknown_refs_for(svc, section)
    if refs:
        log_error = getattr(svc, "_log_error", None)
        if callable(log_error):
            log_error(format_unknown_refs(refs, source=source or None), module="lifecycle")
    return refs


def merge_unknown_refs(*reports: Mapping[str, Iterable[str]]) -> Dict[str, List[str]]:
    """Сложить отчёты нескольких дорог одной команды в один (пути — объединением).

    Один ``config.reload`` может нести и inline-секцию, и конверт switch'а: два
    разных тела, две проверки. Перезапиши второй отчёт первый — ответ назвал бы
    половину опечаток, и именно ту половину, которую вызывающий не выбирал.
    """
    out: Dict[str, List[str]] = {}
    for report in reports:
        for path, names in (report or {}).items():
            out[path] = sorted(set(out.get(path, [])) | {str(n) for n in names})
    return out
