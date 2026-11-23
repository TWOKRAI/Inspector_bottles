# -*- coding: utf-8 -*-
"""Шкала прогресса: путь листа ``system.progress.<id>`` и помощник ``ProgressTracker``.

Purpose:
    Контракт «любой узел сообщает прогресс одним вызовом»: путь листа в state-дереве и dict-значение
    (потребители — ``backend_ctl`` и окно загрузки читают его по этому пути). Рядом с контрактом путей
    ``health/schema.py``: ``process_module`` — ярус core, а ``state_store_module`` (optional) отсюда не импортируется.

Public API:
    ``PROGRESS_ROOT``                          — корень листьев (``"system.progress"``);
    ``progress_path(id) -> str``               — путь листа ``system.progress.<id>``;
    ``ProgressTracker(steps)``                 — считает процент по шагам с весами;
    ``ProgressTracker.advance(step, fraction=1.0, *, label="") -> dict`` — шаг продвинулся;
    ``ProgressTracker.finish(label="") -> dict`` — шкала закрыта (100 %, ``done``).

Лист (Dict at Boundary, pickle-safe)::

    {"percent": int 0..100, "label": str, "done": bool, "updated_at": float}

``percent`` — процент по ФАЗАМ работы, а не по времени и не готовность узлов. ``done`` ставит только ``finish``:
процент 100 без ``done`` бывает (последний шаг дошёл до конца, итог ещё не подведён).

Stability:
    Контракт листа и пути — стабильный (его читают внешние потребители). Класс чистый: без IO, Qt и стора,
    писатель сам кладёт возвращённый dict в свой API записи. НЕ потокобезопасен: одним трекером владеет один
    писатель (например, ``initialize()`` PM).
"""

from __future__ import annotations

import time

#: Корень листьев прогресса в state-дереве.
PROGRESS_ROOT = "system.progress"


def progress_path(progress_id: str) -> str:
    """Путь листа прогресса ``system.progress.<id>`` (например, ``system.progress.boot``)."""
    return f"{PROGRESS_ROOT}.{progress_id}"


class ProgressTracker:
    """Процент загрузки по шагам с весами; процент монотонный (не убывает никогда).

    Args:
        steps: ``[(имя шага, вес в процентах), ...]``; веса в сумме дают 100 (сумму выше 100 процент обрезает).

    Invariants:
        ``percent`` лежит в 0..100 и не убывает; доля каждого шага тоже не убывает (шаг, отступивший назад,
        не уменьшает ни свою долю, ни итог).
    """

    def __init__(self, steps: list[tuple[str, int]]) -> None:
        self._weights: dict[str, int] = dict(steps)
        self._fractions: dict[str, float] = {name: 0.0 for name in self._weights}
        self._percent = 0

    def advance(self, step: str, fraction: float = 1.0, *, label: str = "") -> dict:
        """Шаг ``step`` выполнен на долю ``fraction`` (0..1); вернуть лист для записи.

        Pre:
            ``step`` задан в конструкторе; иначе ``ValueError`` (значение шага в текст не попадает), состояние цело.
            ``fraction`` вне 0..1 обрезается; ``nan`` считается нулём.
        Post:
            ``percent`` = max(прошлый, сумма вес x доля по шагам), целое в 0..100; ``done`` всегда ``False``.
        """
        if step not in self._weights:
            raise ValueError("неизвестный шаг прогресса (имена шагов заданы в конструкторе ProgressTracker)")
        clamped = min(1.0, max(0.0, fraction))
        self._fractions[step] = max(self._fractions[step], clamped)
        total = sum(self._weights[name] * self._fractions[name] for name in self._weights)
        self._percent = max(self._percent, min(100, round(total)))
        return self._leaf(label, done=False)

    def finish(self, label: str = "") -> dict:
        """Закрыть шкалу: 100 % и ``done=True``; вернуть лист для записи.

        Post:
            ``percent == 100``, ``done is True``; повторный вызов даёт тот же итог с новым ``updated_at``.
        """
        self._percent = 100
        return self._leaf(label, done=True)

    def _leaf(self, label: str, *, done: bool) -> dict:
        """Лист прогресса: ровно четыре литеральных ключа, типы ``int/str/bool/float``."""
        return {"percent": self._percent, "label": str(label), "done": done, "updated_at": float(time.time())}
