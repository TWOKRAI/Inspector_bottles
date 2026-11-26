# -*- coding: utf-8 -*-
"""Purpose: «триггер был, а кадр не пришёл» — импульс ждёт свой кадр не дольше срока (П6, W2-t1).

Public API: `FrameWatch(deadline_s)` — `on_trigger(now)`, `on_frame(now)`, `poll(now)`, `withdraw_last()`,
`drop_pending()`, `reset_counts()`, `snapshot()`.

Stability: lite

Условия вызова:

- `deadline_s > 0`;
- `now` — секунды монотонных часов, не убывает и берётся под замком вызывающего; своих часов у помощника нет;
- не потокобезопасен: все методы зовёт один поток или вызывающий держит замок;
- `on_trigger` зовётся ДО прихода кадра этого импульса, иначе ложный пропуск.

О связи с прибором помощник ничего не знает: импульсы во время обрыва — пропуски.

Предел: у кадра нет номера импульса, сопоставление FIFO. Пропуск виден вовремя, только если задержка
кадра < срок < период импульсов; иначе следующий кадр маскирует пропуск.
"""

from __future__ import annotations

from collections import deque

__all__ = ["FrameWatch"]

# Потолок памяти при источнике без кадров: при 100 Гц это ~10 с ожидания, всё сверх — уже пропуски.
_MAX_PENDING = 1024


class FrameWatch:
    """Очередь ждущих импульсов (FIFO) и счёт пропусков."""

    def __init__(self, deadline_s: float) -> None:
        self._deadline_s = deadline_s
        self._pending: deque[float] = deque()  # времена импульсов; `now` не убывает -> старший слева
        self._triggers = 0
        self._misses = 0
        self._unreported = 0  # пропуски, ещё не отданные `poll`
        self._open_miss = False
        self._last_miss_mono: float | None = None

    def on_trigger(self, now: float) -> None:
        """Импульс отправлен или получен. Очередь полна -> самый старый уходит в пропуски."""
        if len(self._pending) >= _MAX_PENDING:
            self._pending.popleft()
            self._count_miss(now)
        self._pending.append(now)
        self._triggers += 1

    def on_frame(self, now: float) -> None:
        """Пришёл кадр: учесть просроченные, снять самый старый оставшийся, закрыть эпизод.

        Пропуски, учтённые здесь, вернёт следующий `poll`. Кадр без ждущего импульса ничего не считает.
        """
        self._expire(now)
        if self._pending:
            self._pending.popleft()
        self._open_miss = False

    def poll(self, now: float) -> int:
        """Снять просроченные (строго `now - t > deadline_s`); вернуть пропуски с прошлого `poll`."""
        self._expire(now)
        missed, self._unreported = self._unreported, 0
        return missed

    def withdraw_last(self) -> bool:
        """Отозвать самый новый ждущий импульс (он не состоялся). Очередь пуста -> `False`.

        Импульс, уже ушедший в пропуски, не отзывается: пропуск остаётся.
        """
        if not self._pending:
            return False
        self._pending.pop()
        self._triggers = max(0, self._triggers - 1)  # после `reset_counts` счёт уже 0
        return True

    def drop_pending(self) -> None:
        """Забыть ждущие импульсы и закрыть эпизод; счётчики и не отданные `poll` пропуски целы."""
        self._pending.clear()
        self._open_miss = False

    def reset_counts(self) -> None:
        """Обнулить счётчики (в том числе не отданные `poll` пропуски); ждущие импульсы остаются.

        Поэтому импульс, ждавший во время сброса, может дать `misses` больше `triggers`.
        """
        self._triggers = 0
        self._misses = 0
        self._unreported = 0
        self._open_miss = False
        self._last_miss_mono = None

    def snapshot(self) -> dict:
        """Счётчики и состояние эпизода одним словарём."""
        return {
            "triggers": self._triggers,
            "misses": self._misses,
            "open_miss": self._open_miss,
            "last_miss_mono": self._last_miss_mono,
        }

    def _expire(self, now: float) -> None:
        while self._pending and now - self._pending[0] > self._deadline_s:
            self._pending.popleft()
            self._count_miss(now)

    def _count_miss(self, now: float) -> None:
        self._misses += 1
        self._unreported += 1
        self._open_miss = True
        self._last_miss_mono = now
