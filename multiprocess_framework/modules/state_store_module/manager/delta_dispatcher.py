"""delta_dispatcher.py — Рассылка дельт подписчикам через IPC.

DeltaDispatcher получает список дельт, матчит их по подпискам,
группирует по subscriber (с дедупликацией!) и отправляет
каждому подписчику одно IPC-сообщение state.changed.

Режим коалесцирования (``FW_STATE_COALESCE``, default OFF) — гашение gui-шторма:
вместо одного IPC-сообщения на КАЖДУЮ мутацию дельты буферизуются per-subscriber
и уходят одним конвертом на тик daemon-flusher'а. Матчинг подписок происходит
В МОМЕНТ мутации (в ``dispatch``), а не при flush — иначе подписчик, появившийся
между мутацией и тиком, получил бы чужие буферизованные дельты. OFF → путь
бит-в-бит как раньше (немедленная отправка в вызывающем потоке).
"""

from __future__ import annotations

import threading
from typing import Any

from ...config_module.feature_flags import resolve
from ..core.delta import Delta
from ..core.subscription_manager import SubscriptionManager
from ..interfaces import IRouter

#: Период тика daemon-flusher'а (сек). В диапазоне плана 100–150 мс: достаточно
#: редко, чтобы схлопнуть burst мутаций в один конверт, но незаметно для GUI.
_DEFAULT_FLUSH_INTERVAL_SEC = 0.12

#: Порог немедленного flush подписчика (защита от burst): как только в его буфере
#: накопилось столько дельт, он флашится сразу, не дожидаясь тика.
_DEFAULT_BUFFER_CAP = 200


