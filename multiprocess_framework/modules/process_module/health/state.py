# -*- coding: utf-8 -*-
"""HealthState — примитив наблюдаемости отказов процесса (Ф2 Task 2.1).

Роль: единый на процесс аккумулятор здоровья, который наполняют плагины через
``ctx.health`` (фасад :class:`HealthReporter`), а публикует в state-дерево
heartbeat процесса (тот же self-publish канал, что и телеметрия fps/latency —
см. ``ProcessHeartbeat._publish_telemetry_to_tree``). Новый IPC-канал НЕ вводится.

Ключевые свойства:
- **rate-limit.** Публикация — по такту heartbeat (раз в ``heartbeat_interval``),
  так что «шторм» одинаковых ошибок не спамит state-дерево естественным образом.
  Отдельно окном ``throttle`` дросселируется ГОЛОС (строка журнала) на пару
  (тип, context) — через общий механизм ``logger_module/core/windowed_voice.py``.
- **факт не дросселируется НИКОГДА** (Task 1.3a). Счётчик ``errors``, запись в
  плоскость ошибок и подряд-счётчик breaker (последний — по ревью Task 1.3a,
  он стоял ПОСЛЕ голоса и терялся вместе с ним) идут на КАЖДЫЙ
  ``report_error``: у каждого вхождения своя
  трасса, свой поток и свои поля, и схлопывать их окном значит терять именно то,
  ради чего инцидент записывают. Своё окно (``DEFAULT_THROTTLE``/``_last_log_ts``)
  у HealthState снято — до Task 1.3a оно держало заодно и запись плоскости.
- **откат в лог-only.** Переключатель ``MULTIPROCESS_HEALTH_LOG_ONLY`` (env) или
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

from ...channel_routing_module.observability.store_tap import ORIGIN_ERROR_MANAGER, ORIGIN_FIELD
from ...logger_module.core.windowed_voice import WindowedVoices, compose_voice_text
from ...logger_module.utils import safe_exception_message
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

#: Переключатель отката: report_error/set_status только логируют, state не трогают.
#: Пара «каноничное имя, легаси-алиас» (D4) — читаются оба, каноничное приоритетнее.
LOG_ONLY_ENV = "MULTIPROCESS_HEALTH_LOG_ONLY"
LEGACY_LOG_ONLY_ENV = "INSPECTOR_HEALTH_LOG_ONLY"

#: Конфиг breaker через env (разумные дефолты в breaker.py) — порог подряд-ошибок…
BREAKER_THRESHOLD_ENV = "MULTIPROCESS_HEALTH_BREAKER_THRESHOLD"
LEGACY_BREAKER_THRESHOLD_ENV = "INSPECTOR_HEALTH_BREAKER_THRESHOLD"
#: …и окно тишины (сек) для шага восстановления.
BREAKER_COOLDOWN_ENV = "MULTIPROCESS_HEALTH_BREAKER_COOLDOWN"
LEGACY_BREAKER_COOLDOWN_ENV = "INSPECTOR_HEALTH_BREAKER_COOLDOWN"


def _env_first(*keys: str) -> str:
    """Первое непустое значение из пары «каноничная ручка, легаси-алиас»."""
    for key in keys:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return ""


#: Защита от чужого ``__str__``. Task 1.3b: хранилище ОДНО — второй держатель
#: механизма (``ObservableMixin.report_error``) берёт ту же функцию оттуда же.
#: Имя ``_safe_message`` оставлено псевдонимом: на него ссылаются докстринг
#: :meth:`HealthState.report_error`, ADR-PM-045 и STATUS модуля.
_safe_message = safe_exception_message


class HealthSelfTestError(RuntimeError):
    """Синтетическая ошибка для диагностического впрыска (``health.report``).

    Отдельный тип, чтобы live-проверка канала наблюдаемости отличала self-test от
    настоящих ошибок по ``last_error.type``.
    """


def _env_log_only() -> bool:
    return _env_first(LOG_ONLY_ENV, LEGACY_LOG_ONLY_ENV).lower() in ("1", "true", "yes", "on")


def _env_float(*names_then_default) -> float:
    """Первое непустое из пары ручек → float; иначе дефолт (последний аргумент)."""
    *names, default = names_then_default
    try:
        raw = _env_first(*names)
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _env_int(*names_then_default) -> int:
    """Первое непустое из пары ручек → int; иначе дефолт (последний аргумент)."""
    *names, default = names_then_default
    try:
        raw = _env_first(*names)
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


@runtime_checkable
class IHealthReporter(Protocol):
    """Контракт фасада ``ctx.health``, который видят плагины.

    Плагин знает только этот интерфейс (ADR-120: плагин — через PluginContext).
    Реализация — :class:`HealthReporter` поверх процесс-общего :class:`HealthState`.
    """

    def report_error(
        self, exc: BaseException, context: str | None = ..., throttle: float | None = ..., **fields: object
    ) -> None:
        """Зарегистрировать проглоченную/обработанную ошибку (инкремент + last_error).

        ``**fields`` едут в контекст записи плоскости ошибок (Ф1.1 / C3): адрес
        потока и трасса у инцидента процессного хука. Без них запись доезжала бы
        обезличенной — «RuntimeError где-то в процессе», — а именно адрес и
        трасса отвечают на первый вопрос разбирающего.
        """
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
        track: Callable[..., None] | None = None,
        log_only: bool | None = None,
        clock: Callable[[], float] = time.time,
        breaker: CircuitBreaker | None = None,
        voices: WindowedVoices | None = None,
    ) -> None:
        """
        Args:
            log: callback логирования (обычно ``services.log_warning``); None → no-op.
            track: callback ПЛОСКОСТИ ОШИБОК (``services.track_error``); None → no-op.
                Заведён C2: до него ни одна дорога плагина в эту плоскость не вела
                (доказано прогоном ``probe_c2_error_route``), а ``report_error``
                называлась инцидентом и уходила строкой в журнал.
            log_only: форсировать режим отката; None → читать из env ``LOG_ONLY_ENV``.
            clock: источник времени (инъекция для детерминизма в тестах).
            breaker: честный circuit breaker подряд-ошибок (Task 2.2); None →
                создать с дефолтами (env ``BREAKER_THRESHOLD_ENV``/``BREAKER_COOLDOWN_ENV``).
                Разделяет ``clock`` с HealthState — тесты двигают одно время.
            voices: держатель окон ГОЛОСА (Task 1.3a); None → свой собственный.
                Свой, а не процессный ``process_voices()``: ключ вида
                ``"RuntimeError|grab_frame"`` у двух HealthState разных процессов
                в одном интерпретаторе (тесты, ProcessManager) — два разных
                события, и общий держатель заглушил бы второе первым. Параметр
                нужен, чтобы дать держателю свои часы (см. ``WindowedVoices``).
        """
        self._lock = threading.Lock()
        self._clock = clock
        self._log: Callable[[str], None] = log if callable(log) else (lambda _msg: None)
        self._track: Callable[..., None] | None = track if callable(track) else None
        self._log_only = _env_log_only() if log_only is None else bool(log_only)

        self._status: HealthStatus = HealthStatus.OK
        self._errors = 0
        self._last_error: dict[str, Any] | None = None
        self._degraded_reason: str | None = None
        self._updated_at = 0.0
        # Начальный ok публикуем один раз (dirty=True со старта), дальше — по изменениям.
        self._dirty = True
        # Окно ГОЛОСА (Task 1.3a) — общий механизм, а не своя карта. Факт
        # (счётчик + запись в плоскость ошибок) окном не управляется вовсе.
        self._voices: WindowedVoices = voices if voices is not None else WindowedVoices()

        # Честный breaker: кормится КАЖДЫМ report_error (Task 2.2). Делит clock с
        # HealthState, чтобы тесты двигали единое время.
        self._breaker = (
            breaker
            if breaker is not None
            else CircuitBreaker(
                fail_threshold=_env_int(BREAKER_THRESHOLD_ENV, LEGACY_BREAKER_THRESHOLD_ENV, DEFAULT_FAIL_THRESHOLD),
                cooldown_sec=_env_float(BREAKER_COOLDOWN_ENV, LEGACY_BREAKER_COOLDOWN_ENV, DEFAULT_COOLDOWN_SEC),
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
        throttle: float | None = None,
        **fields: Any,
    ) -> None:
        """Учесть отказ: счётчик + last_error + запись в плоскость ошибок + голос по окну.

        **Факт учитывается ВСЕГДА** (Task 1.3a): счётчик, ``last_error``, запись
        в плоскость ошибок (``_safe_track``) и подряд-счётчик breaker идут на
        КАЖДОЕ вхождение — со своей трассой, своим потоком и своими полями. Окно
        управляет только ГОЛОСОМ, строкой ``[health] …`` в журнале; следующий
        голос называет, сколько вхождений было подавлено с прошлой записи.

        «ВСЕГДА» здесь названо с границей, а не как заклинание: оно верно, пока
        сам вызов сюда доходит. Ревью Task 1.3a нашло ровно одну дыру в этом
        слове — ``str(exc)`` на входе, — и она закрыта (:func:`_safe_message`);
        оставшийся вход, которому здесь верят на слово, — ``str(context)``:
        сайт, передавший объектом контекст с бросающим ``__str__``, уронит
        ``report_error`` до всего учёта. Не закрыто сознательно: обрезать
        контекст тем же потолком значило бы менять форму ключа окна ради
        случая, которого ни один живой сайт не производит (все зовут со
        строкой). Появится такой сайт — закрывать той же функцией.

        До Task 1.3a ``_safe_track`` стоял ВНУТРИ ветки голоса, и повтор одного
        отказа в окне 5 с не оставлял в плоскости ошибок ничего, кроме числа в
        ``errors``: замер — 5 вхождений из пяти потоков, 1 выжившая запись,
        четыре потеряны вместе с трассами. Комментарий «дроссель общий с логом
        намеренно: у плоскости ошибок своего нет» снят вместе с обходом, который
        он объяснял: своё окно у голоса появилось в Task 1.4
        (``logger_module/core/windowed_voice.py``).

        ``throttle`` — окно ГОЛОСА, сек; ``None`` → политика процесса
        (``observability.voices.default_window_sec``). Ключ окна — пара
        (тип исключения, ``context``).

        **Порядок здесь — часть контракта, а не оформление.** Всё, что задача
        называет ФАКТОМ, стоит ДО решения о голосе, потому что решение принимает
        чужой механизм (держатель окон): упади он — факт уже учтён целиком.
        Фактов три, и раньше третий из них стоял ПОСЛЕ голоса: счётчик +
        ``last_error``, запись в плоскость ошибок (``_safe_track``) и
        **подряд-счётчик breaker**. Ревью Task 1.3a воспроизвело цену этой
        расстановки: держатель, бросающий на ``take()``, оставлял ``errors=5`` и
        5 записей плоскости при ``breaker=closed`` и ``status=ok`` — статус не
        деградировал НИКОГДА, хотя докстринг ``PluginContext.health`` и
        ADR-PM-045 оба перечисляют breaker среди того, что делает ``report_error``.
        Бросок при этом наружу не глушится: у вызывающего (процессные хуки)
        перехват уже стоит, и там он становится посчитанной потерей доставки, а
        не вторым исключением поверх первого.

        ``**fields`` (Ф1.1 / C3) уезжают в КОНТЕКСТ ЗАПИСИ плоскости ошибок
        (``_safe_track`` → ``track_error`` → ``extra``), а не в health-снапшот:
        health — агрегат процесса, и класть в него произвольные поля каждого
        инцидента значило бы публиковать в state-дерево неограниченную форму.
        """
        etype = type(exc).__name__
        emsg = _safe_message(exc)
        ctx = str(context) if context else ""
        where = f" @ {ctx}" if ctx else ""
        now = self._clock()

        with self._lock:
            self._errors += 1
            if not self._log_only:
                self._last_error = {
                    LastErrorKey.TYPE: etype,
                    LastErrorKey.MESSAGE: emsg,
                    LastErrorKey.CONTEXT: ctx,
                    LastErrorKey.TS: now,
                }
                self._updated_at = now
                self._dirty = True

        # C2: инцидент едет в ПЛОСКОСТЬ ОШИБОК. Прежде «report_error» было
        # названием без обязательства: прогон `probe_c2_error_route` показал, что
        # запись уходила в `system.log` через `services.log_warning`, а
        # `errors.log`/`critical.log`/`warnings.log` не видели от плагинов НИЧЕГО.
        # Task 1.3a: БЕЗУСЛОВНО — окно голоса к учёту факта отношения не имеет.
        recorded = self._safe_track(exc, ctx, fields)

        # Честный breaker (Task 2.2): инкремент подряд-счётчика ВНЕ self._lock —
        # breaker держит собственный lock, а переход в degraded ниже снова берёт
        # self._lock, поэтому блокировки не вкладываем (нет цикла lock-order).
        # Ревью Task 1.3a: блок стоит ВЫШЕ решения о голосе — см. «Порядок здесь»
        # в докстринге. Ниже он был третьим фактом, который терял бросок ЧУЖОГО
        # держателя окон.
        transition = self._breaker.record_failure()
        if transition == BreakerState.OPEN:
            reason = f"breaker open: {etype}{where} ×{self._breaker.threshold} подряд"
            self.set_status(HealthStatus.DEGRADED, reason)
            with self._lock:
                self._breaker_owns_degraded = True

        voice_key = f"{etype}|{ctx}"
        voiced, suppressed = self._voices.take(voice_key, throttle)
        if voiced:
            # Маркер дедупа ПУТЕЙ — утверждение о ЧУЖОЙ строке: «факт этого
            # инцидента уже уехал в плоскость ошибок, и стор его получит оттуда».
            # Утверждение составное, и держат его ДВЕ правки ревью Task 1.3a,
            # каждая — свою половину:
            #   «факт уехал»  → признак ``recorded`` здесь (дороги нет / приёмник
            #                   бросил → маркера нет);
            #   «стор получит» → проводка (``wire_observability_store``: владелец
            #                   маркированных строк ровно один и вычисляется по
            #                   тому, кто реально встал).
            # Раскладку самой находки — процесс без ErrorManager, замер контроль
            # 1 строка / опыт 0 — чинит ВТОРАЯ: ``recorded`` там всё равно
            # ``True``, потому что приватный ``_track_error`` глотает молча
            # (см. потолок в докстринге ``_safe_track``). Не сокращать до одной.
            marker = {ORIGIN_FIELD: ORIGIN_ERROR_MANAGER} if recorded else {}
            delivered = self._safe_log(
                compose_voice_text(f"[health] {etype}{where}: {emsg}", suppressed),
                **marker,
            )
            if not delivered:
                # Task 4.13: колбэк голоса не принял вызов — слот, съеденный
                # решением, возвращается вместе с долгом. Иначе первый же отказ
                # приёмника делал бы health немым на всё окно, и это молчание
                # было бы неотличимо от штатного подавления.
                self._voices.release(voice_key, suppressed)

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

    def _safe_track(self, exc: BaseException, context: str, fields: dict[str, Any] | None = None) -> bool:
        """Отдать инцидент плоскости ошибок; её отсутствие — законное состояние.

        Падать здесь запрещено: `report_error` зовут из веток «мы поймали
        исключение», и отказ учёта не имеет права стать вторым исключением
        поверх первого.

        Ф1.1 (C3): ``fields`` — произвольные поля записи (``thread``,
        ``traceback``, ``hook``). При ПУСТЫХ полях форма вызова прежняя,
        байт-в-байт, включая ``None`` на пустом контексте: у ``track_error``
        пустой словарь и ``None`` разбираются одинаково, но соседние тесты
        сверяют именно вызов, и менять его без нужды значит красить их зря.

        Returns:
            Ушёл ли факт в плоскость ошибок. ``False`` — дороги нет
            (``track`` не резолвится) или приёмник бросил. Ревью Task 1.3a:
            по этому признаку и только по нему голос несёт маркер дедупа путей.
            Отдавать маркер при ``False`` значит утверждать чужую строку стора,
            которой нет, — а логгер-tap на такое утверждение пропускает голос,
            и инцидент исчезает целиком.

            **Потолок назван прямо, и он больше, чем кажется.** ``True`` здесь —
            «дорога нашлась и вызов не бросил», а НЕ «запись сделана». У процесса
            без ErrorManager ``_resolve_track`` находит приватный
            ``ObservableMixin._track_error`` — он есть у ЛЮБОГО процесса и молча
            ничего не делает, когда слот ``error`` пуст (замер: резолвится
            ``_track_error``, публичного ``track_error`` нет, вызов возвращает
            ``None``). Значит на раскладке находки Major 1 этот метод отвечает
            ``True``, и один он её НЕ чинит: чинит проводка
            (:func:`~..managers.observability_wiring.wire_observability_store`
            отдаёт владение маркированными строками тому tap'у, который реально
            встал). Здешний признак закрывает две другие дыры — дороги нет вовсе
            (``track=None``: log-only HealthState, суб-плагины) и приёмник бросил.
        """
        if self._track is None:
            return False
        if fields:
            payload: dict[str, Any] | None = {"context": context, **fields}
        else:
            payload = {"context": context} if context else None
        try:
            self._track(exc, payload)
        except Exception:  # noqa: BLE001 — учёт инцидента не роняет обработчик инцидента
            return False
        return True

    def _safe_log(self, msg: str, **extra: Any) -> bool:
        """Сказать вслух. ``extra`` — поля записи (напр. маркер ``origin``).

        Returns:
            Доехало ли (Task 4.13): ``True``, если колбэк принял вызов и
            вернулся, ``False`` — если он бросил или ни одна форма вызова ему не
            подошла. Ответ нужен окну голоса: слот, съеденный решением, обязан
            вернуться, когда строки не случилось.

        Приёмник — утиный колбэк: у процесса это ``log_warning(msg, **kwargs)``,
        а в тестах бывает ``lambda msg: None``. Поэтому форма вызова подбирается
        сверху вниз: с полями → без полей → с ``module=``. Расширенная форма
        стояла здесь и раньше по той же причине (``TypeError`` от колбэка,
        не принимающего kwargs), ``extra`` лишь добавила первую ступень.
        """
        attempts: list[dict[str, Any]] = [extra] if extra else []
        attempts.append({})
        attempts.append({"module": "health"})
        for kwargs in attempts:
            try:
                answer = self._log(msg, **kwargs)  # type: ignore[call-arg]
            except TypeError:
                continue
            except Exception:  # noqa: BLE001 — лог health не критичен
                return False
            # Ответ колбэка ЧИТАЕТСЯ, а не выбрасывается (Task 4.13, добор
            # ревью). Прежняя редакция возвращала True, как только вызов не
            # бросил, — и на боевой проводке этого было достаточно, чтобы дверь
            # онемела: `log_warning` миксина отказ проглатывает и не бросает.
            #
            # `is False`, а не `not answer`, по тому же доводу, что в
            # `report_error`: слот возвращает только тот, кто ЗНАЕТ, что не
            # доставил. Колбэк из тестов (`lambda msg: None`) сведений не даёт,
            # и трактовать его молчание как потерю значило бы снять дросселя
            # вовсе.
            return answer is not False
        # Ни одна форма вызова не подошла: колбэк отверг TypeError'ом все три.
        # Запись потеряна — молчать об этом окну нельзя.
        return False


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
        throttle: float | None = None,
        **fields: Any,
    ) -> None:
        """``**fields`` (Ф1.1 / C3) проходят насквозь в контекст записи плоскости ошибок.

        ``throttle`` — окно ГОЛОСА (Task 1.3a); ``None`` → политика процесса.
        Запись в плоскость ошибок им не управляется: факт идёт всегда.
        """
        ctx = context if context is not None else self._source
        self._state.report_error(exc, context=ctx, throttle=throttle, **fields)

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


def _resolve_track(services: Any) -> Callable[..., None] | None:
    """Найти дорогу в ПЛОСКОСТЬ ОШИБОК (C2).

    Тем же приёмом, что :func:`_resolve_log`, и по той же причине: у процесса
    публичный ``track_error``, у менеджеров — приватный ``_track_error``
    (``ObservableMixin``), а у минимального дубля в тесте может не быть ни
    одного — тогда плоскости просто нет, и это законное состояние.
    """
    for attr in ("track_error", "_track_error"):
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
    hs = HealthState(log=_resolve_log(services), track=_resolve_track(services))
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
