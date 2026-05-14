"""
Тесты для каналов сообщений.

Проверяет функциональность каналов:
- MessageChannel интерфейс
- QueueChannel реализация
- Отправка и получение сообщений
"""

import unittest
from queue import Queue
from typing import Dict, Any

from ..channels.base_channel import MessageChannel
from ..channels.queue_channel import QueueChannel


class TestMessageChannelInterface(unittest.TestCase):
    """Тесты для интерфейса MessageChannel."""

    def test_interface_definition(self):
        """Тест определения интерфейса."""
        # Проверяем, что MessageChannel - абстрактный класс
        with self.assertRaises(TypeError):
            MessageChannel()

    def test_interface_methods(self):
        """Тест наличия методов интерфейса."""
        # Проверяем наличие абстрактных методов
        self.assertTrue(hasattr(MessageChannel, "name"))
        self.assertTrue(hasattr(MessageChannel, "channel_type"))
        self.assertTrue(hasattr(MessageChannel, "send"))
        self.assertTrue(hasattr(MessageChannel, "poll"))
        self.assertTrue(hasattr(MessageChannel, "start_listening"))
        self.assertTrue(hasattr(MessageChannel, "stop_listening"))
        self.assertTrue(hasattr(MessageChannel, "get_info"))


class TestQueueChannel(unittest.TestCase):
    """Тесты для QueueChannel."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.queue = Queue()
        self.channel = QueueChannel("test_queue", self.queue)

    def test_channel_properties(self):
        """Тест свойств канала."""
        self.assertEqual(self.channel.name, "test_queue")
        self.assertEqual(self.channel.channel_type, "queue")

    def test_send_message(self):
        """Тест отправки сообщения."""
        message = {"type": "test", "data": {"test": "value"}}

        result = self.channel.send(message)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["channel"], "test_queue")
        self.assertFalse(self.queue.empty())

    def test_poll_message_non_blocking(self):
        """Тест получения сообщения (non-blocking)."""
        # Отправляем сообщение
        test_message = {"type": "test", "data": {"value": 123}}
        self.queue.put(test_message)

        # Получаем сообщения
        messages = self.channel.poll(timeout=0.0)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["data"]["value"], 123)

    def test_poll_empty_queue(self):
        """Тест опроса пустой очереди."""
        messages = self.channel.poll(timeout=0.0)

        self.assertEqual(len(messages), 0)

    def test_poll_with_timeout(self):
        """Тест опроса с таймаутом."""
        import threading
        import time

        # Запускаем поток, который добавит сообщение через 0.1 секунды
        def delayed_put():
            time.sleep(0.1)
            self.queue.put({"type": "delayed", "data": {}})

        thread = threading.Thread(target=delayed_put)
        thread.start()

        # Опрашиваем с таймаутом больше задержки
        messages = self.channel.poll(timeout=0.5)

        thread.join()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "delayed")

    def test_listening(self):
        """Тест асинхронного прослушивания."""
        received_messages = []

        def callback(message: Dict[str, Any]):
            received_messages.append(message)

        # Запускаем прослушивание
        result = self.channel.start_listening(callback)
        self.assertTrue(result)

        # Отправляем сообщение
        test_message = {"type": "listening_test", "data": {}}
        self.queue.put(test_message)

        # Ждем немного для обработки
        import time

        time.sleep(0.2)

        # Останавливаем прослушивание
        self.channel.stop_listening()

        # Проверяем, что сообщение было получено
        self.assertGreaterEqual(len(received_messages), 1)
        self.assertEqual(received_messages[0]["type"], "listening_test")

    def test_get_info(self):
        """Тест получения информации о канале."""
        info = self.channel.get_info()

        self.assertEqual(info["name"], "test_queue")
        self.assertEqual(info["type"], "queue")
        self.assertIn("queue_size", info)
        self.assertIn("listening", info)

    def test_multiple_messages(self):
        """Тест обработки нескольких сообщений."""
        # Отправляем несколько сообщений
        for i in range(5):
            self.channel.send({"type": "test", "index": i})

        # Получаем все сообщения
        messages = self.channel.poll(timeout=0.0)

        self.assertEqual(len(messages), 5)
        for i, msg in enumerate(messages):
            self.assertEqual(msg["index"], i)

    def test_channel_without_queue(self):
        """Тест создания канала без указания очереди."""
        channel = QueueChannel("auto_queue")

        self.assertEqual(channel.name, "auto_queue")
        self.assertIsNotNone(channel._queue)

        # Проверяем, что можно отправлять сообщения
        result = channel.send({"type": "test"})
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
