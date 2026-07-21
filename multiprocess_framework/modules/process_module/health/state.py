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
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_FAIL_THRESHOLD,
    BreakerState,
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

#: Конфиг breaker через env (разумные дефолты в breaker.py) — порог подряд-ошибок…
BREAKER_THRESHOLD_ENV = "INSPECTOR_HEALTH_BREAKER_THRESHOLD"
#: …и окно тишины (сек) для шага восстановления.
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


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name, "").strip()
        return int(raw) if raw else default
    except (TypeError, ValueError):
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

    def set_status(self, status: "HealthStatus | str", reason: str | None = ...) -> None:
        """Явно выставить статус здоровья."""
        ...

    def degraded(self, reason: str) -> None:
        """Сокращение для ``set_status(DEGRADED, reason)``."""
        ...

    def record_success(self) -> None:
        """Сигнал успешной итерации: сброс подряд-счётчика breaker (Task 2.2)."""
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
        breaker: CircuitBreaker | None = None,
    ) -> None:
        """
        Args:
            log: callback логирования (обычно ``services.log_warning``); None → no-op.
            log_only: форсировать режим отката; None → читать из env ``LOG_ONLY_ENV``.
            clock: источник времени (инъекция для детерминизма в тестах).
            breaker: честный circuit breaker подряд-ошибок (Task 2.2); None →
                создать с дефолтами (env ``BREAKER_THRESHOLD_ENV``/``BREAKER_COOLDOWN_ENV``).
                Разделяет ``clock`` с HealthState — тесты двигают одно время.
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

        # Честный breaker: кормится КАЖДЫМ report_error (Task 2.2). Делит clock с
        # HealthState, чтобы тесты двигали единое время.
        self._breaker = (
            breaker
            if breaker is not None
            else CircuitBreaker(
                fail_threshold=_env_int(BREAKER_THRESHOLD_ENV, DEFAULT_FAIL_THRESHOLD),
                cooldown_sec=_env_float(BREAKER_COOLDOWN_ENV, DEFAULT_COOLDOWN_SEC),
                clock=clock,
            )
        )
        # Владеет ли breaker текущей деградацией: снимаем degraded по восстановлению
        # ТОЛЬКО если её выставил breaker (не затираем чужой явный degraded/failed).
        self._breaker_owns_degraded = False

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
    def breaker_state(self) -> str:
        """Состояние breaker (``closed``/``open``/``half_open``) — Task 2.2."""
        return self._breaker.state

    @property
    def breaker_open(self) -> bool:
        """True, пока breaker не восстановлен (loop-раннер по нему решает про backoff)."""
        return self._breaker.is_open

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

        # Честный breaker (Task 2.2): инкремент подряд-счётчика ВНЕ self._lock —
        # breaker держит собственный lock, а переход в degraded ниже снова берёт
        # self._lock, поэтому блокировки не вкладываем (нет цикла lock-order).
        transition = self._breaker.record_failure()
        if transition == BreakerState.OPEN:
            where = f" @ {ctx}" if ctx else ""
            reason = f"breaker open: {etype}{where} ×{self._breaker.threshold} подряд"
            self.set_status(HealthStatus.DEGRADED, reason)
            with self._lock:
                self._breaker_owns_degraded = True

    def record_success(self) -> None:
        """Сигнал успешной итерации loop-раннера (produce/process удались).

        Сбрасывает подряд-счётчик breaker и — при переходе в ``closed`` — снимает
        деградацию, если её владелец breaker. Сайты, умеющие только report_error,
        не зовут это: их breaker восстанавливается пассивно через :meth:`poll`.
        """
        if self._breaker.record_success() == BreakerState.CLOSED:
            self._mark_dirty()
            self._clear_breaker_degraded()

    def poll(self) -> None:
        """Пассивный шаг восстановления breaker (зовёт heartbeat каждый такт).

        Любой переход breaker меняет публикуемое поле ``health.breaker`` → поднимаем
        dirty; закрытие снимает breaker-owned деградацию.
        """
        transition = self._breaker.poll()
        if transition is None:
            return
        self._mark_dirty()
        if transition == BreakerState.CLOSED:
            self._clear_breaker_degraded()

    def _mark_dirty(self) -> None:
        with self._lock:
            if not self._log_only:
                self._dirty = True

    def _clear_breaker_degraded(self) -> None:
        """Снять деградацию, выставленную breaker'ом (не трогая чужой degraded/failed)."""
        with self._lock:
            owns = self._breaker_owns_degraded and self._status == HealthStatus.DEGRADED
            self._breaker_owns_degraded = False
        if owns:
            self.ok(None)

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

    def mark_dirty(self) -> None:
        """C-2: заново поднять dirty после провала публикации снятого снапшота.

        take_dirty() сбрасывает ``_dirty`` ДО того, как снапшот реально ушёл в
        state-дерево (``publish_health``); если ``proxy.set`` упал — снапшот
        потерян безвозвратно, дерево навсегда останется на последнем удачном
        значении. Публикатор зовёт этот метод при провале, чтобы следующий такт
        heartbeat забрал снапшот повторно (ретрай, а не молчаливая потеря).
        """
        with self._lock:
            self._dirty = True

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            HealthField.STATUS: self._status.value,
            HealthField.ERRORS: self._errors,
            HealthField.LAST_ERROR: dict(self._last_error) if self._last_error else None,
            HealthField.DEGRADED_REASON: self._degraded_reason,
            HealthField.UPDATED_AT: self._updated_at,
            # Task 2.2: чтение state breaker'а lock-free (безопасно под self._lock).
            HealthField.BREAKER: self._breaker.state,
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

    def set_status(self, status: HealthStatus | str, reason: str | None = None) -> None:
        self._state.set_status(status, reason)

    def degraded(self, reason: str) -> None:
        self._state.degraded(reason)

    def failed(self, reason: str) -> None:
        self._state.failed(reason)

    def ok(self, reason: str | None = None) -> None:
        self._state.ok(reason)

    def record_success(self) -> None:
        """Сигнал успешной итерации loop-раннеру (produce/process удались) — Task 2.2."""
        self._state.record_success()

    @property
    def breaker_open(self) -> bool:
        return self._state.breaker_open

    @property
    def breaker_state(self) -> str:
        return self._state.breaker_state

    @property
    def error_count(self) -> int:
        return self._state.error_count

    @property
    def status(self) -> HealthStatus:
        return self._state.status

    @property
    def log_only(self) -> bool:
        return self._state.log_only


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
    any_failed = False
    for field in HEALTH_FIELDS:
        if field not in snap:
            continue
        try:
            proxy.set(health_path(process_name, field), snap[field])
            published = True
        except Exception:  # noqa: BLE001 — телеметрия/health не критичны для работы процесса
            # C-2: молчим (health не должен ронять процесс публикацией), но снапшот
            # НЕ должен потеряться — take_dirty() уже сбросил _dirty=False, поэтому
            # без mark_dirty() ниже провалившийся снимок ушёл бы в никуда навсегда.
            any_failed = True

    if any_failed:
        state.mark_dirty()

    return published
