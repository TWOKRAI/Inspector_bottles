# -*- coding: utf-8 -*-
"""protocol.py — распаковка конверта ответа + типизированные результаты интроспекции.

Чистый слой БЕЗ транспорта и без BackendDriver: только приведение сырого router-ответа
к явным формам. :func:`unwrap` робастно спускается по вложенному ``result``-конверту
оркестратора; dataclass'ы (``RouterStats``/``QueueDepths``/… ``Capabilities``) поверх
готовых introspect.*-команд приводят dict к полям, всегда сохраняя сырой ответ в ``raw``.

Выделено из ``driver.py`` (Phase C, C.1): форма ответа — самостоятельная зона, не
завязанная на сокет/подписки/watch. Пути пост-codemod — ``tooling/backend_ctl/protocol.py``.

**Строгий край.** Обёртки НЕ подставляют ``0``/дефолт вместо отсутствующих данных:
поля, по которым сервер значения не дал, равны ``None``, а их имена перечислены в
``missing``. ``missing == []`` читается как «форма ответа полная». Причина строгости:
``int(stats.get("sent_ok", 0) or 0)`` превращал «сервер переименовал поле» и «ручка не
ответила» в «трафика не было» — ложь, неотличимую от факта.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Классы потери наблюдаемости — ИМПОРТИРУЮТСЯ у публикатора, а не переписываются
#: здесь. На этом проекте ровно этот класс уже стрелял: правило читало
#: несуществующий ``drops_count`` при реальном ``drops``, и фича была мертва при
#: 26 зелёных тестах на моке. Своя копия перечня расходится с публикатором молча.
from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    DELIVERY_COUNTER_KEYS,
    LOSS_COUNTER_KEYS,
    OBSERVED_AT_KEY,
)

#: Служебный ключ, которым :func:`unwrap` помечает «искомых ключей в ответе нет».
#: Появляется ТОЛЬКО в возвращённой копии — исходный dict вызывающего не мутируется.
UNWRAP_MISS = "_unwrap_miss"

#: Часовой для «ключа в ответе не было»: ``None`` — легальное значение (сервер может
#: явно ответить null), поэтому отличать отсутствие через ``.get(key)`` нельзя.
_ABSENT = object()


def unwrap(res: Any, *keys: str, leaf: bool = False) -> Dict[str, Any]:
    """Единая распаковка конверта ответа команды (Task 0.4 — слияние двух хелперов).

    Ответ приезжает либо «плоским», либо завёрнутым оркестратором в
    ``{"success": ..., "result": {<payload>}}`` (иногда в два уровня). Два режима:

    - ``keys`` заданы → вернуть первый узел (спускаясь по ``result``), содержащий любой
      из ``keys`` (например ``router_stats``/``queue_sizes``/``workers``); не нашли —
      копию ``res`` с признаком :data:`UNWRAP_MISS`. Прежний ``_find_payload``.
    - ``leaf=True`` → спуститься по ``result`` до листовой нагрузки хендлера (config.reload
      → ``applied``, logger.sink.* → ``sink``). Прежний ``_leaf_result``.
    - иначе → ``res`` как dict.
    """
    if keys:
        node = res
        for _ in range(4):  # защита от бесконечного спуска на кривом ответе
            if not isinstance(node, dict):
                break
            if any(k in node for k in keys):
                return node
            node = node.get("result")
        # Ключей нет ни на одном уровне. Молчаливый возврат ``res`` означал «парсер
        # дальше отдаст дефолты» — то есть тишину вместо признака расхождения формы.
        # Копия, а не мутация: этот же dict лежит у вызывающего и в ``raw`` обёрток.
        if isinstance(res, dict):
            return {**res, UNWRAP_MISS: list(keys)}
        return {UNWRAP_MISS: list(keys)}
    if leaf:
        node = res if isinstance(res, dict) else {}
        for _ in range(4):  # защита от бесконечного спуска на кривом ответе
            nxt = node.get("result")
            if isinstance(nxt, dict):
                node = nxt
            else:
                break
        return node
    return res if isinstance(res, dict) else {}


def _find_payload(res: Any, *keys: str) -> Dict[str, Any]:
    """Алиас :func:`unwrap` (keys-режим)."""
    return unwrap(res, *keys)


def _leaf_result(res: Any) -> Dict[str, Any]:
    """Алиас :func:`unwrap` (leaf-режим)."""
    return unwrap(res, leaf=True)


def _is_ok(res: Any, payload: Dict[str, Any]) -> bool:
    """Успех ответа: ``success`` берём из полезной нагрузки или из внешнего конверта."""
    if isinstance(payload, dict) and "success" in payload:
        return bool(payload.get("success"))
    return bool(res.get("success")) if isinstance(res, dict) else False


def _read_int(payload: Any, key: str, missing: List[str]) -> Optional[int]:
    """Счётчик: ключа нет или значение не число → ``None`` и имя ключа в ``missing``.

    Ноль — валидное показание («событий не было»), поэтому подставлять его при
    отсутствии ключа нельзя: два разных факта схлопывались в один неотличимый.
    """
    value = payload.get(key, _ABSENT) if isinstance(payload, dict) else _ABSENT
    if value is not _ABSENT and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass  # значение пришло, но числом не является — показания нет
    missing.append(key)
    return None


def _read_mapping(payload: Any, key: str, missing: List[str]) -> Optional[Dict[str, Any]]:
    """Структурная секция-словарь: нет ключа или значение не dict → ``None`` + ``missing``.

    Пустой словарь — валидный ответ («очередей нет»), поэтому он НЕ считается пропуском.
    """
    value = payload.get(key, _ABSENT) if isinstance(payload, dict) else _ABSENT
    if isinstance(value, dict):
        return dict(value)
    missing.append(key)
    return None


def _read_scalar(payload: Any, key: str, missing: List[str]) -> Optional[Any]:
    """Скалярное поле (имя процесса, статус): нет ключа или ``null`` → ``None`` + ``missing``."""
    value = payload.get(key, _ABSENT) if isinstance(payload, dict) else _ABSENT
    if value is not _ABSENT and value is not None:
        return value
    missing.append(key)
    return None


def _read_list(payload: Any, key: str, missing: List[str]) -> Optional[List[Any]]:
    """Список-секция: нет ключа или значение не list → None + missing.

    Пустой список — валидный ответ («команд/handlers нет»), НЕ пропуск.
    """
    value = payload.get(key, _ABSENT) if isinstance(payload, dict) else _ABSENT
    if isinstance(value, list):
        return list(value)
    missing.append(key)
    return None


def _read_breakdown(stats: Any) -> Dict[str, int]:
    """Разбивка счётчиков по kind (``sent_via_channel.system`` и т.п.) — точечные ключи.

    Отдельным словарём, а не полями dataclass, по двум причинам. Во-первых, точка
    в имени не может быть именем поля. Во-вторых (существенное): состав kind'ов
    зависит от топологии и заранее не перечислим — так и записано в источнике
    (``router_manager._inc_stat``: разбивка «заводится на лету»). Поэтому
    отсутствие такого ключа — законное «груза этого класса не было», а НЕ
    расхождение формы: в ``missing`` разбивка не участвует, иначе на каждом
    рецепте без state-трафика инструмент кричал бы о несуществующей пропаже.
    """
    out: Dict[str, int] = {}
    if not isinstance(stats, dict):
        return out
    for key, value in stats.items():
        if "." not in key or isinstance(value, bool):
            continue
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            continue  # не число — не счётчик
    return out


@dataclass
class RouterStats:
    """Счётчики router'а процесса (introspect.router_stats).

    Отвечает на «дошло/ушло/дропнулось ли сообщение». Счётчик, которого не было в
    ответе, равен ``None``, а его имя лежит в ``missing`` — ``None`` и ``0`` здесь
    разные показания: первое «не знаем», второе «трафика не было».
    ``raw`` — весь сырой ответ.

    **Почему полей стало больше.** Четырёх счётчиков не хватало, чтобы ответить
    «куда делись отправки»: ``sent_attempted`` расходится с ``sent_ok`` на сумму
    дверей (``sent_via_channel`` + ``sent_via_targets``) и ошибок, и без этих
    слагаемых тождество приходилось сводить руками через ``raw`` — признак
    дырявой обёртки, а не диагностики. Агрегаты ниже инициализируются router'ом
    при старте, поэтому их отсутствие — настоящее расхождение формы и честно
    попадает в ``missing``. Разбивка по kind живёт в ``by_kind``
    (см. :func:`_read_breakdown`).
    """

    ok: bool
    sent_ok: Optional[int]
    received: Optional[int]
    middleware_dropped: Optional[int]
    errors: Optional[int]
    # Куда делись отправки: попытки, двери доставки, асинхронная очередь отправителя.
    sent_attempted: Optional[int] = None
    sent_via_channel: Optional[int] = None
    sent_via_targets: Optional[int] = None
    queued_async: Optional[int] = None
    send_queue_size: Optional[int] = None
    # Потери на очередях получателя: вытеснено из data / заблокировано на never-drop.
    queue_data_evicted: Optional[int] = None
    queue_system_evict_blocked: Optional[int] = None
    frame_loans_released_on_evict: Optional[int] = None
    #: Ф4 Task 4.3: БЕЗВОЗВРАТНО потерянный never-drop груз (раньше жил только в
    #: stdlib-логе, мимо интроспекции). ``None`` = процесс старой сборки, ``0`` =
    #: потерь не было — разные показания.
    queue_never_drop_loss_total: Optional[int] = None
    #: Ф4 Task 4.3: «кто душит очередь X» — {"{proc}_{qtype}": {sender: {put, lost}}}
    #: со СТОРОНЫ ОТПРАВИТЕЛЯ (глубины получателя под затором врут). Пусто — либо
    #: процесс ничего не слал, либо сборка без счётчика (см. ``missing``).
    queue_senders: Dict[str, Any] = field(default_factory=dict)
    #: Точечные ключи разбивки по kind: {"sent_via_targets.state": 12, …}.
    by_kind: Dict[str, int] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "RouterStats":
        payload = _find_payload(res, "router_stats")
        stats = payload.get("router_stats") if isinstance(payload, dict) else None
        stats = stats if isinstance(stats, dict) else {}
        missing: List[str] = []
        return cls(
            ok=_is_ok(res, payload),
            sent_ok=_read_int(stats, "sent_ok", missing),
            received=_read_int(stats, "received", missing),
            middleware_dropped=_read_int(stats, "middleware_dropped", missing),
            errors=_read_int(stats, "errors", missing),
            sent_attempted=_read_int(stats, "sent_attempted", missing),
            sent_via_channel=_read_int(stats, "sent_via_channel", missing),
            sent_via_targets=_read_int(stats, "sent_via_targets", missing),
            queued_async=_read_int(stats, "queued_async", missing),
            send_queue_size=_read_int(stats, "send_queue_size", missing),
            queue_data_evicted=_read_int(stats, "queue_data_evicted", missing),
            queue_system_evict_blocked=_read_int(stats, "queue_system_evict_blocked", missing),
            frame_loans_released_on_evict=_read_int(stats, "frame_loans_released_on_evict", missing),
            queue_never_drop_loss_total=_read_int(stats, "queue_never_drop_loss_total", missing),
            queue_senders=_read_mapping(stats, "queue_senders", missing) or {},
            by_kind=_read_breakdown(stats),
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class QueueDepths:
    """Глубины собственных очередей процесса (introspect.queues).

    ``sizes`` — {тип_очереди: глубина|None}. None у отдельной очереди = qsize
    недоступен (macOS) — само по себе диагностично. ``sizes is None`` (и
    ``"queue_sizes"`` в ``missing``) — секции в ответе не было вовсе: раньше это
    давало пустой словарь, неотличимый от «очередей нет». ``raw`` — сырой ответ.
    """

    ok: bool
    sizes: Optional[Dict[str, Optional[int]]]
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "QueueDepths":
        payload = _find_payload(res, "queue_sizes")
        missing: List[str] = []
        return cls(
            ok=_is_ok(res, payload),
            sizes=_read_mapping(payload, "queue_sizes", missing),
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class WorkerStatus:
    """Статус процесса и его воркеров (introspect.status).

    ``process``/``status`` — имя и текущий статус процесса; ``workers`` —
    {имя_воркера: сериализуемый статус}. Поле, которого не было в ответе, равно
    ``None``, а его имя лежит в ``missing``: пустой ``workers`` («воркеров нет»)
    и отсутствующая секция ``workers`` («ручка ответила не тем») — разные факты.
    ``raw`` — весь сырой ответ.
    """

    ok: bool
    process: Optional[str]
    status: Optional[str]
    workers: Optional[Dict[str, Any]]
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "WorkerStatus":
        payload = _find_payload(res, "workers", "status")
        missing: List[str] = []
        return cls(
            ok=_is_ok(res, payload),
            process=_read_scalar(payload, "process", missing),
            status=_read_scalar(payload, "status", missing),
            workers=_read_mapping(payload, "workers", missing),
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


#: Ключи плоскости, ненулевое значение которых в покое — повод смотреть.
#: Сверх четырёх классов потери сюда входят пол ошибок (запись спасена, но
#: ШТАТНЫЙ маршрут сломан), его собственные отказы, отброшенная консоль,
#: несобравшееся сообщение и провалы ретеншена.
#:
#: Классы НЕ разделены на «потеря» и «деградация» намеренно: ``system_overview``
#: по своему контракту выдаёт ПОДСКАЗКИ, а не вердикты, а раскладывать чужие
#: счётчики по степеням тяжести, не воспроизведя их семантику, значило бы
#: сочинить вердикт.
OBSERVABILITY_LOSS_KEYS: tuple = LOSS_COUNTER_KEYS + (
    "errors_to_floor",
    "errors_floor_write_failures",
    "console_writes_dropped",
    "message_build_failures",
    "retention_delete_failures",
    "retention_compress_failures",
)

#: То же для секции ``buffer`` плоскости. Набор ключей у буфера логов и буфера
#: статистики РАЗНЫЙ (у второго нет ``dropped`` вовсе), поэтому отсутствие ключа
#: здесь — не расхождение формы, а свойство плоскости.
OBSERVABILITY_BUFFER_LOSS_KEYS: tuple = (
    "dropped",
    "dropped_at_stop",
    "enqueued_after_stop",
    "flush_failed",
    "flush_timeouts",
    "flush_contract_violations",
)


@dataclass
class ObservabilityCounters:
    """Счётчики трёх плоскостей наблюдаемости процесса (introspect.observability).

    ``planes`` — сырые секции ``{logger|error|stats: {...}}``; ``nonzero`` — то же,
    отфильтрованное до ненулевых счётчиков потерь (ключи буфера идут с префиксом
    ``buffer.``). Пустой ``nonzero`` при непустом ``planes`` читается как «тишина»
    — ровно тот инвариант, ради которого задача 2.V2 и существует.

    ``planes is None`` (и ``"counters"`` в ``missing``) — секции в ответе не было:
    это НЕ «потерь нет». Различать обязательно, иначе процесс, у которого команду
    вообще не спросили, выглядел бы здоровее всех.
    """

    ok: bool
    process: Optional[str]
    planes: Optional[Dict[str, Any]]
    nonzero: Dict[str, Dict[str, int]] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "ObservabilityCounters":
        payload = _find_payload(res, "counters", "effective")
        missing: List[str] = []
        planes = _read_mapping(payload, "counters", missing)
        return cls(
            ok=_is_ok(res, payload),
            process=payload.get("process") if isinstance(payload, dict) else None,
            planes=planes,
            nonzero=_nonzero_losses(planes),
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


def _int_or_none(value: Any) -> Optional[int]:
    """int, но не bool. ``True`` как счётчик — это ложь, арифметически незаметная."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _loss_items(section: Any) -> Dict[str, int]:
    """Именованные счётчики потерь ОДНОЙ плоскости, включая нулевые.

    Ключи буфера идут с префиксом ``buffer.``. Нулевые не выбрасываются: по
    дельте между двумя снимками ноль — законное «не росло», и выброси мы его
    здесь, отличить «не росло» от «ключа не было» стало бы нечем.
    ``dropped_by_channel``/``unresolved_channels`` — разбивки-словари, они уже
    отражены своим числовым классом.
    """
    if not isinstance(section, dict):
        return {}
    hits: Dict[str, int] = {}
    for key in OBSERVABILITY_LOSS_KEYS:
        value = _int_or_none(section.get(key))
        if value is not None:
            hits[key] = value
    buffer = section.get("buffer")
    if isinstance(buffer, dict):
        for key in OBSERVABILITY_BUFFER_LOSS_KEYS:
            value = _int_or_none(buffer.get(key))
            if value is not None:
                hits[f"buffer.{key}"] = value
    return hits


