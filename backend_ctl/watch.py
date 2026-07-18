# -*- coding: utf-8 -*-
"""watch.py — WatchController: GUI-эквивалентный watch-профиль как отдельный класс.

Стейт-машина приёмного профиля GUI (state.subscribe + observability.tail + авто-
переподписка после авто-рестарта). Раньше жила ~15 полями и 7 методами внутри
BackendDriver — теперь ВЛАДЕЕТ своим состоянием и инъектируется в driver
(`self._watch = WatchController(self)`), а driver-обёртки лишь делегируют (C.1,
headline распила: «watch-машина не живёт полями чужого класса»).

Контур: слушатель (`_on_event`) в reader-потоке НЕ зовёт request() сам (дедлок —
ответ дренирует тот же reader), а кладёт имя процесса в очередь намерений; отдельный
applier-поток (`_resub_loop`) применяет переподписку на безопасном потоке. Команды
идут через back-ref на driver (`self._d`): subscribe/observability_tail/state_subscribe/
_discover_processes. close() driver'а делегирует гашение applier-потока в :meth:`stop`.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Dict, Optional

# GUI-эквивалентный набор wildcard'ов state-подписки (Task 2.2): зеркало
# multiprocess_prototype/frontend/process.py — ровно то, на что подписан GUI.
# Прототип может передать свой набор в watch_like_gui(patterns=...).
# F7 (framework-first): ``devices.**``/``calibration.**`` — app-домены прототипа,
# захардкоженные здесь как удобный дефолт. Пост-codemod (переезд в tooling/) набор
# инжектируется app-слоем (прототип передаёт свои паттерны), а модульный дефолт
# сузится до generic ``processes.**``/``system.**``. Сейчас поведение НЕ меняем.
GUI_DEFAULT_PATTERNS: tuple[str, ...] = (
    "processes.**",
    "system.**",
    "devices.**",
    "calibration.**",
)


def _drain_queue(q: "queue.Queue") -> None:
    """Ненадолго осушить очередь без блокировки (F3: leftover-намерения на unwatch).

    Снимает все немедленно доступные элементы; ``task_done`` сохраняет баланс для
    ``queue.join()``. Sentinel/имена процессов, оставшиеся после снятия watch, не
    должны применяться — applier их и так пропустит по guard'у, но пустая очередь
    исключает лишний виток.
    """
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return
        else:
            try:
                q.task_done()
            except ValueError:  # task_done без соответствующего get — баланс уже нулевой
                pass


class WatchController:
    """Владелец состояния watch-профиля; команды идут через back-ref на driver."""

    def __init__(self, driver: Any) -> None:
        self._d = driver
        # Слушатель живёт в reader-потоке и НЕ смеет звать request() сам (дедлок —
        # см. start): он лишь кладёт имя процесса в очередь намерений, а отдельный
        # applier-поток применяет их на безопасном потоке. Всё под _watch_lock.
        self._watch_lock = threading.Lock()
        self._watch_active = False
        self._watch_subscribed: set[str] = set()  # процессы с активным obs-хвостом (дедуп)
        self._watch_listener: Optional[Any] = None
        self._resub_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._resub_thread: Optional[threading.Thread] = None
        self._watch_resub_timeout: Optional[float] = None
        self._watch_resub_errors = 0  # счётчик неудачных авто-переподписок (диагностика)
        self._watch_patterns: tuple[str, ...] = ()  # реально включённые watch-паттерны (для unwatch)
        self._watch_tail_level = "WARNING"  # объявленный порог логов (для watch-манифеста, F2)

    def start(
        self,
        *,
        patterns: tuple[str, ...] = GUI_DEFAULT_PATTERNS,
        tail_level: str = "WARNING",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Включить ВЕСЬ приёмный профиль GUI одной командой (state + observability-хвост).

        Одна команда даёт агенту ровно то, что получает GUI:

          - ``state.subscribe`` на каждый wildcard из ``patterns`` (по умолчанию
            :data:`GUI_DEFAULT_PATTERNS` — зеркало ``frontend/process.py``);
          - ``observability.tail`` на КАЖДЫЙ процесс из state-топологии
            (``_discover_processes``) — live логи+ошибки+статистика;
          - **авто-переподписку** observability-хвоста после авто-рестарта процесса
            (порт логики ``ObservabilityTailActivator``, см. ниже).

        Всё приходит в ЕДИНУЮ очередь ``events``; записи наблюдаемости раскладывает по
        плоскостям ``observability_records``. Кадры/SHM через сокет НЕ гоняются (Dict at
        Boundary) — вне контракта watch.

        Сводка best-effort (как у ``debug_session``): недоступный источник — честная
        запись об ошибке, остальные работают. Повторный вызов при активном watch сначала
        делает :meth:`stop_profile` (чистый рестарт профиля).

        **Авто-переподписка и thread-safety (главный риск задачи, п.5 ТЗ).**
        Триггер переподписки — громкое supervisor-событие
        ``processes.<name>.supervisor.event = "recovered"`` (публикуется по возврату
        heartbeat после авто-рестарта, ADR-PMM-015): авто-рестарт поднимает НОВУЮ
        инкарнацию процесса, её форвардер не подписан, а дедуп по имени переподписку
        блокировал бы. Слушатель ловит это в событийном канале и снимает дедуп.

        Слушатель исполняется в **reader-потоке** driver'а (колбэк ``subscribe``). Из
        reader-потока НЕЛЬЗЯ звать ``observability_tail`` напрямую: она уходит в
        ``request()`` и блокируется в ``pending.event.wait()`` — но ответ на этот самый
        запрос дренирует ТОТ ЖЕ reader-поток (``_read_loop`` → ``_dispatch``), который
        сейчас заблокирован. Итог — request таймаутит и на время таймаута встаёт вся
        доставка событий. Поэтому слушатель лишь КЛАДЁТ имя процесса в очередь намерений
        (:attr:`_resub_queue`), а отдельный applier-поток (:meth:`_resub_loop`) применяет
        переподписку на безопасном потоке. Идемпотентность subscribe сохраняется (дедуп).

        Args:
            patterns: набор state-wildcard'ов (по умолчанию GUI-набор).
            tail_level: декларируемый порог логов. **Замечание:** observability.tail
                форвардит ВСЕ плоскости и severity без фильтра на проводе, поэтому
                уровень применяется на стороне клиента —
                ``observability_records(kind="error")`` и т.п. Возвращается в сводке
                как объявленное намерение (сервер его не срезает).
            timeout: таймаут каждой под-команды (и авто-переподписок).

        Returns:
            Сводка: ``{"state": {pattern: res}, "observability": {proc: res},
            "processes": [...], "tail_level": ..., "success": bool}``.
        """
        if self._watch_active:
            self.stop_profile(timeout=timeout)

        summary: Dict[str, Any] = {
            "state": {},
            "observability": {},
            "processes": [],
            "tail_level": tail_level,
        }

        # F4: активируем watch-контур и регистрируем слушатель+applier ПЕРВЫМИ, ДО
        # первичных подписок. Раньше слушатель вешался ПОСЛЕДНИМ (после N×obs_tail до
        # 5с каждый) → supervisor-``recovered``, прилетевший в это окно, терялся и
        # процесс оставался без хвоста. Дедуп ``_watch_subscribed`` оптимистичен и
        # потокобезопасен (под ``_watch_lock``), поэтому ранний старт безопасен:
        # applier переподпишет идемпотентно, если listener опередит основной цикл.
        with self._watch_lock:
            self._watch_active = True
            self._watch_resub_timeout = timeout
            self._watch_subscribed = set()
            self._watch_patterns = tuple(patterns)  # запомнить фактический набор для unwatch
            self._watch_tail_level = tail_level
            self._resub_queue = queue.Queue()  # свежая очередь на поколение watch (F3: изоляция)
            q = self._resub_queue

        # Applier-поток намерений переподписки (безопасный поток для request()).
        self._resub_thread = threading.Thread(target=self._resub_loop, args=(q,), name="backend-ctl-resub", daemon=True)
        self._resub_thread.start()
        # Слушатель авто-переподписки на событийном канале (исполняется в reader-потоке).
        self._watch_listener = self._d.subscribe(self._on_event)

        for pattern in patterns:
            summary["state"][pattern] = self._d.state_subscribe(pattern, timeout=timeout)

        procs = self._d._discover_processes(timeout=timeout)
        summary["processes"] = list(procs)

        for proc in procs:
            # F7: не тейлим собственный процесс driver'а (self._d._sender) — тейлить себя
            # бессмысленно (ObservabilityTailActivator у GUI тоже себя не подписывает).
            # gui-процесс НЕ исключаем: driver может его тейлить, но у него нет пилот-hub'а,
            # поэтому obs_tail(gui) честно вернёт success=False (reason: нет hub'а) — это
            # ОЖИДАЕМО, не ошибка; в сводку кладём как есть, без шумного «fail».
            if proc == self._d._sender:
                continue
            res = self._d.observability_tail(proc, timeout=timeout)
            summary["observability"][proc] = res
            # Дедуп: пометить процесс подписанным независимо от исхода (over-record —
            # безопаснее; recovered-триггер всё равно снимет пометку и переподпишет).
            with self._watch_lock:
                self._watch_subscribed.add(proc)

        # Успех: хотя бы одна state-подписка и хотя бы один obs-хвост не провалились
        # (best-effort — часть процессов может не поддерживать observability-hub).
        state_ok = any((r or {}).get("success") is not False for r in summary["state"].values())
        summary["success"] = bool(state_ok)
        return summary

    def stop_profile(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Выключить GUI-профиль: снять obs-хвосты + слушатель + applier-поток.

        Снимает ``observability.tail`` со всех процессов, на которые watch подписался,
        отключает слушатель авто-переподписки и останавливает applier-поток. Durable-
        намерения (``state.subscribe`` по watch-паттернам и obs-хвосты) вычищаются из
        реестра, чтобы будущий реконнект НЕ воскресил снятый профиль. Серверную
        state-подписку снимаем через ``state_unsubscribe`` (durable-намерение; серверная
        подписка освобождается закрытием соединения, как в ``debug_stop``).

        F3 (гонка in-flight resub): applier может держать незавершённый
        ``observability_tail`` дольше join'а. Само-исцеление — в :meth:`_resub_loop`:
        по завершении resub'а applier перепроверяет ``_watch_active`` и, если watch уже
        снят, ОТМЕНЯЕТ свою переподписку (untail) — форвардер/намерение не воскресают
        независимо от тайминга join'а. Свежая очередь на поколение (:meth:`start`)
        изолирует стоп-sentinel от будущего watch (инвариант «один applier»).

        F2 (б, реконнект без восстановления контура): даже при ``was_active=False``
        всё равно чистим watch-намерения (obs-tail целиком + state.subscribe по
        GUI-паттернам fallback), чтобы «полу-durable» watch не воскрес молча.
        """
        with self._watch_lock:
            was_active = self._watch_active
            self._watch_active = False
            procs = sorted(self._watch_subscribed)
            self._watch_subscribed = set()
            listener = self._watch_listener
            self._watch_listener = None
            thread = self._resub_thread
            self._resub_thread = None
            # Снять ровно те паттерны, что включал start (не хардкод — кастомный набор
            # иначе утёк бы в реестре). Fallback на GUI-набор — только если контур был
            # потерян при реконнекте (was_active=False, паттерны не восстановлены).
            patterns = (
                self._watch_patterns if self._watch_patterns else (GUI_DEFAULT_PATTERNS if not was_active else ())
            )
            self._watch_patterns = ()
            resub_q = self._resub_queue

        if listener is not None:
            self._d.unsubscribe(listener)

        # Остановить applier-поток: sentinel в его (текущего поколения) очередь + join.
        if thread is not None:
            resub_q.put(None)
            thread.join(timeout=2.0)
        # Дренировать хвост очереди этого поколения (leftover-намерения не должны
        # применяться после снятия watch — applier их и так пропустит по guard'у).
        _drain_queue(resub_q)

        summary: Dict[str, Any] = {"observability": {}, "was_active": was_active}
        for proc in procs:
            summary["observability"][proc] = self._d.observability_untail(proc, timeout=timeout)

        # Снять durable state.subscribe watch-паттернов через явную обёртку.
        for pattern in patterns:
            self._d.state_unsubscribe(pattern, timeout=timeout)

        # F2 (б): подчистить ЛЮБЫЕ висящие obs-tail-намерения (watch-owned), если контур
        # был потерян и procs пуст — иначе полу-durable watch воскреснет при реконнекте.
        if not was_active and not procs:
            self._d._subscriptions.remove_by_command("observability.tail.subscribe")

        summary["success"] = True
        return summary

    def stop(self) -> None:
        """Погасить applier-поток на close() driver'а (реконнект зовёт close(), не unwatch).

        Снимает ``_watch_active`` под локом (layer-1 guard не даёт применителю дёргать
        сеть на закрывающемся сокете), забирает поток+очередь, кладёт sentinel и join'ит.
        Вызывается из ``BackendDriver.close()`` ПОСЛЕ пробуждения pending'ов — in-flight
        applier-request к этому моменту уже разбужен, поэтому join не виснет.
        """
        with self._watch_lock:
            self._watch_active = False
            thread = self._resub_thread
            self._resub_thread = None
            resub_q = self._resub_queue
        if thread is not None:
            resub_q.put(None)
            thread.join(timeout=1.0)

    @property
    def resub_errors(self) -> int:
        """Сколько авто-переподписок хвоста завершились ошибкой (диагностика, Task 2.2)."""
        return self._watch_resub_errors

    def default_tail_level(self) -> Optional[str]:
        """Объявленный tail_level активного watch (или None) — дефолт severity-фильтра (F5)."""
        with self._watch_lock:
            return self._watch_tail_level if self._watch_active else None

    def manifest(self) -> Dict[str, Any]:
        """Снимок активного watch-профиля для переживания реконнекта (F2).

        MCP-сервер сохраняет манифест ДО сброса driver'а и после реконнекта передаёт
        его новому driver'у (:meth:`resume`), чтобы восстановить watch-КОНТУР (слушатель
        авто-переподписки + applier), а не только durable-намерения. Раньше реконнект
        replay'ил намерения, но контур не поднимался → авто-resub был мёртв, а unwatch —
        no-op (профиль воскресал каждый реконнект).
        """
        with self._watch_lock:
            if not self._watch_active:
                return {"active": False}
            return {
                "active": True,
                "patterns": list(self._watch_patterns),
                "tail_level": self._watch_tail_level,
                "processes": sorted(self._watch_subscribed),
            }

    def resume(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Восстановить watch-контур из манифеста ПОСЛЕ реконнекта (F2, парный к :meth:`manifest`).

        Поднимает ТОЛЬКО клиентский контур (слушатель + applier + watch-состояние) БЕЗ
        повторных подписок: серверные ``state.subscribe``/``observability.tail`` уже
        восстановлены replay'ем durable-намерений (``replay_subscriptions``) на новом
        соединении. Двойной подписки нет; ``observability.tail`` идемпотентна на сервере.

        Нет активного watch в манифесте → no-op. Идемпотентно: если контур уже поднят
        (``_watch_active``) — сначала :meth:`stop_profile`, чтобы не плодить второй applier.
        """
        if not manifest or not manifest.get("active"):
            return {"resumed": False}
        if self._watch_active:
            self.stop_profile()

        patterns = tuple(manifest.get("patterns") or ())
        procs = list(manifest.get("processes") or [])
        with self._watch_lock:
            self._watch_active = True
            self._watch_patterns = patterns
            self._watch_tail_level = str(manifest.get("tail_level") or "WARNING")
            self._watch_subscribed = set(procs)
            self._watch_resub_timeout = None
            self._resub_queue = queue.Queue()
            q = self._resub_queue

        self._resub_thread = threading.Thread(target=self._resub_loop, args=(q,), name="backend-ctl-resub", daemon=True)
        self._resub_thread.start()
        self._watch_listener = self._d.subscribe(self._on_event)
        return {"resumed": True, "processes": procs, "patterns": list(patterns)}

    def _on_event(self, msg: Dict[str, Any]) -> None:
        """Слушатель событийного канала: ловит supervisor-recovered → намерение переподписки.

        Исполняется в reader-потоке — ТОЛЬКО кладёт имя процесса в очередь намерений
        (никаких блокирующих ``request()`` — см. :meth:`start`). Разбирает
        ``state.changed``-дельты: процесс, чей ``processes.<name>.supervisor.event``
        стал ``recovered``, переподписываем заново (новая инкарнация); процесс, ещё
        не подписанный (свежее появление в топологии), подписываем впервые — паритет
        с ``ObservabilityTailActivator.on_state_delta``.
        """
        if not isinstance(msg, dict) or msg.get("command") != "state.changed":
            return
        data = msg.get("data")
        if not isinstance(data, dict):
            return
        deltas = data.get("deltas")
        if not isinstance(deltas, list):
            return
        for delta in deltas:
            if not isinstance(delta, dict):
                continue
            path = delta.get("path") or ""
            if not path.startswith("processes."):
                continue
            parts = path.split(".")
            proc = parts[1] if len(parts) >= 2 else ""
            if not proc or proc == self._d._sender:
                continue  # F7: себя не тейлим (симметрично стартовому циклу start)
            recovered = path.endswith(".supervisor.event") and delta.get("new_value") == "recovered"
            with self._watch_lock:
                if not self._watch_active:
                    return
                if recovered:
                    # Новая инкарнация: снять дедуп, чтобы переподписать заново.
                    self._watch_subscribed.discard(proc)
                if proc in self._watch_subscribed:
                    continue
                # Пометить оптимистично (как ObservabilityTailActivator) и поставить
                # намерение — applier применит observability_tail на безопасном потоке.
                self._watch_subscribed.add(proc)
            self._resub_queue.put(proc)

    def _resub_loop(self, q: "queue.Queue[Optional[str]]") -> None:
        """Applier-поток намерений переподписки (безопасный поток для ``request()``).

        Дренирует очередь ``q`` СВОЕГО поколения (свежая на каждый watch — изоляция
        стоп-sentinel'ов, инвариант «один applier»): на каждое имя процесса делает
        ``observability_tail`` (тут блокировка в ``request()`` штатна — reader-поток
        свободен дренировать ответ). ``None`` — sentinel остановки (кладёт stop_profile/
        stop). ``task_done`` на каждый элемент — чтобы тесты могли детерминированно
        дождаться обработки через ``_resub_queue.join()``.

        F3 (гонка со snятием watch), два слоя:
          1. Пред-guard: перед resub'ом проверяем ``_watch_active``; watch уже снят →
             пропускаем (не переподписываем на снятом профиле).
          2. Само-исцеление: после resub'а перепроверяем ``_watch_active``; если watch
             сняли, ПОКА наш ``observability_tail`` был in-flight (stop_profile не дождался
             join'а) — немедленно ``observability_untail`` откатывает нашу переподписку
             (форвардер + durable-намерение), чтобы профиль не воскрес.
        """
        while True:
            proc = q.get()
            try:
                if proc is None:
                    return
                # Слой 1: watch снят до старта resub'а — не применяем.
                with self._watch_lock:
                    active = self._watch_active
                if not active:
                    continue
                try:
                    res = self._d.observability_tail(proc, timeout=self._watch_resub_timeout)
                    if isinstance(res, dict) and res.get("success") is False:
                        self._watch_resub_errors += 1
                except Exception:  # noqa: BLE001 — авто-переподписка best-effort, поток не роняем
                    self._watch_resub_errors += 1
                # Слой 2: watch сняли, пока resub был in-flight → откатить (само-исцеление).
                with self._watch_lock:
                    still_active = self._watch_active
                if not still_active:
                    try:
                        self._d.observability_untail(proc, timeout=self._watch_resub_timeout)
                    except Exception:  # noqa: BLE001 — откат best-effort
                        pass
            finally:
                q.task_done()


__all__ = ["WatchController", "GUI_DEFAULT_PATTERNS"]
