# -*- coding: utf-8 -*-
"""`PooledResourceResolver` — `extra.context` записи -> :class:`Resource` (Task 1.2).

**Что здесь может сломаться, учитывая, как оно устроено.**

1. *Ложь вместо пропуска.* Резолвер обязан пропускать отсутствующее поле, а не
   подставлять `"unknown"`: строка-заглушка неотличима от настоящего значения у
   потребителя, и флот устройств склеивается в один `service.name`. Отсюда
   проверка `field in context` (и отдельно `is None`), а не `if context.get(field):` —
   наивная истинность гасит `incarnation = 0`, самое частое значение при первом
   старте процесса.
2. *Утечка маршрутного маркера в Resource.* В `extra.context` шесть полей, и
   шестое — `origin` — к «кто породил запись» отношения не имеет: это внутренний
   маркер того же класса, что `scope` (ADR-LOG-005). Он уезжает в `Attributes`
   записи (см. `mapping.py`), а не сюда. Единственный источник правды о том,
   какие поля контекста забирает Resource, — таблица :data:`CONTEXT_TO_SEMCONV`
   ниже; `mapping.py` изымает ровно её ключи, а не вторую копию списка.
3. *Утечка памяти на долгом прогоне.* Ключ пула включает `incarnation`, то есть
   КАЖДЫЙ рестарт источника добавляет запись. Пул без предела течёт неделю и
   падает на второй; поэтому предел (`resource_pool_size`) и вытеснение LRU со
   счётчиком. Счётчик без вытеснения — слепое место, вытеснение без счётчика —
   тихая потеря кэша, поэтому и то и другое.
4. *`host.name` из записи, которой его там нет.* Замер снимка 1f40ce0d
   (`docs/audits/2026-09-06_otel-input-shape.md`, §3) показал: `host.name` в
   `extra.context` отсутствует вовсе. Он принадлежит ЭКСПОРТЁРУ (IPC локален,
   все записи с той же машины) и берётся из `socket.gethostname()` один раз при
   построении резолвера. Параметр `host_name` существует ради инъекции «снять
   `host.name`» и ради стенда с двумя машинами — не ради конфигурируемости.

Ключ пула — `(proc_name, pid, incarnation)`; значения этих полей по построению
контекста скалярные (str/int), поэтому кортеж хешируем. Форму контекста
несловарного вида резолвер не чинит: такой вход — дефект источника, а не режим
работы.
"""

from __future__ import annotations

import socket
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from .interfaces import Resource

__all__ = [
    "CONTEXT_TO_SEMCONV",
    "POOL_KEY_FIELDS",
    "RESOURCE_CONTEXT_KEYS",
    "SEMCONV_SCHEMA_URL",
    "PooledResourceResolver",
]


#: Единственная таблица «поле `extra.context` -> имя semconv». Второй копии
#: этого списка в пакете нет: `mapping.py` импортирует
#: :data:`RESOURCE_CONTEXT_KEYS` отсюда, иначе изъятие в `Attributes` и сборка
#: Resource разъедутся на первой же правке — молча, потому что оба останутся
#: «правильными» каждый по себе.
CONTEXT_TO_SEMCONV: dict[str, str] = {
    "proc_name": "service.name",
    "fw_version": "service.version",
    "incarnation": "service.instance.id",
    "pid": "process.pid",
    "recipe": "inspector.recipe",
}

#: Ключи `extra.context`, которые забирает Resource. Всё остальное (кроме
#: `trace_id` и `origin`) — атрибуты записи.
RESOURCE_CONTEXT_KEYS = frozenset(CONTEXT_TO_SEMCONV)

#: Ключ пула — **все** поля, из которых собирается `Resource`, а не подмножество.
#:
#: `incarnation` в ключе обязателен: после рестарта процесса `pid` может совпасть
#: с чужим освобождённым, а записи разных инкарнаций — разные источники.
#:
#: Но и тройки `(proc_name, pid, incarnation)` МАЛО, и это не теория — воспроизведено
#: ревью Ф1 (Н-1, 2026-09-06). При ключе из трёх полей две записи с одинаковой тройкой,
#: но разными `recipe`/`fw_version` склеивались в один `Resource`, и наружу уезжали
#: значения ПЕРВОЙ:
#:
#:     resolve({proc_name: camera_0, pid: 1, incarnation: 0, recipe: "A", fw_version: "2.0.0"})
#:     resolve({proc_name: camera_0, pid: 1, incarnation: 0, recipe: "B", fw_version: "9.9.9"})
#:     -> inspector.recipe = "A", service.version = "2.0.0", тот же объект, evicted = 0
#:
#: Сторож не срабатывал ни один: счётчик вытеснения молчит, объект тот же по замыслу.
#: Хуже того, корректность держалась на инварианте ЧУЖОГО модуля — `_build_resource`
#: (`process_module.py`) собирает базовый контекст ровно один раз и не пересчитывает,
#: поэтому `recipe` при той же тройке де-факто не менялся. Инвариант нигде не записан,
#: а рецепт в этом приложении переключается в рантайме: первый, кто сделает базу
#: контекста пересчитываемой, получил бы тихую подмену атрибутов без единого красного.
#:
#: Ключ по всей таблице снимает межмодульную зависимость целиком. Цена нулевая:
#: значения скалярны по построению, а на живой системе `recipe` и `fw_version`
#: постоянны в пределах процесса — мощность ключа та же, что была.
POOL_KEY_FIELDS = tuple(CONTEXT_TO_SEMCONV)

