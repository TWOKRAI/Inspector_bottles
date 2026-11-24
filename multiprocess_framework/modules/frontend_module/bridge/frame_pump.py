"""FramePump — вытягивание кадров из ящика «последний на ключ» таймером на ключ (Qt).

Purpose: тракт кадров gui не накапливает кадры. Поток-источник кладёт кадр в ящик
(``put``), не трогая Qt (ни Signal, ни ``postEvent``): ящик держит не больше одного
кадра на ключ. Насос живёт в Qt-потоке и по таймеру на ключ забирает ``take(key)`` и
отдаёт кадр в ``sink(key, item)``. Частота показа ограничена ``fps_limit`` ключа,
память — «ключи x 1 кадр» при любой частоте входа (ADR FE-007).

Public API:
- FramePump(mailbox, sink, parent=None) — создаётся в Qt-потоке; запускает скан ключей
- set_keys({key: fps_limit}) -> None     — настроить ключи (повторный вызов допустим)
- stop() -> None                         — погасить скан и таймеры (идемпотентно)
- stats(reset_window=False) -> dict      — счётчики на ключ (потокобезопасно)

``mailbox`` — утиная типизация: ``take(key) -> (item, age_s) | None`` и
``pending_keys() -> list[str]`` (``LatestMailbox`` из ``process_module.generic``; импорт
его сюда не нужен). ``sink(key, item)`` получает ВЕСЬ item без изменений (поля
``capture_ns``, ``capture_ts``, ``replay`` насос не читает) и вызывается только в Qt-потоке.

Stability: lite — сигнатуры и набор счётчиков ``stats()`` менять только через ADR (FE-007).
Ни одного ``Signal`` с кадром нет и не должно быть: кадр через сигнал — это снова
неограниченная очередь событий Qt.

Счётчики ``stats()`` на ключ:
- ``shown`` — успешные вызовы ``sink``;
- ``errors`` — вызовы ``sink`` с исключением (насос не останавливается);
- ``max_age_ms`` — максимум возраста снятого кадра (из ``age_s`` ящика) за весь прогон;
- ``window_max_age_ms`` — то же с последнего ``stats(reset_window=True)``;
- ``busy_ms_total`` — суммарное время, проведённое в ``sink`` (``time.perf_counter``).
"""

from __future__ import annotations

import math
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt, QTimer

from multiprocess_framework.modules.logger_module import get_std_logger

__all__ = ["FramePump"]

_log = get_std_logger(__name__)

#: Потолок частоты показа: дисплею не нужно чаще кадра монитора (решение 1 вердикта).
_MAX_FPS = 60
#: Частота ключа, найденного сканом без настройки (неизвестный sender в gui идёт в слот «main»).
_UNCONFIGURED_FPS = 30
#: Период скана ``pending_keys()`` в мс.
_SCAN_PERIOD_MS = 100
#: Не чаще одной строки лога об исключении ``sink`` на ключ за этот срок (иначе строка на тик).
_ERROR_LOG_PERIOD_S = 5.0


class _MailboxLike(Protocol):
    def take(self, key: str) -> tuple[Any, float] | None: ...

    def pending_keys(self) -> list[str]: ...


def _period_ms(fps_limit: Any) -> int:
    """Период таймера в целых мс для ``fps_limit``.

    ``ceil(1000 / clamp(fps_limit or 60, 1, 60))``: ``ceil``, а не ``int`` — ``int`` на
    60 Гц даёт 16 мс = 62,5 Гц выше потолка. ``0``, ``None``, нечисловое, NaN и число,
    не помещающееся в ``float`` (``10**400``), — 60 Гц.
    """
    try:
        fps = float(fps_limit) if fps_limit else float(_MAX_FPS)
    except (TypeError, ValueError, OverflowError):
        fps = float(_MAX_FPS)
    if math.isnan(fps):
        fps = float(_MAX_FPS)
    fps = min(max(fps, 1.0), float(_MAX_FPS))
    return math.ceil(1000.0 / fps)


def _new_counters() -> dict[str, float]:
    return {"shown": 0, "errors": 0, "max_age_ms": 0.0, "window_max_age_ms": 0.0, "busy_ms_total": 0.0}


