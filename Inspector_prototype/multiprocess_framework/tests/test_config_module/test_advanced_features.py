"""
Тесты для продвинутых функций Config.

Проверяет:
- Переменные окружения
- Подписку на изменения
- Обработку различных типов данных
"""
import pytest
import os
from unittest.mock import patch

from multiprocess_framework.modules.Config_module import Config


class TestEnvironmentVariables:
    """Тесты для работы с переменными окружения"""
    
    @pytest.fixture
    def config(self):
        """Создает конфигурацию с префиксом для переменных окружения"""
        return Config(env_prefix='TEST')
    
    def test_get_from_env_string(self, config):
        """Тест получения строкового значения из переменных окружения"""
        with patch.dict(os.environ, {'TEST_KEY': 'value_from_env'}):
            value = config.get('key', env_fallback=True)
            assert value == 'value_from_env'
    
    def test_get_from_env_int(self, config):
        """Тест получения целочисленного значения из переменных окружения"""
        with patch.dict(os.environ, {'TEST_DATABASE_PORT': '5432'}):
            value = config.get('database.port', env_fallback=True)
            assert value == 5432
            assert isinstance(value, int)
    
    def test_get_from_env_float(self, config):
        """Тест получения вещественного значения из переменных окружения"""
        with patch.dict(os.environ, {'TEST_VERSION': '1.5'}):
            value = config.get('version', env_fallback=True)
            assert value == 1.5
            assert isinstance(value, float)
    
    def test_get_from_env_bool_true(self, config):
        """Тест получения булева значения True из переменных окружения"""
        with patch.dict(os.environ, {'TEST_DEBUG': 'true'}):
            value = config.get('debug', env_fallback=True)
            assert value is True
            assert isinstance(value, bool)
    
    def test_get_from_env_bool_false(self, config):
        """Тест получения булева значения False из переменных окружения"""
        with patch.dict(os.environ, {'TEST_DEBUG': 'false'}):
            value = config.get('debug', env_fallback=True)
            assert value is False
            assert isinstance(value, bool)
    
    def test_get_from_env_nested_key(self, config):
        """Тест получения значения для вложенного ключа из переменных окружения"""
        with patch.dict(os.environ, {'TEST_DATABASE_HOST': 'localhost'}):
            value = config.get('database.host', env_fallback=True)
            assert value == 'localhost'
    
    def test_get_from_env_fallback_disabled(self, config):
        """Тест что переменные окружения не используются при env_fallback=False"""
        with patch.dict(os.environ, {'TEST_KEY': 'value_from_env'}):
            value = config.get('key', default='default_value', env_fallback=False)
            assert value == 'default_value'
    
    def test_get_from_env_no_prefix(self):
        """Тест что переменные окружения не используются без префикса"""
        config = Config()  # Без префикса
        with patch.dict(os.environ, {'KEY': 'value'}):
            value = config.get('key', env_fallback=True)
            assert value is None
    
    def test_get_from_env_priority(self, config):
        """Тест приоритета: значение из конфига важнее переменной окружения"""
        # Если значение есть в конфиге, оно используется
        config.set('key', 'value_from_config')
        with patch.dict(os.environ, {'TEST_KEY': 'value_from_env'}):
            # Значение из конфига имеет приоритет
            value = config.get('key', env_fallback=True)
            assert value == 'value_from_config'
        
        # Если значения нет в конфиге, используется переменная окружения
        config.remove('key')
        with patch.dict(os.environ, {'TEST_KEY': 'value_from_env'}):
            value = config.get('key', env_fallback=True)
            assert value == 'value_from_env'