#: Версия словаря semconv, по которой собран `attributes`. Литерал, а не импорт
#: из `opentelemetry.semconv.schemas`: пакет обязан импортироваться без extra
#: `[otel]` (критерий E1). Значение сверено с установленным
#: `opentelemetry-semantic-conventions 0.65b0` — 1.43.0 есть в его перечне
#: `Schemas`, а все шесть имён, которыми мы пользуемся, в нём стабильны.
#:
#: **Ловушка для Ф2, проверенная запуском на SDK 1.44.0.** `Resource.merge`
#: при РАЗНЫХ непустых `schema_url` пишет `Failed to merge resources` в
#: stdlib-`logging` (которого процесс фреймворка не слышит) и **молча
#: возвращает только свои атрибуты** — сторона с чужой схемой исчезает.
#: С дефолтным ресурсом SDK конфликта нет: у `Resource.create()` `schema_url`
#: пуст. Появится детектор со своей схемой — обёртка Ф2 обязана это заметить.
SEMCONV_SCHEMA_URL = "https://opentelemetry.io/schemas/1.43.0"


class PooledResourceResolver:
    """Резолвер :class:`Resource` с LRU-пулом. Удовлетворяет `ResourceResolver`.

    Имя не `ResourceResolver`: так зовут Protocol в `interfaces.py`, и
    одноимённый конкретный класс в том же пакете сломал бы `isinstance()`, ради
    которого Protocol объявлен `@runtime_checkable` (решение Р-2 плана).

    Потокобезопасности НЕТ намеренно: резолвер зовётся из единственного потока
    приёма плагина (Ф2.1). Появится второй — понадобится лок, и это будет видно
    по счётчику `evicted`, растущему быстрее числа источников.
    """

    def __init__(
        self,
        resource_pool_size: int = 64,
        service_namespace: str = "",
        host_name: str | None = None,
    ) -> None:
        """
        Args:
            resource_pool_size: предел пула. `< 1` — отказ на месте: пул нулевого
                размера вытесняет каждую запись и превращает счётчик вытеснения
                в счётчик вызовов.
            service_namespace: `service.namespace`. Пусто — атрибута НЕТ:
                разрешение пустого значения в имя приложения — обязанность
                хоста (`app.yaml`), а не резолвера; подставить здесь литерал
                значило бы завести второй источник имени.
            host_name: `host.name`. `None` — `socket.gethostname()` один раз.
                Пустая строка — атрибута нет (этим и делается инъекция «снять
                `host.name`»).
        """
        if resource_pool_size < 1:
            raise ValueError(
                f"resource_pool_size={resource_pool_size}: пул размера меньше единицы "
                "не кэширует ничего и считает вытеснением каждый вызов"
            )
        self._capacity = int(resource_pool_size)
        self._service_namespace = service_namespace
        self._host_name = socket.gethostname() if host_name is None else host_name
        self._pool: OrderedDict[tuple[Any, ...], Resource] = OrderedDict()
        self._evicted = 0

    # ------------------------------------------------------------------ #
    # Наблюдаемость механизма
    # ------------------------------------------------------------------ #

    @property
    def evicted(self) -> int:
        """Сколько Resource вытеснено из пула за время жизни резолвера.

        Читаемое свойство у механизма, имя точки числовой плоскости
        (`otel_export.resource_evicted`) — у хоста: прецедент
        `BoundedChannel.dropped` фреймворка (решение Р-3 плана). Префикс
        плоскости внутрь механизма не тащится.
        """
        return self._evicted

    @property
    def pooled(self) -> int:
        """Сколько источников сейчас в пуле — пара к :attr:`evicted`.

        Без неё «вытеснений 0» неотличимо от «резолвер ни разу не звали».
        """
        return len(self._pool)

    # ------------------------------------------------------------------ #
    # Контракт
    # ------------------------------------------------------------------ #

    def resolve(self, context: Mapping[str, Any]) -> Resource:
        """Собрать (или взять из пула) Resource источника записи.

        Повтор того же ключа возвращает ТОТ ЖЕ объект и не считается новым
        источником: `Resource` неизменяем (`frozen=True`), делить его между
        записями безопасно, а пересборка на каждую запись сделала бы предел
        пула бессмысленным.
        """
        key = tuple(context.get(name) for name in POOL_KEY_FIELDS)
        cached = self._pool.get(key)
        if cached is not None:
            self._pool.move_to_end(key)
            return cached

        resource = self._build(context)
        self._pool[key] = resource
        if len(self._pool) > self._capacity:
            self._pool.popitem(last=False)
            self._evicted += 1
        return resource

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _build(self, context: Mapping[str, Any]) -> Resource:
        """Собрать Resource из контекста. Отсутствующее поле ПРОПУСКАЕТСЯ.

        `None` считается тем же отсутствием: значением атрибута OTel он быть не
        может, а «ключ есть, значения нет» — это и есть незаполненное поле.
        """
        attributes: dict[str, str | int | float | bool] = {}
        for field, semconv_name in CONTEXT_TO_SEMCONV.items():
            value = context.get(field)
            if value is None:
                continue
            attributes[semconv_name] = value

        # Атрибуты ЭКСПОРТЁРА — одни и те же у всех записей всех источников.
        if self._host_name:
            attributes["host.name"] = self._host_name
        if self._service_namespace:
            attributes["service.namespace"] = self._service_namespace

        return Resource(attributes=attributes, schema_url=SEMCONV_SCHEMA_URL)
