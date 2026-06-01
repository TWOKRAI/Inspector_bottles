# -*- coding: utf-8 -*-
"""
RouterManager — наследник ChannelRoutingManager.

Координирует AsyncSender (outgoing pipeline), AsyncReceiver (incoming poll),
channel_dispatcher (outgoing routing) и message_dispatcher (incoming handling).
"""

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from ...channel_routing_module import ChannelRoutingManager
from ...dispatch_module import Dispatcher, DispatchStrategy
from ...message_module import AddressValidationError, is_broadcast, split_address
from ..interfaces import IMessageChannel

from ._sender import AsyncSender
from ._receiver import AsyncReceiver
from ._middleware import MiddlewarePipeline

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...message_module import Message


class _PendingRequest:
    """Слот ожидания ответа на синхронный request (P0.5).

    Поток-инициатор блокируется на ``event.wait(timeout)``; приёмный поток
    (``receive``) кладёт ответ в ``response`` и взводит ``event``.
    """

    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: Optional[Dict[str, Any]] = None


class RouterManager(ChannelRoutingManager):
    """Фасад маршрутизации: AsyncSender/Receiver, CRM-каналы, channel_dispatcher + message_dispatcher."""

    def __init__(
        self,
        manager_name: str,
        process: Optional[Any] = None,
        queue_registry: Optional[Any] = None,
        dispatch_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        send_queue_size: int = 512,
        logger: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        managers = kwargs.pop("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger

        ChannelRoutingManager.__init__(
            self,
            manager_name=manager_name,
            process=process,
            config=None,
            buffer_strategy=None,  # AsyncSender handles buffering (not CRM buffer)
            dispatcher_key_field="command",
            dispatcher_strategy=dispatch_strategy,
            managers=managers,
            observable_config=kwargs.pop("observable_config", None),
            auto_proxy=kwargs.pop("auto_proxy", True),
            **kwargs,
        )

        self.router_id = manager_name
        self.queue_registry = queue_registry
        self._sender = AsyncSender(
            name=manager_name,
            send_fn=self._do_send,
            queue_size=send_queue_size,
            log_warning=self._log_warning,
            log_error=self._log_error,
        )

        self._receiver = AsyncReceiver(
            name=manager_name,
            log_warning=self._log_warning,
            log_error=self._log_error,
            log_info=self._log_info,
        )

        self._send_mw = MiddlewarePipeline("send", log_warning=self._log_warning)
        self._recv_mw = MiddlewarePipeline("receive", log_warning=self._log_warning)
        self.channel_dispatcher = self._dispatcher
        self.message_dispatcher = Dispatcher(
            f"{manager_name}_message_dispatcher",
            process=process,
            default_strategy=dispatch_strategy,
        )

        self._stats: Dict[str, int] = {
            "sent_attempted": 0,
            "sent_ok": 0,
            "received": 0,
            "errors": 0,
            "middleware_dropped": 0,
        }
        self._stats_lock = threading.Lock()

        # P2.2 (Гибрид, control-plane): реестр обработчиков воркеров по имени.
        # Билет с иерархическим адресом `proc.worker[.…]` на приёме уходит в
        # handler своего воркера (модель «почта»). Кадры (data) сюда НЕ попадают —
        # они едут топологией in-process очередей (модель «трубы», assigned_worker).
        self._worker_handlers: Dict[str, Callable] = {}

        # P0.5: request-response поверх fire-and-forget транспорта.
        # Реестр pending-запросов: correlation_id → _PendingRequest.
        # Заполняется request() на инициаторе, резолвится в receive() при
        # входящем ответе с тем же id. Пустой реестр → нулевой оверхед на
        # горячем приёмном пути (guard `if self._pending_requests`).
        self._pending_requests: Dict[str, _PendingRequest] = {}
        self._pending_lock = threading.Lock()

    def _inc_stat(self, key: str, value: int = 1) -> None:
        with self._stats_lock:
            self._stats[key] += value

    # ================================================================
    # LIFECYCLE
    # ================================================================

    def initialize(self) -> bool:
        try:
            self._dispatcher.initialize()
            self.message_dispatcher.initialize()
            self._sender.start()
            self.is_initialized = True
            self._log_info(
                f"RouterManager '{self.manager_name}' initialized (channels: {self._channel_registry.names()})"
            )
            return True
        except Exception as e:
            self._log_error(f"initialize failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self._sender.stop()
            self._receiver.stop()

            for ch in self._channel_registry.clear():
                try:
                    ch.stop_listening()
                except Exception:  # nosec B110 — best-effort остановка канала при shutdown
                    pass

            self._dispatcher.shutdown()
            self.message_dispatcher.shutdown()
            self.is_initialized = False
            self._log_info("RouterManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"shutdown error: {e}")
            return False

    # ================================================================
    # SEND
    # ================================================================

    def send_async(
        self,
        message: Union["Message", Dict[str, Any]],
        priority: str = "normal",
    ) -> None:
        """Non-blocking: помещает всё сообщение в AsyncSender → обработка в фоне.

        AsyncSender вызывает _do_send() который применяет middleware,
        резолвит каналы и вызывает channel.send(). Это отличие от CRM buffer:
        весь pipeline (включая middleware) выполняется в фоновом потоке.
        """
        self._sender.enqueue(self._to_dict(message), priority)

    def send(self, message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        """Синхронная отправка. Блокирует вызывающий поток."""
        return self._do_send(self._to_dict(message))

    def _do_send(self, msg_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Применить middleware → резолвить каналы → channel.send()."""
        self._inc_stat("sent_attempted")
        try:
            processed = self._send_mw.apply(msg_dict)
            if processed is None:
                self._inc_stat("middleware_dropped")
                return {"status": "dropped", "reason": "send middleware returned None"}

            channels = self._resolve_channels(processed)
            if not channels:
                # Fallback (U1): адресная доставка по msg["targets"] через общий
                # queue_registry ("адресная книга" оркестратора). Срабатывает ТОЛЬКО
                # когда channel/route не резолвится (раньше здесь был silent drop) —
                # реализует Message(targets=[...]) → RouterManager → доставлено,
                # не ломая существующие channel-маршруты.
                delivered = self._deliver_by_targets(processed)
                if delivered is not None:
                    return delivered
                self._inc_stat("errors")
                return {
                    "status": "error",
                    "reason": (
                        f"no channel resolved for "
                        f"channel={processed.get('channel')!r} "
                        f"command={processed.get('command')!r} "
                        f"type={processed.get('type')!r}"
                    ),
                }

            if len(channels) == 1:
                result = channels[0].send(processed)
                if isinstance(result, dict) and result.get("status") == "error":
                    self._inc_stat("errors")
                    self._log_debug(f"channel '{channels[0].name}' error: {result.get('reason')}")
                else:
                    self._inc_stat("sent_ok")
                return result

            results = []
            all_ok = True
            for ch in channels:
                r = ch.send(processed)
                results.append({"channel": ch.name, **r})
                if isinstance(r, dict) and r.get("status") == "error":
                    self._inc_stat("errors")
                    all_ok = False
            if all_ok:
                self._inc_stat("sent_ok")
            return {"status": "success", "broadcast": True, "results": results}

        except Exception as e:
            self._inc_stat("errors")
            self._log_error(f"_do_send exception: {e}")
            return {"status": "error", "reason": str(e)}

    @staticmethod
    def _select_queue_type(msg_dict: Dict[str, Any]) -> str:
        """Единое правило выбора очереди (qtype) для адресной доставки.

        Канонизирует логику, ранее раздублированную в трёх местах (recon #5:
        `send_to_process`, `_deliver_by_targets`, `broadcast`): явный
        `msg["queue_type"]`, иначе "system" для команд, иначе "data". Это
        правило-ПАРИТЕТ с нынешним `ProcessCommunication.send_to_process` —
        менять его (на богатую таблицу `MESSAGE_TYPE_TO_CHANNEL`) будем при
        вводе Event/State-каналов (P3), не ломая поведение сейчас.
        """
        return msg_dict.get("queue_type") or ("system" if msg_dict.get("type") == "command" else "data")

    def _deliver_by_targets(self, msg_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Адресная доставка по msg["targets"] через общий queue_registry.

        "Адресная книга" оркестратора: queue_registry динамически хранит очереди
        всех процессов (обновляется при их создании/удалении). Кладёт сообщение
        напрямую в очередь каждого процесса-получателя по имени — тем же путём, что
        и ProcessCommunication.send_message (проверенный транспорт data-трафика).

        Вызывается из _do_send, КОГДА `_resolve_channels` не вернул ни одного
        канала. Поэтому возможный остаточный `msg["channel"]` (напр. vestigial
        `channel:"data"` у кадров — recon #3) уже доказанно НЕ зарезолвился: targets
        — авторитетный адрес, доставляем по нему (раньше здесь был silent drop из-за
        guard'а на `msg["channel"]`).

        **Иерархическая адресация (P2.1).** Каждый элемент `targets` — dotted-адрес
        `process[.worker[.…]]` (см. `message_module.addressing`). Cross-process
        доставка идёт в очередь `address[0]` (`process_of`); нижние уровни
        (воркер и глубже, `address[1:]`) едут в билете под `_address` для
        intra-process резолва на приёме (P2.2). Плоское имя `"proc"` →
        `address == ["proc"]` → паритет: тот же объект билета (ноль копий —
        важно для горячего data-path кадров), та же очередь, тот же qtype.

        Выбор очереди — :meth:`_select_queue_type`.

        Returns:
            dict-результат при успешной доставке хотя бы одному таргету;
            None — если targets пуст, queue_registry недоступен или ни один таргет
            не доставлен (вызывающий формирует обычную ошибку).
        """
        targets = msg_dict.get("targets")
        if not targets:
            return None
        qr = self.queue_registry
        if qr is None:
            return None

        qtype = self._select_queue_type(msg_dict)

        delivered = 0
        for target in targets:
            if not target or is_broadcast(target):
                continue
            try:
                address = split_address(target)  # prefix-валидация dotted-адреса
            except AddressValidationError as exc:
                self._log_debug(f"_deliver_by_targets: невалидный адрес {target!r}: {exc}")
                continue
            process = address[0]
            # len==1 (плоское имя) → исходный билет без копии (паритет, горячий путь).
            # Иначе — per-target копия с полным address (воркер+ резолвится на приёме).
            ticket = msg_dict if len(address) == 1 else {**msg_dict, "_address": address}
            try:
                if qr.send_to_queue(process, qtype, ticket):
                    delivered += 1
            except Exception as exc:
                self._log_debug(f"_deliver_by_targets: send_to_queue('{process}', '{qtype}') failed: {exc}")

        if delivered > 0:
            self._inc_stat("sent_ok")
            return {"status": "success", "delivered_by_targets": delivered}
        return None

    # ================================================================
    # REQUEST-RESPONSE (P0.5) — синхронный round-trip поверх fire-and-forget
    # ================================================================

    @staticmethod
    def _extract_correlation_id(msg: Dict[str, Any]) -> Optional[str]:
        """Достать correlation-id из билета.

        Приоритет: top-level ``request_id`` (generic-путь), затем
        ``data.correlation_id`` (PM-обёртка ``process.command``). Симметрично
        используется и при отправке ответа (:meth:`reply_to_request`), и при
        резолве входящего ответа (:meth:`receive`).
        """
        rid = msg.get("request_id")
        if rid:
            return rid
        data = msg.get("data")
        if isinstance(data, dict):
            return data.get("correlation_id")
        return None

    def request(
        self,
        message: Union["Message", Dict[str, Any]],
        timeout: float = 5.0,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Синхронный request-response: отправить и дождаться ответа.

        Назначает ``correlation_id`` (если не задан), регистрирует pending-слот,
        отправляет через обычный транспорт (:meth:`send`) и блокирует поток до
        прихода ответа с тем же id (резолвится в :meth:`receive`) или таймаута.

        ВАЖНО (контракт): нельзя вызывать из того же потока, который крутит
        :meth:`receive`/``start_listening`` — ответ некому будет разобрать
        (дедлок до таймаута). Инициатор (GUI/driver) обязан звать request() из
        потока, отдельного от приёмного цикла процесса.

        Returns:
            dict ответа (содержит ``success``/``result``, у PM-пути ещё
            вложенный ``data``). При таймауте — ``{"success": False,
            "error": "timeout", "correlation_id": cid}``. При ошибке отправки —
            ``{"success": False, "error": <reason>, "correlation_id": cid}``.
        """
        msg = self._to_dict(message)
        cid = correlation_id or self._extract_correlation_id(msg) or str(uuid.uuid4())
        msg["request_id"] = cid
        # Зеркалим id в data.correlation_id для приёмников, читающих вложенный id
        # (PM-обёртка process.command). setdefault — не затираем явный id.
        data = msg.get("data")
        if isinstance(data, dict):
            data.setdefault("correlation_id", cid)

        pending = _PendingRequest()
        with self._pending_lock:
            self._pending_requests[cid] = pending
        try:
            send_result = self.send(msg)
            if isinstance(send_result, dict) and send_result.get("status") == "error":
                return {
                    "success": False,
                    "error": send_result.get("reason", "send failed"),
                    "correlation_id": cid,
                }
            if not pending.event.wait(timeout):
                return {"success": False, "error": "timeout", "correlation_id": cid}
            return (
                pending.response
                if pending.response is not None
                else {
                    "success": False,
                    "error": "empty response",
                    "correlation_id": cid,
                }
            )
        finally:
            with self._pending_lock:
                self._pending_requests.pop(cid, None)

    def _resolve_pending(self, correlation_id: str, response: Dict[str, Any]) -> bool:
        """Доставить ответ ожидающему request() по correlation_id.

        Returns True, если pending-слот найден и взведён; False — если такого
        запроса нет (чужой/просроченный ответ, билет идёт обычным путём).
        """
        with self._pending_lock:
            pending = self._pending_requests.get(correlation_id)
        if pending is None:
            return False
        pending.response = response
        pending.event.set()
        return True

    def reply_to_request(
        self,
        request_msg: Dict[str, Any],
        result: Any,
        success: bool = True,
        response_command: str = "command.response",
    ) -> Optional[Dict[str, Any]]:
        """Отправить ответ на request-билет, ЕСЛИ он его требует.

        No-op (возврат None), когда в ``request_msg`` нет correlation-id —
        сохраняет fire-and-forget совместимость для команд без ответа (весь
        нынешний GUI-трафик). Адресат: ``data.reply_to`` / ``reply_to`` /
        ``sender`` входящего билета. Ответ едет control-plane (system-очередь
        приёмника, ``queue_type="system"``), где крутится его message_processor.
        """
        cid = self._extract_correlation_id(request_msg)
        if not cid:
            return None
        data = request_msg.get("data")
        reply_target = data.get("reply_to") if isinstance(data, dict) else None
        reply_target = reply_target or request_msg.get("reply_to") or request_msg.get("sender")
        if not reply_target:
            self._log_debug("reply_to_request: нет адресата (sender/reply_to) — ответ не отправлен")
            return None

        sender_name = getattr(self.process, "name", None) or self.router_id
        response = {
            "type": "response",
            "command": response_command,
            "sender": sender_name,
            "targets": [reply_target],
            "queue_type": "system",
            "request_id": cid,
            "success": success,
            "result": result,
        }
        return self.send(response)

    # ================================================================
    # RECEIVE
    # ================================================================

    def receive(
        self,
        timeout: float = 0.0,
        return_messages: bool = True,
        input_channels_only: bool = True,
        channel_types: Optional[List[str]] = None,
    ) -> List[Union["Message", Dict[str, Any]]]:
        """Sync опрос каналов + receive middleware + message_dispatcher.
        input_channels_only=True: опрашивать только каналы процесса (process.name_*).
        channel_types: если задан (например ['system'] или ['data']), опрашивать только
        каналы с соответствующим суффиксом (process_system, process_data).
        Это устраняет гонку между system_thread и worker: system_thread опрашивает
        только system, worker — только data.
        """
        from ...message_module import Message

        raw = self._poll_all_channels(
            timeout,
            input_channels_only=input_channels_only,
            channel_types=channel_types,
        )
        result = []

        for msg_dict in raw:
            try:
                processed = self._recv_mw.apply(msg_dict)
                if processed is None:
                    self._inc_stat("middleware_dropped")
                    continue

                processed.setdefault("_receive_info", {}).update(
                    {
                        "router_id": self.router_id,
                        "receive_time": time.time(),
                    }
                )

                # P0.5 (request-response): входящий билет с correlation_id,
                # совпадающим с нашим pending-запросом → это ОТВЕТ на наш
                # request(). Резолвим pending и потребляем билет (дальше не
                # диспетчеризуем). Guard на пустой реестр = ноль оверхеда,
                # когда request() не используется. Чужие запросы с
                # correlation_id безопасны: их id нет в нашем реестре.
                #
                # ВАЖНО (self-resolve guard): резолвим ТОЛЬКО билеты type="response".
                # Без этого самоадресованный запрос (targets=[host], когда адаптер
                # и приёмник в одном процессе — driver→ProcessManager) ловился бы
                # собственным pending как «ответ» и НЕ доходил до handler'а
                # (process.command → system.shutdown/process.stop молча эхо-резолвились).
                # Все билдеры ответов (reply_to_request/адаптер/_handle_process_command)
                # ставят type="response", запросы — type="command"/"data".
                if self._pending_requests and processed.get("type") == "response":
                    cid = self._extract_correlation_id(processed)
                    if cid and self._resolve_pending(cid, processed):
                        self._inc_stat("received")
                        continue

                # P2.2 (Гибрид, control-plane): билет с адресом до воркера
                # (proc.worker[.…]) и НЕ data-кадр → доставляем worker-handler'у
                # (модель «почта»). Кадры остаются на data-пути (трубы).
                if self._route_to_worker(processed):
                    result.append(Message.from_dict(processed) if return_messages else processed)
                    self._inc_stat("received")
                    continue

                dispatch_key = processed.get("command") or processed.get("type", "")
                if dispatch_key:
                    try:
                        self.message_dispatcher.dispatch(
                            processed,
                            key_field="command" if processed.get("command") else "type",
                        )
                    except Exception as exc:
                        self._log_warning(f"message_dispatcher error for '{dispatch_key}': {exc}")

                result.append(Message.from_dict(processed) if return_messages else processed)
                self._inc_stat("received")

            except Exception as e:
                self._inc_stat("errors")
                self._log_error(f"receive error: {e}")

        return result

    def _route_to_worker(self, processed: Dict[str, Any]) -> bool:
        """P2.2 (Гибрид, control-plane): доставить билет worker-handler'у по адресу.

        Возвращает True, если билет адресован воркеру (`_address[1]`), это НЕ
        data-кадр, и обработчик воркера зарегистрирован — тогда вызывает его и
        билет считается доставленным (process-level dispatch пропускается).

        Возвращает False (билет идёт обычным путём — «дефолт на процесс»), когда:
          - нет ни одного worker-handler (быстрый выход, ноль накладных на горячем пути);
          - в билете нет адреса до воркера (`_address` отсутствует или длиной < 2);
          - билет — data-кадр (Гибрид: кадры едут трубами, не уводим в «почту»);
          - для воркера нет обработчика (лог + fallback на process-dispatch, не падение).

        Исключение в самом обработчике логируется и НЕ роняет приёмный цикл —
        билет всё равно считается доставленным воркеру (return True).
        """
        if not self._worker_handlers:
            return False
        address = processed.get("_address")
        if not address or len(address) < 2:
            return False
        if processed.get("type") == "data":
            # Гибрид: кадры остаются на data-пути (трубы), не уводим в worker-handler.
            return False
        worker = address[1]
        handler = self._worker_handlers.get(worker)
        if handler is None:
            self._log_debug(
                f"receive: нет worker-handler для '{worker}' (адрес {address}) — fallback на process-dispatch"
            )
            return False
        try:
            handler(processed)
        except Exception as exc:
            self._log_warning(f"worker-handler '{worker}' error: {exc}")
        return True

    def _poll_all_channels(
        self,
        timeout: float = 0.0,
        input_channels_only: bool = True,
        channel_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Опросить каналы.
        input_channels_only: только process.name_* (входные очереди).
        channel_types: если задан, только каналы с суффиксом _system, _data и т.д.
        """
        snapshot = self._channel_registry.snapshot()
        messages: List[Dict[str, Any]] = []
        process_name = getattr(self.process, "name", None) if self.process else None
        prefix = f"{process_name}_" if (input_channels_only and process_name) else None

        for ch_name, ch in snapshot.items():
            if prefix and not ch_name.startswith(prefix):
                continue
            if channel_types:
                suffix = (
                    ch_name[len(prefix) :]
                    if prefix and len(ch_name) > len(prefix)
                    else ch_name.split("_")[-1]
                    if "_" in ch_name
                    else ch_name
                )
                if suffix not in channel_types:
                    continue
            if not hasattr(ch, "poll"):
                continue
            try:
                for msg in ch.poll(timeout):
                    if isinstance(msg, dict):
                        msg["_source_channel"] = ch_name
                    messages.append(msg)
            except Exception as e:
                self._log_error(f"poll error on '{ch_name}': {e}")
        return messages

    # ================================================================
    # ASYNC RECEIVE
    # ================================================================

    def start_listening(self, poll_interval: float = 0.01) -> bool:
        return self._receiver.start(self.receive, poll_interval)

    def stop_listening(self, timeout: float = 5.0) -> bool:
        return self._receiver.stop(timeout)

    def add_message_callback(self, callback: Callable) -> None:
        self._receiver.add_callback(callback)

    def remove_message_callback(self, callback: Callable) -> None:
        self._receiver.remove_callback(callback)

    # ================================================================
    # CHANNEL REGISTRATION (override CRM — no auto-dispatcher registration)
    # ================================================================

    def register_channel(self, channel: IMessageChannel) -> bool:
        """Зарегистрировать IMessageChannel.

        Override CRM's register_channel() чтобы:
          1. Проверить тип (IMessageChannel, не просто IChannel)
          2. Inject log-callbacks (_attach_logger)
          3. НЕ auto-регистрировать в channel_dispatcher — RouterManager
             управляет routing через register_route() явно.
        """
        if not isinstance(channel, IMessageChannel):
            self._log_warning(
                f"[RouterManager] register_channel: expected IMessageChannel, got {type(channel).__name__}"
            )
            return False
        if hasattr(channel, "_attach_logger"):
            channel._attach_logger(self._log_warning, self._log_error)
        return self._channel_registry.register(channel)

    # ================================================================
    # CHANNEL ROUTING (channel_dispatcher API)
    # ================================================================

    def register_route(
        self,
        key: str,
        channel_name: Optional[str],
        strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        efficiency: int = 0,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Привязать routing-ключ к каналу через channel_dispatcher.

        Использует name-returning handler pattern: dispatcher возвращает имя канала,
        RouterManager затем резолвит канал по имени в _resolve_channels().

        Это отличается от CRM's register_route() где handler пишет напрямую.
        """
        return self.channel_dispatcher.register_handler(
            key=key,
            handler=self._make_channel_handler(channel_name),
            expects_full_message=True,
            efficiency=efficiency,
            tags=tags or [],
            strategy=strategy,
        )

    def register_broadcast_route(
        self,
        key: str,
        channel_names: List[str],
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Привязать ключ к группе каналов (fan-out / broadcast)."""
        names = list(channel_names)
        return self.channel_dispatcher.register_handler(
            key=key,
            handler=lambda msg: names,
            expects_full_message=True,
            tags=tags or [],
        )

    def register_channel_scenario(
        self,
        scenario_name: str,
        channel_names: List[str],
        description: str = "",
    ) -> bool:
        self.channel_dispatcher.create_scenario(scenario_name, description)
        for i, ch_name in enumerate(channel_names):
            _ch = ch_name
            self.channel_dispatcher.add_handler_to_scenario(
                scenario_name=scenario_name,
                handler_key=f"stage_{i}_{ch_name}",
                handler=lambda msg, captured=_ch: captured,
                stage=i,
            )
        return True

    # ================================================================
    # MESSAGE HANDLERS (message_dispatcher API)
    # ================================================================

    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        efficiency: int = 0,
        tags: Optional[List[str]] = None,
        strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
    ) -> bool:
        return self.message_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata or {},
            efficiency=efficiency,
            tags=tags or [],
            strategy=strategy,
        )

    def register_worker_handler(self, worker_name: str, handler: Callable) -> bool:
        """P2.2 (Гибрид, control-plane): зарегистрировать обработчик воркера.

        На приёме билет с адресом до воркера (`targets=["proc.worker"]` →
        `_address=["proc","worker"]`), не являющийся data-кадром, попадёт в
        `handler(message_dict)` (модель «почта»). Это транспортный дом для
        команд/конфига конкретному плагину-в-воркере; кадры (data-plane) сюда
        НЕ заходят — они едут топологией in-process очередей (assigned_worker).

        Идемпотентно: повторная регистрация заменяет обработчик. Новых
        IPC-очередей не создаёт — это in-process реестр.
        """
        if not worker_name or handler is None:
            return False
        self._worker_handlers[worker_name] = handler
        return True

    def unregister_worker_handler(self, worker_name: str) -> bool:
        """Снять обработчик воркера (см. :meth:`register_worker_handler`)."""
        return self._worker_handlers.pop(worker_name, None) is not None

    def register_message_scenario(self, scenario_name: str, description: str = "") -> bool:
        return self.message_dispatcher.create_scenario(scenario_name, description)

    def add_handler_to_message_scenario(
        self,
        scenario_name: str,
        handler_key: str,
        handler: Callable,
        stage: int = 0,
    ) -> bool:
        return self.message_dispatcher.add_handler_to_scenario(
            scenario_name=scenario_name,
            handler_key=handler_key,
            handler=handler,
            stage=stage,
        )

    # ================================================================
    # MIDDLEWARE
    # ================================================================

    def add_send_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        self._send_mw.add(fn)

    def add_receive_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        self._recv_mw.add(fn)

    def remove_send_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Удалить send middleware по identity."""
        self._send_mw.remove(fn)

    def remove_receive_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Удалить receive middleware по identity."""
        self._recv_mw.remove(fn)

    def clear_middleware(self) -> None:
        self._send_mw.clear()
        self._recv_mw.clear()

    # ================================================================
    # STATISTICS & MONITORING
    # ================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Полная статистика: счётчики, каналы, dispatcher'ы, потоки."""
        base = super().get_stats() if hasattr(super(), "get_stats") else {}
        ch_h = self.channel_dispatcher.get_all_handlers()
        msg_h = self.message_dispatcher.get_all_handlers()
        with self._stats_lock:
            stats_snap = dict(self._stats)

        router_stats: Dict[str, Any] = {
            "router_id": self.router_id,
            "is_initialized": self.is_initialized,
            "sender_alive": self._sender.is_alive,
            "listener_alive": self._receiver.is_alive,
            "send_queue_size": self._sender.qsize,
            "channels_count": len(self._channel_registry),
            "callbacks_count": self._receiver.callback_count,
            "send_middleware_count": len(self._send_mw),
            "recv_middleware_count": len(self._recv_mw),
            "channel_handlers": len(ch_h),
            "message_handlers": len(msg_h),
            "channel_routes": ch_h,
            "message_handler_list": msg_h,
            "queued_async": self._sender.queued,
            "dropped": self._sender.dropped,
            "processed": self._receiver.processed,
            **stats_snap,
            "errors": stats_snap["errors"] + self._receiver.errors,
            "channels": self._channel_registry.get_info(),
        }

        if isinstance(base, dict):
            base["router"] = router_stats
            return base
        return {"router": router_stats}

    def get_dispatcher_info(self) -> Dict[str, Any]:
        """Состояние обоих dispatcher'ов: handlers, scenarios, counts."""
        ch_h = self.channel_dispatcher.get_all_handlers()
        ch_s = self.channel_dispatcher.get_all_scenarios()
        msg_h = self.message_dispatcher.get_all_handlers()
        msg_s = self.message_dispatcher.get_all_scenarios()

        return {
            "channel_dispatcher": {
                "name": self.channel_dispatcher.manager_name,
                "handler_count": len(ch_h),
                "handlers": ch_h,
                "scenarios": ch_s,
            },
            "message_dispatcher": {
                "name": self.message_dispatcher.manager_name,
                "handler_count": len(msg_h),
                "handlers": msg_h,
                "scenarios": msg_s,
            },
        }

    # ================================================================
    # INTERNAL HELPERS
    # ================================================================

    @staticmethod
    def _to_dict(message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        if hasattr(message, "to_dict"):
            return message.to_dict()
        return dict(message)

    def _resolve_channels(self, msg_dict: Dict[str, Any]) -> List[IMessageChannel]:
        """Найти каналы для исходящего сообщения.

        Приоритет:
          1. msg["channel"] задан явно → прямой O(1) lookup
          2. channel_dispatcher.dispatch() → str | List[str] (имена каналов)
          3. [] → ошибка
        """
        ch_name = msg_dict.get("channel")
        # "queue" — легаси-дефолт из MESSAGE_TYPE_DEFAULTS, а НЕ реальный канал Router
        # (реальные: system_events, {proc}_data, {proc}_local). Трактуем как «канал не
        # задан»: проваливаемся в dispatcher/targets без WARNING-шума на старте.
        if ch_name and ch_name != "queue":
            ch = self._channel_registry.get(ch_name)
            if ch:
                return [ch]
            self._log_warning(f"channel '{ch_name}' not registered")
            return []

        key_field = "command" if msg_dict.get("command") else "type"
        if not msg_dict.get(key_field):
            self._log_warning("_resolve_channels: no 'channel', 'command' or 'type' in message")
            return []

        dispatch_result = self.channel_dispatcher.dispatch(msg_dict, key_field=key_field)

        if isinstance(dispatch_result, str):
            ch = self._channel_registry.get(dispatch_result)
            if ch:
                return [ch]
            self._log_warning(f"channel '{dispatch_result}' from dispatcher not registered")
            return []

        if isinstance(dispatch_result, list):
            snapshot = self._channel_registry.snapshot()
            resolved = [snapshot[n] for n in dispatch_result if n in snapshot]
            missing = [n for n in dispatch_result if n not in snapshot]
            if missing:
                self._log_warning(f"broadcast: channels not found: {missing}")
            return resolved

        self._log_debug(
            f"channel_dispatcher returned no route for key_field={key_field!r} value={msg_dict.get(key_field)!r}"
        )
        return []

    @staticmethod
    def _make_channel_handler(channel_name: Optional[str]) -> Callable:
        """Создать name-returning handler для channel_dispatcher.

        RouterManager routing pattern: handler returns channel NAME (str),
        not the written result. _resolve_channels() resolves name → channel.
        """
        if channel_name is not None:
            _name = channel_name
            return lambda msg: _name
        return lambda msg: msg.get("channel")

    # ================================================================
    # REGISTRATION API (config-driven, Phase 8)
    # ================================================================

    def register_channel_handler(self, key: str, handler: Callable, **kwargs) -> bool:
        """Зарегистрировать произвольный routing-handler в channel_dispatcher.

        Аналог command_manager.register_command() для каналов.
        Используется при config-driven channel setup (Phase 8).
        """
        return self.channel_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=kwargs.get("expects_full_message", True),
            efficiency=kwargs.get("efficiency", 0),
            tags=kwargs.get("tags", []),
        )

    def cleanup(self) -> None:
        """Alias for shutdown()."""
        self.shutdown()