class DeltaDispatcher:
    """Рассылка дельт подписчикам через IPC.

    Batch-режим: собирает дельты из Transaction, отправляет одним сообщением.
    Дедупликация по subscriber: если процесс подписан на cameras.0.* и cameras.**,
    он получает каждую дельту ОДИН раз.
    """

    def __init__(
        self,
        subscription_mgr: SubscriptionManager,
        router: IRouter | None = None,
        sender_name: str = "StateStore",
        logger: Any = None,
        coalesce: bool | None = None,
        flush_interval_sec: float = _DEFAULT_FLUSH_INTERVAL_SEC,
        buffer_cap: int = _DEFAULT_BUFFER_CAP,
        state_queue: bool | None = None,
    ) -> None:
        """
        Args:
            subscription_mgr: менеджер подписок для матчинга дельт.
            router: реализация IRouter для отправки IPC-сообщений (None для тестов).
            sender_name: имя отправителя в IPC-сообщениях.
            logger: ObservableMixin-совместимый объект с методами _log_*.
            coalesce: явный override флага ``FW_STATE_COALESCE`` (ctor > env >
                default). None → значение флага из env/default. Разрешается ОДИН
                раз здесь (не на hot-path).
            flush_interval_sec: период тика daemon-flusher'а (только при ON).
            buffer_cap: порог немедленного flush подписчика (защита от burst).
            state_queue: явный override флага ``FW_STATE_QUEUE`` (ctor > env >
                default). None → значение флага из env/default. Определяет
                ``queue_type`` конверта state.changed: ON → ``"state"`` (drop_oldest),
                OFF → ``"system"`` (как раньше). Разрешается ОДИН раз здесь.
        """
        self._subs = subscription_mgr
        self._router = router
        self._sender = sender_name
        self._log = logger

        # --- Очередь класса "state" (FW_STATE_QUEUE) ---
        # queue_type конверта разрешается единожды в ctor: ON → state.changed едет
        # в {proc}_state (drop_oldest, QoS _STATE) вместо never-drop system-очереди.
        self._state_queue_type = "state" if resolve("FW_STATE_QUEUE", explicit=state_queue) else "system"

        # --- Коалесцирование (FW_STATE_COALESCE) ---
        # Флаг разрешается единожды в ctor: hot-path (dispatch) читает готовый bool.
        self._coalesce = resolve("FW_STATE_COALESCE", explicit=coalesce)
        self._flush_interval_sec = flush_interval_sec
        self._buffer_cap = buffer_cap
        # Буфер сматченных дельт: subscriber -> список дельт (порядок revision
        # сохраняется). Доступ только под _buffer_lock.
        self._buffer: dict[str, list[Delta]] = {}
        self._buffer_lock = threading.Lock()
        # Daemon-flusher: создаётся ТОЛЬКО при ON (start_flusher), OFF → None.
        self._flusher: threading.Thread | None = None
        self._stop_event = threading.Event()
        # _wake — досрочное пробуждение flusher'а (cap-flush / shutdown). Все
        # _send_state_changed в ON-режиме уходят ИЗ ОДНОГО потока (flusher): это
        # даёт тотальный порядок конвертов per-subscriber. cap НЕ шлёт в потоке-
        # мутаторе (иначе pop-под-локом + send-вне-лока в ≥2 потоках-мутаторах
        # переупорядочивал бы конверты, и приёмник глушил бы «устаревший» пакет
        # [1..cap] после обогнавшего его [cap+1] — бесшумная потеря), а лишь будит
        # flusher, чтобы тот флашнул немедленно.
        self._wake = threading.Event()

    def dispatch(self, deltas: list[Delta]) -> dict[str, int]:
        """Сгруппировать дельты по подписчику, отправить state.changed.

        Логика:
        1. Для каждой delta -> subs.match(delta) -> list[Subscription]
        2. Группировка: {subscriber: list[Delta]} с дедупликацией
           (каждая delta у subscriber встречается не более одного раза)
        3. Для каждого subscriber -> отправить одно IPC-сообщение state.changed

        Args:
            deltas: список дельт для рассылки.

        Returns:
            {subscriber: количество_дельт} — статистика рассылки.
        """
        if not deltas:
            return {}

        # Матчинг подписок и группировка per-subscriber — ВСЕГДА в момент мутации
        # (и в OFF, и в ON). Это ключевой инвариант коалесцирования: подписчик,
        # появившийся между мутацией и flush, не должен получить чужие
        # буферизованные дельты, поэтому match происходит здесь, а не при flush.
        subscriber_deltas = self._match_and_group(deltas)

        if not self._coalesce:
            # OFF: путь бит-в-бит — немедленная отправка в вызывающем потоке.
            stats: dict[str, int] = {}
            for subscriber, sub_deltas in subscriber_deltas.items():
                stats[subscriber] = len(sub_deltas)
                self._send_state_changed(subscriber, sub_deltas)
            return stats

        # ON: буферизация (отправка отложена до тика flusher'а или cap-flush).
        return self._buffer_deltas(subscriber_deltas)

    def _match_and_group(self, deltas: list[Delta]) -> dict[str, list[Delta]]:
        """Сматчить дельты по подпискам и сгруппировать per-subscriber с дедупом.

        Дедупликация по subscriber: если процесс подписан на пересекающиеся
        паттерны (``cameras.0.*`` и ``cameras.**``), каждая дельта попадает к
        нему ровно один раз. Порядок дельт сохраняется (важно для монотонности
        revision у получателя).

        Args:
            deltas: список дельт для рассылки.

        Returns:
            {subscriber: список уникальных дельт в исходном порядке}.
        """
        subscriber_delta_indices: dict[str, set] = {}
        subscriber_deltas: dict[str, list[Delta]] = {}

        for idx, delta in enumerate(deltas):
            matched_subs = self._subs.match(delta)
            for sub in matched_subs:
                name = sub.subscriber
                # Дедупликация: если эта delta (по индексу) уже добавлена — пропускаем
                if name not in subscriber_delta_indices:
                    subscriber_delta_indices[name] = set()
                    subscriber_deltas[name] = []
                if idx not in subscriber_delta_indices[name]:
                    subscriber_delta_indices[name].add(idx)
                    subscriber_deltas[name].append(delta)

        return subscriber_deltas

    def dispatch_single(self, delta: Delta) -> dict[str, int]:
        """Обёртка для одной дельты.

        Args:
            delta: единственная дельта для рассылки.

        Returns:
            {subscriber: количество_дельт} — статистика рассылки.
        """
        return self.dispatch([delta])

    # -------------------------------------------------------------------
    # Коалесцирование (FW_STATE_COALESCE)
    # -------------------------------------------------------------------

    @property
    def coalescing_enabled(self) -> bool:
        """True, если активен режим коалесцирования (флаг разрешён в ctor)."""
        return self._coalesce

    def _buffer_deltas(self, subscriber_deltas: dict[str, list[Delta]]) -> dict[str, int]:
        """Добавить сматченные дельты в буфер per-subscriber (ON-режим).

        Дельты уже сматчены и сгруппированы (``_match_and_group``). Здесь только
        конкатенация в буфер под локом с сохранением порядка. Дедуп keep-last
        ЗАПРЕЩЁН (рвёт непрерывность revision → resync-шторм у клиента) — только
        накопление. После добавления проверяется cap: если буфер подписчика достиг
        порога, flusher БУДИТСЯ (``_wake``) для немедленного тика — но сама отправка
        выполняется ТОЛЬКО в потоке flusher'а (``_flush_once``), а не здесь. Это
        критично: dispatch зовётся из ≥2 потоков-мутаторов PM, и отправка из потока-
        мутатора нарушила бы тотальный порядок конвертов per-subscriber (см. ctor
        ``_wake``). cap здесь — «флашни как можно скорее», а не «флашни прямо тут».

        Args:
            subscriber_deltas: {subscriber: список дельт} из ``_match_and_group``.

        Returns:
            {subscriber: сколько дельт добавлено этим вызовом} — статистика,
            совместимая по форме с OFF-путём.
        """
        stats: dict[str, int] = {}
        cap_reached = False
        with self._buffer_lock:
            for subscriber, sub_deltas in subscriber_deltas.items():
                buf = self._buffer.get(subscriber)
                if buf is None:
                    buf = []
                    self._buffer[subscriber] = buf
                buf.extend(sub_deltas)
                stats[subscriber] = len(sub_deltas)
                if len(buf) >= self._buffer_cap:
                    cap_reached = True

        # cap: разбудить flusher — он сделает _flush_once немедленно (единственный
        # отправитель). НЕ шлём в этом (мутаторском) потоке.
        if cap_reached:
            self._wake.set()

        return stats

    def _flush_once(self) -> int:
        """Один тик flush: swap всего буфера под локом, отправка вне лока.

        Тестируемая единица (дёргается тестами напрямую вместо ожидания
        реального таймера). Каждому подписчику — один конверт ``state.changed``
        со всеми накопленными дельтами (min/max revision считает
        ``_send_state_changed``).

        Returns:
            Число подписчиков, которым ушёл конверт на этом тике.
        """
        with self._buffer_lock:
            local, self._buffer = self._buffer, {}
        sent = 0
        for subscriber, deltas in local.items():
            if deltas:
                self._send_state_changed(subscriber, deltas)
                sent += 1
        return sent

    def _flusher_loop(self) -> None:
        """Тело daemon-flusher'а — ЕДИНСТВЕННЫЙ отправитель конвертов в ON-режиме.

        Каждую итерацию ждёт либо тик ``_flush_interval_sec``, либо досрочное
        пробуждение ``_wake`` (cap-flush / shutdown). ``_wake.wait`` возвращает
        True при set() (разбудили), False по таймауту (регулярный тик) — в обоих
        случаях делаем flush. Останов проверяется отдельным ``_stop_event`` до и
        после ожидания: при shutdown wake+stop выставляются вместе, поток выходит
        не досылая (финальный дренаж делает ``stop_flusher`` уже после join).
        Исключения тика не роняют поток (``_send_state_changed`` глотает ошибки
        отправки; здесь — страховочный барьер).
        """
        while not self._stop_event.is_set():
            self._wake.wait(self._flush_interval_sec)
            self._wake.clear()
            if self._stop_event.is_set():
                break
            try:
                self._flush_once()
            except Exception as exc:  # nosec B110 — тик не должен ронять поток
                if self._log is not None:
                    self._log._log_error(f"Ошибка flush-тика коалесцирования: {exc}")

    def start_flusher(self) -> None:
        """Запустить daemon-flusher (только при ON; иначе no-op).

        Вызывается из ``StateStoreManager.initialize()``. При OFF поток не
        создаётся вовсе. Идемпотентно: повторный вызов при живом потоке —
        no-op.
        """
        if not self._coalesce:
            return
        if self._flusher is not None and self._flusher.is_alive():
            return
        self._stop_event.clear()
        self._flusher = threading.Thread(
            target=self._flusher_loop,
            name="StateCoalesceFlusher",
            daemon=True,
        )
        self._flusher.start()

    def stop_flusher(self, timeout: float = 2.0) -> None:
        """Остановить flusher с гарантией доставки буфера (финальный flush).

        Вызывается из ``StateStoreManager.shutdown()``. Порядок: сигнал останова
        → пробуждение flusher'а (чтобы не спал до конца интервала) → join потока
        (с таймаутом) → финальный ``_flush_once`` (дренаж всего, что осталось в
        буфере на момент останова). Финальный flush безопасен: поток уже
        остановлен join'ом — конкурентного отправителя нет, тотальный порядок не
        нарушается. Выполняется всегда — даже если поток не создавался (OFF: буфер
        пуст, flush — no-op), — что делает метод безопасным при любом режиме.

        Args:
            timeout: максимум ожидания join потока (сек).
        """
        if self._flusher is not None:
            self._stop_event.set()
            self._wake.set()  # разбудить flusher, чтобы не ждал конца интервала
            self._flusher.join(timeout=timeout)
            self._flusher = None
        # Финальный дренаж буфера — гарантия доставки перед остановкой (поток мёртв).
        self._flush_once()

    def _send_state_changed(self, subscriber: str, deltas: list[Delta]) -> None:
        """Отправить state.changed сообщение подписчику.

        При router=None — только логирование (для тестов).

        Args:
            subscriber: имя процесса-подписчика.
            deltas: список дельт для отправки.
        """
        # revision конверта (Ф4.9, ADR-SS-014) — максимальная revision среди
        # дельт этого пакета, т.е. "дерево не старше этой revision, насколько
        # известно этому пакету". Аддитивное поле: старые получатели (без
        # watch-from-revision) его игнорируют, обратная совместимость сохранена.
        #
        # first_revision (Ф4.9-фикс, HIGH-1, ревью 2026-07-11) — МИНИМАЛЬНАЯ
        # revision среди дельт пакета. Одной мутации (set/delete) соответствует
        # одна дельта — first_revision == revision. Но merge() инкрементирует
        # revision НА КАЖДЫЙ изменившийся лист (см. TreeStore._merge_recursive),
        # поэтому пакет из merge на N≥2 листьев несётревизии
        # [last+1 .. last+N] ОДНИМ конвертом. Раньше клиент сравнивал только
        # max(revision) с last+1 — пакет из 2+ листьев (envelope=last+2)
        # ложно распознавался как разрыв (пропущенный пакет), хотя на деле все
        # промежуточные revision содержатся В ЭТОМ ЖЕ пакете. first_revision
        # позволяет StateProxy проверить непрерывность ПО ВСЕМУ диапазону
        # пакета, а не только по его верхней границе.
        revisions = [d.revision for d in deltas]
        first_revision = min(revisions) if revisions else 0
        envelope_revision = max(revisions) if revisions else 0

        message = {
            "type": "event",
            "sender": self._sender,
            "targets": [subscriber],
            # queue_type: доставка в {subscriber}_<qtype>, который опрашивает штатный
            # message_processor подписчика — event_dispatcher синхронно вызовет handler
            # state.changed при опросе. См. U1-fallback в RouterManager._deliver_by_targets
            # (доставка по targets через queue_registry).
            # OFF → "system" (never-drop, как раньше). ON (FW_STATE_QUEUE) → "state"
            # (drop_oldest): burst state.set не топит never-drop system-почту команд;
            # переполнение {proc}_state → data_evicted + resync клиента по разрыву revision.
            "queue_type": self._state_queue_type,
            "command": "state.changed",
            "data": {
                "deltas": [d.to_dict() for d in deltas],
                "revision": envelope_revision,
                "first_revision": first_revision,
            },
        }

        if self._router is not None:
            try:
                self._router.send_async(message, priority="normal")
            except Exception as exc:
                if self._log is not None:
                    self._log._log_error(f"Ошибка отправки state.changed подписчику '{subscriber}': {exc}")
        else:
            if self._log is not None:
                self._log._log_debug(
                    f"Рассылка state.changed для '{subscriber}': {len(deltas)} дельт (router=None, пропуск)"
                )
