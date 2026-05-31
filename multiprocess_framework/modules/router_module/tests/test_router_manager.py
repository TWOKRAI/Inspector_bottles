# -*- coding: utf-8 -*-
"""
Тесты для RouterManager.

Покрывает всю публичную функциональность:
- Жизненный цикл (initialize / shutdown)
- Регистрация и управление каналами
- Синхронная отправка через explicit channel и через зарегистрированный маршрут
- Асинхронная отправка (send_async) с PriorityQueue
- Получение (receive) — sync poll
- Маршрутизация через channel_dispatcher (exact, broadcast)
- Обработчики входящих сообщений (message_dispatcher)
- Middleware pipeline (send / receive)
- Инспекция (get_dispatcher_info, get_stats)
"""

import threading
import time
import unittest
from queue import Queue
from types import SimpleNamespace
from typing import Callable

from ..core.router_manager import RouterManager
from ..channels.queue_channel import QueueChannel


# ---------------------------------------------------------------------------
# Вспомогательные инструменты
# ---------------------------------------------------------------------------


def _make_router(name: str = "test_router") -> RouterManager:
    return RouterManager(manager_name=name)


def _make_channel(name: str = "test_channel") -> tuple:
    """Возвращает (QueueChannel, Queue) — канал и базовую очередь для проверки."""
    q: Queue = Queue()
    return QueueChannel(name, q), q


# ---------------------------------------------------------------------------
# Тесты жизненного цикла
# ---------------------------------------------------------------------------


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()

    def tearDown(self):
        if self.router.is_initialized:
            self.router.shutdown()

    def test_initialize_returns_true(self):
        result = self.router.initialize()
        self.assertTrue(result)
        self.assertTrue(self.router.is_initialized)

    def test_router_id_equals_manager_name(self):
        self.assertEqual(self.router.router_id, self.router.manager_name)
        self.assertEqual(self.router.manager_name, "test_router")

    def test_sender_thread_starts_on_initialize(self):
        self.router.initialize()
        stats = self.router.get_stats()
        self.assertTrue(stats["router"]["sender_alive"])

    def test_shutdown_stops_router(self):
        self.router.initialize()
        result = self.router.shutdown()
        self.assertTrue(result)
        self.assertFalse(self.router.is_initialized)

    def test_shutdown_clears_channels(self):
        ch, _ = _make_channel()
        self.router.register_channel(ch)
        self.router.initialize()
        self.router.shutdown()
        self.assertEqual(len(self.router.get_all_channels()), 0)

    def test_cleanup_alias_for_shutdown(self):
        self.router.initialize()
        self.router.cleanup()
        self.assertFalse(self.router.is_initialized)


# ---------------------------------------------------------------------------
# Тесты каналов
# ---------------------------------------------------------------------------


