# -*- coding: utf-8 -*-
"""events.py — событийный канал driver'а (push-сообщения без reply).

Mixin `_EventChannelMixin`: bounded-очередь + список подписчиков под одним
Condition. reader-поток пишет (`_emit_event`), клиентский поток дренирует
(`events`); подписчики зовутся синхронно в reader-потоке (колбэк не роняет reader).

Выделено из ``driver.py`` (Phase C, C.1) как mixin — код переезжает дословно на тот
же ``self`` (поведение бит-в-бит), давая модульную границу без перестройки
concurrency-контура. Хост (`BackendDriver`) обязан завести поля в ``__init__``:
``_events`` (deque), ``_events_cv`` (Condition), ``_subscribers`` (list),
``_event_errors`` (int), и транспортные ``_running``/``_reader`` (для выхода из
бесконечного ожидания на закрытом соединении). B.1 перестроит канал на курсорные
плоскости — тогда этот модуль станет местом той работы.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

# Колбэк подписчика на события (получает распарсенный push-dict).
EventCallback = Callable[[Dict[str, Any]], None]


class _EventChannelMixin:
    """Событийный канал: bounded-очередь push-сообщений + синхронные подписчики."""

    def _emit_event(self, msg: Dict[str, Any]) -> None:
        """Положить событие в bounded-очередь и синхронно оповестить подписчиков.

        Вызывается только из reader-потока. Исключение любого колбэка не роняет
        reader-поток (глотается, инкрементит счётчик _event_errors) и не мешает
        остальным подписчикам.
        """
        with self._events_cv:
            self._events.append(msg)
            subscribers = list(self._subscribers)  # снимок под локом
            self._events_cv.notify_all()
        # Колбэки — вне лока: могут быть медленными и/или звать driver повторно.
        for cb in subscribers:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001 — контракт: колбэк не роняет reader
                self._event_errors += 1

    def subscribe(self, callback: EventCallback) -> EventCallback:
        """Подписаться на события: callback зовётся на каждое push-сообщение.

        Колбэк исполняется в reader-потоке — держи его лёгким (тяжёлую работу
        отдай в свой поток/очередь). Возвращает сам callback (хэндл для unsubscribe).
        """
        with self._events_cv:
            self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: EventCallback) -> None:
        """Отписать ранее зарегистрированный callback (no-op, если его нет)."""
        with self._events_cv:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def events(
        self,
        timeout: Optional[float] = 0.0,
        *,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Прочитать накопленные события (drain).

        Семантика timeout:
        - `0.0` (по умолчанию) — поллинг: сразу вернуть, что накоплено (может быть []);
        - `>0` — блокировать до появления хотя бы одного события, но не дольше timeout,
          затем слить всё накопленное;
        - `None` — блокировать до первого события (или до close()).

        max_items ограничивает размер пачки (остаток останется в очереди).
        Возвращает список событий в порядке поступления (FIFO).
        """
        with self._events_cv:
            # Три режима ожидания разведены явно — так `deadline` в блокирующей
            # ветке всегда float (без Optional-narrowing) и каждая семантика читается
            # отдельно. Поллинг (timeout == 0.0) вообще не ждёт — сразу к drain.
            if timeout is None:
                while not self._events:
                    # Бесконечное ожидание: не висеть вечно на закрытом/не открытом
                    # соединении — выходим (новых событий не будет).
                    if not self._running and self._reader is None:
                        break
                    self._events_cv.wait()
            elif timeout > 0.0:
                deadline = time.monotonic() + timeout
                while not self._events:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._events_cv.wait(remaining)
            if max_items is None:
                count = len(self._events)
            else:
                count = min(max_items, len(self._events))
            return [self._events.popleft() for _ in range(count)]

    @property
    def event_errors(self) -> int:
        """Сколько раз колбэк подписчика бросил исключение (диагностика)."""
        return self._event_errors


__all__ = ["_EventChannelMixin", "EventCallback"]
