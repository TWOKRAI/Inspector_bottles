# -*- coding: utf-8 -*-
"""Резолв правил наблюдаемости по иерархическому имени источника (Ф2.2).

**Зачем.** После Ф6 адрес записи — это ``__name__`` мигрированного файла
(``multiprocess_framework.modules.router_module.core.router_manager``), то есть
готовое дерево. До этой задачи оно никак не использовалось: гейт знал только
скоуп, а точное совпадение имени применялось ровно в одном месте (per-module
файлы, ``logger_core._route``) — и на живом прогоне 2026-08-03 из 384 созданных
per-module файлов непустыми оказались **4**, причём все четыре по совпадению
имени процесса с ключом файла, а не по маршруту. Ручка «в какой файл» и «какой
группе тише» физически отсутствовала.

**Модель — Spring/.NET: правило по самому длинному совпавшему префиксу.**
Новый плагин ``Plugins.processing.roi_crop`` автоматически подчиняется правилу
``Plugins.processing``; конфиг при добавлении плагина не трогают.

    Plugins.processing.roi_crop  →  Plugins.processing  →  Plugins  →  ""

Корень — **пустая строка**. Одна форма, а не пара синонимов (``""``/``root``):
второй способ сказать то же самое означает, что рано или поздно они разъедутся,
и правило «самое длинное совпадение» перестанет быть однозначным.

**Две оси резолвятся НЕЗАВИСИМО.** Правило может задать уровень и промолчать про
приёмники — тогда уровень берётся с него, а приёмники с более короткого
префикса. Иначе объявление ``{level: DEBUG}`` у листа молча обнуляло бы
раскладку по файлам, заданную у корня пакета, — то есть настройка одной ручки
ломала бы соседнюю.

**Молчание отличается от пустоты.** ``None`` (ключа нет) — «наследую»;
``channels: []`` — «приёмников нет, и это моё решение». То же правило, что
принято решением Г3 для слоёв конфига, — второго диалекта для той же мысли в
проекте быть не должно.

**Совпадение — только по границе точки.** Ходьба ``rpartition('.')`` даёт это
по построению: правило ``vision.capture`` не подхватит источник
``vision.captureX``. Реализация через ``str.startswith`` этим свойством не
обладает, и ошибка была бы молчаливой — источник получил бы чужой уровень.

Класс держит СВОЙ кэш и не знает ни про менеджер, ни про каналы: резолв имени —
чистая функция от таблицы правил, и проверяться он обязан без поднятия
логгера.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

__all__ = ["NameHierarchy", "ROOT_NAME"]

#: Имя корня дерева. Правило под этим ключом действует на все источники, у
#: которых не нашлось более длинного совпадения.
ROOT_NAME = ""


class NameHierarchy:
    """Таблица правил «префикс имени → уровень/приёмники» с кэшем резолва.

    Args:
        rules: отображение «префикс → правило». Правило — любой объект с
            атрибутами ``level`` (``str | None``) и ``channels``
            (``list[str] | None``); Pydantic-схема
            :class:`~..configs.logger_manager_config.LoggerRuleSchema` подходит,
            но резолв на неё не завязан — тесты собирают правила чем угодно.

    Пустая таблица — законное и **дефолтное** состояние: ``bool(hierarchy)``
    даёт ``False``, и вызывающий пропускает ветку резолва целиком. Это не
    микрооптимизация: без правил поведение обязано остаться бит-в-бит прежним,
    и самый честный способ это гарантировать — не входить в новый код вовсе.
    """

    __slots__ = ("_rules", "_level_cache", "_channels_cache")

    def __init__(self, rules: Optional[Mapping[str, object]] = None) -> None:
        self._rules: Dict[str, object] = dict(rules or {})
        self._level_cache: Dict[str, Optional[str]] = {}
        self._channels_cache: Dict[str, Optional[Tuple[str, ...]]] = {}

    def __bool__(self) -> bool:
        return bool(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    @property
    def rules(self) -> Dict[str, object]:
        """Копия таблицы правил — для интроспекции и readback пульта."""
        return dict(self._rules)

    def level(self, name: str) -> Optional[str]:
        """Уровень от самого длинного правила, которое про него говорит.

        Returns:
            Имя уровня (``"DEBUG"``…) либо ``None`` — «ни одно правило по этому
            имени уровня не задаёт». ``None`` **не** значит «писать всё»:
            решение в этом случае принимает скоуп, как до Ф2.2.
        """
        cached = self._level_cache.get(name, _MISS)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        resolved = self._walk_level(name)
        self._level_cache[name] = resolved
        return resolved

    def channels(self, name: str) -> Optional[Tuple[str, ...]]:
        """Приёмники от самого длинного правила, которое про них говорит.

        Returns:
            Кортеж имён приёмников (возможно **пустой** — «приёмников нет, это
            объявлено») либо ``None`` — «ни одно правило приёмников не задаёт»,
            и набор берётся у скоупа.

        Кортеж, а не список: значение уходит в кэш и наружу, и изменяемый
        список позволил бы одному вызывающему испортить маршрут всем
        последующим записям (тот же урок, что у ``_effective_route``).
        """
        cached = self._channels_cache.get(name, _MISS)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        resolved = self._walk_channels(name)
        self._channels_cache[name] = resolved
        return resolved

    def clear_cache(self) -> None:
        """Забыть резолв. Зовётся из единственной точки инвалидации менеджера.

        Своей точки инвалидации у иерархии нет намеренно: вторая точка — это
        вторая политика, а кэш решений гейта и кэш резолва имени обязаны
        стареть ВМЕСТЕ. Оставленный кэш имени дал бы симптом «уровень сменили,
        а он не сменился» — и искался бы он в конфиге, а не здесь.
        """
        self._level_cache.clear()
        self._channels_cache.clear()

    # --- Internal ---

    def _walk_level(self, name: str) -> Optional[str]:
        node = name
        rules = self._rules
        while True:
            rule = rules.get(node)
            if rule is not None:
                value = getattr(rule, "level", None)
                if value is not None:
                    return value
            if not node:
                return None
            node = node.rpartition(".")[0]

    def _walk_channels(self, name: str) -> Optional[Tuple[str, ...]]:
        node = name
        rules = self._rules
        while True:
            rule = rules.get(node)
            if rule is not None:
                value = getattr(rule, "channels", None)
                if value is not None:
                    return tuple(value)
            if not node:
                return None
            node = node.rpartition(".")[0]


#: Часовой промаха кэша. ``None`` — законное значение обеих карт («правило
#: молчит»), и ``.get(name)`` не отличил бы его от промаха: молчащие имена
#: пересчитывались бы на каждой записи, то есть ровно те, ради которых кэш и
#: заводится (тот же класс, что ``_ROUTE_MISS`` в ``logger_core``).
_MISS = object()