class TestChannels(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_register_channel_returns_true(self):
        ch, _ = _make_channel()
        self.assertTrue(self.router.register_channel(ch))

    def test_register_channel_visible_in_get_all(self):
        ch, _ = _make_channel()
        self.router.register_channel(ch)
        self.assertEqual(len(self.router.get_all_channels()), 1)

    def test_get_channel_by_name(self):
        ch, _ = _make_channel("my_ch")
        self.router.register_channel(ch)
        self.assertIsNotNone(self.router.get_channel("my_ch"))
        self.assertIsNone(self.router.get_channel("nonexistent"))

    def test_unregister_channel(self):
        ch, _ = _make_channel()
        self.router.register_channel(ch)
        self.assertTrue(self.router.unregister_channel("test_channel"))
        self.assertIsNone(self.router.get_channel("test_channel"))

    def test_unregister_nonexistent_returns_false(self):
        self.assertFalse(self.router.unregister_channel("ghost"))

    def test_register_invalid_object_returns_false(self):
        self.assertFalse(self.router.register_channel(object()))  # type: ignore

    def test_multiple_channels(self):
        for i in range(3):
            ch, _ = _make_channel(f"ch_{i}")
            self.router.register_channel(ch)
        self.assertEqual(len(self.router.get_all_channels()), 3)


# ---------------------------------------------------------------------------
# Тесты отправки (send — синхронная)
# ---------------------------------------------------------------------------


class TestSendSync(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    # --- Прямой lookup по полю "channel" ---

    def test_send_explicit_channel_success(self):
        """Если msg['channel'] задан явно — прямой O(1) lookup, маршрут не нужен."""
        result = self.router.send(
            {
                "type": "command",
                "command": "do_work",
                "channel": "test_channel",
                "data": {},
            }
        )
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.q.empty())

    def test_send_explicit_channel_payload_correct(self):
        msg = {"command": "ping", "channel": "test_channel", "value": 42}
        self.router.send(msg)
        received = self.q.get_nowait()
        self.assertEqual(received["command"], "ping")
        self.assertEqual(received["value"], 42)

    def test_send_unknown_explicit_channel_returns_error(self):
        result = self.router.send({"channel": "no_such_channel", "command": "x"})
        self.assertEqual(result["status"], "error")

    # --- Маршрутизация через channel_dispatcher ---

    def test_send_via_registered_route(self):
        """register_route() связывает команду с каналом через channel_dispatcher."""
        self.router.register_route("my_cmd", "test_channel")
        result = self.router.send({"command": "my_cmd", "data": {}})
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.q.empty())

    def test_send_without_route_returns_error(self):
        """Без явного channel и без маршрута — ошибка (нет тихого fallback)."""
        result = self.router.send({"command": "unregistered_cmd", "data": {}})
        self.assertEqual(result["status"], "error")

    def test_send_increments_sent_attempted(self):
        self.router.send({"channel": "test_channel", "command": "a"})
        self.router.send({"channel": "test_channel", "command": "b"})
        stats = self.router.get_stats()
        self.assertEqual(stats["router"]["sent_attempted"], 2)

    def test_send_ok_counter_incremented_on_success(self):
        self.router.send({"channel": "test_channel", "command": "ok"})
        stats = self.router.get_stats()
        self.assertEqual(stats["router"]["sent_ok"], 1)

    def test_sent_ok_not_incremented_on_error(self):
        self.router.send({"command": "x"})  # нет канала → ошибка
        stats = self.router.get_stats()
        self.assertEqual(stats["router"]["sent_ok"], 0)


# ---------------------------------------------------------------------------
# Тесты отправки broadcast
# ---------------------------------------------------------------------------


