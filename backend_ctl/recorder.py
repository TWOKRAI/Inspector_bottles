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
        self._fh = open(path, "w", encoding="utf-8")
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

    def write_event(self, seq: int, ts: float, event: Dict[str, Any]) -> None:
        self._write_line({"seq": seq, "ts": ts, "event": event})

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

        # Очередь writer'а + сигнализация. seq — плотный счётчик ЗАПИСАННЫХ событий.
        self._queue: Deque[Tuple[int, float, Dict[str, Any]]] = collections.deque()
        self._qlock = threading.Lock()
        self._qcond = threading.Condition(self._qlock)
        self._seq = 0
        self._dropped = 0
        self._events_written = 0

        # Управление завершением. reason фиксируется первым источником (limit/stop).
        self._stop_requested = False
        self._reason: str = REASON_STOPPED
        self._reason_locked = False
        self._finalized = False
        self._subscriptions: List[Dict[str, Any]] = []
        self._created_ts: float = 0.0

    @property
    def path(self) -> str:
        return self._path

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- Старт ----

    def start(self) -> Dict[str, Any]:
        """Собрать header, подписаться на hub, поднять writer-поток.

        Returns:
            ``{"success": True, "path", "subscriptions": [...], "hint"?}`` — если
            активных подписок нет, лента будет пустой: возвращаем ``hint`` (не
            авто-подписка — запись не должна молча менять топологию наблюдения).
        """
        if self.active:
            return {"success": False, "error": "запись уже идёт"}
        self._created_ts = time.time()
        header = self._collect_header()
        self._subscriptions = list(header.get("subscriptions") or [])

        self._writer = RecordWriter(self._path)
        self._writer.write_header(header)

        # Подписка ДО старта потока: колбэк лёгкий (только enqueue).
        self._listener = self._drv.subscribe(self._on_event)
        self._thread = threading.Thread(target=self._writer_loop, name="bctl-recorder", daemon=True)
        self._thread.start()

        out: Dict[str, Any] = {"success": True, "path": self._path, "subscriptions": self._subscriptions}
        if not self._subscriptions:
            out["hint"] = (
                "запись стартовала без активных подписок — лента будет пустой. Подпишись "
                "на поток (watch_like_gui / state_subscribe / log_tail), затем повтори активность."
            )
        return out

    def _collect_header(self) -> Dict[str, Any]:
        """Снимок системы для строки-header (best-effort по секциям)."""
        drv = self._drv
        telemetry = _safe_section("telemetry", lambda: self._collect_telemetry())
        return {
            "format": FORMAT,
            "version": VERSION,
            "created_ts": self._created_ts,
            "endpoint": {
                "host": _safe_section("host", lambda: drv.host),
                "port": _safe_section("port", lambda: drv.port),
            },
            "session": _safe_section("session", lambda: getattr(drv, "_session", None)),
            "subscriptions": _safe_section("subscriptions", lambda: drv.export_subscriptions()),
            "snapshot": {
                "overview": _safe_section("overview", lambda: drv.system_overview()),
                "state": _safe_section("state", lambda: self._collect_state()),
                "telemetry": telemetry,
                "events_stats": _safe_section("events_stats", lambda: drv.events_stats()),
            },
        }

    def _collect_telemetry(self) -> Dict[str, Any]:
        """values (плоский path→value из read-model) + history (export_history, записанные ts)."""
        drv = self._drv
        snap = drv.telemetry_snapshot()
        values = {path: entry.get("value") for path, entry in (snap.get("metrics") or {}).items()}
        with drv._telemetry_lock:
            history = drv._telemetry_model.export_history()
        # history — JSON-safe: tuple → list.
        history_json = {path: [[ts, val] for ts, val in points] for path, points in history.items()}
        return {"values": values, "history": history_json}

    def _collect_state(self) -> Any:
        """Полное state-дерево через существующую ручку (тот же вес, что state_get_subtree('' ))."""
        res = self._drv.send_command("ProcessManager", "state.get_subtree", {"path": ""})
        return res

    # ---- Колбэк подписки (reader-поток) ----

    def _on_event(self, msg: Dict[str, Any]) -> None:
        """Лёгкий колбэк: ТОЛЬКО enqueue (контракт §7 — не блокировать reader)."""
        with self._qlock:
            if self._stop_requested:
                return
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

    def _writer_loop(self) -> None:
        """Сливать очередь в файл до запроса стопа; следить за лимитами."""
        assert self._writer is not None
        writer = self._writer
        while True:
            with self._qlock:
                while not self._queue and not self._stop_requested:
                    self._qcond.wait()
                batch = list(self._queue)
                self._queue.clear()
                stop_now = self._stop_requested and not batch
            if stop_now:
                break
            for seq, ts, event in batch:
                writer.write_event(seq, ts, event)
                self._events_written += 1
                if self._events_written >= self._max_events or writer.bytes_written >= self._max_bytes:
                    self._set_reason(REASON_LIMIT)
                    with self._qlock:
                        self._stop_requested = True
                    break
            writer.flush()
        self._finalize()

    def _finalize(self) -> None:
        """Записать footer + закрыть файл (ровно один раз)."""
        if self._finalized:
            return
        self._finalized = True
        writer = self._writer
        if writer is None:
            return
        writer.write_footer(
            {
                "footer": True,
                "stopped_ts": time.time(),
                "events_written": self._events_written,
                "dropped": self._dropped,
                "reason": self._reason,
            }
        )
        writer.close()

    # ---- Стоп (идемпотентно, все пути) ----

    def stop(self, reason: str = REASON_STOPPED) -> Dict[str, Any]:
        """Остановить запись: отписаться, дослить очередь, footer, fsync. Идемпотентно."""
        # Отписка от hub'а: новых событий в очередь не поступит.
        if self._listener is not None:
            try:
                self._drv.unsubscribe(self._listener)
            except Exception:  # noqa: BLE001 — teardown не роняем
                pass
            self._listener = None
        self._set_reason(reason)
        with self._qlock:
            self._stop_requested = True
            self._qcond.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        # На случай, если поток не поднимался/уже мёртв — гарантируем footer.
        self._finalize()
        return self.status()

    def status(self) -> Dict[str, Any]:
        """Текущее состояние записи (файл, счётчики, активность)."""
        return {
            "success": True,
            "recording": self.active,
            "path": self._path,
            "events_written": self._events_written,
            "dropped": self._dropped,
            "reason": None if self.active else self._reason,
            "subscriptions": self._subscriptions,
        }


__all__ = [
    "FORMAT",
    "VERSION",
    "DEFAULT_MAX_EVENTS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_RING_MAXLEN",
    "REASON_STOPPED",
    "REASON_LIMIT",
    "REASON_DISCONNECT",
    "REASON_DUMP",
    "RecordWriter",
    "Recorder",
]
