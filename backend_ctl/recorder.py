# -*- coding: utf-8 -*-
"""recorder.py — flight recorder: запись потока событий driver'а → offline-реплей (D.4).

Идея (аналог Java Flight Recorder / Chrome tracing): живая сессия отладки
невоспроизводима — агент видит поток событий один раз. Recorder пишет снимок
состояния + JSONL-ленту событий; :func:`load_recording` + :class:`ReplayPlayer`
прогружают запись в **тот же** read-model оффлайн, и ``telemetry_snapshot`` /
``telemetry_history`` / ``events_page`` / ``await_condition`` работают над записью
без живой системы.

Ключевой дизайн — «detached driver» (§3 плана): реплей качает события через ту же
точку входа (:meth:`BackendDriver._emit_event`), что и живой транспорт. Неподключённый
``BackendDriver`` уже является рабочим offline read-model — hub, telemetry-model,
подписчики и курсоры создаются в ``__init__`` до всякого ``connect()``. Второго
read-model / второго классификатора не появляется.

Формат файла — JSONL (Dict at Boundary), одна запись = один файл:
  * строка 1 — header (версия формата, endpoint/session, активные подписки, снимок);
  * строки событий — ``{"seq", "ts", "event": <оригинальный push-dict>}`` (только
    arrival-плоскость; плоскостные кольца при загрузке восстанавливает тот же
    ``_classify``);
  * последняя строка — footer (маркер чистого завершения + reason + счётчик потерь).

Файл без footer = запись оборвана жёстко (crash) — при загрузке это честно
сообщается (``truncated: true``), но грузится всё разобранное.
"""

from __future__ import annotations

import collections
import json
import os
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
#  Константы формата                                                          #
# --------------------------------------------------------------------------- #

#: Тег формата записи (несовместимое изменение схемы → bump VERSION + отказ грузить).
FORMAT: str = "bctl-record"
#: Версия формата. Незнакомая версия при загрузке → обучающий отказ (не тихий разбор).
VERSION: int = 1

#: Лимит событий по умолчанию: по достижении запись авто-останавливается (reason="limit").
DEFAULT_MAX_EVENTS: int = 100_000
#: Мягкий лимит размера файла (~200 МБ): та же авто-остановка (файл валиден).
DEFAULT_MAX_BYTES: int = 200 * 1024 * 1024
#: Ёмкость очереди writer'а: переполнение видимо в footer.dropped, не тихая потеря.
DEFAULT_QUEUE_MAXLEN: int = 50_000
#: Дефолтный потолок колец detached-driver'а при реплее (переопределяемо ring_maxlen).
DEFAULT_RING_MAXLEN: int = 10_000

#: Режимы сессии backend_ctl (общее место: и mcp_driver_session, и mcp_tools ходят сюда,
#: обе — «вниз» на recorder, обратной зависимости tools→session нет).
MODE_LIVE: str = "live"
MODE_REPLAY: str = "replay"

#: Причины завершения записи (footer.reason).
REASON_STOPPED: str = "stopped"
REASON_LIMIT: str = "limit"
REASON_DISCONNECT: str = "disconnect"
REASON_DUMP: str = "dump"


# --------------------------------------------------------------------------- #
#  RecordWriter — сериализация header / событий / footer в JSONL              #
# --------------------------------------------------------------------------- #


class RecordWriter:
    """Пишет одну запись в JSONL-файл: header → событийные строки → footer.

    Не потокобезопасен сам по себе — единственный писатель (writer-поток Recorder'а)
    обращается к нему последовательно. ``ensure_ascii=False`` (человекочитаемо),
    flush по батчу, fsync на footer/close (durability при чистом завершении).
    """

    def __init__(self, path: str) -> None:
        self._path = path
        # Каталог создаётся заранее вызывающим; открываем на запись (перезапись).
        # OSError → RecordingError с путём и причиной (Task 1.4): голый PermissionError
        # ловила выше ветка «соединение оборвано» и сбрасывала здоровый driver.
        try:
            self._fh = open(path, "w", encoding="utf-8")
        except OSError as exc:
            raise RecordingError(
                f"не удалось открыть файл записи {path!r} на запись ({exc.__class__.__name__}: {exc})"
            ) from exc
        self._bytes = 0
        self._closed = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def bytes_written(self) -> int:
        return self._bytes

    def _write_line(self, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False, default=str) + "\n"
        self._fh.write(line)
        # len по utf-8 — честный размер на диске (для лимита max_bytes).
        self._bytes += len(line.encode("utf-8"))

    def write_header(self, header: Dict[str, Any]) -> None:
        self._write_line(header)
        self._fh.flush()

    def write_event(self, seq: int, ts: float, event: Dict[str, Any], *, pre_header: bool = False) -> None:
        """Записать событие ленты. ``pre_header`` — событие пришло, пока собирался снимок.

        Ключ ``pre_header`` пишется ТОЛЬКО когда он True: обычная строка ленты остаётся
        прежней формы, а помеченные несут честный сигнал «это могло уже попасть в снимок»
        (при реплее переприменяется идемпотентно).
        """
        row: Dict[str, Any] = {"seq": seq, "ts": ts, "event": event}
        if pre_header:
            row["pre_header"] = True
        self._write_line(row)

    def flush(self) -> None:
        if not self._closed:
            self._fh.flush()

    def write_footer(self, footer: Dict[str, Any]) -> None:
        """Записать footer, flush + fsync (durability маркера чистого завершения)."""
        if self._closed:
            return
        self._write_line(footer)
        self._fh.flush()
        try:
            os.fsync(self._fh.fileno())
        except OSError:
            pass  # fsync недоступен (напр. спец-ФС) — не роняем запись

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._fh.flush()
        finally:
            self._fh.close()


