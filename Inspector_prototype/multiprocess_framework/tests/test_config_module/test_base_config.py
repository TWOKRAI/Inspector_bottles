"""
Тесты для базового класса Config.

Проверяет:
- Инициализацию конфигурации
- Базовые операции (get, set, has, remove)
- Работу с вложенными ключами
- Магические методы
- Работу с секциями
- Потокобезопасность
"""
import pytest
import threading
import tempfile
import os
from pathlib import Path

from multiprocess_framework.modules.Config_module import Config, ConfigSection


class TestConfigBasic:
    """Тесты базовой функциональности Config"""
    
    def test_init_empty(self):
        """Тест создания пустой конфигурации"""
        config = Config()
        assert len(config) == 0
        assert config.file_path is None
    
    def test_init_with_data(self):
        """Тест создания конфигурации с начальными данными"""
        initial_data = {'database': {'host': 'localhost', 'port': 5432}}
        config = Config(initial_data=initial_data)
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
    
    def test_init_with_file_path(self, temp_dir):
        """Тест создания конфигурации с автоматической загрузкой из файла"""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML не установлен")
        
        # Создаем временный файл
        yaml_path = temp_dir / 'config.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write('database:\n  host: localhost\n  port: 5432\n')
        
        config = Config(file_path=str(yaml_path))
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.file_path is not None
    
    def test_set_and_get(self, config):
        """Тест установки и получения значений"""
        config.set('key1', 'value1')
        assert config.get('key1') == 'value1'
        
        config.set('key2', 42)
        assert config.get('key2') == 42
        
        config.set('key3', True)
        assert config.get('key3') is True
    
    def test_nested_keys(self, config):
        """Тест работы с вложенными ключами"""
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        config.set('database.name', 'mydb')
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('database.name') == 'mydb'
    
    def test_deep_nested_keys(self, config):
        """Тест работы с глубоко вложенными ключами"""
        config.set('app.database.connection.host', 'localhost')
        config.set('app.database.connection.port', 5432)
        
        assert config.get('app.database.connection.host') == 'localhost'
        assert config.get('app.database.connection.port') == 5432
    
    def test_get_with_default(self, config):
        """Тест получения значения с значением по умолчанию"""
        assert config.get('nonexistent', 'default') == 'default'
        assert config.get('nonexistent', 42) == 42
        assert config.get('nonexistent') is None
    
    def test_has(self, config):
        """Тест проверки наличия ключа"""
        config.set('key1', 'value1')
        config.set('database.host', 'localhost')
        
        assert config.has('key1') is True
        assert config.has('database.host') is True
        assert config.has('nonexistent') is False
        assert config.has('database.port') is False
    
    def test_remove(self, config):
        """Тест удаления ключа"""
        config.set('key1', 'value1')
        config.set('database.host', 'localhost')
        
        assert config.remove('key1') is True
        assert config.has('key1') is False
        
        assert config.remove('database.host') is True
        assert config.has('database.host') is False
        
        assert config.remove('nonexistent') is False
    
    def test_clear(self, config):
        """Тест очистки конфигурации"""
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        
        config.clear()
        assert len(config) == 0
        assert config.has('key1') is False
        assert config.has('key2') is False
    
    def test_update(self, config):
        """Тест обновления конфигурации из словаря"""
        config.set('key1', 'old_value')
        
        config.update({'key1': 'new_value', 'key2': 'value2'})
        assert config.get('key1') == 'new_value'
        assert config.get('key2') == 'value2'
    
    def test_update_with_prefix(self, config):
        """Тест обновления конфигурации с префиксом"""
        config.update({'host': 'localhost', 'port': 5432}, prefix='database')
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
    
    def test_update_deep_merge(self, config):
        """Тест глубокого объединения при обновлении"""
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        
        config.update({'database': {'port': 3306, 'name': 'mydb'}})
        
        # Старые значения должны сохраниться
        assert config.get('database.host') == 'localhost'
        # Новые значения должны добавиться
        assert config.get('database.port') == 3306
        assert config.get('database.name') == 'mydb'
    
    def test_magic_methods(self, config):
        """Тест магических методов"""
        # __setitem__ и __getitem__
        config['key1'] = 'value1'
        assert config['key1'] == 'value1'
        
        # __contains__
        assert 'key1' in config
        assert 'nonexistent' not in config
        
        # __delitem__
        del config['key1']
        assert 'key1' not in config
        
        # __len__
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        assert len(config) == 2
        
        # __repr__
        repr_str = repr(config)
        assert 'Config' in repr_str
    
    def test_magic_methods_nested(self, config):
        """Тест магических методов с вложенными ключами"""
        config['database.host'] = 'localhost'
        assert config['database.host'] == 'localhost'
        
        assert 'database.host' in config
        
        del config['database.host']
        assert 'database.host' not in config
    
    def test_magic_methods_key_error(self, config):
        """Тест KeyError при использовании магических методов"""
        with pytest.raises(KeyError):
            _ = config['nonexistent']
        
        with pytest.raises(KeyError):
            del config['nonexistent']
    
    def test_data_property(self, config):
        """Тест свойства data (копия данных)"""
        config.set('key1', 'value1')
        config.set('database.host', 'localhost')
        
        data = config.data
        assert data['key1'] == 'value1'
        assert data['database']['host'] == 'localhost'
        
        # Изменение копии не должно влиять на оригинал
        data['key1'] = 'modified'
        assert config.get('key1') == 'value1'
    
    def test_file_path_property(self, config, temp_dir):
        """Тест свойства file_path"""
        assert config.file_path is None
        
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML не установлен")
        
        yaml_path = temp_dir / 'config.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write('key: value\n')
        
        config.load(str(yaml_path))
        assert config.file_path == Path(yaml_path)


