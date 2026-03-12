# -*- coding: utf-8 -*-
"""
RouterManager — фасад маршрутизации сообщений.

Координирует: AsyncSender, AsyncReceiver, ChannelRegistry, MiddlewarePipeline,
channel_dispatcher (исходящие), message_dispatcher (входящие).

Полная документация: router_module/README.md
"""
import time
from typing import Any, Callable, Dict, List, Optional, Union

from ...base_manager import BaseManager, ObservableMixin
from ...dispatch_module import Dispatcher, DispatchStrategy
from ..interfaces import IMessageChannel

from ._sender           import AsyncSender
from ._receiver         import AsyncReceiver
from ._channel_registry import ChannelRegistry
from ._middleware        import MiddlewarePipeline

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...message_module import Message


class RouterManager(BaseManager, ObservableMixin):
    """
    Масштабируемый менеджер маршрутизации сообщений.

    Координирует работу AsyncSender, AsyncReceiver, ChannelRegistry
    и двух Dispatcher'ов. Сам не содержит потоков и мьютексов — вся
    сложность делегирована в специализированные компоненты.

    Attrs:
        router_id:          Синоним manager_name (backward compat)
        channel_dispatcher: Dispatcher для маршрутизации ИСХОДЯЩИХ → каналы
        message_dispatcher: Dispatcher для обработки ВХОДЯЩИХ сообщений
    """

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
        # --- BaseManager + ObservableMixin ---
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        managers = kwargs.get("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=kwargs.get("config", {}),
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self.router_id = manager_name       # backward compat
        self.queue_registry = queue_registry

        # --- Компоненты ---
        self._channels = ChannelRegistry(
            log_warning=self._log_warning,
            log_error=self._log_error,
            log_debug=self._log_debug,
        )

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

        # --- Dispatcher'ы ---
        self.channel_dispatcher = Dispatcher(
            f"{manager_name}_channel_dispatcher",
            default_strategy=dispatch_strategy,
        )
        self.message_dispatcher = Dispatcher(
            f"{manager_name}_message_dispatcher",
            default_strategy=dispatch_strategy,
        )

        # --- Локальная статистика (операции самого роутера) ---
        self._stats: Dict[str, int] = {
            "sent_attempted":     0,
            "sent_ok":            0,
            "received":           0,
            "errors":             0,
            "middleware_dropped": 0,
        }

    # ================================================================
    # LIFECYCLE
    # ================================================================

    def initialize(self) -> bool:
        """Запустить фоновый поток-отправщик.

        Поток-приёмник запускается отдельно через start_listening().
        """
        try:
            self._sender.start()
            self.is_initialized = True
            self._log_info(
                f"RouterManager '{self.manager_name}' initialized "
                f"(channels: {self._channels.names()})"
            )
            return True
        except Exception as e:
            self._log_error(f"initialize failed: {e}")
            return False

    def shutdown(self) -> bool:
        """Корректная остановка всех компонентов."""
        try:
            self._sender.stop()
            self._receiver.stop()

            for ch in self._channels.clear():
                try:
                    ch.stop_listening()
                except Exception:
                    pass

            self.channel_dispatcher.shutdown()
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
        """Non-blocking отправка — безопасна для UI-потока.

        Помещает сообщение в PriorityQueue AsyncSender'а.
        При переполнении буфера — предупреждение, не зависание.

        Args:
            message:  Message-объект или словарь.
            priority: 'urgent' | 'high' | 'normal' | 'low'
        """
        self._sender.enqueue(self._to_dict(message), priority)

    def send(self, message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        """Синхронная отправка. Блокирует вызывающий поток.

        Для фоновых потоков и тестов.
        НЕ вызывать из UI-потока — используй send_async().
        """
        return self._do_send(self._to_dict(message))

    def _do_send(self, msg_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Внутренняя отправка: send middleware → resolve channels → channel.send()."""
        self._stats["sent_attempted"] += 1
        try:
            processed = self._send_mw.apply(msg_dict)
            if processed is None:
                self._stats["middleware_dropped"] += 1
                return {"status": "dropped", "reason": "send middleware returned None"}

            channels = self._resolve_channels(processed)
            if not channels:
                self._stats["errors"] += 1
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
                    self._stats["errors"] += 1
                    self._log_debug(f"channel '{channels[0].name}' error: {result.get('reason')}")
                else:
                    self._stats["sent_ok"] += 1
                return result

            # Broadcast
            results = []
            all_ok = True
            for ch in channels:
                r = ch.send(processed)
                results.append({"channel": ch.name, **r})
                if isinstance(r, dict) and r.get("status") == "error":
                    self._stats["errors"] += 1
                    all_ok = False
            if all_ok:
                self._stats["sent_ok"] += 1
            return {"status": "success", "broadcast": True, "results": results}

        except Exception as e:
            self._stats["errors"] += 1
            self._log_error(f"_do_send exception: {e}")
            return {"status": "error", "reason": str(e)}

    # ================================================================
    # RECEIVE
    # ================================================================

    def receive(
        self,
        timeout: float = 0.0,
        return_messages: bool = True,
    ) -> List[Union["Message", Dict[str, Any]]]:
        """Sync опрос всех каналов + receive middleware + message_dispatcher.

        Args:
            timeout:         Таймаут на один канал (0 = non-blocking).
            return_messages: True → Message-объекты, False → словари.
        """
        from ...message_module import Message  # avoid circular import

        raw = self._channels.poll_all(timeout)
        result = []

        for msg_dict in raw:
            try:
                processed = self._recv_mw.apply(msg_dict)
                if processed is None:
                    self._stats["middleware_dropped"] += 1
                    continue

                processed.setdefault("_receive_info", {}).update({
                    "router_id": self.router_id,
                    "receive_time": time.time(),
                })

                # fire-and-forget dispatch входящего
                dispatch_key = processed.get("command") or processed.get("type", "")
                if dispatch_key:
                    try:
                        self.message_dispatcher.dispatch(
                            processed,
                            key_field="command" if processed.get("command") else "type",
                        )
                    except Exception:
                        pass

                result.append(Message.from_dict(processed) if return_messages else processed)
                self._stats["received"] += 1

            except Exception as e:
                self._stats["errors"] += 1
                self._log_error(f"receive error: {e}")

        return result

    # ================================================================
    # ASYNC RECEIVE
    # ================================================================

    def start_listening(self, poll_interval: float = 0.01) -> bool:
        """Запустить фоновый listener-поток."""
        return self._receiver.start(self.receive, poll_interval)

    def stop_listening(self, timeout: float = 5.0) -> bool:
        """Остановить listener-поток."""
        return self._receiver.stop(timeout)

    def add_message_callback(self, callback: Callable) -> None:
        """Зарегистрировать колбэк для входящих сообщений."""
        self._receiver.add_callback(callback)

    def remove_message_callback(self, callback: Callable) -> None:
        """Удалить колбэк."""
        self._receiver.remove_callback(callback)

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

        Args:
            key:          Ключ диспетчеризации. Для PATTERN_MATCH — regex.
            channel_name: Имя канала. None → брать из msg["channel"] (dynamic).
            strategy:     EXACT / PATTERN / FALLBACK.
            efficiency:   Приоритет при FALLBACK_MATCH.
            tags:         Теги для группировки маршрутов.
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
        """Зарегистрировать chain-broadcast сценарий через channel_dispatcher."""
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
        """Зарегистрировать обработчик входящих сообщений."""
        return self.message_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata or {},
            efficiency=efficiency,
            tags=tags or [],
            strategy=strategy,
        )

    def register_message_scenario(self, scenario_name: str, description: str = "") -> bool:
        """Создать chain-сценарий обработки входящих."""
        return self.message_dispatcher.create_scenario(scenario_name, description)

    def add_handler_to_message_scenario(
        self,
        scenario_name: str,
        handler_key: str,
        handler: Callable,
        stage: int = 0,
    ) -> bool:
        """Добавить шаг в сценарий обработки входящих."""
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
        """Добавить middleware для исходящих сообщений.

        fn(msg) → dict | None.  None → сообщение отбрасывается.
        """
        self._send_mw.add(fn)

    def add_receive_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Добавить middleware для входящих сообщений."""
        self._recv_mw.add(fn)

    def clear_middleware(self) -> None:
        """Сбросить все middleware (send + receive)."""
        self._send_mw.clear()
        self._recv_mw.clear()

    # ================================================================
    # CHANNELS (делегирует в ChannelRegistry)
    # ================================================================

    def register_channel(self, channel: IMessageChannel) -> bool:
        """Зарегистрировать канал. Thread-safe.

        Если канал поддерживает _attach_logger() (наследует MessageChannel),
        автоматически инжектит log-колбэки роутера — errors из канала попадут
        в LoggerManager через ObservableMixin.
        """
        if hasattr(channel, "_attach_logger"):
            channel._attach_logger(self._log_warning, self._log_error)
        return self._channels.register(channel)

    def unregister_channel(self, channel_name: str) -> bool:
        """Удалить канал. Thread-safe."""
        return self._channels.unregister(channel_name)

    def get_channel(self, channel_name: str) -> Optional[IMessageChannel]:
        """Получить канал по имени или None. Thread-safe."""
        return self._channels.get(channel_name)

    def get_all_channels(self) -> List[IMessageChannel]:
        """Список всех зарегистрированных каналов. Thread-safe."""
        return self._channels.all()

    # ================================================================
    # STATISTICS & MONITORING
    # ================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Полная статистика: счётчики, каналы, dispatcher'ы, потоки."""
        base = super().get_stats() if hasattr(super(), "get_stats") else {}

        _ch_handlers  = self.channel_dispatcher.get_all_handlers()
        _msg_handlers = self.message_dispatcher.get_all_handlers()

        router_stats: Dict[str, Any] = {
            "router_id":             self.router_id,
            "is_initialized":        self.is_initialized,
            "sender_alive":          self._sender.is_alive,
            "listener_alive":        self._receiver.is_alive,
            "send_queue_size":       self._sender.qsize,
            "channels_count":        len(self._channels),
            "callbacks_count":       self._receiver.callback_count,
            "send_middleware_count": len(self._send_mw),
            "recv_middleware_count": len(self._recv_mw),
            # integer aliases — backward compat
            "channel_handlers":      len(_ch_handlers),
            "message_handlers":      len(_msg_handlers),
            # полные списки для инспекции
            "channel_routes":        _ch_handlers,
            "message_handler_list":  _msg_handlers,
            # агрегированные счётчики
            "queued_async":          self._sender.queued,
            "dropped":               self._sender.dropped,
            "processed":             self._receiver.processed,
            **self._stats,
            # errors — суммируем с ошибками receiver'а
            "errors":  self._stats["errors"] + self._receiver.errors,
            "channels": self._channels.get_info(),
        }

        if isinstance(base, dict):
            base["router"] = router_stats
            return base
        return {"router": router_stats}

    def get_dispatcher_info(self) -> Dict[str, Any]:
        """Состояние обоих dispatcher'ов: handlers, scenarios, counts."""
        ch_h  = self.channel_dispatcher.get_all_handlers()
        ch_s  = self.channel_dispatcher.get_all_scenarios()
        msg_h = self.message_dispatcher.get_all_handlers()
        msg_s = self.message_dispatcher.get_all_scenarios()

        return {
            "channel_dispatcher": {
                "name":          self.channel_dispatcher.manager_name,
                "handler_count": len(ch_h),
                "handlers":      ch_h,
                "scenarios":     ch_s,
            },
            "message_dispatcher": {
                "name":          self.message_dispatcher.manager_name,
                "handler_count": len(msg_h),
                "handlers":      msg_h,
                "scenarios":     msg_s,
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
          2. channel_dispatcher.dispatch() → str | List[str]
          3. [] → ошибка (нет тихого fallback)
        """
        # 1. Explicit channel — fast path
        ch_name = msg_dict.get("channel")
        if ch_name:
            ch = self._channels.get(ch_name)
            if ch:
                return [ch]
            self._log_warning(f"channel '{ch_name}' not registered")
            return []

        # 2. Dispatcher
        key_field = "command" if msg_dict.get("command") else "type"
        if not msg_dict.get(key_field):
            self._log_warning("_resolve_channels: no 'channel', 'command' or 'type' in message")
            return []

        dispatch_result = self.channel_dispatcher.dispatch(msg_dict, key_field=key_field)

        if isinstance(dispatch_result, str):
            ch = self._channels.get(dispatch_result)
            if ch:
                return [ch]
            self._log_warning(f"channel '{dispatch_result}' from dispatcher not registered")
            return []

        if isinstance(dispatch_result, list):
            snapshot = self._channels.snapshot()
            resolved = [snapshot[n] for n in dispatch_result if n in snapshot]
            missing  = [n for n in dispatch_result if n not in snapshot]
            if missing:
                self._log_warning(f"broadcast: channels not found: {missing}")
            return resolved

        self._log_warning(
            f"channel_dispatcher returned no route for "
            f"key_field={key_field!r} value={msg_dict.get(key_field)!r}"
        )
        return []

    @staticmethod
    def _make_channel_handler(channel_name: Optional[str]) -> Callable:
        """Создать routing-handler для channel_dispatcher.

        channel_name=str  → возвращает имя канала (static)
        channel_name=None → берёт из msg["channel"] (dynamic)
        """
        if channel_name is not None:
            _name = channel_name
            return lambda msg: _name
        return lambda msg: msg.get("channel")

    # ================================================================
    # BACKWARD COMPAT
    # ================================================================

    def register_channel_handler(self, key: str, handler: Callable, **kwargs) -> bool:
        """Backward-compat: регистрирует routing-handler в channel_dispatcher.

        handler(msg) → str (channel_name) | List[str] (broadcast).
        Новый API: register_route() или register_message_handler().
        """
        return self.channel_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=kwargs.get("expects_full_message", True),
            efficiency=kwargs.get("efficiency", 0),
            tags=kwargs.get("tags", []),
        )

    def cleanup(self) -> None:
        """Alias for shutdown() — backward compatibility."""
        self.shutdown()
