# -*- coding: utf-8 -*-
"""HealthState — примитив наблюдаемости отказов процесса (Ф2 Task 2.1).

Роль: единый на процесс аккумулятор здоровья, который наполняют плагины через
``ctx.health`` (фасад :class:`HealthReporter`), а публикует в state-дерево
heartbeat процесса (тот же self-publish канал, что и телеметрия fps/latency —
см. ``ProcessHeartbeat._publish_metrics_to_tree``). Новый IPC-канал НЕ вводится.

Ключевые свойства:
- **rate-limit.** Публикация — по такту heartbeat (раз в ``heartbeat_interval``),
  так что «шторм» одинаковых ошибок не спамит state-дерево естественным образом.
  Дополнительно логирование дросселируется окном ``throttle`` на пару
  (тип, context), чтобы не залить и лог.
- **counter честный.** ``errors`` инкрементится на КАЖДЫЙ ``report_error`` —
  даже под throttle/лог-only — потому что breaker (Ф2 Task 2.2) читает счётчик и
  ему нужна правда о числе проглоченных ошибок.
- **откат в лог-only.** Переключатель ``INSPECTOR_HEALTH_LOG_ONLY`` (env) или
  явный ``log_only=True`` вырождает report_error/set_status в чистое логирование:
  state-дерево не трогается (dirty не поднимается) — путь отката, заложенный в
  дизайн по требованию плана.

Dict at Boundary: наружу (в state-дерево) уходит только dict/скаляр — см.
:mod:`.schema` и :func:`publish_health`.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Protocol, runtime_checkable

from .breaker import (
    DEFAULT_COOLDOWN_SEC as _BREAKER_DEFAULT_COOLDOWN,
    DEFAULT_THRESHOLD as _BREAKER_DEFAULT_THRESHOLD,
    CircuitBreaker,
)
from .schema import (
    HEALTH_FIELDS,
    HealthField,
    HealthStatus,
    LastErrorKey,
    health_path,
)

#: Окно дросселирования логов по умолчанию (сек): повтор той же ошибки в этом окне
#: не пишется в лог второй раз. На счётчик ``errors`` не влияет.
DEFAULT_THROTTLE = 5.0

#: Переключатель отката: report_error/set_status только логируют, state не трогают.
LOG_ONLY_ENV = "INSPECTOR_HEALTH_LOG_ONLY"

#: Порог breaker процесса: N подряд report_error → degraded. Env-override (Ф2 Task 2.2).
BREAKER_THRESHOLD_ENV = "INSPECTOR_HEALTH_BREAKER_THRESHOLD"
#: Cooldown breaker процесса (сек) перед half-open пробой. Env-override.
BREAKER_COOLDOWN_ENV = "INSPECTOR_HEALTH_BREAKER_COOLDOWN"

#: Обрезка длинных сообщений исключений (защита state-дерева от гигантских строк).
_MAX_MESSAGE_LEN = 500


class HealthSelfTestError(RuntimeError):
    """Синтетическая ошибка для диагностического впрыска (``health.report``).

    Отдельный тип, чтобы live-проверка канала наблюдаемости отличала self-test от
    настоящих ошибок по ``last_error.type``.
    """


def _env_log_only() -> bool:
    return os.environ.get(LOG_ONLY_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@runtime_checkable
class IHealthReporter(Protocol):
    """Контракт фасада ``ctx.health``, который видят плагины.

    Плагин знает только этот интерфейс (ADR-120: плагин — через PluginContext).
    Реализация — :class:`HealthReporter` поверх процесс-общего :class:`HealthState`.
    """

    def report_error(self, exc: BaseException, context: str | None = ..., throttle: float = ...) -> None:
        """Зарегистрировать проглоченную/обработанную ошибку (инкремент + last_error)."""
        ...

    def report_success(self, context: str | None = ...) -> None:
        """Учесть успешную операцию (обнуляет серию breaker)."""
        ...

    def set_status(self, status: "HealthStatus | str", reason: str | None = ...) -> None:
        """Явно выставить статус здоровья."""
        ...

    def degraded(self, reason: str) -> None:
        """Сокращение для ``set_status(DEGRADED, reason)``."""
        ...


class HealthState:
    """Единый на процесс аккумулятор здоровья (thread-safe).

    Плагины наполняют его из своих воркер-потоков через :class:`HealthReporter`,
    heartbeat-поток снимает грязный снапшот (:meth:`take_dirty`) и публикует —
    отсюда блокировка вокруг мутаций и снапшота.
    """

    def __init__(
        self,
        *,
        log: Callable[[str], None] | None = None,
        log_only: bool | None = None,
        clock: Callable[[], float] = time.time,
        breaker_threshold: int | None = None,
        breaker_cooldown_sec: float | None = None,
        breaker_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            log: callback логирования (обычно ``services.log_warning``); None → no-op.
            log_only: форсировать режим отката; None → читать из env ``LOG_ONLY_ENV``.
            clock: источник времени для timestamp'ов (инъекция для детерминизма).
            breaker_threshold: порог breaker (N подряд report_error → degraded);
                None → env ``INSPECTOR_HEALTH_BREAKER_THRESHOLD`` или дефолт.
            breaker_cooldown_sec: cooldown breaker; None → env или дефолт.
            breaker_clock: монотонный источник для cooldown breaker (инъекция в тестах).
        """
        self._lock = threading.Lock()
        self._clock = clock
        self._log: Callable[[str], None] = log if callable(log) else (lambda _msg: None)
        self._log_only = _env_log_only() if log_only is None else bool(log_only)

        self._status: HealthStatus = HealthStatus.OK
        self._errors = 0
        self._last_error: dict[str, Any] | None = None
        self._degraded_reason: str | None = None
        self._updated_at = 0.0
        # Начальный ok публикуем один раз (dirty=True со старта), дальше — по изменениям.
        self._dirty = True
        # Дросселирование логов: (тип|context) → ts последней записи в лог.
        self._last_log_ts: dict[str, float] = {}

        # Breaker процесса (Ф2 Task 2.2): считает ПОДРЯД идущие report_error —
        # когда серия достигает порога, процесс сам деградирует. Счётчик breaker
        # отдельный от монотонного errors: любой report_success/возврат в ok его
        # обнуляет. Callback'и (on_open→degraded, on_close→ok) зовутся ВНЕ lock
        # breaker'а, поэтому взятие self._lock внутри них безопасно.
        threshold = (
            _env_int(BREAKER_THRESHOLD_ENV, _BREAKER_DEFAULT_THRESHOLD)
            if breaker_threshold is None
            else int(breaker_threshold)
        )
        cooldown = (
            _env_float(BREAKER_COOLDOWN_ENV, _BREAKER_DEFAULT_COOLDOWN)
            if breaker_cooldown_sec is None
            else float(breaker_cooldown_sec)
        )
        self._breaker = CircuitBreaker(
            threshold=threshold,
            cooldown_sec=cooldown,
            clock=breaker_clock,
            on_open=self._on_breaker_open,
            on_close=self._on_breaker_close,
            name="process",
        )

    # --- свойства (для breaker/тестов) ---

    @property
    def log_only(self) -> bool:
        return self._log_only

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._errors

    @property
    def status(self) -> HealthStatus:
        with self._lock:
            return self._status

    @property
    def breaker(self) -> CircuitBreaker:
        """Breaker процесса (для produce-цикла / диагностики)."""
        return self._breaker

    @property
    def breaker_open(self) -> bool:
        """Разомкнут ли breaker процесса (серия отказов достигла порога)."""
        return self._breaker.is_open

    def breaker_snapshot(self) -> dict[str, Any]:
        """Снимок breaker для диагностики (health.status). Не часть контракта схемы."""
        return self._breaker.snapshot()

    # --- breaker callbacks (зовутся ВНЕ lock breaker'а) ---

    def _on_breaker_open(self, breaker: CircuitBreaker) -> None:
        """Серия отказов достигла порога → деградировать процесс.

        Fallback-деградация: НЕ затираем уже выставленную (более конкретную)
        причину — напр. от produce-breaker источника. Если процесс ещё ok —
        ставим общую причину «breaker open».
        """
        if self.status is HealthStatus.OK:
            self.degraded(f"breaker open: {breaker.consecutive} подряд ошибок")

    def _on_breaker_close(self, breaker: CircuitBreaker) -> None:
        """Восстановление после серии (успех) → вернуть процесс в ok."""
        self.ok()

    # --- мутации (зовут плагины через HealthReporter) ---

    def report_error(
        self,
        exc: BaseException,
        context: str | None = None,
        throttle: float = DEFAULT_THROTTLE,
    ) -> None:
        """Учесть ошибку: инкремент счётчика + запись last_error + дросселированный лог.

        Счётчик растёт всегда (честность для breaker). last_error/dirty обновляются
        только вне лог-only. Лог — не чаще, чем раз в ``throttle`` сек на пару
        (тип исключения, context).
        """
        etype = type(exc).__name__
        emsg = str(exc)[:_MAX_MESSAGE_LEN]
        ctx = str(context) if context else ""
        now = self._clock()
        key = f"{etype}|{ctx}"

        should_log = False
        with self._lock:
            self._errors += 1
            last = self._last_log_ts.get(key)
            if last is None or (now - last) >= float(throttle):
                self._last_log_ts[key] = now
                should_log = True
            if not self._log_only:
                self._last_error = {
                    LastErrorKey.TYPE: etype,
                    LastErrorKey.MESSAGE: emsg,
                    LastErrorKey.CONTEXT: ctx,
                    LastErrorKey.TS: now,
                }
                self._updated_at = now
                self._dirty = True

        if should_log:
            where = f" @ {ctx}" if ctx else ""
            self._safe_log(f"[health] {etype}{where}: {emsg}")

        # Breaker считает подряд-фейлы; вне self._lock (record_failure может позвать
        # on_open → degraded, который берёт self._lock). Инкремент — всегда (честность),
        # даже под лог-only; сам degrade под лог-only подавляется в set_status.
        self._breaker.record_failure()

    def report_success(self, context: str | None = None) -> None:
        """Учесть успешную операцию: обнулить серию breaker.

        Дёшево при штатной работе (breaker CLOSED → просто сброс счётчика). Если
        breaker был разомкнут — успех замыкает его (on_close → ok()). Зовётся
        produce-циклом источника на каждый удачный кадр (см. SourceProducer).
        ``context`` пока не используется в состоянии — принят для симметрии с
        report_error и будущей per-site диагностики.
        """
        self._breaker.record_success()

    def set_status(self, status: HealthStatus | str, reason: str | None = None) -> None:
        """Явно выставить статус (ok/degraded/failed) + причину. Идемпотентно."""
        st = status if isinstance(status, HealthStatus) else HealthStatus(str(status))
        rsn = str(reason) if reason is not None else None
        now = self._clock()

        changed = False
        with self._lock:
            if self._status != st or self._degraded_reason != rsn:
                changed = True
                self._status = st
                self._degraded_reason = rsn
                if not self._log_only:
                    self._updated_at = now
                    self._dirty = True

        # Возврат в ok — ручное восстановление: обнуляем серию breaker (без on_close,
        # чтобы не зациклиться с этим же путём). Вне self._lock — breaker берёт свой.
        if st is HealthStatus.OK:
            self._breaker.reset()

        if changed:
            suffix = f": {rsn}" if rsn else ""
            self._safe_log(f"[health] status → {st.value}{suffix}")

    def degraded(self, reason: str) -> None:
        self.set_status(HealthStatus.DEGRADED, reason)

    def failed(self, reason: str) -> None:
        self.set_status(HealthStatus.FAILED, reason)

    def ok(self, reason: str | None = None) -> None:
        """Восстановление: вернуть статус ok (сбрасывает degraded_reason)."""
        self.set_status(HealthStatus.OK, reason)

    # --- чтение/публикация ---

    def snapshot(self) -> dict[str, Any]:
        """Полный снимок здоровья (для health.status / тестов)."""
        with self._lock:
            return self._snapshot_locked()

    def take_dirty(self) -> dict[str, Any] | None:
        """Снять снапшот, если со времени прошлой публикации что-то менялось.

        Возвращает dict (и сбрасывает dirty) или None. Используется heartbeat'ом:
        публикуем только при изменениях — это и есть rate-limit на такт heartbeat.
        """
        with self._lock:
            if not self._dirty:
                return None
            self._dirty = False
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            HealthField.STATUS: self._status.value,
            HealthField.ERRORS: self._errors,
            HealthField.LAST_ERROR: dict(self._last_error) if self._last_error else None,
            HealthField.DEGRADED_REASON: self._degraded_reason,
            HealthField.UPDATED_AT: self._updated_at,
        }

    def _safe_log(self, msg: str) -> None:
        try:
            self._log(msg)
        except TypeError:
            # Логгеры процесса принимают module= kwarg — пробуем расширенную форму.
            try:
                self._log(msg, module="health")  # type: ignore[call-arg]
            except Exception:  # noqa: BLE001 — лог health не критичен
                pass
        except Exception:  # noqa: BLE001
            pass


