# -*- coding: utf-8 -*-
"""Брокер подписки на наблюдаемость (Task 5.11).

Подписка на живой хвост — это форвардер на **каждом** процессе
(``observability.tail.subscribe``, per-subscriber). Процесс не знает о соседях,
поэтому «подписать всех и переподписывать по мере жизни системы» каждый
потребитель до 5.11 строил заново: GUI — циклом по дельтам ``processes.*`` с
триггером ``supervisor.event="recovered"``, backend_ctl — durable-реестром
намерений и applier-потоком (где уже ловили дедлок автоподписки из reader'а).
Обе копии неполны по одной причине: **сигнал «поднялась свежая инкарнация» есть
только у оркестратора**.

Брокер держит реестр намерений («этот адрес хочет всё») и разворачивает их в
команды подписки. **Записи он не видит**: каждый процесс пушит их адресно
подписчику, оркестратор в потоке записей не участвует — он брокер, не транзит
(закрытое решение п. 9 плана). Отсюда же следует, что здесь нет ни буфера, ни
переупаковки, ни счётчиков записей — только адреса и команды.

Форма взята у ``_replay_telemetry_runtime_delta``: PM хранит рантайм-намерение и
доигрывает его пересозданным детям (fan-out на switch, адресно на рестарт).
Второй конструкции для той же задачи не заводится.

**Почему дедлок-путь не воспроизводится.** Обе отправки — fire-and-forget
(``comm.broadcast`` / ``comm.send_to_process``): брокер не ждёт ответа ребёнка ни
в одном хендлере. Это структурное свойство, а не договорённость «не звать из
такого-то потока» — именно договорённость и не удержалась у драйвера.

Модуль намеренно ничего не знает о ``ProcessManagerProcess``: снаружи приходят
три callable (рассылка, адресная отправка, свой хвост), поэтому механизм
проверяется в изоляции.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

#: Команды процесса, в которые разворачивается намерение подписчика.
SUBSCRIBE_COMMAND = "observability.tail.subscribe"
UNSUBSCRIBE_COMMAND = "observability.tail.unsubscribe"

#: Причины раздачи (в лог и в readback) — по ним в разборе видно, ЧТО именно
#: потребовало переподписки: команда, старт инкарнации или снятие подписчика.
REASON_COMMAND = "command"
REASON_INSTANCE = "instance.started"


class ObservabilitySubscriptionBroker:
    """Реестр намерений «хочу всю наблюдаемость» + их разворачивание в процессы."""

    def __init__(
        self,
        *,
        broadcast: Callable[[str, dict], int],
        send_to: Callable[[str, str, dict], bool],
        subscribe_self: Optional[Callable[[str], dict]] = None,
        unsubscribe_self: Optional[Callable[[str], dict]] = None,
        log_info: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Args:
            broadcast: ``(command, data) -> охват`` — fan-out всем живым детям.
            send_to: ``(target, command, data) -> доставлено`` — адресно одному.
            subscribe_self: подписать хвост САМОГО оркестратора (он такой же
                источник записей; исключи его — и «всё» у брокера разошлось бы
                со «всем» у оператора). Нет hub'а → процесс ответит честным
                отказом, отдельной ветки для этого не нужно.
            unsubscribe_self: симметричное снятие своего хвоста.
            log_info / log_error: журнал охвата и сбоев раздачи.
        """
        self._broadcast = broadcast
        self._send_to = send_to
        self._subscribe_self = subscribe_self
        self._unsubscribe_self = unsubscribe_self
        self._log_info = log_info
        self._log_error = log_error
        # Реестр намерений: адрес подписчика → запись о намерении. Под локом,
        # потому что пишут его хендлеры команд, а читает раздача со шва старта
        # инкарнации (её зовут и из монитора через process.restart).
        self._lock = threading.RLock()
        self._subscribers: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Намерения
    # ------------------------------------------------------------------

    def subscribe_all(self, subscriber: str, *, origin: str = REASON_COMMAND) -> dict:
        """Записать намерение и развернуть его прямо сейчас: один broadcast + свой хвост.

        Идемпотентна по подписчику: повторный вызов не плодит намерение, но
        раздачу повторяет — на стороне процесса подписка тоже идемпотентна, а
        повтор это единственный способ подобрать процесс, до которого прошлая
        раздача не доехала.
        """
        name = str(subscriber or "").strip()
        if not name:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        now = time.time()
        with self._lock:
            entry = self._subscribers.get(name)
            if entry is None:
                entry = {"subscriber": name, "since": now, "origin": str(origin), "replays": 0}
                self._subscribers[name] = entry
        result = self._fan_out(name, SUBSCRIBE_COMMAND, reason=REASON_COMMAND)
        return {"success": True, "subscriber": name, **result}

    def unsubscribe_all(self, subscriber: str) -> dict:
        """Снять намерение и разослать снятие. ``subscriber`` обязателен.

        Пустой адрес НЕ означает «снять всех»: у процесса такая форма есть
        (teardown), но здесь она снесла бы хвост соседнего потребителя — ровно
        тот дефект, из-за которого подписка на процессе стала per-subscriber.
        """
        name = str(subscriber or "").strip()
        if not name:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        with self._lock:
            held = self._subscribers.pop(name, None) is not None
        result = self._fan_out(name, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)
        # `held=False` — не ошибка, но и не тишина: «снял то, чего не держал»
        # читается совсем иначе, чем «снял».
        return {"success": True, "subscriber": name, "held": held, **result}

    def forget_subscriber(self, name: str) -> bool:
        """Забыть намерение подписчика-ПРОЦЕССА, снятого с топологии.

        Один из двух сигналов о смерти подписчика, которые у оркестратора есть ПО
        ФАКТУ: процесс снят с топологии. Второй — :meth:`forget_session` (сокет
        внешнего подписчика закрыт). Гадать по имени («похоже на процесс») здесь
        по-прежнему нельзя — это класс «правдоподобное ≠ проверенное».
        """
        key = str(name or "").strip()
        if not key:
            return False
        with self._lock:
            dropped = self._subscribers.pop(key, None) is not None
        if dropped:
            # B-5-1 (вторая половина): снятое намерение обязано снять и форвардеры
            # на детях — так же, как это делает unsubscribe_all. Иначе на каждом
            # ребёнке остаётся форвардер-сирота, вечно пушащий записи мёртвому
            # адресу (relay-шум на хаб). Реактивное снятие (процесс ушёл с
            # топологии) молчать о себе детям не имеет права.
            self._fan_out(key, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)
            if self._log_info:
                self._log_info(f"[observability] брокер: намерение '{key}' снято — процесс-подписчик убран с топологии")
        return dropped

    def forget_session(self, session_id: str) -> list:
        """Забыть намерения подписчиков, чей адрес принадлежит закрытой сессии (5.11-R1).

        Внешний подписчик (драйвер) адресуется как ``"<sender>.<session>"``, а
        session уникален на соединение. Значит закрытие сокета — сигнал о смерти
        этого адреса ПО ФАКТУ, симметричный снятию процесса с топологии.

        Почему без него нельзя было оставлять. Реконнект MCP-сессии берёт НОВЫЙ
        session, поэтому старый адрес не знает уже никто — явный ``unsubscribe_all``
        новой сессии снять его не может в принципе. Хуже: шов инкарнации честно
        доигрывает намерения мёртвых подписчиков на КАЖДЫЙ свежий процесс, то есть
        мёртвая подписка не затухает, а воскресает. Живой замер ревью: три цикла
        «connect → watch → close» оставляли три намерения по 8 процессов каждое.

        Returns:
            Снятые адреса (для лога и тестов).
        """
        sid = str(session_id or "").strip()
        if not sid:
            return []
        suffix = f".{sid}"
        with self._lock:
            doomed = [name for name in self._subscribers if name.endswith(suffix)]
            for name in doomed:
                self._subscribers.pop(name, None)
        # Снять форвардеры мёртвого адреса на детях (симметрично forget_subscriber
        # и unsubscribe_all). Рассылка ВНЕ лока: forget_session зовут из read-потока
        # канала, а fan-out — fire-and-forget (broadcast не ждёт ответа ребёнка),
        # поэтому канал не блокируется.
        for name in doomed:
            self._fan_out(name, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)
        if doomed and self._log_info:
            self._log_info(f"[observability] брокер: намерения {doomed} сняты — соединение сессии '{sid}' закрыто")
        return doomed

    # ------------------------------------------------------------------
    # Раздача
    # ------------------------------------------------------------------

    def replay(self, *, target: Optional[str] = None, reason: str = REASON_INSTANCE) -> dict:
        """Доиграть ВСЕ намерения: адресно (``target``) или fan-out'ом.

        Зовётся со шва «поднялась свежая инкарнация» — единственного места, через
        которое проходят все пути старта. Прежний триггер потребителей
        (``supervisor.event="recovered"``) видел только цикл give-up→recover и
        поэтому промахивался мимо ручного рестарта и hot-swap'а.
        """
        with self._lock:
            names = sorted(self._subscribers)
        if not names:
            return {"subscribers": [], "reached": 0}
        reached = 0
        for name in names:
            res = self._fan_out(name, SUBSCRIBE_COMMAND, target=target, reason=reason)
            reached += int(res.get("reached", 0))
        if self._log_info:
            self._log_info(
                f"[observability] брокер: подписки доиграны ({reason}, target={target!r}): "
                f"подписчики={names}, охват={reached}"
            )
        return {"subscribers": names, "reached": reached}

    def _fan_out(
        self,
        subscriber: str,
        command: str,
        *,
        target: Optional[str] = None,
        reason: str = REASON_COMMAND,
    ) -> dict:
        """Одна отправка: адресная (``target``) либо fan-out. Свой хвост — только на fan-out.

        Исключение транспорта не имеет права ронять ни команду подписчика, ни
        старт процесса: раздача — обслуживание, а не lifecycle. Но и молчать
        нельзя, поэтому провал попадает и в лог, и в ответ (``error``).
        """
        payload = {"subscriber": subscriber}
        out: Dict[str, Any] = {"reached": 0}
        try:
            if target is not None:
                out["reached"] = 1 if self._send_to(target, command, payload) else 0
                out["target"] = target
            else:
                out["reached"] = int(self._broadcast(command, payload))
        except Exception as exc:  # noqa: BLE001 — см. докстринг
            out["error"] = str(exc)
            if self._log_error:
                self._log_error(f"[observability] брокер: раздача '{command}' для '{subscriber}' не удалась: {exc}")
        if target is None:
            own = self._own_tail(subscriber, command)
            if own is not None:
                out["orchestrator"] = own
        with self._lock:
            entry = self._subscribers.get(subscriber)
            if entry is not None:
                entry["replays"] = int(entry.get("replays", 0)) + 1
                entry["last_reason"] = str(reason)
                entry["last_at"] = time.time()
                entry["last_reached"] = int(out["reached"])
                entry["last_target"] = target
        return out

    def _own_tail(self, subscriber: str, command: str) -> Optional[dict]:
        """Свой (оркестраторов) хвост — тем же вызовом, что и у любого процесса."""
        fn = self._subscribe_self if command == SUBSCRIBE_COMMAND else self._unsubscribe_self
        if not callable(fn):
            return None
        try:
            return dict(fn(subscriber) or {})
        except Exception as exc:  # noqa: BLE001 — свой хвост не важнее чужих
            if self._log_error:
                self._log_error(f"[observability] брокер: свой хвост для '{subscriber}' не поставлен: {exc}")
            return {"success": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Readback
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Состояние брокера для ``introspect.observability`` оркестратора.

        Механизм, о котором нельзя спросить, через час неотличим от сломанного:
        «хвоста нет» — это либо снятое намерение, либо не доехавшая раздача, и
        различают их ровно охват и причина последней раздачи.
        """
        with self._lock:
            entries: List[dict] = [dict(v) for _k, v in sorted(self._subscribers.items())]
        return {"subscribers": entries, "count": len(entries)}

    def subscriber_names(self) -> List[str]:
        """Адреса действующих намерений (для тестов и логов)."""
        with self._lock:
            return sorted(self._subscribers)
