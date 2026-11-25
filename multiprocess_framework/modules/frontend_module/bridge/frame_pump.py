"""FramePump — вытягивание кадров из ящика «последний на ключ» таймером на ключ (Qt).

Purpose: тракт кадров gui не накапливает кадры. Поток-источник кладёт кадр в ящик
(``put``), не трогая Qt (ни Signal, ни ``postEvent``): ящик держит не больше одного
кадра на ключ. Насос живёт в Qt-потоке и по таймеру на ключ забирает ``take(key)`` и
отдаёт кадр в ``sink(key, item)``. Частота показа ограничена ``fps_limit`` ключа,
память — «ключи x 1 кадр» при любой частоте входа (ADR FE-007).

Public API:
- FramePump(mailbox, sink, parent=None, *, on_silence=None, silence_s=0.0) — создаётся в
  Qt-потоке; запускает скан ключей
- set_keys({key: fps_limit}) -> None     — настроить ключи (повторный вызов допустим)
- stop() -> None                         — погасить скан и таймеры (идемпотентно)
- stats(reset_window=False) -> dict      — счётчики на ключ (потокобезопасно)

``mailbox`` — утиная типизация: ``take(key) -> (item, age_s) | None`` и
``pending_keys() -> list[str]`` (``LatestMailbox`` из ``process_module.generic``; импорт
его сюда не нужен). ``sink(key, item)`` получает ВЕСЬ item без изменений (поля
``capture_ns``, ``capture_ts``, ``replay`` насос не читает) и вызывается только в Qt-потоке.
``sink`` возвращает ``False``, когда кадр не показан (``Callable[[str, Any], object]``);
любое другое значение, в том числе ``None``, — «показан».

Тишина ключа (включена при ``on_silence is not None and silence_s > 0``): ``on_silence(key,
age_s)`` — на этот ключ ``age_s`` секунд (не меньше ``silence_s``) не показан кадр; зовётся на
пустом тике, не чаще раза на целую секунду возраста. Возраст считается от последнего
ПОКАЗАННОГО кадра ключа, без кадров — от заведения ключа. ``on_silence(key, None)`` — после
``sink`` первого показанного кадра, пришедшего после сообщённой тишины. Кадр, не показанный
``sink`` (``False`` или исключение), тишину не прерывает. Колбэк зовётся в Qt-потоке вне
замка насоса; при снятии ключа не зовётся. Часы — ``time.perf_counter``; выключенный
механизм их ради тишины не читает.

Stability: lite — сигнатуры и набор счётчиков ``stats()`` менять только через ADR (FE-007).
Ни одного ``Signal`` с кадром нет и не должно быть: кадр через сигнал — это снова
неограниченная очередь событий Qt.

Счётчики ``stats()`` на ключ:
- ``shown`` — вызовы ``sink`` без исключения, в том числе вернувшие ``False`` (постоянно
  падающая копия растит ``shown``, пока стоит плашка тишины);
- ``errors`` — вызовы ``sink`` и ``on_silence`` с исключением (насос не останавливается);
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
#: Не чаще одной строки лога об исключении ``sink`` (и отдельно ``on_silence``) на ключ за этот
#: срок (иначе строка на тик).
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
        sink: Callable[[str, Any], object],
        parent: QObject | None = None,
        *,
        on_silence: Callable[[str, float | None], None] | None = None,
        silence_s: float = 0.0,
    ) -> None:
        """Создать насос и запустить скан ключей.

        Pre: вызван в Qt-потоке при живом ``QCoreApplication``; ``mailbox`` потокобезопасен
            (``put`` зовут другие потоки); ``sink`` вызывается только в Qt-потоке и возвращает
            ``False``, когда кадр не показан.
        Post: ключей нет, идёт скан ``pending_keys()`` с периодом 100 мс; ни один кадр не
            снят, пока не настроен ключ или скан его не нашёл. Тишина ключа сообщается в
            ``on_silence`` (в Qt-потоке) только при ``on_silence is not None`` и
            ``silence_s > 0``; иначе колбэк не зовётся и часы ради него не читаются.
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
        self._on_silence = on_silence
        self._silence_s = silence_s
        self._silence_on = on_silence is not None and silence_s > 0
        # состояние тишины трогает только Qt-поток, замок не нужен:
        # время последнего показанного кадра ключа (без кадров — заведения ключа),
        self._last_shown: dict[str, float] = {}
        # последняя сообщённая целая секунда тишины ключа,
        self._silent: dict[str, int] = {}
        # время последней строки лога об исключении on_silence
        self._last_silence_error_log: dict[str, float] = {}
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
        Post: после возврата ни ``sink``, ни ``on_silence`` больше не вызываются (закрытие окна
            не оставляет вызовов в разрушенный виджет), в том числе если ``stop()`` позван из
            самого ``sink`` или ``on_silence``; ``set_keys`` ничего не делает; счётчики остаются
            доступны через ``stats()``.
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
            if self._silence_on:
                self._last_shown[key] = time.perf_counter()
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
        """Остановить таймер ключа, снять счётчики и состояние тишины. Замок взят.

        ``on_silence`` здесь не зовётся: плашки снятых ключей убирает потребитель при ``set_keys``.
        """
        timer = self._timers.pop(key)
        timer.stop()
        timer.deleteLater()
        self._counters.pop(key, None)
        self._last_error_log.pop(key, None)
        self._last_shown.pop(key, None)
        self._silent.pop(key, None)
        self._last_silence_error_log.pop(key, None)

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
        """Один ``take(key)`` и один ``sink(key, item)``; пустой ящик — только проверка тишины."""
        if self._stopped:
            return
        taken = self._mailbox.take(key)
        if taken is None:
            if self._silence_on:
                self._check_silence(key)
            return
        item, age_s = taken
        failed: Exception | None = None
        result: object = None
        started = time.perf_counter()
        try:
            result = self._sink(key, item)
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
        # кадр показан: sink вернулся без исключения и не False. Из sink могли позвать stop()
        # (дальше потребителя не зовём) или снять ключ через set_keys (его состояние не воскрешаем)
        shown = failed is None and result is not False
        if self._silence_on and shown and not self._stopped and key in self._timers:
            self._last_shown[key] = finished
            if self._silent.pop(key, None) is not None:  # 0 — тоже сообщённая тишина
                self._call_on_silence(key, None)

    def _check_silence(self, key: str) -> None:
        """Пустой тик включённого механизма: сообщить новую целую секунду тишины ключа."""
        since = self._last_shown.get(key)
        if since is None:  # ключ уже снят
            return
        age_s = time.perf_counter() - since
        if age_s >= self._silence_s and int(age_s) != self._silent.get(key):
            # запоминаем ДО вызова: бросивший или крутящий события колбэк не получит повтор
            self._silent[key] = int(age_s)
            self._call_on_silence(key, age_s)

    def _call_on_silence(self, key: str, age_s: float | None) -> None:
        """``on_silence`` вне замка; исключение — в ``errors`` и в лог со своим дросселем.

        Это последний вызов потребителя в тике: после ``stop()`` из колбэка вслед ничего не идёт.
        """
        try:
            self._on_silence(key, age_s)
        except Exception as exc:  # noqa: BLE001 — сбой колбэка не должен остановить насос
            now = time.perf_counter()
            with self._lock:
                counters = self._counters.get(key)  # колбэк мог снять ключ через set_keys
                if counters is not None:
                    counters["errors"] += 1
                log_error = now - self._last_silence_error_log.get(key, -math.inf) >= _ERROR_LOG_PERIOD_S
                if log_error and counters is not None:
                    self._last_silence_error_log[key] = now
            if log_error:
                _log.warning(
                    "FramePump: on_silence(%r) бросил исключение (лог не чаще раза в %.0f с)",
                    key,
                    _ERROR_LOG_PERIOD_S,
                    exc_info=exc,
                )