class TestConfigSection:
    """Тесты для ConfigSection"""
    
    @pytest.fixture
    def config_with_section(self):
        """Создает конфигурацию с секцией database"""
        config = Config()
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        config.set('database.name', 'mydb')
        return config
    
    def test_section_get(self, config_with_section):
        """Тест получения значений из секции"""
        db_section = config_with_section.section('database')
        
        assert db_section.get('host') == 'localhost'
        assert db_section.get('port') == 5432
        assert db_section.get('name') == 'mydb'
    
    def test_section_set(self, config_with_section):
        """Тест установки значений в секции"""
        db_section = config_with_section.section('database')
        
        db_section.set('user', 'admin')
        db_section.set('password', 'secret')
        
        assert config_with_section.get('database.user') == 'admin'
        assert config_with_section.get('database.password') == 'secret'
    
    def test_section_update(self, config_with_section):
        """Тест обновления секции"""
        db_section = config_with_section.section('database')
        
        db_section.update({'user': 'admin', 'password': 'secret'})
        
        assert config_with_section.get('database.user') == 'admin'
        assert config_with_section.get('database.password') == 'secret'
    
    def test_section_has(self, config_with_section):
        """Тест проверки наличия ключа в секции"""
        db_section = config_with_section.section('database')
        
        assert db_section.has('host') is True
        assert db_section.has('port') is True
        assert db_section.has('user') is False
    
    def test_section_remove(self, config_with_section):
        """Тест удаления ключа из секции"""
        db_section = config_with_section.section('database')
        
        assert db_section.remove('host') is True
        assert config_with_section.has('database.host') is False
        
        assert db_section.remove('nonexistent') is False
    
    def test_section_data(self, config_with_section):
        """Тест получения всех данных секции"""
        db_section = config_with_section.section('database')
        
        data = db_section.data
        assert data['host'] == 'localhost'
        assert data['port'] == 5432
        assert data['name'] == 'mydb'
    
    def test_section_magic_methods(self, config_with_section):
        """Тест магических методов секции"""
        db_section = config_with_section.section('database')
        
        # __getitem__ и __setitem__
        db_section['user'] = 'admin'
        assert db_section['user'] == 'admin'
        
        # __contains__
        assert 'host' in db_section
        assert 'user' in db_section  # Теперь user существует после установки
        
        # __delitem__
        del db_section['host']
        assert 'host' not in db_section
    
    def test_section_sync(self, config_with_section):
        """Тест синхронизации секции с основным конфигом"""
        db_section = config_with_section.section('database')
        
        # Изменение через секцию
        db_section.set('user', 'admin')
        
        # Проверка через основной конфиг
        assert config_with_section.get('database.user') == 'admin'
        
        # Изменение через основной конфиг
        config_with_section.set('database.password', 'secret')
        
        # Проверка через секцию
        assert db_section.get('password') == 'secret'


class TestConfigThreadSafety:
    """Тесты потокобезопасности Config"""
    
    @pytest.fixture
    def config(self):
        """Создает конфигурацию для тестов потокобезопасности"""
        return Config()
    
    @pytest.fixture
    def results(self):
        """Создает список для хранения результатов"""
        return []
    
    @pytest.fixture
    def lock(self):
        """Создает блокировку для синхронизации"""
        return threading.Lock()
    
    def worker_set(self, config, thread_id, count):
        """Рабочая функция для установки значений"""
        for i in range(count):
            config.set(f'thread_{thread_id}.value_{i}', i)
    
    def worker_get(self, config, thread_id, count, results, lock):
        """Рабочая функция для получения значений"""
        for i in range(count):
            value = config.get(f'thread_{thread_id}.value_{i}')
            with lock:
                results.append((thread_id, i, value))
    
    def test_thread_safety_set(self, config):
        """Тест потокобезопасности при установке значений"""
        threads = []
        num_threads = 5
        operations_per_thread = 10
        
        for i in range(num_threads):
            t = threading.Thread(target=self.worker_set, args=(config, i, operations_per_thread))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Проверяем что все значения установлены
        for i in range(num_threads):
            for j in range(operations_per_thread):
                assert config.get(f'thread_{i}.value_{j}') == j
    
    def test_thread_safety_get(self, config, results, lock):
        """Тест потокобезопасности при получении значений"""
        # Устанавливаем значения
        for i in range(5):
            for j in range(10):
                config.set(f'thread_{i}.value_{j}', j)
        
        # Читаем из нескольких потоков
        threads = []
        for i in range(5):
            t = threading.Thread(
                target=self.worker_get,
                args=(config, i, 10, results, lock)
            )
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Проверяем что все значения получены корректно
        assert len(results) == 50
        for thread_id, index, value in results:
            assert value == index
    
    def test_thread_safety_mixed(self, config, results, lock):
        """Тест потокобезопасности при смешанных операциях"""
        def writer(thread_id):
            for i in range(10):
                config.set(f'key_{thread_id}_{i}', i)
        
        def reader(thread_id):
            for i in range(10):
                value = config.get(f'key_{thread_id}_{i}', -1)
                with lock:
                    if value != -1:
                        results.append((thread_id, i, value))
        
        threads = []
        # Создаем потоки записи
        for i in range(3):
            t = threading.Thread(target=writer, args=(i,))
            threads.append(t)
            t.start()
        
        # Создаем потоки чтения
        for i in range(3):
            t = threading.Thread(target=reader, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Проверяем что нет ошибок и все значения корректны
        assert len(results) > 0