class TestBroadcast(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch1, self.q1 = _make_channel("ch1")
        self.ch2, self.q2 = _make_channel("ch2")
        self.router.register_channel(self.ch1)
        self.router.register_channel(self.ch2)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_register_broadcast_route_delivers_to_all(self):
        self.router.register_broadcast_route("alert", ["ch1", "ch2"])
        result = self.router.send({"command": "alert", "data": "fire!"})
        self.assertEqual(result["status"], "success")
        self.assertTrue(result.get("broadcast"))
        self.assertFalse(self.q1.empty())
        self.assertFalse(self.q2.empty())

    def test_broadcast_results_contain_channel_names(self):
        self.router.register_broadcast_route("notify", ["ch1", "ch2"])
        result = self.router.send({"command": "notify"})
        channels_in_result = {r["channel"] for r in result["results"]}
        self.assertIn("ch1", channels_in_result)
        self.assertIn("ch2", channels_in_result)


# ---------------------------------------------------------------------------
# Тесты получения (receive — sync poll)
# ---------------------------------------------------------------------------


class TestReceive(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_receive_returns_message_objects(self):
        self.q.put({"type": "command", "command": "hello", "data": {}})
        messages = self.router.receive(timeout=0.1)
        self.assertEqual(len(messages), 1)

    def test_receive_message_dict_access(self):
        """Message поддерживает dict-интерфейс: msg['field']."""
        self.q.put({"type": "command", "command": "test_recv", "data": {}})
        messages = self.router.receive(timeout=0.1)
        self.assertEqual(messages[0]["command"], "test_recv")

    def test_receive_returns_dicts_when_requested(self):
        self.q.put({"type": "log", "level": "info", "message": "hi"})
        messages = self.router.receive(timeout=0.1, return_messages=False)
        self.assertIsInstance(messages[0], dict)

    def test_receive_empty_channel_returns_empty_list(self):
        messages = self.router.receive(timeout=0.0)
        self.assertEqual(messages, [])

    def test_receive_increments_received_counter(self):
        self.q.put({"type": "command", "command": "c1"})
        self.q.put({"type": "command", "command": "c2"})
        self.router.receive()
        stats = self.router.get_stats()
        self.assertEqual(stats["router"]["received"], 2)

    def test_receive_source_channel_tagged(self):
        """Входящие сообщения помечаются _source_channel."""
        self.q.put({"type": "command", "command": "tagged"})
        messages = self.router.receive(return_messages=False)
        self.assertEqual(messages[0].get("_source_channel"), "test_channel")


# ---------------------------------------------------------------------------
# Тесты channel_types (фильтр суффикса после префикса процесса)
# ---------------------------------------------------------------------------


class TestChannelTypesFilter(unittest.TestCase):
    def setUp(self):
        proc = SimpleNamespace(name="proc")
        self.router = RouterManager(manager_name="rt", process=proc)
        self.ch_sys, self.q_sys = _make_channel("proc_system")
        self.ch_data, self.q_data = _make_channel("proc_data")
        self.router.register_channel(self.ch_sys)
        self.router.register_channel(self.ch_data)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_receive_with_channel_types_filter(self):
        self.q_sys.put({"type": "command", "command": "sys_cmd"})
        self.q_data.put({"type": "command", "command": "data_cmd"})
        msgs = self.router.receive(
            timeout=0.2,
            return_messages=False,
            channel_types=["system"],
        )
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].get("command"), "sys_cmd")


# ---------------------------------------------------------------------------
# Тесты register_channel — инъекция логгера
# ---------------------------------------------------------------------------


