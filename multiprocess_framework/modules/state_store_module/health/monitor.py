"""monitor.py — HealthMonitor: watchdog на базе state-обновлений.

Отслеживает свежесть обновлений state-ветвей по каждому процессу.
Если процесс не обновлял свою ветвь дольше heartbeat_timeout →
помечается как "unresponsive".

Не использует потоки или asyncio — pull-based: явный вызов check().
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..core.tree_store import TreeStore
from ..core import match_pattern, split_pattern


# ---------------------------------------------------------------------------
# Статусы процессов
# ---------------------------------------------------------------------------

STATUS_RUNNING = "running"
STATUS_UNRESPONSIVE = "unresponsive"
STATUS_UNKNOWN = "unknown"

# Статусы overall health
OVERALL_OK = "ok"
OVERALL_DEGRADED = "degraded"
OVERALL_CRITICAL = "critical"


# ---------------------------------------------------------------------------
# WatchedProcess — внутреннее состояние одного отслеживаемого процесса
# ---------------------------------------------------------------------------

@dataclass
class WatchedProcess:
    """Внутреннее состояние мониторинга одного процесса.

    Attributes:
        name: имя процесса (camera_0, renderer и т.д.)
        pattern: glob-паттерн state-путей этого процесса (cameras.0.state.**)
        last_seen: время последней активности (time.monotonic) или None
        status: текущий статус ("running" | "unresponsive" | "unknown")
    """

    name: str
    pattern: str
    last_seen: Optional[float] = None  # time.monotonic()
    status: str = STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """Watchdog: отслеживает state-обновления от процессов.

    Если процесс не обновлял свою state-ветвь дольше timeout →
    помечается как "unresponsive".

    Не использует threading.Timer или asyncio — работает через
    явный вызов check() (pull-based, чтобы не зависеть от event loop).

    Пример:
        monitor = HealthMonitor(store, heartbeat_timeout=5.0)
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")

        # При каждом state-изменении:
        monitor.record_activity("cameras.0.state.actual_fps")

        # Периодическая проверка (вызывается из main loop или таймера):
        health = monitor.check()
        # {"camera_0": "running", "renderer": "unresponsive"}
    """

    def __init__(self, store: TreeStore, heartbeat_timeout: float = 5.0) -> None:
        """
        Args:
            store: TreeStore — хранилище для записи результатов здоровья.
            heartbeat_timeout: время (в секундах) без активности,
                после которого процесс считается "unresponsive".
        """
        self._store = store
        self._timeout = heartbeat_timeout
        # name → WatchedProcess
        self._watched: dict[str, WatchedProcess] = {}
        # последний результат check()
        self._last_health: dict[str, str] = {}

    # -----------------------------------------------------------------------
    # Регистрация процессов
    # -----------------------------------------------------------------------

    def register(self, name: str, pattern: str) -> None:
        """Зарегистрировать процесс для мониторинга.

        Если процесс с таким именем уже зарегистрирован — перезаписывает паттерн,
        сохраняя last_seen (процесс мог обновить state до перерегистрации).

        Args:
            name: имя процесса (camera_0, renderer и т.д.)
            pattern: glob-паттерн state-путей этого процесса
        """
        if name in self._watched:
            # Обновляем паттерн, сохраняем last_seen и status
            existing = self._watched[name]
            self._watched[name] = WatchedProcess(
                name=name,
                pattern=pattern,
                last_seen=existing.last_seen,
                status=existing.status,
            )
        else:
            self._watched[name] = WatchedProcess(name=name, pattern=pattern)

    def unregister(self, name: str) -> None:
        """Снять процесс с мониторинга.

        Если процесс не зарегистрирован — операция игнорируется.

        Args:
            name: имя процесса.
        """
        self._watched.pop(name, None)
        self._last_health.pop(name, None)

    # -----------------------------------------------------------------------
    # Запись активности
    # -----------------------------------------------------------------------

    def record_activity(self, path: str) -> None:
        """Записать активность по пути. Вызывается при каждом state-изменении.

        Находит зарегистрированный процесс, чей паттерн совпадает с путём,
        и обновляет его last_seen timestamp.

        Если несколько процессов матчат один путь — обновляются все.
        Если никто не матчит — вызов игнорируется (не ошибка).

        Args:
            path: точечный путь изменённого state-узла.
        """
        path_segs = tuple(path.split(".")) if path else ()

        for proc in self._watched.values():
            pattern_segs = split_pattern(proc.pattern)
            if match_pattern(pattern_segs, path_segs):
                proc.last_seen = time.monotonic()

    # -----------------------------------------------------------------------
    # Проверка здоровья
    # -----------------------------------------------------------------------

    def check(self) -> dict[str, str]:
        """Проверить здоровье всех зарегистрированных процессов.

        Алгоритм для каждого процесса:
          - last_seen is None → "unknown" (никогда не видели активность)
          - now - last_seen < timeout → "running"
          - now - last_seen >= timeout → "unresponsive"

        Также записывает результаты в TreeStore:
          store.set("system.health.<name>", status, source="health_monitor")
          store.set("system.health.overall", "ok"|"degraded"|"critical")

        Логика overall:
          - Все "running" → "ok"
          - Хотя бы один "unresponsive" → "degraded"
          - Все "unresponsive" или "unknown" (нет "running") → "critical"

        Returns:
            {name: status} — snapshot здоровья всех процессов.
        """
        now = time.monotonic()
        result: dict[str, str] = {}

        for name, proc in self._watched.items():
            if proc.last_seen is None:
                status = STATUS_UNKNOWN
            elif (now - proc.last_seen) >= self._timeout:
                status = STATUS_UNRESPONSIVE
            else:
                status = STATUS_RUNNING

            proc.status = status
            result[name] = status

            # Записываем индивидуальный статус в store
            self._store.set(
                f"system.health.{name}",
                status,
                source="health_monitor",
            )

        # Вычисляем overall health
        overall = self._compute_overall(result)
        self._store.set("system.health.overall", overall, source="health_monitor")

        # Сохраняем snapshot
        self._last_health = dict(result)

        return result

    def get_health(self) -> dict[str, str]:
        """Вернуть последний результат check() без пересчёта.

        Если check() ещё не вызывался — возвращает пустой dict.

        Returns:
            Последний snapshot {name: status}.
        """
        return dict(self._last_health)

    # -----------------------------------------------------------------------
    # Свойства
    # -----------------------------------------------------------------------

    @property
    def watched_processes(self) -> list[str]:
        """Список имён зарегистрированных процессов."""
        return list(self._watched.keys())

    # -----------------------------------------------------------------------
    # Внутренние методы
    # -----------------------------------------------------------------------

    def _compute_overall(self, statuses: dict[str, str]) -> str:
        """Вычислить overall health на основе индивидуальных статусов.

        Правила:
          - Нет процессов → "ok" (пустая система здорова по умолчанию)
          - Все "running" → "ok"
          - Хотя бы один "unresponsive" → "degraded"
          - Нет ни одного "running" (все "unresponsive" или "unknown") → "critical"

        Args:
            statuses: {name: status} для всех процессов.

        Returns:
            "ok" | "degraded" | "critical"
        """
        if not statuses:
            return OVERALL_OK

        has_running = any(s == STATUS_RUNNING for s in statuses.values())
        has_unresponsive = any(s == STATUS_UNRESPONSIVE for s in statuses.values())

        if not has_running:
            # Нет ни одного running — критично
            return OVERALL_CRITICAL

        if has_unresponsive:
            # Есть и running, и unresponsive — деградация
            return OVERALL_DEGRADED

        return OVERALL_OK