class FramePump(QObject):
    """Таймер на ключ: ``take(key)`` из ящика и ``sink(key, item)`` в Qt-потоке."""

    def __init__(
        self,
        mailbox: _MailboxLike,
        sink: Callable[[str, Any], None],
        parent: QObject | None = None,
    ) -> None:
        """Создать насос и запустить скан ключей.

        Pre: вызван в Qt-потоке при живом ``QCoreApplication``; ``mailbox`` потокобезопасен
            (``put`` зовут другие потоки); ``sink`` вызывается только в Qt-потоке.
        Post: ключей нет, идёт скан ``pending_keys()`` с периодом 100 мс; ни один кадр не
            снят, пока не настроен ключ или скан его не нашёл.
        """
        super().__init__(parent)
        self._mailbox = mailbox
        self._sink = sink
        # замок держат set_keys и обновление счётчиков: stats() читает другой поток
        # (heartbeat), а набор ключей меняется в Qt-потоке
        self._lock = threading.Lock()
        self._timers: dict[str, QTimer] = {}
        self._counters: dict[str, dict[str, float]] = {}
        self._last_error_log: dict[str, float] = {}
        self._stopped = False
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(_SCAN_PERIOD_MS)
        self._scan_timer.timeout.connect(self._scan)
        self._scan_timer.start()

    def set_keys(self, keys: Mapping[str, Any]) -> None:
        """Настроить набор ключей: ``{key: fps_limit}``.

        Pre: Qt-поток; ``fps_limit`` — число, ``0``/``None`` = потолок 60 Гц; нечисловое и
            NaN трактуются как ``None`` и не роняют вызов.
        Post: у каждого ключа из ``keys`` свой таймер ``Qt.PreciseTimer`` с периодом
            ``ceil(1000 / clamp(fps, 1, 60))`` мс (уже существующий — только новый период;
            ключ, найденный сканом, перехвачен); таймеры ключей, которых в ``keys`` нет
            (в том числе найденных сканом), остановлены и их счётчики сняты; если у такого
            ключа в ящике остался кадр, скан заведёт ему таймер на 30 Гц заново. После
            ``stop()`` вызов ничего не делает.
        """
        # все периоды считаются ДО изменения состояния: сбой на одном ключе не оставит
        # набор применённым наполовину
        periods = {key: _period_ms(fps_limit) for key, fps_limit in keys.items()}
        with self._lock:
            if self._stopped:
                return
            for key in [k for k in self._timers if k not in periods]:
                self._drop_key(key)
            for key, period_ms in periods.items():
                self._ensure_key(key, period_ms)

    def stop(self) -> None:
        """Остановить скан и все таймеры.

        Pre: вызывается из Qt-потока (таймеры и их удаление принадлежат ему; T3 зовёт из
            ``aboutToQuit``); повторный вызов допустим.
        Post: после возврата ни один ``sink`` больше не вызывается (закрытие окна не
            оставляет вызовов в разрушенный виджет); ``set_keys`` ничего не делает; счётчики
            остаются доступны через ``stats()``.
        """
        with self._lock:
            self._stopped = True
            self._scan_timer.stop()
            for timer in self._timers.values():
                timer.stop()
                timer.deleteLater()
            self._timers.clear()

    def stats(self, reset_window: bool = False) -> dict[str, dict[str, float]]:
        """Снять счётчики ключей (потокобезопасно, можно из другого потока).

        Pre: нет.
        Post: новый словарь ``{key: {shown, errors, max_age_ms, window_max_age_ms,
            busy_ms_total}}`` — копия под замком, ``set_keys`` в другом потоке не даёт
            ``RuntimeError``. ``reset_window=True`` после снятия обнуляет
            ``window_max_age_ms`` всех ключей (значение в ответе — до обнуления);
            вызов без аргумента окно не трогает.
        """
        with self._lock:
            snapshot = {key: dict(counters) for key, counters in self._counters.items()}
            if reset_window:
                for counters in self._counters.values():
                    counters["window_max_age_ms"] = 0.0
        return snapshot

    # -- внутреннее (замок self._lock уже взят вызывающим, где сказано) ----------------

    def _ensure_key(self, key: str, period_ms: int) -> None:
        """Завести таймер ключа или сменить период существующего. Замок взят."""
        timer = self._timers.get(key)
        if timer is None:
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(period_ms)
            timer.timeout.connect(self._tick_handler(key))
            self._timers[key] = timer
            self._counters.setdefault(key, _new_counters())
            timer.start()
        elif timer.interval() != period_ms:
            timer.setInterval(period_ms)

    def _tick_handler(self, key: str) -> Callable[[], None]:
        """Обработчик таймера ключа со СЛАБОЙ ссылкой на насос.

        ``functools.partial(self._tick, key)`` держит насос сильной ссылкой изнутри соединения
        сигнала: образуется цикл, и сборка мусора разрушает насос уже после ``stop()`` в
        произвольный момент; воспроизведено: процесс падает (Fatal Python error: Aborted)
        в следующем ``exec()``. Слабая ссылка цикла не создаёт.
        """
        pump_ref = weakref.ref(self)

        def handler() -> None:
            pump = pump_ref()
            if pump is not None:
                pump._tick(key)  # noqa: SLF001 — тот же класс

        return handler

    def _drop_key(self, key: str) -> None:
        """Остановить таймер ключа и снять его счётчики. Замок взят."""
        timer = self._timers.pop(key)
        timer.stop()
        timer.deleteLater()
        self._counters.pop(key, None)
        self._last_error_log.pop(key, None)

    def _scan(self) -> None:
        """Найти ключи с ожидающим кадром без таймера и завести им таймер на 30 Гц."""
        if self._stopped:
            return
        pending = self._mailbox.pending_keys()
        with self._lock:
            if self._stopped:
                return
            for key in pending:
                if key not in self._timers:
                    self._ensure_key(key, _period_ms(_UNCONFIGURED_FPS))

    def _tick(self, key: str) -> None:
        """Один ``take(key)`` и один ``sink(key, item)``; пустой ящик — тик пропущен."""
        if self._stopped:
            return
        taken = self._mailbox.take(key)
        if taken is None:
            return
        item, age_s = taken
        failed: Exception | None = None
        started = time.perf_counter()
        try:
            self._sink(key, item)
        except Exception as exc:  # noqa: BLE001 — сбой sink не должен остановить насос
            failed = exc
        finished = time.perf_counter()
        age_ms = age_s * 1000.0
        with self._lock:
            counters = self._counters.get(key)  # sink мог снять ключ через set_keys
            if counters is not None:
                counters["busy_ms_total"] += (finished - started) * 1000.0
                counters["max_age_ms"] = max(counters["max_age_ms"], age_ms)
                counters["window_max_age_ms"] = max(counters["window_max_age_ms"], age_ms)
                counters["errors" if failed is not None else "shown"] += 1
            log_error = (
                failed is not None and finished - self._last_error_log.get(key, -math.inf) >= _ERROR_LOG_PERIOD_S
            )
            if log_error:
                self._last_error_log[key] = finished
        if log_error:
            _log.warning(
                "FramePump: sink(%r) бросил исключение (лог не чаще раза в %.0f с)",
                key,
                _ERROR_LOG_PERIOD_S,
                exc_info=failed,
            )