class HealthReporter:
    """Фасад ``ctx.health`` — тонкая обёртка над процесс-общим :class:`HealthState`.

    Один HealthState на процесс (агрегат уровня процесса, путь
    ``processes.<name>.health.*``); reporter лишь подставляет дефолтный ``source``
    (имя плагина) как context, если сайт не передал свой.
    """

    def __init__(self, state: HealthState, source: str = "") -> None:
        self._state = state
        self._source = source or ""

    def report_error(
        self,
        exc: BaseException,
        context: str | None = None,
        throttle: float = DEFAULT_THROTTLE,
    ) -> None:
        ctx = context if context is not None else self._source
        self._state.report_error(exc, context=ctx, throttle=throttle)

    def report_success(self, context: str | None = None) -> None:
        """Успешная операция сайта — обнулить серию breaker (см. HealthState)."""
        self._state.report_success(context=context)

    def set_status(self, status: HealthStatus | str, reason: str | None = None) -> None:
        self._state.set_status(status, reason)

    def degraded(self, reason: str) -> None:
        self._state.degraded(reason)

    def failed(self, reason: str) -> None:
        self._state.failed(reason)

    def ok(self, reason: str | None = None) -> None:
        self._state.ok(reason)

    @property
    def error_count(self) -> int:
        return self._state.error_count

    @property
    def status(self) -> HealthStatus:
        return self._state.status

    @property
    def log_only(self) -> bool:
        return self._state.log_only

    @property
    def breaker_open(self) -> bool:
        """Разомкнут ли breaker процесса (для backoff produce-цикла)."""
        return self._state.breaker_open

    def breaker_snapshot(self) -> dict[str, Any]:
        return self._state.breaker_snapshot()