class TestChangeCallbacks:
    """Тесты для подписки на изменения"""
    
    @pytest.fixture
    def config(self):
        """Создает конфигурацию для тестов"""
        return Config()
    
    @pytest.fixture
    def callback_calls(self):
        """Создает список для хранения вызовов callback"""
        return []
    
    def callback(self, callback_calls, key, old_value, new_value):
        """Вспомогательная функция callback"""
        callback_calls.append((key, old_value, new_value))
    
    def test_on_change_specific_key(self, config, callback_calls):
        """Тест подписки на изменения конкретного ключа"""
        config.on_change('database.host', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        
        # Должен быть вызван только для database.host
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('database.host', None, 'localhost')
    
    def test_on_change_all_keys(self, config, callback_calls):
        """Тест подписки на все изменения"""
        config.on_change('*', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        
        # Должны быть вызваны для всех ключей
        assert len(callback_calls) == 2
        assert ('key1', None, 'value1') in callback_calls
        assert ('key2', None, 'value2') in callback_calls
    
    def test_on_change_decorator(self, config, callback_calls):
        """Тест использования on_change как декоратор"""
        @config.on_change('key')
        def callback(key, old_value, new_value):
            self.callback(callback_calls, key, old_value, new_value)
        
        config.set('key', 'value')
        
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('key', None, 'value')
    
    def test_on_change_multiple_callbacks(self, config, callback_calls):
        """Тест множественных callback'ов для одного ключа"""
        def callback1(key, old_value, new_value):
            callback_calls.append(('callback1', key, old_value, new_value))
        
        def callback2(key, old_value, new_value):
            callback_calls.append(('callback2', key, old_value, new_value))
        
        config.on_change('key', callback1)
        config.on_change('key', callback2)
        
        config.set('key', 'value')
        
        # Оба callback'а должны быть вызваны
        assert len(callback_calls) == 2
    
    def test_on_change_old_and_new_value(self, config, callback_calls):
        """Тест что callback получает старое и новое значение"""
        config.set('key', 'old_value')
        
        config.on_change('key', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.set('key', 'new_value')
        
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('key', 'old_value', 'new_value')
    
    def test_on_change_not_notify(self, config, callback_calls):
        """Тест что notify=False не вызывает callback"""
        config.on_change('key', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.set('key', 'value', notify=False)
        
        # Callback не должен быть вызван
        assert len(callback_calls) == 0
    
    def test_on_change_update(self, config, callback_calls):
        """Тест что update вызывает callback"""
        config.on_change('*', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.update({'key1': 'value1', 'key2': 'value2'})
        
        # Должен быть вызван один раз для общего обновления
        assert len(callback_calls) > 0
    
    def test_on_change_remove(self, config, callback_calls):
        """Тест что remove вызывает callback"""
        config.set('key', 'value')
        config.on_change('key', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.remove('key')
        
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('key', 'value', None)
    
    def test_on_change_clear(self, config, callback_calls):
        """Тест что clear вызывает callback"""
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        config.on_change('*', lambda k, o, n: self.callback(callback_calls, k, o, n))
        
        config.clear()
        
        # Должен быть вызван callback для очистки
        assert len(callback_calls) > 0
    
    def test_on_change_callback_error(self, config, callback_calls):
        """Тест что ошибка в callback не прерывает выполнение"""
        def bad_callback(key, old_value, new_value):
            raise ValueError("Error in callback")
        
        def good_callback(key, old_value, new_value):
            self.callback(callback_calls, key, old_value, new_value)
        
        config.on_change('key', bad_callback)
        config.on_change('key', good_callback)
        
        # Оба callback'а должны быть вызваны, ошибка не должна прервать выполнение
        config.set('key', 'value')
        
        # Хороший callback должен быть вызван
        assert len(callback_calls) == 1


class TestDataTypes:
    """Тесты для различных типов данных"""
    
    @pytest.fixture
    def config(self):
        """Создает конфигурацию для тестов"""
        return Config()
    
    def test_string(self, config):
        """Тест работы со строками"""
        config.set('key', 'value')
        assert config.get('key') == 'value'
        assert isinstance(config.get('key'), str)
    
    def test_int(self, config):
        """Тест работы с целыми числами"""
        config.set('key', 42)
        assert config.get('key') == 42
        assert isinstance(config.get('key'), int)
    
    def test_float(self, config):
        """Тест работы с вещественными числами"""
        config.set('key', 3.14)
        assert config.get('key') == 3.14
        assert isinstance(config.get('key'), float)
    
    def test_bool(self, config):
        """Тест работы с булевыми значениями"""
        config.set('key1', True)
        config.set('key2', False)
        
        assert config.get('key1') is True
        assert config.get('key2') is False
        assert isinstance(config.get('key1'), bool)
        assert isinstance(config.get('key2'), bool)
    
    def test_list(self, config):
        """Тест работы со списками"""
        config.set('key', [1, 2, 3])
        value = config.get('key')
        
        assert value == [1, 2, 3]
        assert isinstance(value, list)
    
    def test_dict(self, config):
        """Тест работы со словарями"""
        config.set('key', {'nested': 'value'})
        value = config.get('key')
        
        assert value == {'nested': 'value'}
        assert isinstance(value, dict)
    
    def test_none(self, config):
        """Тест работы с None"""
        config.set('key', None)
        assert config.get('key') is None
    
    def test_nested_structure(self, config):
        """Тест работы с вложенными структурами"""
        data = {
            'database': {
                'host': 'localhost',
                'port': 5432,
                'options': ['option1', 'option2']
            },
            'api': {
                'endpoints': ['/api/v1', '/api/v2']
            }
        }
        
        config.update(data)
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('database.options') == ['option1', 'option2']
        assert config.get('api.endpoints') == ['/api/v1', '/api/v2']
