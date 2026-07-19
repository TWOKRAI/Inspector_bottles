# -*- coding: utf-8 -*-
"""events.py — событийный канал driver'а: курсорные плоскости (B.1).

Ядро — :class:`EventHub` (композиция, как ``WatchController``): reader-поток пишет
(`emit`), читатели ходят курсорами (`page`) — недеструктивно и независимо друг от
друга. Аналог: K8s watch (resourceVersion + bookmarks), CDP event domains,
journald cursor.

Устройство:

  * **arrival-кольцо** — оригинальные push-сообщения в порядке прихода (плотный
    глобальный ``seq``). Источник для ``plane="all"`` и для legacy-дренажа
    :meth:`drain` (обёртка ``events()``);
  * **плоскостные кольца** (:data:`PLANES`) — классифицированные view сообщений с
    плотным per-plane ``seq``: state / logs / errors / stats / telemetry / ui +
    ``other`` (всё, что не подошло ни под одну классификацию, — НЕ теряется молча);
  * **курсор** ``"plane:seq@gen"`` — позиция читателя. ``gen`` — токен поколения
    hub'а: реконнект пересоздаёт driver (и hub), нумерация начинается заново —
    курсор прежнего поколения даёт явный ``reset_required``, а не тихое чтение
    не с того места. Полный re-list после реконнекта — Phase D;
  * **dropped** — точная потеря ОТНОСИТЕЛЬНО КУРСОРА: плотный seq ⇒
    ``oldest_в_кольце − cursor − 1``. Переполнение кольца видно читателю, а не
    съедается молча (тот же класс «тихой слепоты», что чинил Phase 0);
  * **bookmark** — курсор «хвост сейчас»: начать читать только новое.

Классификация push'ей:

  * ``state.changed`` → ``state`` (сообщение целиком) + ``telemetry`` (каждая
    дельта отдельным ``telemetry.delta``-item — курсорное зеркало ingest-потока
    telemetry read-model, вход для B.2 ``metric_threshold``; удаление узла
    помечено ``deleted: True``). Из-за fan-out'а k дельт → k item'ов при общем
    maxlen плоскость telemetry вытесняется быстрее остальных: ``dropped``
    НЕсравним между плоскостями — это счётчик потери СВОЕЙ плоскости, не
    общий барометр системы;
  * ``log.record`` → ``logs``; ``ui.event`` → ``ui``;
  * ``observability.record`` → расщепляется ПО ``kind`` записей (log→logs,
    error→errors, stats→stats; без kind → other): смешанный батч даёт по view на
    плоскость, форма конверта (``data.records``) сохраняется. Оригинал в
    arrival-кольце НЕ расщепляется — legacy-дренаж бит-в-бит;
  * прочее (незнакомая команда, некарантинный поздний reply) → ``other``.

Синхронные подписчики (``subscribe``) получают ОРИГИНАЛЬНОЕ сообщение в
reader-потоке (колбэк не роняет reader) — контракт Ф1 Task 1.1 сохранён.

`_EventChannelMixin` остался публичным API driver'а — теперь это тонкие делегаты
в ``self._hub`` (хост заводит его в ``__init__``); транспортные ``_running``/
``_reader`` доезжают в hub предикатом ``alive`` (выход из бесконечного ожидания
на закрытом соединении).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from itertools import islice
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

# Колбэк подписчика на события (получает распарсенный push-dict).
EventCallback = Callable[[Dict[str, Any]], None]

# Команда live-хвоста наблюдаемости на проводе (Ф5.20b): процесс пушит записи
# логов/ошибок/статистики адресно подписчику ЭТИМ command (зеркало
# RecordForwardChannel.FORWARD_COMMAND). Строка-контракт, не импортируем из
# framework-канала — чтобы driver не тянул серверный модуль (Dict at Boundary).
OBSERVABILITY_RECORD_COMMAND: str = "observability.record"

# Зеркало Delta.to_dict(): new_value == '__MISSING__' → удаление узла. Литерал,
# а не импорт state_store_module — package __init__ тянет Qt в headless-клиент;
# дрейф маркера ловит контракт-тест test_missing_marker_matches_state_store.
MISSING_MARKER: str = "__MISSING__"

#: Плоскости событий (B.1). ``other`` — сверх плана: события мимо классификации
#: обязаны остаться видимыми, а не пропасть молча.
PLANES: Tuple[str, ...] = ("state", "logs", "errors", "stats", "telemetry", "ui", "other")

#: Псевдо-плоскость «все события в порядке прихода» (arrival-кольцо, оригиналы).
ALL_PLANE: str = "all"

# kind записи наблюдаемости → плоскость (нормализатор record_display проставляет
# kind ∈ {log, error, stats}; чужой/отсутствующий kind → other).
_KIND_TO_PLANE: Dict[Any, str] = {"log": "logs", "error": "errors", "stats": "stats"}

# Размер страницы events_page: дефолт держит MCP-ответ компактным, потолок
# страхует контекст агента от заливки (response_format-лимиты целиком — Phase E).
_DEFAULT_PAGE_LIMIT = 100
_MAX_PAGE_LIMIT = 500


def iter_state_deltas(msg: Any) -> List[Dict[str, Any]]:
    """Дельты push'а ``state.changed`` — ЕДИНСТВЕННЫЙ разборщик этого wire-контракта.

    Возвращает только dict-дельты с непустым строковым ``path``. Им пользуются
    плоскостная классификация, telemetry-ingest driver'а и предикаты
    ``await_condition`` — три независимых парсера разъезжались бы молча.
    """
    if not isinstance(msg, dict) or msg.get("command") != "state.changed":
        return []
    data = msg.get("data")
    deltas = data.get("deltas") if isinstance(data, dict) else None
    if not isinstance(deltas, list):
        return []
    out: List[Dict[str, Any]] = []
    for delta in deltas:
        if isinstance(delta, dict):
            path = delta.get("path")
            if isinstance(path, str) and path:
                out.append(delta)
    return out


#: supervisor-переходы, означающие смену идентичности процесса (рестарт/смерть).
#: Приход такого события = наблюдаемый процесс пересёк границу инкарнации.
_RESTART_BOUNDARY_EVENTS: frozenset = frozenset({"recovered", "crashed", "gave_up"})


def _is_restart_boundary(msg: Dict[str, Any]) -> bool:
    """True, если push несёт supervisor-переход рестарта наблюдаемого процесса
    (``processes.<name>.supervisor.event`` ∈ boundary). Такой переход = смена
    инкарнации → курсорные плоскости B.1 обязаны сброситься (§8), иначе курсор
    молча читает СКВОЗЬ границу рестарта (долг ревью B.1)."""
    for delta in iter_state_deltas(msg):
        path = delta.get("path")
        if isinstance(path, str) and path.endswith(".supervisor.event"):
            value = delta.get("new_value", delta.get("value"))
            if value in _RESTART_BOUNDARY_EVENTS:
                return True
    return False


def _classify(msg: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Разложить push-сообщение по плоскостям: список пар (plane, view).

    view для state/logs/ui/other — само сообщение (без копий); для
    observability.record — производный конверт с записями одной плоскости; для
    telemetry — производный ``telemetry.delta`` на каждую дельту: дельта в
    ``data``, удаление узла (:data:`MISSING_MARKER`) помечено ``deleted: True``
    — читатель (B.2 metric_threshold) не должен сравнивать строку-сентинел
    с числом.
    """
    cmd = msg.get("command")
    if cmd == "state.changed":
        views: List[Tuple[str, Dict[str, Any]]] = [("state", msg)]
        for delta in iter_state_deltas(msg):
            if delta.get("new_value") == MISSING_MARKER:
                delta = {**delta, "deleted": True}
            views.append(("telemetry", {"command": "telemetry.delta", "data": delta}))
        return views
    if cmd == "log.record":
        return [("logs", msg)]
    if cmd == "ui.event":
        return [("ui", msg)]
    if cmd == OBSERVABILITY_RECORD_COMMAND:
        return _classify_observability(msg)
    return [("other", msg)]


