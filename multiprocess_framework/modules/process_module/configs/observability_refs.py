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

Модуль чистый: ни менеджеров, ни I/O — на входе dict и известные имена, на выходе
имена-сироты. Решение, что с ними делать (отказать или сказать вслух), принимает
вызывающий: у ручки оператора и у файла рецепта эти ответы РАЗНЫЕ.
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
