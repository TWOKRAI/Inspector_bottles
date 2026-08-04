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

#: Ф2.х (Н5): потолок кэшей резолва. Ключ — имя источника, а имя приходит с
#: call-site и бывает динамическим (проба ревью Ф2: 3000 разных имён — 3000
#: записей в карте, потолка не было; класс Ф0.3/F6). На переполнении карта
#: чистится целиком: кэш — мемо чистой функции, сброс корректность не трогает.
_RESOLVE_CACHE_CEILING = 4096


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

    __slots__ = (
        "_rules",
        "_level_cache",
        "_channels_cache",
        "_extra_cache",
        "_groups",
        "_via_group",
    )

    def __init__(
        self,
        rules: Optional[Mapping[str, object]] = None,
        groups: Optional[Mapping[str, object]] = None,
        *,
        complain: Optional[object] = None,
    ) -> None:
        self._groups: Dict[str, Tuple[str, ...]] = {
            str(label): tuple(str(m) for m in (members or ())) for label, members in (groups or {}).items()
        }
        self._rules, self._via_group = _expand_groups(dict(rules or {}), self._groups, complain)
        self._level_cache: Dict[str, Optional[str]] = {}
        self._channels_cache: Dict[str, Optional[Tuple[str, ...]]] = {}
        self._extra_cache: Dict[str, Tuple[str, ...]] = {}

    def __bool__(self) -> bool:
        return bool(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    @property
    def rules(self) -> Dict[str, object]:
        """Копия таблицы правил — для интроспекции и readback пульта.

        Таблица уже **раскрытая** (Ф2.5): правило, написанное на ярлык, лежит
        здесь по каждому члену группы. Это и есть то, что действует, — а
        написанное человеком показывает :attr:`groups` рядом.
        """
        return dict(self._rules)

    @property
    def groups(self) -> Dict[str, Tuple[str, ...]]:
        """Ярлыки как их объявили: ``имя → префиксы`` (Ф2.5)."""
        return dict(self._groups)

    def group_of(self, prefix: str) -> Optional[str]:
        """Ярлык, через который правило доехало до префикса, либо ``None``.

        Нужен провенансу: без него readback показал бы ``level_from`` = член
        группы, хотя написан был ярлык, — и оператор искал бы в конфиге строку,
        которой там нет.
        """
        return self._via_group.get(prefix)

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
        if len(self._level_cache) >= _RESOLVE_CACHE_CEILING:
            self._level_cache.clear()
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
        if len(self._channels_cache) >= _RESOLVE_CACHE_CEILING:
            self._channels_cache.clear()
        self._channels_cache[name] = resolved
        return resolved

    def channels_extra(self, name: str) -> Tuple[str, ...]:
        """Приёмники, ДОБАВЛЯЕМЫЕ к унаследованным (Ф2.6, Р-2.6-Ж).

        Returns:
            Кортеж имён — возможно пустой. ``None`` здесь не возвращается
            намеренно: «добавить нечего» и «ключ не задан» — одно и то же, а
            различать их значило бы завести отмену добавок предков, то есть
            третью операцию на оси.

        **Накапливается по всей ветке, а не по длиннейшему префиксу.** Это
        единственное место, где резолв ведёт себя иначе, чем :meth:`channels`, и
        различие содержательное: добавка — операция, а не значение. Если бы
        побеждал длиннейший префикс, объявление ``channels_extra`` у листа молча
        отменяло бы добавку, заданную у пакета, — ровно тот дефект, ради которого
        уровень и приёмники резолвятся независимо.

        Порядок — от корня к листу: общие приёмники раньше частных, и он
        устойчив (иначе один и тот же маршрут выглядел бы по-разному в readback
        пульта от запуска к запуску). Дубли снимаются: два правила на ветке могут
        назвать один приёмник, а запись, ушедшая в один файл дважды, нарушает
        инвариант «одна ошибка — одна запись» (Ф0.9).
        """
        cached = self._extra_cache.get(name, _MISS)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        resolved = self._walk_extra(name)
        if len(self._extra_cache) >= _RESOLVE_CACHE_CEILING:
            self._extra_cache.clear()
        self._extra_cache[name] = resolved
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
        self._extra_cache.clear()

    def resolve(self, name: str) -> Dict[str, object]:
        """Полный разбор имени для пульта: что действует и **какое правило победило**.

        Образец — ``GET /actuator/loggers/{name}`` в Spring Boot: ответ даётся на
        ЛЮБОЕ введённое имя, в том числе на то, под которым ещё никто не писал.
        Это отличает вопрос-гипотезу («если я напишу правило вот так, что получится?»)
        от разбора уже случившегося, и закрывает резидуал 2.2 №4: ``effective_*``
        существовали в коде, а ручки посмотреть на них не было.

        Возвращается **словарь**, а не объект: ответ уходит через IPC на пульт, а
        между процессами ходит только ``dict`` (правило проекта «Dict at Boundary»).

        Ключи происхождения различают три разных «ничего»:

        * ``None`` — про эту ось не сказало ни одно правило на ветке;
        * ``""`` — сказало правило КОРНЯ (корень и есть пустая строка);
        * иначе — сам победивший префикс.

        Путать первое со вторым нельзя: «никто не настраивал» и «настроено глобально»
        приводят к одному значению, но чинятся по-разному.

        **Диагностический путь, не горячий.** Кэша нет намеренно: пульт спрашивает
        редко, а третья карта того же возраста — это третья причина для рассинхрона
        при старении. Согласие с горячими :meth:`level`/:meth:`channels`/
        :meth:`channels_extra` закреплено тестом: readback, расходящийся с гейтом,
        хуже отсутствующего — по нему принимают решения.
        """
        chain: list = []
        node = name
        while True:
            if node in self._rules:
                chain.append(node)
            if not node:
                break
            node = node.rpartition(".")[0]

        level: Optional[str] = None
        level_from: Optional[str] = None
        channels: Optional[Tuple[str, ...]] = None
        channels_from: Optional[str] = None
        extra_from: list = []

        for key in chain:
            rule = self._rules[key]
            if level is None:
                value = getattr(rule, "level", None)
                if value is not None:
                    level, level_from = value, key
            if channels is None:
                value = getattr(rule, "channels", None)
                if value is not None:
                    channels, channels_from = tuple(value), key
            if getattr(rule, "channels_extra", None):
                extra_from.append(key)

        return {
            "name": name,
            "level": level,
            "level_from": level_from,
            # Ф2.5: через какой ЯРЛЫК правило доехало. `level_from` называет член
            # группы (по нему и шёл резолв), а в конфиге написан ярлык — без этой
            # пары провенанс отправлял бы искать несуществующую строку.
            "level_via_group": self._via_group.get(level_from) if level_from is not None else None,
            "channels": list(channels) if channels is not None else None,
            "channels_from": channels_from,
            "channels_via_group": self._via_group.get(channels_from) if channels_from is not None else None,
            "channels_extra": list(self.channels_extra(name)),
            # Корень→лист, как и сами добавки: порядок вклада обязан читаться так же,
            # как порядок приёмников, иначе оператор сверяет два разных направления.
            "extra_from": list(reversed(extra_from)),
            "matched_rules": chain,
        }

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

    def _walk_extra(self, name: str) -> Tuple[str, ...]:
        """Собрать добавки со ВСЕЙ ветки: лист → корень, отдать корень → лист."""
        node = name
        rules = self._rules
        collected: list = []
        while True:
            rule = rules.get(node)
            if rule is not None:
                value = getattr(rule, "channels_extra", None)
                if value:
                    collected.append(tuple(value))
            if not node:
                break
            node = node.rpartition(".")[0]
        if not collected:
            return ()
        seen: Dict[str, None] = {}
        for group in reversed(collected):
            for channel in group:
                seen.setdefault(channel, None)
        return tuple(seen)


def _expand_groups(
    rules: Dict[str, object],
    groups: Dict[str, Tuple[str, ...]],
    complain: Optional[object] = None,
) -> Tuple[Dict[str, object], Dict[str, str]]:
    """Раскрыть правила, написанные на ярлык, в правила по каждому члену (Ф2.5).

    Модель — ``logging.group.*`` в Spring Boot: ярлык это **алиас набора
    префиксов**, а не новый уровень дерева. Поэтому резолв о группах не знает
    вовсе и не платит за них ничего: раскрытие происходит ОДИН раз, при сборке
    дерева, а дальше работает та же ходьба по точкам.

    Ярлык сам по себе префиксом НЕ становится. Иначе одно имя было бы
    одновременно алиасом и узлом дерева, и «самое длинное совпадение» перестало
    бы быть однозначным.

    Returns:
        Пара «раскрытая таблица, карта ``префикс → ярлык``». Вторая нужна
        провенансу: ``level_from`` покажет члена, а человек писал ярлык.

    Два правила приоритета, оба следствие одного соотношения «адресное сильнее
    оптового» (то же, что у скоупа и правила имени, Р-2.2-А):

    * собственное правило члена **сильнее** раскрытия — молча, это не конфликт;
    * два ярлыка на один префикс — **конфликт**, и он громкий: побеждает первый
      по сортировке, а не первый в словаре. Порядок ключей словаря — это порядок
      строк в YAML, и молчаливое разрешение сделало бы поведение зависимым от
      того, что оператор считает косметикой.
    """
    if not groups:
        return rules, {}

    expanded = dict(rules)
    via: Dict[str, str] = {}
    claimed: Dict[str, str] = {}
    # Сортировка — не вкусовщина: она делает победителя конфликта не зависящим ни
    # от порядка строк в конфиге, ни от порядка вставки в словарь.
    for label in sorted(groups):
        rule = rules.get(label)
        if rule is None:
            continue  # ярлык объявлен, но правила на него нет — законно и тихо
        # Ф2.х (Н4): ярлык, совпавший с началом ДРУГОГО правила, — почти наверняка
        # не ярлык, а узел дерева в голове оператора: правило под ним станет
        # правилом группы, а поддерево `label.*` его не унаследует. Р-2.5-Г
        # запретил точку В ярлыке ради однозначности longest-prefix; одно-
        # сегментная коллизия статически не запрещаема (ярлык и префикс живут в
        # разных секциях конфига), поэтому она хотя бы громкая. Поведение не
        # меняется — побеждает трактовка «ярлык», как и раньше.
        if complain is not None:
            shadowed = sorted(k for k in rules if k.startswith(label + "."))
            if shadowed:
                complain(
                    f"ярлык '{label}' совпадает с началом правил {shadowed}: правило под "
                    f"'{label}' раскрыто как правило ГРУППЫ, поддерево '{label}.*' его не "
                    f"наследует. Если имелся в виду узел дерева — переименуй ярлык"
                )
        for member in groups[label]:
            if member in rules:
                continue  # собственное правило члена сильнее (Р-2.5-Б)
            owner = claimed.get(member)
            if owner is not None:
                if complain is not None:
                    complain(
                        f"источник '{member}' назван двумя группами — '{owner}' и '{label}'; "
                        f"действует правило группы '{owner}' (первая по сортировке). "
                        f"Убери имя из одной из групп, иначе смысл конфига зависит от порядка строк"
                    )
                continue
            claimed[member] = label
            expanded[member] = rule
            via[member] = label
    # Ярлык уходит из таблицы: он не префикс, и оставленный ключ ловил бы источник
    # с таким же именем — ровно та коллизия имён, что уже стреляла в 2.6 (`gui`).
    for label in groups:
        expanded.pop(label, None)
    return expanded, via


#: Часовой промаха кэша. ``None`` — законное значение обеих карт («правило
#: молчит»), и ``.get(name)`` не отличил бы его от промаха: молчащие имена
#: пересчитывались бы на каждой записи, то есть ровно те, ради которых кэш и
#: заводится (тот же класс, что ``_ROUTE_MISS`` в ``logger_core``).
_MISS = object()