def _nonzero_losses(planes: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Ненулевые счётчики потерь по плоскостям. Пусто = тишина.

    Считаются только положительные int'ы: ``None`` («показания нет») порогом не
    считается.
    """
    out: Dict[str, Dict[str, int]] = {}
    if not isinstance(planes, dict):
        return out
    for plane, section in planes.items():
        hits = {key: value for key, value in _loss_items(section).items() if value > 0}
        if hits:
            out[plane] = hits
    return out


#: Порядок предпочтения плоскостей при выборе часов окна. Метка ``observed_at``
#: снимается каждым менеджером своими часами (одна и та же функция, но три
#: независимых вызова), поэтому окно считается по ОДНОЙ плоскости — смешивать
#: метки разных менеджеров значило бы получить длительность, которой не было ни у
#: одного из них. Порядок фиксирован, чтобы ответ не зависел от порядка ключей в
#: чужом словаре.
_WINDOW_PLANE_ORDER: tuple = ("logger", "error", "stats")


@dataclass
class DeliveryWindow:
    """Идут ли записи МЕЖДУ ДВУМЯ снимками счётчиков (Task 5.7, драйверная половина).

    Один снимок отвечает «сколько записано с начала жизни процесса» — по нему
    нельзя сказать, работает ли наблюдаемость СЕЙЧАС. Поток — это разница во
    времени, и держать её может только тот, кто делает два замера.

    Три состояния РАЗЛИЧИМЫ намеренно, и это не украшение:

      * ``delivering`` — счётчик доставки вырос: записи доходят до приёмников;
      * ``losing`` — выросли счётчики потерь: записи были и НЕ доехали. С
        ``delivering`` не исключают друг друга (часть доехала, часть отброшена);
      * ``silent_source`` — не выросло ничего: источник за окно не сказал ни
        слова. Это **не** провал вердикта и не поломка — на процессе, который
        молчит по делу, требовать записей нечего. Схлопни ``silent_source`` в
        провал — и «ничего не писали» стало бы неотличимо от «пишем в никуда»,
        то есть вернулся бы ровно тот класс, который задача закрывает.

    ``self_cost`` — цена САМОГО опроса. Читающая команда идёт через диспетчер и
    сама пишет записи; на процессе с включённым DEBUG этого хватало бы, чтобы
    ``delivering`` был истинным ВСЕГДА, даже на молчащем источнике. Поэтому цена
    не предполагается нулевой, а измеряется: два чтения подряд без паузы дают
    прирост ровно одного опроса, и он вычитается (``written_net``).

    **Граница вычета названа прямо: он верен в ЭКСКЛЮЗИВНОМ окне.** Зазор
    ``after → control`` приписывается своему опросу целиком, поэтому чужой писатель
    в этом зазоре (второй клиент драйвера, GUI-панель — на DEBUG это ≈5 записей на
    опрос) вычитается как своя цена. Честного разделения «мои записи / чужие» здесь
    нет: счётчик считает записи, а не их авторов. Что сделано вместо этого —
    ``cost_exceeds_window``: если вычет оказался БОЛЬШЕ всего окна при непустом
    окне, арифметика заведомо недостоверна, и тогда ``silent_source`` не
    выставляется. Уверенная тишина на пишущем источнике — это ровно тот класс,
    который задача 5.7 закрывала; лучше сказать «не установлено», чем сказать
    неверно. Механизм честного вычета по авторству — резидуал (корзина 3).

    ``counters_reset`` — база сдвинулась между снимками, окно недостоверно, и это
    отдельное состояние, а не «тишина». Счётчики живут в объектах менеджеров, а
    менеджер у каждой плоскости СВОЙ: пересборка (чужой ``config.reload``,
    ``switch``, авто-рестарт внутри выдержки) обнуляет ровно одну плоскость.
    Поэтому сдвиг ищется **поплоскостно**, а не по сумме: сумма, в которой одна
    плоскость обнулилась, а соседняя выросла, растёт — и окно объявлялось бы
    достоверным при сдвинутой базе. ``reset_planes`` называет виновных поимённо:
    вердикт «база уехала» без адреса нечинибелен.
    """

    delivering: bool
    silent_source: bool
    losing: bool
    written_delta: int
    self_cost: int
    written_net: int
    loss_delta: int
    counters_reset: bool
    window_sec: Optional[float] = None
    by_channel: Dict[str, int] = field(default_factory=dict)
    losses: Dict[str, Dict[str, int]] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    reset_planes: List[str] = field(default_factory=list)
    cost_exceeds_window: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """Плоский dict для ответа наружу (Dict at Boundary)."""
        return {
            "delivering": self.delivering,
            "silent_source": self.silent_source,
            "losing": self.losing,
            "written_delta": self.written_delta,
            "self_cost": self.self_cost,
            "written_net": self.written_net,
            "loss_delta": self.loss_delta,
            "counters_reset": self.counters_reset,
            "reset_planes": self.reset_planes,
            "cost_exceeds_window": self.cost_exceeds_window,
            "window_sec": self.window_sec,
            "written_by_channel": self.by_channel,
            "losses": self.losses,
            "missing": self.missing,
        }


def _written_total(planes: Any) -> Optional[int]:
    """Сумма счётчиков доставки по всем плоскостям снимка.

    ``None`` — ни одна плоскость счётчика не дала: это «показаний нет», и оно не
    равно нулю. Ноль в такой позиции читался бы как «записей не было», то есть
    ответом на вопрос, который никто не смог задать.
    """
    if not isinstance(planes, dict):
        return None
    total: Optional[int] = None
    for section in planes.values():
        if not isinstance(section, dict):
            continue
        for key in DELIVERY_COUNTER_KEYS:
            value = _int_or_none(section.get(key))
            if value is not None:
                total = value if total is None else total + value
    return total


def _written_by_channel(planes: Any) -> Dict[str, int]:
    """Разбивка доставки по приёмникам, суммарно по плоскостям."""
    out: Dict[str, int] = {}
    if not isinstance(planes, dict):
        return out
    for section in planes.values():
        if not isinstance(section, dict):
            continue
        by_channel = section.get("channel_written_by_channel")
        if not isinstance(by_channel, dict):
            continue
        for name, value in by_channel.items():
            number = _int_or_none(value)
            if number is not None:
                out[str(name)] = out.get(str(name), 0) + number
    return out


def _loss_total(planes: Any) -> int:
    """Сумма всех именованных счётчиков потерь снимка."""
    if not isinstance(planes, dict):
        return 0
    return sum(sum(_loss_items(section).values()) for section in planes.values())


def _reset_planes(before: Any, after: Any) -> List[str]:
    """Плоскости, чья база уехала между снимками — поимённо, в порядке первого снимка.

    Судить о сдвиге базы по СУММЕ нельзя: менеджер у каждой плоскости свой, и
    пересборка обнуляет ровно одну. Обнулившийся logger при выросшем stats даёт
    растущую сумму — сдвиг становится невидим ровно там, где он и происходит
    (авто-рестарт процесса внутри выдержки `config_reload_verified`).

    Сдвигом считается любое из трёх, и все три — одно обстоятельство «мерить нечем»:

      * счётчик доставки плоскости уменьшился;
      * суммарные потери плоскости уменьшились;
      * плоскость показывала число в первом снимке и перестала во втором (её
        вклад молча исчезает из суммы — тот же сдвиг, только без отрицательной
        дельты, по которой его ловили раньше).

    Появление НОВОЙ плоскости сдвигом не считается: её вклад до окна был нулевым,
    прирост честен.
    """
    out: List[str] = []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return out
    for name, first in before.items():
        if not isinstance(first, dict):
            continue
        second = after.get(name)
        written_before = _written_total({name: first})
        if not isinstance(second, dict):
            if written_before is not None:
                out.append(str(name))
            continue
        written_after = _written_total({name: second})
        if written_before is not None and (written_after is None or written_after < written_before):
            out.append(str(name))
            continue
        if sum(_loss_items(second).values()) < sum(_loss_items(first).values()):
            out.append(str(name))
    return out


def _window_seconds(before: Any, after: Any) -> Optional[float]:
    """Длительность окна по метке ``observed_at`` ОДНОЙ плоскости (см. порядок выше)."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    planes = [name for name in _WINDOW_PLANE_ORDER if name in before and name in after]
    planes += [name for name in after if name in before and name not in _WINDOW_PLANE_ORDER]
    for name in planes:
        first, second = before.get(name), after.get(name)
        if not isinstance(first, dict) or not isinstance(second, dict):
            continue
        started, ended = first.get(OBSERVED_AT_KEY), second.get(OBSERVED_AT_KEY)
        if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
            return float(ended) - float(started)
    return None


def delivery_window(before: Any, after: Any, *, control: Any = None) -> DeliveryWindow:
    """Свести два (или три) снимка ``counters`` в вердикт о потоке записей.

    Args:
        before: снимок в момент смены — секция ``counters`` ответа ``config.reload``.
        after: снимок после выдержки — секция ``counters`` ``introspect.observability``.
        control: НЕОБЯЗАТЕЛЬНЫЙ третий снимок, снятый сразу за ``after`` без паузы.
            Прирост ``after → control`` — цена одного опроса, она вычитается из
            наблюдённой дельты. Без него цена считается нулевой, и это честно
            только там, где опрос заведомо не пишет (уровень выше DEBUG).

    Отсутствие показаний и ноль различаются: снимок без счётчика доставки даёт
    ``missing``, а не «записей не было».
    """
    missing: List[str] = []
    written_before = _written_total(before)
    written_after = _written_total(after)
    if written_before is None:
        missing.append("before.channel_written_records")
    if written_after is None:
        missing.append("after.channel_written_records")

    self_cost = 0
    if control is not None:
        written_control = _written_total(control)
        if written_control is None:
            missing.append("control.channel_written_records")
        elif written_after is not None:
            self_cost = max(0, written_control - written_after)

    reset_planes = _reset_planes(before, after)

    if written_before is None or written_after is None:
        return DeliveryWindow(
            delivering=False,
            silent_source=False,
            losing=False,
            written_delta=0,
            self_cost=self_cost,
            written_net=0,
            loss_delta=0,
            # Ревью корзины 2 (Ф-4): здесь стояло жёсткое `False` рядом с
            # непустым `reset_planes` — два поля одного ответа противоречили друг
            # другу, и читатель, спрашивающий «база уезжала?», получал «нет» при
            # уехавшей базе. Отсутствие СУММАРНОГО счётчика не отменяет того, что
            # по конкретной плоскости перезапуск виден.
            counters_reset=bool(reset_planes),
            window_sec=_window_seconds(before, after),
            by_channel={},
            losses={},
            missing=missing,
            reset_planes=reset_planes,
        )

    written_delta = written_after - written_before
    loss_delta = _loss_total(after) - _loss_total(before)
    # Пояс к per-plane признаку: суммарные потери, УЕХАВШИЕ НАЗАД, — это тоже
    # перезапуск базы, даже если ни одна плоскость поимённо его не показала
    # (плоскость могла исчезнуть из снимка целиком). Ревью корзины 2, Ф-4:
    # без этого пояса `losing` считался бы по отрицательной дельте как «не
    # теряем», то есть отсутствие данных выдавалось бы за благополучие.
    reset = bool(reset_planes) or loss_delta < 0
    written_net = max(0, written_delta - self_cost)
    # Вычет съел больше, чем показало всё окно: в зазоре писал кто-то ещё, и
    # арифметика цены недостоверна. Тишину в этом случае не утверждаем (см.
    # докстринг DeliveryWindow, граница эксклюзивного окна).
    cost_exceeds_window = written_delta > 0 and self_cost > written_delta
    losing = (not reset) and loss_delta > 0
    delivering = (not reset) and written_net > 0
    # Разбивка по приёмникам — только приросты: абсолютные числа второго снимка
    # ответили бы на «сколько за всю жизнь», а спрашивают про окно.
    by_before = _written_by_channel(before)
    by_channel = {
        name: value - by_before.get(name, 0)
        for name, value in _written_by_channel(after).items()
        if value - by_before.get(name, 0) > 0
    }
    losses_before = {plane: _loss_items(section) for plane, section in (before or {}).items()}
    losses: Dict[str, Dict[str, int]] = {}
    for plane, section in (after or {}).items():
        base = losses_before.get(plane, {})
        grown = {key: value - base.get(key, 0) for key, value in _loss_items(section).items()}
        grown = {key: value for key, value in grown.items() if value > 0}
        if grown:
            losses[plane] = grown
    return DeliveryWindow(
        delivering=delivering,
        silent_source=(not reset) and not delivering and loss_delta == 0 and not cost_exceeds_window,
        losing=losing,
        written_delta=written_delta,
        self_cost=self_cost,
        written_net=written_net,
        loss_delta=loss_delta,
        counters_reset=reset,
        window_sec=_window_seconds(before, after),
        by_channel=by_channel,
        losses=losses,
        missing=missing,
        reset_planes=reset_planes,
        cost_exceeds_window=cost_exceeds_window,
    )


@dataclass
class MemoryStats:
    """Инвентарь памяти процесса (introspect.memory): SHM / пул / очереди.

    Только СТАТИСТИКА (Dict at Boundary) — кадры и содержимое SHM по сокету не
    гоняем. Секции независимы и best-effort: недоступная подсистема → ``None``
    (не ошибка). ``memory`` — ``MemoryManager.get_stats()``; ``pool`` — loan-счётчики
    SHM-колец из ПУБЛИЧНОГО ``router_manager.get_stats()`` (F6: ``frame_loan_pools``/
    ``frame_slots_*``); ``queues`` — глубины очередей (как introspect.queues);
    ``shm_registry`` — инвентарь SHM-реестра (launcher-level file-marker: в дочернем
    процессе обычно ``None``); ``os_memory`` — RSS/VMS процесса ОС (``{rss, vms, pid}``,
    Task 3.2; секция ответа зовётся ``os``, атрибут — ``os_memory``, чтобы не затенять
    stdlib-``os``). ``raw`` — сырой ответ.

    **Здесь ``None`` двузначен, и различает их ``missing``.** Секция, пришедшая явным
    ``null``, — это ОТВЕТ сервера «подсистема недоступна» (штатный best-effort контракт
    команды), она ``None`` и в ``missing`` НЕ попадает. Секция, которой в ответе не
    было вовсе, — расхождение формы: тоже ``None``, но её имя есть в ``missing``.
    """

    ok: bool
    memory: Optional[Dict[str, Any]]
    pool: Optional[Dict[str, Any]]
    queues: Optional[Dict[str, Any]]
    shm_registry: Optional[Dict[str, Any]]
    os_memory: Optional[Dict[str, Any]] = None
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "MemoryStats":
        payload = _find_payload(res, "memory", "pool", "queues", "shm_registry", "os")
        missing: List[str] = []

        def _sec(key: str) -> Optional[Dict[str, Any]]:
            val = payload.get(key, _ABSENT) if isinstance(payload, dict) else _ABSENT
            if val is _ABSENT:
                missing.append(key)
                return None
            return val if isinstance(val, dict) else None

        return cls(
            ok=_is_ok(res, payload),
            memory=_sec("memory"),
            pool=_sec("pool"),
            queues=_sec("queues"),
            shm_registry=_sec("shm_registry"),
            os_memory=_sec("os"),
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class ProcessCapabilities:
    """Карточка процесса из introspect.capabilities (контактная книжка, Ф1 Task 1.9).

    Контракт процесса: ``commands`` — [{name, description, tags}], ``registers`` —
    {имя_регистра: [имена_полей]} (структура, без значений), ``router_handlers`` —
    НЕ-командные ключи event_dispatcher.

    **Строгий край (довесок к Task 1.1).** Типы полей `commands`/`router_handlers`/
    `registers` остаются НЕ-Optional (`[]`/`{}`) — потребители (`capability_render.py`,
    `command_validate.py`, `dump_capabilities.py`, `mcp_driver_session.py`) итерируют
    их напрямую без None-проверок. Провенанс не теряется: ключ, которого в ответе не
    было вовсе, попадает в ``missing`` — секция-пустышка ОТ СЕРВЕРА («команд нет») и
    секция-пропуск (сервер переименовал ключ / ручка не ответила) дают одинаковый
    `[]`/`{}`, но различаются наличием имени в ``missing``. ``raw`` — весь сырой ответ.
    """

    ok: bool
    process: Optional[str]
    commands: List[Dict[str, Any]]
    router_handlers: List[str]
    registers: Dict[str, List[str]]
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "ProcessCapabilities":
        payload = _find_payload(res, "commands", "registers")
        missing: List[str] = []
        return cls(
            ok=_is_ok(res, payload),
            process=_read_scalar(payload, "process", missing),
            commands=_read_list(payload, "commands", missing) or [],
            router_handlers=_read_list(payload, "router_handlers", missing) or [],
            registers=_read_mapping(payload, "registers", missing) or {},
            missing=missing,
            raw=res if isinstance(res, dict) else {},
        )


@dataclass
class Capabilities:
    """Свод «контактной книжки» по всей системе (driver-side fan-out, Ф1 Task 1.9).

    ``processes`` — карточки всех процессов (включая ProcessManager);
    ``topology`` — {имя: {"class": dotted-path}} управляемых процессов (из PM);
    ``channels`` — каналы router'а PM. ``ok`` = PM ответил и все карточки собраны.
    """

    ok: bool
    processes: Dict[str, ProcessCapabilities]
    topology: Dict[str, Dict[str, Any]]
    channels: List[Dict[str, str]]
    raw: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "unwrap",
    "UNWRAP_MISS",
    "RouterStats",
    "QueueDepths",
    "WorkerStatus",
    "MemoryStats",
    "ObservabilityCounters",
    "DeliveryWindow",
    "delivery_window",
    "OBSERVABILITY_LOSS_KEYS",
    "OBSERVABILITY_BUFFER_LOSS_KEYS",
    "ProcessCapabilities",
    "Capabilities",
]