def extract_observability_records(data: Any) -> List[Dict[str, Any]]:
    """Развернуть конверт observability.record в плоский список записей.

    ``data.records`` (пачка из drain log/stats) и/или ``data.record`` (одиночная
    write-through запись error/critical) → список record-dict'ов в порядке
    поступления. ЕДИНСТВЕННЫЙ разборщик этого wire-контракта — им пользуются и
    плоскостная классификация здесь, и ``BackendDriver.observability_records``
    (два независимых парсера разъезжались бы молча).
    """
    if not isinstance(data, dict):
        return []
    records: List[Dict[str, Any]] = []
    batch = data.get("records")
    if isinstance(batch, list):
        records.extend(r for r in batch if isinstance(r, dict))
    single = data.get("record")
    if isinstance(single, dict):
        records.append(single)
    return records


def _classify_observability(msg: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Расщепить observability.record по kind записей (батч и/или одиночная).

    Каждая плоскость получает конверт прежней формы (``data.records`` — всегда
    список, одиночная ``data.record`` нормализуется в батч из одной), прочие ключи
    ``data`` и верхнего уровня сохраняются. Сообщение без разборных записей —
    целиком в ``other``.
    """
    data = msg.get("data")
    records = extract_observability_records(data)
    if not records:
        return [("other", msg)]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        groups.setdefault(_KIND_TO_PLANE.get(rec.get("kind"), "other"), []).append(rec)
    base_data = {k: v for k, v in data.items() if k not in ("records", "record")}
    return [(plane, {**msg, "data": {**base_data, "records": group}}) for plane, group in groups.items()]


class EventHub:
    """Курсорные плоскости событий: недеструктивное повторяемое чтение с видимой потерей.

    Один Condition охраняет все кольца, счётчики и список подписчиков (наследник
    ``_events_cv``); на нём же блокируется legacy-``drain(timeout)`` и будятся
    ожидающие при :meth:`wake` (close() driver'а).
    """

    def __init__(self, maxlen: int = 1000, *, alive: Optional[Callable[[], bool]] = None) -> None:
        self._cv = threading.Condition()
        # Предикат «соединение ещё живо»: выход drain(None) из вечного ожидания
        # на закрытом/не открытом соединении (новых событий не будет).
        self._alive: Callable[[], bool] = alive if alive is not None else (lambda: False)
        # Токен поколения в курсорах: новый hub (реконнект) ⇒ старый курсор даёт
        # явный reset_required, а не тихое чтение с совпавшего по числу места.
        # §8: тот же токен ротируется на границе рестарта наблюдаемого процесса.
        self._gen = uuid.uuid4().hex[:6]
        self._gen_rotations = 0  # сколько раз токен ротирован из-за рестарта (диагностика)

        self._arrival: Deque[Tuple[int, Dict[str, Any]]] = deque(maxlen=maxlen)
        self._gseq = 0  # плотный глобальный seq (arrival)
        self._rings: Dict[str, Deque[Tuple[int, Dict[str, Any]]]] = {p: deque(maxlen=maxlen) for p in PLANES}
        self._pseq: Dict[str, int] = dict.fromkeys(PLANES, 0)  # плотные per-plane seq

        self._drain_seq = 0  # внутренний курсор legacy-дренажа events()
        self._subscribers: List[EventCallback] = []
        self._event_errors = 0  # счётчик исключений колбэков (диагностика)

    # ---- Запись (reader-поток) ----

    def emit(self, msg: Dict[str, Any]) -> None:
        """Принять push: arrival-кольцо + классификация по плоскостям + подписчики.

        Вызывается из reader-потока. Исключение любого колбэка не роняет
        reader (глотается, инкрементит ``event_errors``) и не мешает остальным.
        """
        with self._cv:
            self._gseq += 1
            self._arrival.append((self._gseq, msg))
            for plane, view in _classify(msg):
                self._pseq[plane] += 1
                self._rings[plane].append((self._pseq[plane], view))
            if _is_restart_boundary(msg):
                # §8: наблюдаемый процесс пересёк рестарт (supervisor.event) → ротируем
                # generation-токен. Курсоры «до рестарта» на следующем page() дадут
                # reset_required, а не прочитают молча через границу инкарнации —
                # закрытый долг ревью B.1. Событие-граница уже в кольцах (см. выше).
                self._gen = uuid.uuid4().hex[:6]
                self._gen_rotations += 1
            subscribers = list(self._subscribers)  # снимок под локом
            self._cv.notify_all()
        # Колбэки — вне лока: могут быть медленными и/или звать driver повторно.
        for cb in subscribers:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001 — контракт: колбэк не роняет reader
                self._event_errors += 1

    def wake(self) -> None:
        """Разбудить ожидающих в drain(timeout): новых событий не будет (close())."""
        with self._cv:
            self._cv.notify_all()

    # ---- Подписчики (синхронные, reader-поток) ----

    def subscribe(self, callback: EventCallback) -> EventCallback:
        """Подписаться: callback зовётся на каждое push-сообщение (оригинал).

        Колбэк исполняется в reader-потоке — держи его лёгким (тяжёлую работу
        отдай в свой поток/очередь). Возвращает сам callback (хэндл для unsubscribe).
        """
        with self._cv:
            self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: EventCallback) -> None:
        """Отписать ранее зарегистрированный callback (no-op, если его нет)."""
        with self._cv:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    @property
    def event_errors(self) -> int:
        """Сколько раз колбэк подписчика бросил исключение (диагностика)."""
        return self._event_errors

    # ---- Курсорное чтение (B.1) ----

    def page(
        self,
        plane: Optional[str] = None,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Недеструктивная страница событий плоскости от курсора.

        Args:
            plane: имя плоскости (:data:`PLANES`) или ``"all"``/``None`` — все
                события в порядке прихода (оригинальные сообщения).
            cursor: ``next_cursor``/``bookmark`` прошлого ответа; ``None`` — с
                самого старого доступного (потеря до него — в ``dropped``).
            limit: максимум событий в странице (дефолт 100, потолок 500).

        Returns:
            ``{"success": True, "plane", "items": [{"seq", "event"}, ...], "count",
            "next_cursor", "dropped", "bookmark"}``. ``dropped`` — сколько событий
            между курсором и первым возвращённым вытеснено из кольца (читатель
            видит свою слепую зону). ЛЮБАЯ ошибка курсора (нечитаемый, чужое
            поколение, чужая плоскость, впереди потока) → error-dict c
            ``reset_required: True`` + ``bookmark`` — восстановление всегда одно:
            начать заново с ``cursor=null`` (полный re-list — Phase D). Неизвестная
            плоскость → error-dict со списком ``planes``.
        """
        plane_key = ALL_PLANE if plane is None else plane
        if plane_key != ALL_PLANE and plane_key not in self._rings:
            return {
                "success": False,
                "error": f"неизвестная плоскость {plane_key!r}",
                "planes": [ALL_PLANE, *PLANES],
            }
        try:
            cursor_seq = self._parse_cursor(cursor, plane_key)
        except ValueError as exc:
            with self._cv:
                newest = self._gseq if plane_key == ALL_PLANE else self._pseq[plane_key]
            return {
                "success": False,
                "error": str(exc),
                "reset_required": True,
                "bookmark": self._fmt_cursor(plane_key, newest),
            }
        try:
            page_limit = int(limit) if limit is not None else _DEFAULT_PAGE_LIMIT
        except (TypeError, ValueError):
            return {"success": False, "error": f"limit должен быть целым числом, получено {limit!r}"}
        page_limit = max(1, min(page_limit, _MAX_PAGE_LIMIT))

        with self._cv:
            ring = self._arrival if plane_key == ALL_PLANE else self._rings[plane_key]
            newest = self._gseq if plane_key == ALL_PLANE else self._pseq[plane_key]
            bookmark = self._fmt_cursor(plane_key, newest)
            if cursor_seq > newest:
                return {
                    "success": False,
                    "error": (
                        f"курсор {cursor!r} впереди потока (последний seq {newest}) — "
                        "вероятно, курсор прежнего соединения; начни заново с cursor=null"
                    ),
                    "reset_required": True,
                    "bookmark": bookmark,
                }
            ring_len = len(ring)
            oldest = ring[0][0] if ring_len else newest + 1
            dropped = max(0, oldest - (cursor_seq + 1))
            offset = max(cursor_seq + 1, oldest) - oldest  # плотный seq ⇒ индекс в деке
            selected = list(islice(ring, offset, offset + page_limit))

        items = [{"seq": s, "event": m} for s, m in selected]
        if items:
            next_seq = items[-1]["seq"]
        elif ring_len == 0:
            # Всё вытеснено: потеря уже сообщена в dropped — курсор вперёд, чтобы
            # не рапортовать одну и ту же слепую зону бесконечно.
            next_seq = newest
        else:
            next_seq = cursor_seq  # догнали хвост — курсор стабилен
        return {
            "success": True,
            "plane": plane_key,
            "items": items,
            "count": len(items),
            "next_cursor": self._fmt_cursor(plane_key, next_seq),
            "dropped": dropped,
            "bookmark": bookmark,
        }

    def _fmt_cursor(self, plane_key: str, seq: int) -> str:
        return f"{plane_key}:{seq}@{self._gen}"

    def _parse_cursor(self, cursor: Optional[Any], plane_key: str) -> int:
        """Курсор → seq. ValueError с обучающим текстом на любой неразборный вход.

        Принимается ТОЛЬКО полная форма ``plane:seq@gen`` — та, что выдают
        ``next_cursor``/``bookmark``. Усечённые формы (без ``@gen`` или без
        префикса плоскости) отвергаются: пропуск проверки поколения/плоскости
        означал бы тихое чтение не с того места — ровно тот класс слепоты,
        который B.1 устраняет.
        """
        if cursor in (None, "", 0):
            return 0
        text = str(cursor)
        if "@" not in text or ":" not in text:
            raise ValueError(
                f"нечитаемый курсор {cursor!r}: ожидаю полную форму 'plane:seq@gen' "
                "из next_cursor/bookmark прошлого ответа — начни заново с cursor=null"
            )
        text, _, gen = text.rpartition("@")
        if gen != self._gen:
            raise ValueError(
                f"курсор поколения {gen!r} не подходит к текущему {self._gen!r} "
                "(driver пересоздан после реконнекта) — начни заново с cursor=null"
            )
        prefix, _, seq_text = text.partition(":")
        if prefix != plane_key:
            raise ValueError(
                f"курсор плоскости {prefix!r} не подходит к чтению {plane_key!r} — у каждой плоскости своя нумерация"
            )
        if not seq_text.isdigit():
            raise ValueError(
                f"нечитаемый курсор {cursor!r}: ожидаю 'plane:seq@gen' из next_cursor/bookmark — "
                "начни заново с cursor=null"
            )
        return int(seq_text)

    # ---- Legacy-дренаж (обёртка events(), удаление — F.1) ----

    def drain(
        self,
        timeout: Optional[float] = 0.0,
        *,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Прежняя семантика events(): «всё новое с прошлого дренажа», деструктивно.

        Реализована внутренним курсором поверх arrival-кольца: сами кольца не
        трогает (курсорные читатели events_page не страдают), но два конкурирующих
        вызова drain по-прежнему крадут события друг у друга — это и есть причина
        депрекации. Вытеснение из кольца между дренажами — молча (легаси-поведение
        deque(maxlen) сохранено бит-в-бит).

        Семантика timeout:
        - ``0.0`` (по умолчанию) — поллинг: сразу вернуть, что накоплено (может быть []);
        - ``>0`` — блокировать до появления нового события, но не дольше timeout;
        - ``None`` — блокировать до первого нового события (или до close()).

        max_items ограничивает размер пачки (остаток отдаст следующий вызов).
        """
        with self._cv:
            # Три режима ожидания разведены явно (как в прежней реализации).
            if timeout is None:
                while not self._has_new():
                    if not self._alive():
                        break
                    self._cv.wait()
            elif timeout > 0.0:
                deadline = time.monotonic() + timeout
                while not self._has_new():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cv.wait(remaining)
            fresh = [(s, m) for s, m in self._arrival if s > self._drain_seq]
            if max_items is not None:
                fresh = fresh[:max_items]
            if fresh:
                self._drain_seq = fresh[-1][0]
            return [m for _, m in fresh]

    def _has_new(self) -> bool:
        """Есть ли в arrival событие новее drain-курсора (зовётся под ``_cv``)."""
        return bool(self._arrival) and self._arrival[-1][0] > self._drain_seq

    # ---- Диагностика ----

    def stats(self) -> Dict[str, Any]:
        """Счётчики hub'а: per-plane seq/размер/вытеснено + arrival + подписчики.

        ``evicted`` выводится из плотного seq (``seq − size``) — отдельных
        счётчиков не нужно. Вход для system_overview (B.3). ``evicted``/``dropped``
        разных плоскостей НЕсравнимы между собой: telemetry получает k item'ов на
        одну state.changed с k дельтами и вытесняется пропорционально быстрее.
        """
        with self._cv:
            planes = {
                p: {"seq": self._pseq[p], "size": len(self._rings[p]), "evicted": self._pseq[p] - len(self._rings[p])}
                for p in PLANES
            }
            return {
                "planes": planes,
                "all": {"seq": self._gseq, "size": len(self._arrival), "evicted": self._gseq - len(self._arrival)},
                "drain_cursor": self._drain_seq,
                "subscribers": len(self._subscribers),
                "event_errors": self._event_errors,
                "gen_rotations": self._gen_rotations,
            }


class _EventChannelMixin:
    """Публичное API событийного канала driver'а — тонкие делегаты в ``self._hub``."""

    def _emit_event(self, msg: Dict[str, Any]) -> None:
        """Точка входа транспорта: push из reader-потока → hub (кольца + подписчики)."""
        self._hub.emit(msg)

    def subscribe(self, callback: EventCallback) -> EventCallback:
        """Подписаться на события: callback зовётся на каждое push-сообщение."""
        return self._hub.subscribe(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        """Отписать ранее зарегистрированный callback (no-op, если его нет)."""
        self._hub.unsubscribe(callback)

    def events(
        self,
        timeout: Optional[float] = 0.0,
        *,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """УСТАРЕЛО (B.1): деструктивный дренаж всех плоскостей — конкурирующие
        читатели крадут события друг у друга. Используй :meth:`events_page`
        (курсорное недеструктивное чтение). Обёртка живёт до перевода вызывающих
        и удаляется в F.1 (см. plans/backend-ctl-debug-console.md).
        """
        return self._hub.drain(timeout, max_items=max_items)

    def events_page(
        self,
        plane: Optional[str] = None,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Курсорная страница событий плоскости (см. :meth:`EventHub.page`)."""
        return self._hub.page(plane, cursor=cursor, limit=limit)

    def events_stats(self) -> Dict[str, Any]:
        """Счётчики событийного hub'а (см. :meth:`EventHub.stats`)."""
        return self._hub.stats()

    @property
    def event_errors(self) -> int:
        """Сколько раз колбэк подписчика бросил исключение (диагностика)."""
        return self._hub.event_errors


__all__ = [
    "EventHub",
    "_EventChannelMixin",
    "EventCallback",
    "OBSERVABILITY_RECORD_COMMAND",
    "MISSING_MARKER",
    "PLANES",
    "ALL_PLANE",
    "extract_observability_records",
    "iter_state_deltas",
]
