"""throttle.py — Middleware для ограничения частоты обновлений по паттернам путей.

Позволяет задать минимальный интервал между записями для группы путей.
Полезно для высокочастотных метрик (fps, seq), которые не нужно писать в
StateStore на каждый кадр.

Порядок правил: первое матчащее правило применяется.
"""

from __future__ import annotations

import time
from typing import Any

from multiprocess_prototype.state_store.core.subscription_manager import _match_pattern, _split_pattern
from multiprocess_prototype.state_store.middleware.base import StateMiddleware


class ThrottleMiddleware(StateMiddleware):
    """Ограничение частоты обновлений по паттернам путей.

    Пример::

        ThrottleMiddleware({
            "**.state.actual_fps": 1.0,    # max 1 раз/сек
            "**.state.drops_count": 2.0,   # max 1 раз/2 сек
            "**.state.last_frame_seq": 0,  # полная блокировка
        })

    Правила:
    - ``0``  — полная блокировка: путь никогда не попадёт в StateStore.
    - ``>0`` — минимальный интервал в секундах между двумя пропущенными записями.
    - Путь не покрыт ни одним правилом — пропускать всегда (без ограничений).
    - Последнее заблокированное значение накапливается в ``_pending`` и может
      быть сброшено вручную через :meth:`flush` (например, при shutdown).
    """

    @property
    def name(self) -> str:
        return "throttle"

    def __init__(self, rules: dict[str, float]) -> None:
        # Словарь правил: паттерн → интервал (0 = полная блокировка)
        self._rules: dict[str, float] = dict(rules)

        # Последний момент пропуска для каждого конкретного пути
        self._last_pass: dict[str, float] = {}

        # Последнее заблокированное значение: path → (value, source)
        self._pending: dict[str, tuple[Any, str]] = {}

    # ------------------------------------------------------------------
    # before_set — основная логика throttle
    # ------------------------------------------------------------------

    def before_set(
        self,
        path: str,
        value: Any,
        source: str,
        context: dict,
    ) -> tuple[bool, Any]:
        """Проверить, нужно ли пропустить обновление по пути ``path``.

        Алгоритм:
        1. Найти первое матчащее правило для ``path``.
        2. Нет правила → пропустить (True, value).
        3. ``interval == 0`` → заблокировать навсегда (False, value).
        4. Прошло меньше ``interval`` с последнего пропуска → сохранить
           в ``_pending``, вернуть (False, value).
        5. Иначе → пропустить, обновить ``_last_pass``, очистить ``_pending``.
        """
        interval = self._find_rule(path)

        # Путь не покрыт правилами — пропускаем без ограничений
        if interval is None:
            return True, value

        # Полная блокировка
        if interval == 0:
            self._pending[path] = (value, source)
            context["rejection_reason"] = "throttled"
            return False, value

        now = time.monotonic()
        last = self._last_pass.get(path)

        if last is not None and (now - last) < interval:
            # Слишком рано — накапливаем последнее значение
            self._pending[path] = (value, source)
            context["rejection_reason"] = "throttled"
            return False, value

        # Пропускаем: обновляем время и убираем pending для этого пути
        self._last_pass[path] = now
        self._pending.pop(path, None)
        return True, value

    # ------------------------------------------------------------------
    # flush — принудительный сброс накопленных значений
    # ------------------------------------------------------------------

    def flush(self) -> list[tuple[str, Any, str]]:
        """Принудительный сброс всех накопленных throttled-значений.

        Вызывается при shutdown, чтобы не потерять последние значения.

        Returns:
            Список кортежей ``(path, value, source)`` для каждого pending значения.
            После вызова ``_pending`` очищается.
        """
        result = [
            (path, value, source)
            for path, (value, source) in self._pending.items()
        ]
        self._pending.clear()
        return result

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _find_rule(self, path: str) -> float | None:
        """Найти первое матчащее правило для ``path``.

        Args:
            path: конкретный путь в дереве состояний.

        Returns:
            Интервал в секундах, если правило найдено; ``None`` если нет.
        """
        path_segs = tuple(path.split("."))
        for pattern, interval in self._rules.items():
            pattern_segs = _split_pattern(pattern)
            if _match_pattern(pattern_segs, path_segs):
                return interval
        return None