# --------------------------------------------------------------------------- #
#  Recorder — подписчик hub'а + writer-поток                                  #
# --------------------------------------------------------------------------- #


def _safe_section(name: str, fn: Callable[[], Any]) -> Any:
    """Собрать секцию header'а best-effort: сбой ручки → честная пометка, не срыв записи.

    Тяжёлый header (полное state-дерево, fan-out overview) на большом/недоступном
    бэкенде не должен ронять старт записи — недоступная секция помечается ``error``.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — header best-effort по контракту §8 рисков
        return {"error": f"{type(exc).__name__}: {exc}", "section": name}


def _collect_telemetry(drv: Any) -> Dict[str, Any]:
    """values (плоский path→value из read-model) + history (export_history, записанные ts)."""
    snap = drv.telemetry_snapshot()
    values = {path: entry.get("value") for path, entry in (snap.get("metrics") or {}).items()}
    with drv._telemetry_lock:
        history = drv._telemetry_model.export_history()
    history_json = {path: [[ts, val] for ts, val in points] for path, points in history.items()}
    return {"values": values, "history": history_json}


def _collect_state(drv: Any) -> Any:
    """Полное state-дерево через существующую ручку (тот же вес, что state_get_subtree('' ))."""
    return drv.send_command("ProcessManager", "state.get_subtree", {"path": ""})


def collect_header(drv: Any, created_ts: float, *, subscribed_ts: Optional[float] = None) -> Dict[str, Any]:
    """Снимок системы для строки-header (best-effort по секциям).

    Переиспользуется :class:`Recorder` (старт записи) и :func:`dump_recording`
    (one-shot дамп чёрного ящика) — один сборщик header'а, не два.

    ``subscribed_ts`` — момент, с которого лента уже пишется. Он РАНЬШЕ секций снимка:
    сбор снимка тяжёлый (fan-out overview + полное state-дерево), и всё, что прилетело
    за это время, обязано быть в ленте. Наличие поля даёт читателю честную границу
    «снимок собран не мгновенно» вместо иллюзии атомарного среза.
    """
    header: Dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "created_ts": created_ts,
        "endpoint": {
            "host": _safe_section("host", lambda: drv.host),
            "port": _safe_section("port", lambda: drv.port),
        },
        "session": _safe_section("session", lambda: getattr(drv, "_session", None)),
        "subscriptions": _safe_section("subscriptions", lambda: drv.export_subscriptions()),
        "snapshot": {
            "overview": _safe_section("overview", lambda: drv.system_overview()),
            "state": _safe_section("state", lambda: _collect_state(drv)),
            "telemetry": _safe_section("telemetry", lambda: _collect_telemetry(drv)),
            "events_stats": _safe_section("events_stats", lambda: drv.events_stats()),
        },
    }
    if subscribed_ts is not None:
        header["subscribed_ts"] = subscribed_ts
        # Момент готовности снимка: события ленты с ts до него собирались параллельно
        # со снимком и могут в нём уже отражаться (помечаются pre_header).
        header["header_ready_ts"] = time.time()
    return header


class Recorder:
    """Пишущая сторона flight recorder'а: лёгкий подписчик hub'а + writer-поток.

    Колбэк подписки (reader-поток driver'а) обязан быть лёгким — он ТОЛЬКО кладёт
    событие в bounded-очередь (контракт §7: не блокировать reader). Отдельный
    writer-поток сериализует очередь в файл. Переполнение очереди видно в
    ``footer.dropped`` — не тихая потеря.

    Лимиты (``max_events`` / ``max_bytes``): по достижении запись авто-останавливается
    с ``reason="limit"`` (файл валиден). :meth:`stop` идемпотентна и вызывается на
    всех путях завершения (stop/limit/disconnect).
    """

    def __init__(
        self,
        drv: Any,
        path: str,
        *,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        queue_maxlen: int = DEFAULT_QUEUE_MAXLEN,
    ) -> None:
        self._drv = drv
        self._path = path
        self._max_events = max(1, int(max_events))
        self._max_bytes = max(1, int(max_bytes))
        self._max_queue = max(1, int(queue_maxlen))

        self._writer: Optional[RecordWriter] = None
        self._listener: Optional[Callable[[Dict[str, Any]], None]] = None
        self._thread: Optional[threading.Thread] = None

        # Очередь writer'а + сигнализация. seq — плотный счётчик ПОСТАВЛЕННЫХ В ОЧЕРЕДЬ
        # событий (тот же, что пишется в файл как event.seq).
        self._queue: Deque[Tuple[int, float, Dict[str, Any]]] = collections.deque()
        self._qlock = threading.Lock()
        self._qcond = threading.Condition(self._qlock)
        self._seq = 0
        # Инвариант учёта (пин теста): events_written + dropped == accepted, где accepted —
        # число событий, ПРИНЯТЫХ колбэком пока запись активна (прошедших stop-гейт). Всё
        # принятое обязано быть либо записано, либо посчитано в dropped — тихой потери нет.
        self._accepted = 0
        self._dropped = 0
        self._events_written = 0

        # Управление завершением. reason фиксируется первым источником (limit/stop).
        self._stop_requested = False
        self._reason: str = REASON_STOPPED
        self._reason_locked = False
        # Финализация (footer+close) — РОВНО один раз, владелец строго writer-поток.
        # _finalize_lock сериализует guard _finalized (writer-поток vs fallback stop()).
        self._finalized = False
        self._finalize_lock = threading.Lock()
        self._subscriptions: List[Dict[str, Any]] = []
        self._created_ts: float = 0.0
        # Границы окна старта: подписка активна с _subscribed_ts, снимок готов к
        # _header_ready_ts. События между ними попадают и в ленту (помечены pre_header),
        # и потенциально в снимок — дубль честно виден, потери нет.
        self._subscribed_ts: float = 0.0
        self._header_ready_ts: float = 0.0

    @property
    def path(self) -> str:
        return self._path

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- Старт ----

    def start(self) -> Dict[str, Any]:
        """Подписаться на hub, собрать header, поднять writer-поток.

        Порядок критичен. Подписка идёт ПЕРВОЙ, до сбора header'а: сбор снимка тяжёлый
        (fan-out ``system_overview`` + полное state-дерево + телеметрия — сотни мс на
        живом бэкенде), и если подписываться после него, всё пришедшее за это окно не
        попадает ни в снимок (он снят раньше), ни в ленту (подписки ещё нет) — при
        ``dropped == 0``, то есть потеря невидима. Колбэк ТОЛЬКО кладёт в очередь,
        поэтому подписка до writer-потока безопасна: события копятся в bounded-очереди
        и сливаются, как только поток поднимется.

        Returns:
            ``{"success": True, "path", "subscriptions": [...], "hint"?}`` — если
            активных подписок нет, лента будет пустой: возвращаем ``hint`` (не
            авто-подписка — запись не должна молча менять топологию наблюдения).
        """
        if self.active:
            return {"success": False, "error": "запись уже идёт"}
        self._created_ts = time.time()
        self._subscribed_ts = time.time()
        self._listener = self._drv.subscribe(self._on_event)
        try:
            header = self._collect_header()
            self._header_ready_ts = float(header.get("header_ready_ts") or time.time())
            self._subscriptions = list(header.get("subscriptions") or [])

            self._writer = RecordWriter(self._path)
            self._writer.write_header(header)

            self._thread = threading.Thread(target=self._writer_loop, name="bctl-recorder", daemon=True)
            self._thread.start()
        except BaseException:
            # Старт не доехал (не открылся файл, сорвался сбор) — снять подписку, иначе
            # мёртвый подписчик остаётся на hot-path EventHub и держит Recorder замыканием.
            self._detach_listener()
            raise

        out: Dict[str, Any] = {"success": True, "path": self._path, "subscriptions": self._subscriptions}
        if not self._subscriptions:
            out["hint"] = (
                "запись стартовала без активных подписок — лента будет пустой. Подпишись "
                "на поток (watch_like_gui / state_subscribe / log_tail), затем повтори активность."
            )
        return out

    def _collect_header(self) -> Dict[str, Any]:
        """Снимок системы для строки-header (делегат :func:`collect_header`)."""
        return collect_header(self._drv, self._created_ts, subscribed_ts=self._subscribed_ts)

    def _detach_listener(self) -> None:
        """Снять подписку с hub'а, идемпотентно. Teardown не роняем."""
        if self._listener is None:
            return
        try:
            self._drv.unsubscribe(self._listener)
        except Exception:  # noqa: BLE001 — teardown не роняем
            pass
        self._listener = None

    # ---- Колбэк подписки (reader-поток) ----

    def _on_event(self, msg: Dict[str, Any]) -> None:
        """Лёгкий колбэк: ТОЛЬКО enqueue (контракт §7 — не блокировать reader)."""
        with self._qlock:
            if self._stop_requested:
                # Запись уже останавливается — событие пост-стоп, в ленту не входит
                # (не accepted: не теряем «данные записи», их просто нет после стопа).
                return
            self._accepted += 1
            if len(self._queue) >= self._max_queue:
                # Очередь переполнена — writer не успевает. Роняем НОВОЕ событие и
                # считаем (видимо в footer.dropped), а не тихо теряем.
                self._dropped += 1
                return
            self._seq += 1
            self._queue.append((self._seq, time.time(), msg))
            self._qcond.notify()

    # ---- Writer-поток ----

    def _set_reason(self, reason: str) -> None:
        """Зафиксировать причину завершения (первый источник — limit или stop — выигрывает)."""
        with self._qlock:
            if not self._reason_locked:
                self._reason = reason
                self._reason_locked = True

    def _drain_pending_to_dropped(self) -> None:
        """Учесть всё поставленное в очередь, но не записанное, как dropped (под _qlock).

        Зовётся при остановке по ЛИМИТУ: _stop_requested уже True (продюсер больше не
        кладёт — _on_event на стоп-гейте возвращается), поэтому drain захватывает всё,
        что просочилось в очередь до выставления флага. Инвариант
        ``events_written + dropped == accepted`` сохраняется: остаток ленты не теряется
        молча, а честно виден в footer.dropped.
        """
        with self._qlock:
            self._dropped += len(self._queue)
            self._queue.clear()

    def _writer_loop(self) -> None:
        """Сливать очередь в файл до стопа; при лимите — остаток в dropped (не тихо).

        Единственный писатель файла (RecordWriter не потокобезопасен) и единственный
        владелец :meth:`_finalize` — footer/close случаются строго здесь, не в stop().
        """
        assert self._writer is not None
        writer = self._writer
        try:
            while True:
                with self._qlock:
                    while not self._queue and not self._stop_requested:
                        self._qcond.wait()
                    batch = list(self._queue)
                    self._queue.clear()
                hit_limit = False
                for idx, (seq, ts, event) in enumerate(batch):
                    # Лимит проверяется ПЕРЕД записью: не пишем поверх max_events/max_bytes.
                    if self._events_written >= self._max_events or writer.bytes_written >= self._max_bytes:
                        self._set_reason(REASON_LIMIT)
                        with self._qlock:
                            self._stop_requested = True
                            # Текущее + весь остаток batch не будут записаны → в dropped.
                            self._dropped += len(batch) - idx
                        hit_limit = True
                        break
                    writer.write_event(seq, ts, event, pre_header=ts < self._header_ready_ts)
                    self._events_written += 1
                writer.flush()
                if hit_limit:
                    # Просочившееся в очередь после clear (до флага) — тоже в dropped.
                    self._drain_pending_to_dropped()
                    break
                # Чистый стоп (stopped/disconnect): дослили batch; выходим, когда очередь
                # пуста — pending события записаны, НЕ сброшены (в отличие от лимита).
                with self._qlock:
                    if self._stop_requested and not self._queue:
                        break
        finally:
            self._finalize()

    def _finalize(self) -> None:
        """Отписаться + записать footer + закрыть файл — ровно один раз, идемпотентно.

        Владелец — writer-поток (единственный писатель файла). ``stop()`` НЕ зовёт это
        напрямую, пока поток жив, чтобы не гонять RecordWriter из двух потоков; guard
        под ``_finalize_lock`` защищает и от fallback-вызова (поток не поднимался).
        """
        with self._finalize_lock:
            if self._finalized:
                return
            self._finalized = True
        # Отписка — на ВСЕХ путях завершения (stop/limit/disconnect), идемпотентно:
        # иначе мёртвый подписчик копится в EventHub и держит Recorder через замыкание.
        self._detach_listener()
        writer = self._writer
        if writer is None:
            return
        with self._qlock:
            reason, events_written, dropped = self._reason, self._events_written, self._dropped
        # close() — в finally: отказ записи footer'а (ENOSPC, битый дескриптор) не должен
        # утекать файловым дескриптором. Повтор невозможен (_finalized уже True), поэтому
        # закрыть обязаны здесь и сейчас.
        try:
            writer.write_footer(
                {
                    "footer": True,
                    "stopped_ts": time.time(),
                    "events_written": events_written,
                    "dropped": dropped,
                    "reason": reason,
                }
            )
        finally:
            writer.close()

    # ---- Стоп (идемпотентно, все пути) ----

    def stop(self, reason: str = REASON_STOPPED) -> Dict[str, Any]:
        """Сигнализировать стоп и дождаться финализации writer-потоком. Идемпотентно.

        stop() НЕ пишет в файл сам: только ставит стоп-флаг, будит и join-ит writer-поток
        (он дослит очередь и запишет footer через :meth:`_finalize`). Отписка — тоже в
        _finalize (все пути). Fallback-финализация — ТОЛЬКО если writer-поток не поднимался
        (гарантия footer'а без гонки с живым писателем).
        """
        self._set_reason(reason)
        with self._qlock:
            self._stop_requested = True
            self._qcond.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        # Финализируем сами ТОЛЬКО когда нет живого writer-потока (не поднимался/уже мёртв):
        # если join истёк по таймауту и поток ещё пишет — владелец footer'а он, не гоняем.
        if thread is None or not thread.is_alive():
            self._finalize()
        return self.status()

    def status(self) -> Dict[str, Any]:
        """Текущее состояние записи (файл, счётчики, активность)."""
        with self._qlock:
            events_written, dropped, reason = self._events_written, self._dropped, self._reason
        active = self.active
        return {
            "success": True,
            "recording": active,
            "path": self._path,
            "events_written": events_written,
            "dropped": dropped,
            "reason": None if active else reason,
            "subscriptions": self._subscriptions,
        }


def dump_recording(drv: Any, path: str, *, ring_limit: int = 500) -> Dict[str, Any]:
    """One-shot дамп чёрного ящика: header-снимок + текущее arrival-кольцо (§5.3).

    EventHub — always-on чёрный ящик в пределах maxlen; дамп = тот же writer-код на
    готовых данных (~ноль доп. цены). Покрывает «система умерла — сохрани, что успел
    увидеть». ts событий — время дампа (кольцо не хранит per-event arrival ts);
    ``reason="dump"`` в footer сигналит, что это снимок, а не хронированная запись.
    """
    dump_ts = time.time()
    writer = RecordWriter(path)
    try:
        writer.write_header(collect_header(drv, dump_ts))
        seq = 0
        cursor: Optional[str] = None
        # Пройти всё arrival-кольцо страницами до исчерпания (курсорное чтение B.1).
        while True:
            page = drv.events_page("all", cursor=cursor, limit=ring_limit)
            if not isinstance(page, dict) or not page.get("success"):
                break
            items = page.get("items") or []
            for item in items:
                seq += 1
                event = item.get("event")
                if isinstance(event, dict):
                    writer.write_event(seq, dump_ts, event)
            next_cursor = page.get("next_cursor")
            if not items or next_cursor == cursor:
                break
            cursor = next_cursor
        writer.write_footer(
            {"footer": True, "stopped_ts": time.time(), "events_written": seq, "dropped": 0, "reason": REASON_DUMP}
        )
    finally:
        writer.close()
    return {"success": True, "path": path, "events_written": seq, "reason": REASON_DUMP}


# --------------------------------------------------------------------------- #
#  Загрузка записи + detached-driver реплей                                   #
# --------------------------------------------------------------------------- #


class RecordingError(ValueError):
    """Запись не грузится: не тот формат / незнакомая версия (обучающий текст)."""


class Recording:
    """Разобранная запись: header + событийная лента + footer (+флаг обрыва).

    ``truncated=True`` — файл без footer (жёсткий обрыв записи, crash): грузится всё
    разобранное, но честно помечается. Создаётся через :func:`load_recording`.
    """

    def __init__(
        self,
        header: Dict[str, Any],
        events: List[Dict[str, Any]],
        footer: Optional[Dict[str, Any]],
        *,
        truncated: bool,
        path: str,
        skipped_malformed: int = 0,
    ) -> None:
        self.header = header
        self.events = events
        self.footer = footer
        self.truncated = truncated
        self.path = path
        # Битые СРЕДНИЕ строки JSONL (частичная порча файла), НЕ смешиваются с truncated
        # (оборванный хвост). truncated=False + skipped_malformed>0 → файл завершён чисто,
        # но внутри есть потерянные строки — честный отдельный сигнал.
        self.skipped_malformed = skipped_malformed

    @property
    def snapshot(self) -> Dict[str, Any]:
        return self.header.get("snapshot") or {}


def load_recording(path: str) -> Recording:
    """Разобрать JSONL-запись; провалидировать формат/версию; определить обрыв.

    Raises:
        RecordingError: файл не bctl-record или незнакомая версия формата
            (обучающий текст — не тихий разбор чужой схемы).
        FileNotFoundError: файла нет.
    """
    # Читаем сырые строки целиком: битую СРЕДНЮЮ строку (за которой есть валидные)
    # надо отличить от оборванного ХВОСТА (последняя строка) — первое = порча файла
    # (skipped_malformed), второе = truncated. По ходу чтения этого не различить.
    # FileNotFoundError оставляем как есть (документированный контракт функции), прочие
    # файловые беды (нет прав, путь — каталог, битая кодировка) → RecordingError с путём:
    # иначе голый OSError выдавал себя за обрыв связи и сбрасывал driver (Task 1.4).
    try:
        with open(path, encoding="utf-8") as fh:
            raw_lines = [stripped for raw in fh if (stripped := raw.strip())]
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordingError(f"не удалось прочитать файл записи {path!r} ({exc.__class__.__name__}: {exc})") from exc
    if not raw_lines:
        raise RecordingError(f"пустой/нечитаемый файл записи {path!r}")

    lines: List[Dict[str, Any]] = []
    skipped_malformed = 0
    last_idx = len(raw_lines) - 1
    for idx, raw in enumerate(raw_lines):
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            if idx == last_idx:
                # Оборванный хвост (crash в середине write последней строки) — не порча,
                # запись пометится truncated (footer не встретится).
                continue
            # Битая строка В СЕРЕДИНЕ файла — реальная потеря, не тихо: считаем отдельно.
            skipped_malformed += 1
    if not lines:
        raise RecordingError(f"пустой/нечитаемый файл записи {path!r}")

    header = lines[0]
    if not isinstance(header, dict) or header.get("format") != FORMAT:
        raise RecordingError(
            f"{path!r} — не запись bctl-record (format={header.get('format')!r}). "
            "Ожидаю файл, созданный record_start/record_dump."
        )
    version = header.get("version")
    if version != VERSION:
        raise RecordingError(
            f"незнакомая версия записи {version!r} (поддерживается {VERSION}). "
            "Файл создан другой версией backend_ctl — обнови инструмент или пересними запись."
        )

    footer = lines[-1] if isinstance(lines[-1], dict) and lines[-1].get("footer") else None
    events = [ln for ln in lines[1:] if isinstance(ln, dict) and "event" in ln]
    return Recording(header, events, footer, truncated=footer is None, path=path, skipped_malformed=skipped_malformed)


def _flatten_tree(tree: Any, prefix: str = "") -> Dict[str, Any]:
    """Вложенное state-дерево → плоские dotted-пути (только скалярные листья).

    ``{"processes": {"cam": {"state": {"fps": 30}}}}`` → ``{"processes.cam.state.fps": 30}``.
    Не-dict листья — значения; dict — рекурсия. Граница — точка-разделитель (как в
    read-model snapshot).
    """
    out: Dict[str, Any] = {}
    if not isinstance(tree, dict):
        return out
    for key, value in tree.items():
        if not isinstance(key, str):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten_tree(value, path))
        else:
            out[path] = value
    return out