# ---------------------------------------------------------------------------
# Привязка к процессу + публикация через heartbeat
# ---------------------------------------------------------------------------


def _resolve_log(services: Any) -> Callable[[str], None] | None:
    """Найти подходящий log-callback у services (warning → error → info)."""
    for attr in ("log_warning", "_log_warning", "log_error", "_log_error", "log_info", "_log_info"):
        fn = getattr(services, attr, None)
        if callable(fn):
            return fn
    return None


def get_or_create_health_state(services: Any) -> HealthState:
    """Вернуть (создав при необходимости) единый HealthState процесса.

    HealthState живёт на объекте процесса как приватный атрибут ``_health_state``
    — тем же приёмом, что и ``_state_proxy``. И PluginContext (через ctx.health), и
    ProcessHeartbeat (публикация) достают ОДИН И ТОТ ЖЕ инстанс через services.

    Если services иммутабелен (мок/минимальный фейк) — setattr гасится, reporter
    всё равно работает, просто состояние не разделяется (для юнит-тестов ок).
    """
    existing = getattr(services, "_health_state", None)
    if isinstance(existing, HealthState):
        return existing
    hs = HealthState(log=_resolve_log(services))
    try:
        services._health_state = hs
    except Exception:  # noqa: BLE001 — services может быть иммутабельным
        pass
    return hs


def publish_health(state: HealthState | None, proxy: Any, process_name: str) -> bool:
    """Опубликовать грязный снапшот health в state-дерево (leaf-wise, через proxy.set).

    Зовётся из heartbeat-петли. Публикует только если ``take_dirty`` вернул снимок
    (rate-limit на такт heartbeat). Возвращает True, если что-то опубликовано.

    Leaf-wise (как телеметрия), а не одним merge — предсказуемые дельты
    ``state.changed`` на каждый лист и совместимость с тем, как дерево читают
    driver/GUI по конкретным путям.
    """
    if state is None or proxy is None or not process_name:
        return False
    snap = state.take_dirty()
    if snap is None:
        return False

    published = False
    for field in HEALTH_FIELDS:
        if field not in snap:
            continue
        try:
            proxy.set(health_path(process_name, field), snap[field])
            published = True
        except Exception:  # noqa: BLE001 — телеметрия/health не критичны для работы процесса
            pass
    return published
