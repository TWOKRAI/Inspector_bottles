"""
Тесты для методов регистрации ProcessManager.

Проверяют:
- load_process_config с переопределением
- register_process
- register_queue
- register_worker
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from multiprocess_framework.modules.Process_manager_module import ProcessManager


class TestProcessManagerRegistration:
    """Тесты методов регистрации ProcessManager"""
    
    @pytest.fixture
    def process_manager(self):
        """Создает ProcessManager для тестов"""
        return ProcessManager()
    
    @pytest.fixture
    def base_config(self):
        """Базовый конфиг для тестов"""
        return {
            "test_process": {
                "name": "test_process",
                "class": "src.Test_example.multiprocess_chat_app.ChatProcess",
                "priority": "normal",
                "enabled": True,
                "config": {
                    "key1": "value1",
                    "nested": {
                        "key2": "value2"
                    }
                }
            }
        }
    
    def test_load_process_config_new_process(self, process_manager, base_config):
        """Тест загрузки конфига для нового процесса"""
        # Загружаем базовый конфиг
        process_manager.config_manager.update_process_config(base_config)
        
        # Загружаем новый процесс
        new_config = {
            "new_process": {
                "name": "new_process",
                "class": "src.Test_example.multiprocess_chat_app.ChatProcess",
                "priority": "high",
                "enabled": True
            }
        }
        
        result = process_manager.load_process_config("new_process", new_config)
        assert result is True
        
        # Проверяем что процесс добавлен
        config = process_manager.get_process_config()
        assert "new_process" in config
        assert config["new_process"]["priority"] == "high"
    
    def test_load_process_config_override(self, process_manager, base_config):
        """Тест переопределения конфига существующего процесса"""
        # Загружаем базовый конфиг
        process_manager.config_manager.update_process_config(base_config)
        
        # Переопределяем конфиг
        override_config = {
            "test_process": {
                "priority": "high",  # Изменяем приоритет
                "config": {
                    "key1": "new_value1",  # Переопределяем значение
                    "nested": {
                        "key2": "new_value2",  # Переопределяем вложенное
                        "key3": "new_value3"  # Добавляем новое
                    }
                }
            }
        }
        
        result = process_manager.load_process_config("test_process", override_config)
        assert result is True
        
        # Проверяем что конфиг переопределен
        config = process_manager.get_process_config()
        process_config = config["test_process"]
        
        assert process_config["priority"] == "high"
        assert process_config["config"]["key1"] == "new_value1"
        assert process_config["config"]["nested"]["key2"] == "new_value2"
        assert process_config["config"]["nested"]["key3"] == "new_value3"
        # Проверяем что базовые поля сохранены
        assert process_config["name"] == "test_process"
    
    def test_register_process(self, process_manager):
        """Тест программной регистрации процесса"""
        result = process_manager.register_process(
            name="test_process",
            class_path="src.Test_example.multiprocess_chat_app.ChatProcess",
            config={"key": "value"},
            priority="high",
            enabled=True
        )
        
        assert result is True
        
        # Проверяем что процесс зарегистрирован
        config = process_manager.get_process_config()
        assert "test_process" in config
        assert config["test_process"]["priority"] == "high"
        assert config["test_process"]["config"]["key"] == "value"
    
    def test_register_queue(self, process_manager, base_config):
        """Тест регистрации очереди"""
        # Загружаем базовый конфиг
        process_manager.config_manager.update_process_config(base_config)
        
        result = process_manager.register_queue(
            process_name="test_process",
            queue_name="test_queue",
            maxsize=50
        )
        
        assert result is True
        
        # Проверяем что очередь зарегистрирована
        config = process_manager.get_process_config()
        assert "queues" in config["test_process"]
        assert "test_queue" in config["test_process"]["queues"]
        assert config["test_process"]["queues"]["test_queue"]["maxsize"] == 50
    
    def test_register_worker(self, process_manager, base_config):
        """Тест регистрации воркера"""
        # Загружаем базовый конфиг
        process_manager.config_manager.update_process_config(base_config)
        
        result = process_manager.register_worker(
            process_name="test_process",
            worker_name="test_worker",
            worker_class_path="TestModule.TestWorker",
            config={"interval": 1.0},
            priority="high",
            auto_start=True
        )
        
        assert result is True
        
        # Проверяем что воркер зарегистрирован
        config = process_manager.get_process_config()
        assert "workers" in config["test_process"]
        assert "test_worker" in config["test_process"]["workers"]
        worker_config = config["test_process"]["workers"]["test_worker"]
        assert worker_config["priority"] == "high"
        assert worker_config["auto_start"] is True
        assert worker_config["config"]["interval"] == 1.0
    
    def test_deep_merge(self, process_manager):
        """Тест рекурсивного объединения словарей"""
        base = {
            "key1": "value1",
            "nested": {
                "key2": "value2",
                "key3": "value3"
            }
        }
        
        override = {
            "key1": "new_value1",
            "nested": {
                "key2": "new_value2",
                "key4": "new_value4"
            }
        }
        
        result = process_manager._deep_merge(base, override)
        
        assert result["key1"] == "new_value1"
        assert result["nested"]["key2"] == "new_value2"
        assert result["nested"]["key3"] == "value3"  # Сохранено из base
        assert result["nested"]["key4"] == "new_value4"  # Добавлено из override

