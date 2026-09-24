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

from typing import Any, Dict, List, Optional

from multiprocess_prototype.frontend.headless_process import HeadlessGuiProcess


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
        raise NotImplementedError

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
        raise NotImplementedError

    def cmd_unsubscribe(self, data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """``frames.unsubscribe {"subscriber": str}``.

        Post: ``{"success": True, "subscriber": str, "removed": bool}`` — ``removed`` =
              адрес был подписан; после возврата на этот адрес не уходит ни одного push'а.
              Неизвестный адрес — не ошибка (``removed=False``): брокер наблюдаемости шлёт
              эту команду при смерти сессии, подписка к тому моменту может быть снята.
              Пустой ``subscriber`` — ``{"success": False, "reason": str}``.
        """
        raise NotImplementedError

    def cmd_stats(self, data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """``frames.stats``.

        Post: ``{"success": True, "sent": {адрес: int}, "sent_total": int, "errors": int,
              "bseq": int}`` — ``sent`` по ТЕКУЩИМ подписчикам (снятый адрес исчезает);
              ``sent_total`` — все push'и за жизнь моста, монотонен и переживает
              ``unsubscribe``; ``errors`` — исключения ``send_async``; ``bseq`` — номер
              последнего построенного дескриптора (0 — ни одного).
        """
        raise NotImplementedError

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
        raise NotImplementedError


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
        raise NotImplementedError

    def _on_drained(self, msgs: list) -> None:
        """Post: ``self.frame_bridge.on_drained(msgs)``."""
        raise NotImplementedError


__all__ = ["BridgeGuiProcess", "FrameBridge"]