def _extract_state_tree(state_section: Any) -> Dict[str, Any]:
    """Достать нативное state-дерево из записанной секции (форма ответа get_subtree)."""
    if not isinstance(state_section, dict):
        return {}
    # Ответ state.get_subtree несёт дерево в "value"; допускаем и уже-плоскую секцию.
    for key in ("value", "subtree", "data"):
        inner = state_section.get(key)
        if isinstance(inner, dict):
            return inner
    # Секция помечена ошибкой сбора (best-effort) — дерева нет.
    if "error" in state_section:
        return {}
    return state_section


class ReplayPlayer:
    """Проигрыватель записи в detached (неподключённый) :class:`BackendDriver`.

    Реплей качает события через ту же точку входа :meth:`BackendDriver._emit_event`,
    что и живой транспорт — классификация по плоскостям, telemetry-ingest, курсоры,
    ``dropped`` исполняются тем же кодом. Часы read-model инъектируются (:meth:`now`)
    так, что точки истории несут ЗАПИСАННЫЕ ts (playhead), а не время загрузки.

    Playhead — индекс следующего непрокрученного события. ``position="end"`` качает
    всю ленту сразу (финальное состояние); ``position="start"`` — только снимок
    header'а (пошаговый тайм-трэвел через :func:`replay_await_condition`).
    """

    def __init__(
        self,
        recording: Recording,
        *,
        ring_maxlen: Optional[int] = None,
        position: str = "end",
    ) -> None:
        from backend_ctl.driver import BackendDriver
        from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

        self.recording = recording
        self._events = recording.events
        self._playhead = 0
        # Часы реплея: до первого события — created_ts header'а; при прокрутке —
        # ts текущего события (инъектируется в read-model, см. now()).
        self._clock_ts: float = float(recording.header.get("created_ts") or 0.0)

        endpoint = recording.header.get("endpoint") or {}
        host = endpoint.get("host") if isinstance(endpoint.get("host"), str) else "127.0.0.1"
        port = endpoint.get("port") if isinstance(endpoint.get("port"), int) else 8765
        # Кольца: min(число событий, дефолт) либо явный ring_maxlen. Длинная запись
        # при "end" честно показывает вытеснение через dropped/evicted (как вживую).
        if ring_maxlen is not None:
            maxlen = max(1, int(ring_maxlen))
        else:
            maxlen = max(1, min(len(self._events) or 1, DEFAULT_RING_MAXLEN))
        self.driver = BackendDriver(host, port, event_queue_maxlen=maxlen)
        # Подменяем telemetry-model на clock-aware ДО прокрутки: _ingest_state_changed
        # уже подписан из __init__ и читает self._telemetry_model в момент вызова —
        # путь единый, второго ingest не появляется. Detached (нет reader-потока) →
        # подмена атрибута безопасна.
        self.driver._telemetry_model = TelemetryReadModel(clock=self.now)

        self._prime()
        if position == "end":
            self.pump(len(self._events))
        elif position != "start":
            raise RecordingError(f"неизвестная position {position!r}: ожидаю 'end' или 'start'")

    # ---- Часы реплея ----

    def now(self) -> float:
        """Текущее время playhead'а (инъектируется в read-model для истории)."""
        return self._clock_ts

    # ---- Прайм стартового состояния ----

    def _prime(self) -> None:
        """Залить header-снимок в read-model ДО первого события (состояние на старте)."""
        snap = self.recording.snapshot
        model = self.driver._telemetry_model
        with self.driver._telemetry_lock:
            # 1. Полное state-дерето (flatten → dotted) — для state_get/state_get_subtree.
            state_tree = _extract_state_tree(snap.get("state"))
            model.prime(_flatten_tree(state_tree))
            # 2. Telemetry values — авторитетны для метрик (последнее значение).
            telemetry = snap.get("telemetry") or {}
            values = telemetry.get("values") or {}
            if isinstance(values, dict):
                model.prime({p: v for p, v in values.items() if isinstance(p, str)})
            # 3. История — записанные ts (замещает буферы prime-точек, см. import_history).
            history = telemetry.get("history") or {}
            if isinstance(history, dict):
                model.import_history(history)

    # ---- Прокрутка ленты (playhead) ----

    @property
    def playhead(self) -> int:
        return self._playhead

    @property
    def total(self) -> int:
        return len(self._events)

    def has_more(self) -> bool:
        return self._playhead < len(self._events)

    def pump(self, n: int) -> int:
        """Прокрутить до n событий через _emit_event (тот же путь, что живой транспорт).

        Возвращает число реально прокрученных событий (< n у конца ленты). Часы
        сдвигаются на ts события ПЕРЕД emit — точки истории несут записанный ts.
        """
        pumped = 0
        while pumped < n and self._playhead < len(self._events):
            entry = self._events[self._playhead]
            ts = entry.get("ts")
            if isinstance(ts, (int, float)):
                self._clock_ts = float(ts)
            event = entry.get("event")
            if isinstance(event, dict):
                self.driver._emit_event(event)
            self._playhead += 1
            pumped += 1
        return pumped

    # ---- Read-served ручки (offline) ----

    def system_overview(self) -> Dict[str, Any]:
        """Записанный снимок overview (IPC fan-out оффлайн неисполним) с пометкой recorded."""
        overview = self.recording.snapshot.get("overview")
        if isinstance(overview, dict):
            return {**overview, "recorded": True}
        return {"success": True, "recorded": True, "note": "overview не записан в header"}

    def state_get(self, path: str) -> Dict[str, Any]:
        """Точное значение пути из read-model (примированного снимком записи)."""
        with self.driver._telemetry_lock:
            snap = self.driver._telemetry_model.snapshot(path)
        if path in snap:
            return {"success": True, "path": path, "value": snap[path], "recorded": True}
        return {"success": True, "path": path, "found": False, "recorded": True}

    def state_get_subtree(self, prefix: str = "") -> Dict[str, Any]:
        """Снимок поддерева (плоские dotted-пути) из read-model записи."""
        with self.driver._telemetry_lock:
            subtree = self.driver._telemetry_model.snapshot(prefix)
        return {"success": True, "path": prefix, "subtree": subtree, "recorded": True}

    def status(self) -> Dict[str, Any]:
        """Статус загруженного реплея (имя/позиция/total/обрыв) — для record_status."""
        return {
            "success": True,
            "mode": "replay",
            "path": self.recording.path,
            "position": self._playhead,
            "total": self.total,
            "truncated": self.recording.truncated,
            "skipped_malformed": self.recording.skipped_malformed,
        }

    def await_condition(
        self,
        kind: str,
        spec: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Offline-await: прокрутка playhead'а до попадания (делегат §5.1)."""
        return replay_await_condition(self, kind, spec, timeout=timeout)


def replay_await_condition(
    player: ReplayPlayer,
    kind: str,
    spec: Optional[Dict[str, Any]],
    *,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Offline-семантика await_condition над записью — «прокрутка до попадания» (§5.1).

    Живой await ждёт будущего; над записью будущее — остаток ленты. Порядок:
      1. проверить условие на ТЕКУЩЕМ достигнутом состоянии read-model (initial_check,
         тот же код) → мгновенный успех, лента не двигается;
      2. иначе прокручивать playhead (``pump(1)`` → ``_emit_event`` в вызывающем
         потоке; подписчики синхронны, wall-clock ожидания НЕТ) до попадания либо
         конца записи;
      3. попадание → успех + секция ``replay`` (playhead ОСТАЁТСЯ на месте попадания —
         снимок/история после показывают состояние момента срабатывания);
      4. конец без попадания → таймаут-эквивалент (``end_of_recording``).

    ``timeout`` в offline игнорируется (нечего ждать — прокрутка мгновенна).
    Предикаты и ``_Waiter`` переиспользуются из :func:`conditions.setup_condition`
    (нет второго парсера условий).
    """
    from backend_ctl.conditions import setup_condition

    drv = player.driver
    setup = setup_condition(drv, kind, spec)
    if isinstance(setup, dict):  # ошибка валидации kind/spec — обучающий текст
        return setup
    waiter, initial_check = setup

    listener = drv.subscribe(waiter.offer)
    try:
        # Порядок race-free тот же, что вживую: подписка → начальная проверка →
        # прокрутка. Offline reader-потока нет — offer зовётся синхронно из pump.
        waiter.resolve_initial(initial_check())
        while waiter.matched is None and player.has_more():
            player.pump(1)
    finally:
        drv.unsubscribe(listener)

    replay = {"position": player.playhead, "of": player.total}
    # elapsed_sec — часть контракта ответа живого await_condition (и на успехе, и на
    # таймауте). Оффлайн прокрутка мгновенна, поэтому 0.0, но поле обязано быть: клиент
    # разбирает один и тот же ответ независимо от режима сессии.
    if waiter.matched is not None:
        return {"success": True, "kind": kind, "matched": waiter.matched, "elapsed_sec": 0.0, "replay": replay}
    return {
        "success": False,
        "timed_out": True,
        "end_of_recording": True,
        "kind": kind,
        "waited": dict(spec) if isinstance(spec, dict) else spec,
        "elapsed_sec": 0.0,
        "events_seen": waiter.events_seen,
        "last_seen": waiter.last_seen,
        "replay": replay,
    }


__all__ = [
    "FORMAT",
    "VERSION",
    "MODE_LIVE",
    "MODE_REPLAY",
    "DEFAULT_MAX_EVENTS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_RING_MAXLEN",
    "REASON_STOPPED",
    "REASON_LIMIT",
    "REASON_DISCONNECT",
    "REASON_DUMP",
    "RecordWriter",
    "Recorder",
    "collect_header",
    "dump_recording",
    "Recording",
    "RecordingError",
    "load_recording",
    "ReplayPlayer",
    "replay_await_condition",
]
