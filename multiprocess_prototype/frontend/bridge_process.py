# -*- coding: utf-8 -*-
"""Мост кадров: третье воплощение процесса ``gui`` (gui-service Task 1.3).

``gui`` — процесс топологии, у которого три воплощения, подменяемых overlay'ем:

    headless : ``HeadlessGuiProcess`` — принимает data-трафик и выбрасывает
    мост     : :class:`BridgeGuiProcess` — принимает, выбрасывает и сообщает подписчикам,
               в каком слоте SHM лежит кадр (overlay ``presentation_bridge.yaml``)
    с Qt     : ``frontend.process.GuiProcess`` — принимает и рисует

Мост пикселей не читает: подписчик (Пульт, ``RemoteFrameSource``) на той же машине сам
открывает слот по имени из дескриптора. Протокол (команды, push, ключи дескриптора) —
модуль ``frontend_module.bridge.remote_frame_source``; здесь только хост.

Без подписчиков мост ведёт себя ровно как headless: дескрипторы не строятся,
``send_async`` не зовётся.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.frontend_module.bridge.remote_frame_source import (
    FRAMES_PUSH,
    FRAMES_STATS,
    FRAMES_SUBSCRIBE,
    FRAMES_UNSUBSCRIBE,
    build_frame_descriptor,
)
from multiprocess_prototype.frontend.headless_process import HeadlessGuiProcess


def _merge_args(data: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Аргументы команды: data-словарь (generic command-путь) + kwargs (как у ui.tap)."""
    args = dict(data) if isinstance(data, dict) else {}
    args.update(kwargs or {})
    return args


