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


@dataclass
class MemoryStats:
    """Инвентарь памяти процесса (introspect.memory): SHM / пул / очереди.

    Только СТАТИСТИКА (Dict at Boundary) — кадры и содержимое SHM по сокету не
    гоняем. Секции независимы и best-effort: недоступная подсистема → ``None``
    (не ошибка). ``memory`` — ``MemoryManager.get_stats()``; ``pool`` — loan-счётчики
    SHM-колец из ПУБЛИЧНОГО ``router_manager.get_stats()`` (F6: ``frame_loan_pools``/
    ``frame_slots_*``); ``queues`` — глубины очередей (как introspect.queues);
    ``shm_registry`` — инвентарь SHM-реестра (launcher-level file-marker: в дочернем
    процессе обычно ``None``). ``raw`` — сырой ответ.

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
    missing: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, res: Any) -> "MemoryStats":
        payload = _find_payload(res, "memory", "pool", "queues", "shm_registry")
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
    "ProcessCapabilities",
    "Capabilities",
]