class TestAttachLogger(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_attach_logger_injects_callbacks(self):
        ch, _ = _make_channel("logged_ch")
        pre_w, pre_e = ch._log_warning, ch._log_error
        self.router.register_channel(ch)
        # bound methods — разные объекты, но те же реализации от этого RouterManager
        self.assertIs(ch._log_warning.__self__, self.router)
        self.assertIs(ch._log_error.__self__, self.router)
        self.assertIsNot(ch._log_warning, pre_w)
        self.assertIsNot(ch._log_error, pre_e)


# ---------------------------------------------------------------------------
# Тесты message_dispatcher — обработчики входящих
# ---------------------------------------------------------------------------


class TestMessageHandlers(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_register_message_handler_returns_true(self):
        result = self.router.register_message_handler(
            "process_data",
            lambda msg: None,
        )
        self.assertTrue(result)

    def test_message_handler_called_on_receive(self):
        received: list = []

        def handler(msg):
            received.append(msg.get("command") if isinstance(msg, dict) else msg["command"])

        self.router.register_message_handler("on_event", handler)
        self.q.put({"type": "command", "command": "on_event", "data": {}})
        self.router.receive(timeout=0.1)
        self.assertEqual(received, ["on_event"])

    def test_multiple_handlers_for_different_keys(self):
        log: list = []
        self.router.register_message_handler("cmd_a", lambda m: log.append("a"))
        self.router.register_message_handler("cmd_b", lambda m: log.append("b"))
        self.q.put({"command": "cmd_a"})
        self.q.put({"command": "cmd_b"})
        self.router.receive()
        self.assertIn("a", log)
        self.assertIn("b", log)

    def test_unregistered_command_does_not_crash(self):
        """Нет handler'а — message_dispatcher просто не вызывает ничего, без исключения."""
        self.q.put({"command": "unknown_xyz", "data": {}})
        messages = self.router.receive(timeout=0.1)
        self.assertEqual(len(messages), 1)


# ---------------------------------------------------------------------------
# Тесты send_async
# ---------------------------------------------------------------------------


class TestSendAsync(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_send_async_is_non_blocking(self):
        """send_async() возвращает управление немедленно (None)."""
        result = self.router.send_async(
            {"command": "ping", "channel": "test_channel"},
            priority="normal",
        )
        self.assertIsNone(result)

    def test_send_async_delivers_message(self):
        self.router.send_async(
            {"command": "async_cmd", "channel": "test_channel"},
            priority="high",
        )
        time.sleep(0.3)  # даём фоновому потоку время обработать
        self.assertFalse(self.q.empty())
        msg = self.q.get_nowait()
        self.assertEqual(msg["command"], "async_cmd")

    def test_send_async_increments_queued_async(self):
        self.router.send_async({"channel": "test_channel", "command": "x"})
        time.sleep(0.1)
        stats = self.router.get_stats()
        self.assertGreaterEqual(stats["router"]["queued_async"], 1)

    def test_send_async_all_priorities_accepted(self):
        for prio in ("urgent", "high", "normal", "low"):
            self.router.send_async(
                {"channel": "test_channel", "command": f"cmd_{prio}"},
                priority=prio,
            )
        time.sleep(0.4)
        count = 0
        while not self.q.empty():
            self.q.get_nowait()
            count += 1
        self.assertEqual(count, 4)


# ---------------------------------------------------------------------------
# Тесты middleware
# ---------------------------------------------------------------------------


class TestMiddleware(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_send_middleware_can_enrich_message(self):
        def add_signature(msg: dict):
            msg["_signed"] = True
            return msg

        self.router.add_send_middleware(add_signature)
        self.router.send({"command": "x", "channel": "test_channel"})
        received = self.q.get_nowait()
        self.assertTrue(received.get("_signed"))

    def test_send_middleware_returning_none_drops_message(self):
        self.router.add_send_middleware(lambda msg: None)
        self.router.send({"command": "x", "channel": "test_channel"})
        self.assertTrue(self.q.empty())

    def test_receive_middleware_can_enrich_message(self):
        def tag_incoming(msg: dict):
            msg["_tagged"] = True
            return msg

        self.router.add_receive_middleware(tag_incoming)
        self.q.put({"type": "command", "command": "z"})
        messages = self.router.receive(return_messages=False)
        self.assertTrue(messages[0].get("_tagged"))

    def test_receive_middleware_returning_none_drops_message(self):
        self.router.add_receive_middleware(lambda msg: None)
        self.q.put({"type": "command", "command": "drop_me"})
        messages = self.router.receive()
        self.assertEqual(len(messages), 0)
        stats = self.router.get_stats()
        self.assertGreaterEqual(stats["router"]["middleware_dropped"], 1)

    def test_clear_middleware_removes_all(self):
        self.router.add_send_middleware(lambda m: None)
        self.router.add_receive_middleware(lambda m: None)
        self.router.clear_middleware()
        # После очистки сообщение должно пройти через send
        result = self.router.send({"command": "ok", "channel": "test_channel"})
        self.assertEqual(result["status"], "success")

    def test_multiple_send_middlewares_chained(self):
        def step1(msg):
            msg["s1"] = True
            return msg

        def step2(msg):
            msg["s2"] = True
            return msg

        self.router.add_send_middleware(step1)
        self.router.add_send_middleware(step2)
        self.router.send({"command": "x", "channel": "test_channel"})
        received = self.q.get_nowait()
        self.assertTrue(received.get("s1"))
        self.assertTrue(received.get("s2"))

    def test_receive_middleware_exception_then_second_runs(self):
        def broken(msg: dict):
            raise RuntimeError("mw1")

        def enrich(msg: dict):
            msg["_after_bad"] = True
            return msg

        self.router.add_receive_middleware(broken)
        self.router.add_receive_middleware(enrich)
        self.q.put({"type": "command", "command": "pipe_test"})
        messages = self.router.receive(timeout=0.1, return_messages=False)
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].get("_after_bad"))


# ---------------------------------------------------------------------------
# Тесты register_channel_handler (backward compat)
# ---------------------------------------------------------------------------


class TestChannelHandlerBackwardCompat(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_register_channel_handler_returns_true(self):
        """register_channel_handler() теперь делегирует в channel_dispatcher."""
        result = self.router.register_channel_handler(
            key="legacy_route",
            handler=lambda msg: "test_channel",
            efficiency=5,
        )
        self.assertTrue(result)

    def test_registered_handler_visible_in_stats(self):
        self.router.register_channel_handler(
            key="legacy_key",
            handler=lambda msg: "test_channel",
        )
        stats = self.router.get_stats()
        self.assertGreaterEqual(stats["router"]["channel_handlers"], 1)

    def test_registered_handler_routes_message(self):
        """Handler возвращает имя канала → сообщение уходит туда."""
        self.router.register_channel_handler(
            key="legacy_cmd",
            handler=lambda msg: "test_channel",
        )
        result = self.router.send({"command": "legacy_cmd", "data": {}})
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.q.empty())


# ---------------------------------------------------------------------------
# Тесты get_dispatcher_info
# ---------------------------------------------------------------------------


class TestDispatcherInfo(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_get_dispatcher_info_returns_both_dispatchers(self):
        info = self.router.get_dispatcher_info()
        self.assertIn("channel_dispatcher", info)
        self.assertIn("message_dispatcher", info)

    def test_dispatcher_info_has_required_keys(self):
        info = self.router.get_dispatcher_info()
        for key in ("name", "handler_count", "handlers", "scenarios"):
            self.assertIn(key, info["channel_dispatcher"], f"missing key: {key}")
            self.assertIn(key, info["message_dispatcher"], f"missing key: {key}")

    def test_dispatcher_info_counts_match_registered(self):
        ch, _ = _make_channel()
        self.router.register_channel(ch)
        self.router.register_route("cmd_x", "test_channel")
        self.router.register_message_handler("on_x", lambda m: None)

        info = self.router.get_dispatcher_info()
        self.assertEqual(info["channel_dispatcher"]["handler_count"], 1)
        self.assertEqual(info["message_dispatcher"]["handler_count"], 1)


# ---------------------------------------------------------------------------
# Тесты статистики
# ---------------------------------------------------------------------------


class TestStats(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_stats_has_router_key(self):
        stats = self.router.get_stats()
        self.assertIn("router", stats)

    def test_stats_sent_attempted_counter(self):
        for _ in range(5):
            self.router.send({"channel": "test_channel", "command": "x"})
        self.assertEqual(self.router.get_stats()["router"]["sent_attempted"], 5)

    def test_stats_sent_ok_counter(self):
        for _ in range(3):
            self.router.send({"channel": "test_channel", "command": "x"})
        self.router.send({"command": "x"})  # ошибка — нет канала
        stats = self.router.get_stats()["router"]
        self.assertEqual(stats["sent_ok"], 3)
        self.assertEqual(stats["sent_attempted"], 4)

    def test_stats_error_counter(self):
        self.router.send({"command": "x"})  # нет канала → ошибка
        stats = self.router.get_stats()["router"]
        self.assertGreaterEqual(stats["errors"], 1)

    def test_stats_channel_handlers_is_int(self):
        stats = self.router.get_stats()["router"]
        self.assertIsInstance(stats["channel_handlers"], int)

    def test_stats_message_handlers_is_int(self):
        stats = self.router.get_stats()["router"]
        self.assertIsInstance(stats["message_handlers"], int)

    def test_stats_channels_count(self):
        stats = self.router.get_stats()["router"]
        self.assertEqual(stats["channels_count"], 1)

    def test_stats_send_queue_size(self):
        stats = self.router.get_stats()["router"]
        self.assertIn("send_queue_size", stats)


# ---------------------------------------------------------------------------
# Тесты async listener
# ---------------------------------------------------------------------------


class TestAsyncListener(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_start_stop_listening(self):
        self.assertTrue(self.router.start_listening())
        time.sleep(0.05)
        stats = self.router.get_stats()["router"]
        self.assertTrue(stats["listener_alive"])
        self.assertTrue(self.router.stop_listening())
        time.sleep(0.1)
        stats = self.router.get_stats()["router"]
        self.assertFalse(stats["listener_alive"])

    def test_message_callback_called_on_incoming(self):
        received: list = []
        self.router.add_message_callback(lambda msg: received.append(msg))
        self.router.start_listening(poll_interval=0.01)

        self.q.put({"type": "command", "command": "cb_test"})
        time.sleep(0.3)
        self.router.stop_listening()

        self.assertEqual(len(received), 1)

    def test_remove_callback(self):
        def cb(msg):
            pass

        self.router.add_message_callback(cb)
        self.router.remove_message_callback(cb)
        stats = self.router.get_stats()["router"]
        self.assertEqual(stats["callbacks_count"], 0)


# ---------------------------------------------------------------------------
# Тесты thread-safety
# ---------------------------------------------------------------------------


class TestThreadSafety(unittest.TestCase):
    """Параллельная регистрация / удаление каналов и колбэков не должна
    приводить к race condition или исключениям."""

    def setUp(self):
        self.router = _make_router("thread_safe_router")
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_concurrent_register_unregister(self):
        """Несколько потоков одновременно регистрируют и удаляют каналы."""
        errors: list = []

        def worker(i: int) -> None:
            try:
                ch, _ = _make_channel(f"ch_thread_{i}")
                self.router.register_channel(ch)
                time.sleep(0.01)
                self.router.unregister_channel(f"ch_thread_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Errors in threads: {errors}")

    def test_concurrent_send_async(self):
        """Много потоков вызывают send_async одновременно — нет дедлока."""
        ch, q = _make_channel("bulk_ch")
        self.router.register_channel(ch)
        errors: list = []

        def sender(i: int) -> None:
            try:
                self.router.send_async(
                    {"channel": "bulk_ch", "command": f"cmd_{i}"},
                    priority="normal",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=sender, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Errors in send_async threads: {errors}")
        time.sleep(0.5)
        count = 0
        while not q.empty():
            q.get_nowait()
            count += 1
        self.assertGreater(count, 0)

    def test_concurrent_add_remove_callbacks(self):
        """Потоки добавляют и удаляют колбэки одновременно."""
        errors: list = []

        def adder(cb: Callable) -> None:
            try:
                self.router.add_message_callback(cb)
            except Exception as e:
                errors.append(e)

        def remover(cb: Callable) -> None:
            try:
                self.router.remove_message_callback(cb)
            except Exception as e:
                errors.append(e)

        callbacks = [lambda msg, i=i: None for i in range(10)]
        threads = [threading.Thread(target=adder, args=(cb,)) for cb in callbacks] + [
            threading.Thread(target=remover, args=(cb,)) for cb in callbacks
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Errors in callback threads: {errors}")

    def test_get_stats_during_concurrent_sends(self):
        """get_stats() вызван во время активных отправок — не падает."""
        ch, _ = _make_channel("stats_ch")
        self.router.register_channel(ch)
        stop = threading.Event()
        errors: list = []

        def continuous_sender() -> None:
            while not stop.is_set():
                try:
                    self.router.send_async({"channel": "stats_ch", "command": "x"})
                    time.sleep(0.005)
                except Exception as e:
                    errors.append(e)

        t = threading.Thread(target=continuous_sender, daemon=True)
        t.start()
        try:
            for _ in range(20):
                stats = self.router.get_stats()
                self.assertIn("router", stats)
                time.sleep(0.01)
        finally:
            stop.set()
            t.join(timeout=3.0)

        self.assertEqual(errors, [], f"Errors in concurrent stats test: {errors}")

    def test_concurrent_stats_consistency(self):
        """sent_attempted совпадает с числом sync send + send_async под нагрузкой."""
        ch, _ = _make_channel("stats_mix")
        self.router.register_channel(ch)
        n = 25
        errors: list = []

        def sync_send(i: int) -> None:
            try:
                self.router.send({"channel": "stats_mix", "command": f"s{i}"})
            except Exception as e:
                errors.append(e)

        def async_send(i: int) -> None:
            try:
                self.router.send_async({"channel": "stats_mix", "command": f"a{i}"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=sync_send, args=(i,)) for i in range(n)] + [
            threading.Thread(target=async_send, args=(i,)) for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
        self.assertEqual(errors, [], f"thread errors: {errors}")
        time.sleep(1.0)
        stats = self.router.get_stats()["router"]
        self.assertEqual(stats["sent_attempted"], 2 * n)


# ---------------------------------------------------------------------------
# Тесты middleware — исключение в fn не убивает pipeline
# ---------------------------------------------------------------------------


class TestMiddlewareRobustness(unittest.TestCase):
    def setUp(self):
        self.router = _make_router()
        self.ch, self.q = _make_channel()
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_exception_in_send_middleware_does_not_drop_message(self):
        """Если middleware бросает исключение — pipeline продолжается."""

        def broken(msg: dict):
            raise RuntimeError("middleware bug")

        self.router.add_send_middleware(broken)
        result = self.router.send({"command": "x", "channel": "test_channel"})
        # broken middleware пропускается, сообщение доходит
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.q.empty())

    def test_exception_in_receive_middleware_does_not_drop_message(self):
        """Если receive middleware бросает — сообщение доходит до result."""

        def broken(msg: dict):
            raise ValueError("oops")

        self.router.add_receive_middleware(broken)
        self.q.put({"type": "command", "command": "robust_test"})
        messages = self.router.receive(timeout=0.1)
        self.assertEqual(len(messages), 1)


class _FakeQueueRegistry:
    """Мини queue_registry для проверки target-aware fallback."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_to_queue(self, target, qtype, msg) -> bool:
        self.sent.append((target, qtype, msg))
        return True


class TestTargetAwareDeliveryFallback(unittest.TestCase):
    """U1: _do_send fallback — доставка по msg['targets'] через queue_registry,
    когда channel/route не резолвится (раньше здесь был silent drop)."""

    def test_targets_without_channel_delivered_via_queue_registry(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb1", queue_registry=qr)
        result = router.send(
            {
                "type": "event",
                "command": "state.changed",
                "targets": ["gui"],
                "queue_type": "system",
                "data": {"deltas": []},
            }
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(qr.sent), 1)
        target, qtype, _msg = qr.sent[0]
        self.assertEqual(target, "gui")
        self.assertEqual(qtype, "system")

    def test_explicit_queue_type_respected(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb2", queue_registry=qr)
        router.send({"type": "event", "command": "ev", "targets": ["p"], "queue_type": "system"})
        self.assertEqual(qr.sent[0][1], "system")

    def test_command_defaults_to_system_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb3", queue_registry=qr)
        router.send({"type": "command", "command": "do.thing", "targets": ["worker_a"]})
        self.assertEqual(qr.sent[0][1], "system")

    def test_non_command_defaults_to_data_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb4", queue_registry=qr)
        router.send({"type": "event", "command": "ev", "targets": ["p"]})
        self.assertEqual(qr.sent[0][1], "data")

    def test_explicit_channel_not_hijacked_by_targets(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb5", queue_registry=qr)
        ch, q = _make_channel("explicit_ch")
        router.register_channel(ch)
        router.send({"channel": "explicit_ch", "targets": ["gui"], "command": "x"})
        # Канал зарезолвился → fallback не сработал, queue_registry не тронут
        self.assertEqual(len(qr.sent), 0)
        self.assertFalse(q.empty())

    def test_vestigial_unregistered_channel_still_delivered_by_targets(self):
        # recon #3: кадры несут vestigial channel="data" (канал с таким именем НЕ
        # зарегистрирован). Раньше guard на msg["channel"] дропал такие сообщения —
        # теперь, раз канал не зарезолвился, доставляем по targets в data-очередь.
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb5b", queue_registry=qr)
        result = router.send(
            {
                "type": "data",
                "channel": "data",
                "targets": ["display_proc"],
                "data": {"shm_name": "slot0", "shm_actual_name": "psm_1234"},
            }
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(qr.sent), 1)
        target, qtype, _msg = qr.sent[0]
        self.assertEqual(target, "display_proc")
        self.assertEqual(qtype, "data")

    def test_no_targets_no_channel_returns_error(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_fb6", queue_registry=qr)
        result = router.send({"type": "event", "command": "orphan_no_route"})
        self.assertEqual(result.get("status"), "error")
        self.assertEqual(len(qr.sent), 0)

    def test_fallback_skipped_when_no_queue_registry(self):
        router = RouterManager(manager_name="r_fb7")  # queue_registry=None
        result = router.send({"type": "event", "command": "x", "targets": ["gui"]})
        self.assertEqual(result.get("status"), "error")


class TestHierarchicalDelivery(unittest.TestCase):
    """P2.1: cross-process доставка по address[0]; воркер+ едет в билете (_address)."""

    def test_flat_target_parity_no_address_key(self):
        # Плоское имя → паритет: та же очередь, билет БЕЗ _address (ноль изменений).
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_h1", queue_registry=qr)
        router.send({"type": "command", "command": "do.thing", "targets": ["worker_a"]})
        self.assertEqual(len(qr.sent), 1)
        process, qtype, ticket = qr.sent[0]
        self.assertEqual(process, "worker_a")
        self.assertEqual(qtype, "system")
        self.assertNotIn("_address", ticket)

    def test_dotted_target_delivered_to_process_queue_carries_address(self):
        # "proc.worker" → очередь "proc", билет несёт полный address.
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_h2", queue_registry=qr)
        router.send({"type": "data", "targets": ["display_proc.slot1"], "data": {}})
        self.assertEqual(len(qr.sent), 1)
        process, qtype, ticket = qr.sent[0]
        self.assertEqual(process, "display_proc")  # address[0]
        self.assertEqual(qtype, "data")
        self.assertEqual(ticket["_address"], ["display_proc", "slot1"])

    def test_deep_address_preserved_in_ticket(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_h3", queue_registry=qr)
        router.send({"type": "command", "command": "c", "targets": ["p.w.sub"]})
        process, _qtype, ticket = qr.sent[0]
        self.assertEqual(process, "p")
        self.assertEqual(ticket["_address"], ["p", "w", "sub"])

    def test_invalid_address_skipped_not_crashing(self):
        # Воркер без процесса (".worker") нарушает prefix-правило → пропуск, не падение.
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_h4", queue_registry=qr)
        result = router.send({"type": "command", "command": "c", "targets": [".worker", "valid_proc"]})
        # Невалидный пропущен, валидный доставлен.
        self.assertEqual(len(qr.sent), 1)
        self.assertEqual(qr.sent[0][0], "valid_proc")
        self.assertEqual(result.get("status"), "success")

    def test_multicast_per_target_address_isolated(self):
        # Мультикаст с разными воркерами: каждая очередь несёт СВОЙ address.
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="r_h5", queue_registry=qr)
        router.send({"type": "data", "targets": ["procA.w1", "procB.w2"], "data": {}})
        self.assertEqual(len(qr.sent), 2)
        by_proc = {process: ticket for process, _q, ticket in qr.sent}
        self.assertEqual(by_proc["procA"]["_address"], ["procA", "w1"])
        self.assertEqual(by_proc["procB"]["_address"], ["procB", "w2"])


if __name__ == "__main__":
    unittest.main()