class FrameBridge:
    """Состояние и логика моста без процесса вокруг (тестируется на фейковом роутере).

    Потоки: команды ``frames.*`` приходят на потоке ``message_processor``,
    :meth:`on_drained` — на потоке ``data_drain``; состояние
    ``{адрес: {"senders": set | None, "sent": int}}`` — под одним lock.
    """

    def __init__(
        self,
        router: Any,
        name: str,
        *,
        seqlock: bool,
        owner_incarnation: bool,
        loan_protocol: bool,
    ) -> None:
        """Pre:  ``router`` — объект с ``send_async(message, priority="normal")``;
              ``name`` — имя процесса-хоста (поле ``sender`` push'ей); флаги —
              значения ``FW_SHM_SEQLOCK`` / ``FW_SHM_OWNER_INCARNATION`` /
              ``FW_SHM_LOAN_PROTOCOL`` этого процесса.
        Post: подписчиков нет; ``bseq`` = 0; ``sent_total`` = 0; ``errors`` = 0;
              ни одного вызова ``router``.
        """
        self._router = router
        self._name = name
        self._seqlock = bool(seqlock)
        self._owner_incarnation = bool(owner_incarnation)
        self._loan_protocol = bool(loan_protocol)
        self._lock = threading.Lock()
        self._subs: Dict[str, Dict[str, Any]] = {}
        self._bseq = 0
        self._sent_total = 0
        self._errors = 0

    def cmd_subscribe(self, data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """``frames.subscribe {"subscriber": str, "senders": list[str] | None}``.

        Аргументы — ``data`` (dict) поверх которого ``kwargs``.
        Post (отказ): ``{"success": False, "reason": str}``, состояние не меняется, если
              * ``loan_protocol`` включён — ``reason`` содержит ``"FW_SHM_LOAN_PROTOCOL"``
                (проверяется первым, до разбора аргументов);
              * ``subscriber`` отсутствует/пуст;
              * ``senders`` не ``None`` и не list/tuple строк.
        Post (успех): РОВНО ``{"success": True, "seqlock": bool, "owner_incarnation": bool}``;
              адрес ``subscriber`` получает дескрипторы кадров, чей ``sender`` входит в
              ``senders`` (``None`` либо ключ отсутствует — все отправители). Повторный
              вызов с тем же адресом заменяет фильтр, счётчик ``sent`` адреса сохраняется.
        """
        if self._loan_protocol:
            return {
                "success": False,
                "reason": "FW_SHM_LOAN_PROTOCOL включён: мост кадров не возвращает заём слота "
                "(поток кадров под этим флагом — Task 2.1)",
            }
        args = _merge_args(data, kwargs)
        subscriber = str(args.get("subscriber") or "").strip()
        if not subscriber:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        senders = args.get("senders")
        if senders is not None:
            if not isinstance(senders, (list, tuple)) or not all(isinstance(x, str) for x in senders):
                return {"success": False, "reason": f"senders — список строк либо None, получено {senders!r}"}
            senders = set(senders)
        with self._lock:
            prev = self._subs.get(subscriber)
            self._subs[subscriber] = {"senders": senders, "sent": prev["sent"] if prev else 0}
        return {"success": True, "seqlock": self._seqlock, "owner_incarnation": self._owner_incarnation}

    def cmd_unsubscribe(self, data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """``frames.unsubscribe {"subscriber": str}``.

        Post: ``{"success": True, "subscriber": str, "removed": bool}`` — ``removed`` =
              адрес был подписан; после возврата на этот адрес не уходит ни одного push'а.
              Неизвестный адрес — не ошибка (``removed=False``): брокер наблюдаемости шлёт
              эту команду при смерти сессии, подписка к тому моменту может быть снята.
              Пустой ``subscriber`` — ``{"success": False, "reason": str}``.
        """
        subscriber = str(_merge_args(data, kwargs).get("subscriber") or "").strip()
        if not subscriber:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        with self._lock:
            removed = self._subs.pop(subscriber, None) is not None
        return {"success": True, "subscriber": subscriber, "removed": removed}

    def cmd_stats(self, data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """``frames.stats``.

        Post: ``{"success": True, "sent": {адрес: int}, "sent_total": int, "errors": int,
              "bseq": int}`` — ``sent`` по ТЕКУЩИМ подписчикам (снятый адрес исчезает);
              ``sent_total`` — все push'и за жизнь моста, монотонен и переживает
              ``unsubscribe``; ``errors`` — исключения ``send_async``; ``bseq`` — номер
              последнего построенного дескриптора (0 — ни одного).
              ``sent``/``sent_total`` считают ПОСТАНОВКИ в очередь ``AsyncSender`` роутера
              (``send_async`` → ``put_nowait``), а не записи в сокет: дроп на
              переполненной очереди (``queue.Full`` — счётчик ``dropped`` отправителя, без
              исключения) здесь тоже посчитан как отправленный; дальнейшие потери (relay
              хаба, очередь observability) видны разницей с ``received`` у клиента.
        """
        with self._lock:
            return {
                "success": True,
                "sent": {addr: sub["sent"] for addr, sub in self._subs.items()},
                "sent_total": self._sent_total,
                "errors": self._errors,
                "bseq": self._bseq,
            }

    def on_drained(self, msgs: List[Dict[str, Any]]) -> None:
        """Разослать дескрипторы кадров из вычерпанной пачки.

        Pre:  ``msgs`` — dict'ы data-конвертов (``receive(return_messages=False)``).
        Post: подписчиков нет — ни одного ``build_frame_descriptor`` и ``send_async``.
              Иначе на каждый ``msg``, для которого
              ``build_frame_descriptor(msg.get("sender"), msg.get("data"), bseq)`` не ``None``
              и фильтр хотя бы одного подписчика пропускает ``msg["sender"]``: ``bseq``
              увеличен на 1 (первый дескриптор — ``bseq == 1``), и КАЖДОМУ такому подписчику
              ровно один вызов ``router.send_async(message, priority="normal")`` с
              ``message == {"type": "event", "targets": [адрес], "queue_type":
              "observability", "command": "frames.frame", "sender": name,
              "data": descriptor}`` (один и тот же дескриптор, один ``bseq``). Успешный
              вызов: ``sent[адрес] += 1``, ``sent_total += 1``. Исключение ``send_async`` —
              ``errors += 1``, остальным подписчикам отправка продолжается, наружу не
              пробрасывается. Сообщение без кадра (нет ``shm_actual_name``) — пропускается.
        """
        for msg in msgs:
            if not isinstance(msg, dict):
                continue
            sender = msg.get("sender")
            # Рассылка одного кадра — под lock: unsubscribe, вернувшийся на потоке
            # message_processor, гарантирует «ни одного push'а после». send_async — постановка
            # в очередь, не сеть; держать lock на ней дёшево.
            with self._lock:
                if not self._subs:
                    return  # без подписчиков — как headless, ноль работы
                targets = [a for a, sub in self._subs.items() if sub["senders"] is None or sender in sub["senders"]]
                if not targets:
                    continue
                descriptor = build_frame_descriptor(sender, msg.get("data"), self._bseq + 1)
                if descriptor is None:
                    continue
                self._bseq += 1
                for addr in targets:
                    message = {
                        "type": "event",
                        "targets": [addr],
                        "queue_type": "observability",
                        "command": FRAMES_PUSH,
                        "sender": self._name,
                        "data": descriptor,
                    }
                    try:
                        self._router.send_async(message, priority="normal")
                    except Exception:  # noqa: BLE001 — один отказ не рвёт рассылку остальным
                        self._errors += 1
                        continue
                    self._subs[addr]["sent"] += 1
                    self._sent_total += 1


class BridgeGuiProcess(HeadlessGuiProcess):
    """Headless-``gui`` + мост кадров: команды ``frames.*`` и push дескрипторов.

    Дренаж data-очереди унаследован без изменений; разница — :meth:`_on_drained`
    отдаёт пачку :class:`FrameBridge`. Команды ``introspect.*`` отвечают как у любого
    процесса. Флаги ``FW_SHM_*`` читаются из окружения процесса при старте.
    """

    def _init_application_threads(self) -> None:
        """Post: ``self.frame_bridge`` — :class:`FrameBridge` над ``self.router_manager``;
        в ``command_manager`` зарегистрированы ``frames.subscribe`` /
        ``frames.unsubscribe`` / ``frames.stats``; затем — дренаж базового класса.
        """
        from multiprocess_framework.modules.config_module.feature_flags import is_enabled

        self.frame_bridge = FrameBridge(
            self.router_manager,
            self.name,
            seqlock=is_enabled("FW_SHM_SEQLOCK"),
            owner_incarnation=is_enabled("FW_SHM_OWNER_INCARNATION"),
            loan_protocol=is_enabled("FW_SHM_LOAN_PROTOCOL"),
        )
        cm = self.command_manager
        if cm is None:
            self._log_error(
                f"BridgeGuiProcess '{self.name}': нет command_manager — команды frames.* не зарегистрированы",
                module="frame_bridge",
            )
        else:
            specs = (
                (FRAMES_SUBSCRIBE, self.frame_bridge.cmd_subscribe, "Подписать адрес на дескрипторы кадров gui"),
                (FRAMES_UNSUBSCRIBE, self.frame_bridge.cmd_unsubscribe, "Снять подписку на дескрипторы кадров"),
                (FRAMES_STATS, self.frame_bridge.cmd_stats, "Счётчики моста кадров по адресам"),
            )
            for command, handler, desc in specs:
                cm.register_command(command, handler, metadata={"description": desc}, tags=["system"])
        super()._init_application_threads()

    def _on_drained(self, msgs: list) -> None:
        """Post: ``self.frame_bridge.on_drained(msgs)``."""
        bridge = getattr(self, "frame_bridge", None)
        if bridge is not None:
            bridge.on_drained(msgs)


__all__ = ["BridgeGuiProcess", "FrameBridge"]
