"""
Комплексные тесты для ObservableMixin.

ObservableMixin - это универсальный миксин для добавления наблюдаемости 
(логирование, ошибки, статистика) к любым классам системы.

Тесты покрывают все аспекты:
- Инициализация и конфигурация менеджеров
- Управление состоянием (включение/выключение)
- Специализированные методы (логирование, статистика, ошибки)
- Контекстные менеджеры для временных изменений
- Декораторы для автоматического мониторинга
- Интеграционные сценарии
"""
import pytest
from unittest.mock import Mock, patch
from multiprocess_framework.modules.Base_manager_module.observable_mixin import ObservableMixin


@pytest.fixture
def logger_manager():
    """Фикстура для создания мока логгер-менеджера."""
    manager = Mock()
    # Мокаем все стандартные методы логирования
    manager.debug = Mock()
    manager.info = Mock()
    manager.warning = Mock()
    manager.error = Mock()
    return manager


@pytest.fixture
def error_manager():
    """Фикстура для создания мока менеджера ошибок."""
    manager = Mock()
    # Мокаем методы обработки ошибок
    manager.track_error = Mock()
    manager.record_error = Mock()
    return manager


@pytest.fixture
def stats_manager():
    """Фикстура для создания мока менеджера статистики."""
    manager = Mock()
    # Мокаем методы для работы с метриками и временем
    manager.record_metric = Mock()
    manager.increment = Mock()
    manager.record_timing = Mock()
    manager.timing = Mock()
    return manager


class TestObservableMixin:
    """Тесты базовой функциональности ObservableMixin."""
    
    def test_initialization_without_managers(self):
        """Тест инициализации ObservableMixin без менеджеров."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass()
        # Проверяем что все внутренние словари пусты
        assert obj._managers == {}
        assert obj._config == {}
        assert obj._enabled == {}
    
    def test_initialization_with_managers(self, logger_manager, error_manager):
        """Тест инициализации ObservableMixin с менеджерами и конфигурацией."""
        class TestClass(ObservableMixin):
            pass
        
        managers = {'logger': logger_manager, 'error': error_manager}
        config = {'logger': True, 'error': True}
        obj = TestClass(managers=managers, config=config)
        
        # Проверяем что менеджеры зарегистрированы
        assert len(obj._managers) == 2
        # Проверяем что менеджеры включены согласно конфигурации
        assert obj.is_enabled('logger') is True
        assert obj.is_enabled('error') is True
    
    def test_register_manager(self, logger_manager):
        """Тест регистрации менеджера после инициализации."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass()
        # Регистрируем новый менеджер
        obj.register_manager('test', logger_manager, enabled=True)
        
        # Проверяем что менеджер добавлен
        assert 'test' in obj._managers
        assert obj._managers['test'] == logger_manager
        # Проверяем что менеджер включен
        assert obj.is_enabled('test') is True
    
    def test_enable_disable(self, logger_manager):
        """Тест включения/выключения менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager})
        
        # Выключаем менеджер
        obj.disable('logger')
        assert obj.is_enabled('logger') is False
        
        # Включаем обратно
        obj.enable('logger')
        assert obj.is_enabled('logger') is True
    
    def test_call_manager_enabled(self, logger_manager):
        """Тест вызова метода включенного менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': True})
        
        # Вызываем метод менеджера
        result = obj._call_manager('logger', 'info', 'test message')
        
        # Проверяем что метод был вызван
        logger_manager.info.assert_called_once_with('test message')
        # result может быть None или результат вызова метода
    
    def test_call_manager_disabled(self, logger_manager):
        """Тест что вызов метода отключенного менеджера игнорируется."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': False})
        
        # Вызываем метод отключенного менеджера
        result = obj._call_manager('logger', 'info', 'test message')
        
        # Метод не должен быть вызван
        logger_manager.info.assert_not_called()
        # Должен вернуться None
        assert result is None
    
    def test_log_methods(self, logger_manager):
        """Тест всех методов логирования разных уровней."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': True})
        
        # Вызываем все уровни логирования
        obj._log_debug('debug message')
        obj._log_info('info message')
        obj._log_warning('warning message')
        obj._log_error('error message')
        
        # Проверяем что каждый метод был вызван с правильным сообщением
        logger_manager.debug.assert_called_once_with('debug message')
        logger_manager.info.assert_called_once_with('info message')
        logger_manager.warning.assert_called_once_with('warning message')
        logger_manager.error.assert_called_once_with('error message')
    
    def test_track_error(self, error_manager):
        """Тест отслеживания ошибок через error_manager."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'error': error_manager}, config={'error': True})
        
        # Создаем тестовую ошибку
        error = Exception("Test error")
        context = {'module': 'test'}
        
        # Отслеживаем ошибку
        obj._track_error(error, context)
        
        # Проверяем что метод track_error был вызван с правильными аргументами
        error_manager.track_error.assert_called_once_with(error, context)
    
    def test_record_metric(self, stats_manager):
        """Тест записи метрики через statistics_manager."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'statistics': stats_manager}, config={'statistics': True})
        
        # Записываем метрику
        obj._record_metric('test.metric', value=5, tags={'env': 'test'})
        
        # Проверяем вызов
        stats_manager.record_metric.assert_called_once_with('test.metric', 5, {'env': 'test'})
    
    def test_context_manager(self, logger_manager):
        """Тест временного изменения состояния менеджера через контекст."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': True})
        
        # Проверяем начальное состояние
        assert obj.is_enabled('logger') is True
        
        # Временно отключаем в контексте
        with obj.context('logger', enabled=False):
            assert obj.is_enabled('logger') is False
        
        # После выхода из контекста состояние должно восстановиться
        assert obj.is_enabled('logger') is True
    
    def test_unregister_manager(self, logger_manager):
        """Тест удаления менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager})
        
        # Удаляем менеджер
        obj.unregister_manager('logger')
        
        # Проверяем что менеджер удален из всех внутренних структур
        assert 'logger' not in obj._managers
        assert 'logger' not in obj._enabled
    
    def test_get_manager(self, logger_manager):
        """Тест получения менеджера по имени."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager})
        
        # Получаем существующий менеджер
        manager = obj.get_manager('logger')
        assert manager == logger_manager
        
        # Пытаемся получить несуществующий менеджер
        nonexistent = obj.get_manager('nonexistent')
        assert nonexistent is None
    
    def test_has_manager(self, logger_manager):
        """Тест проверки наличия менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager})
        
        # Проверяем существующий менеджер
        assert obj.has_manager('logger') is True
        
        # Проверяем несуществующий менеджер
        assert obj.has_manager('nonexistent') is False
    
    def test_get_enabled_managers(self, logger_manager, error_manager, stats_manager):
        """Тест получения списка включенных менеджеров."""
        class TestClass(ObservableMixin):
            pass
        
        managers = {'logger': logger_manager, 'error': error_manager, 'stats': stats_manager}
        config = {'logger': True, 'error': False, 'stats': True}
        obj = TestClass(managers=managers, config=config)
        
        # Получаем включенные менеджеры
        enabled = obj.get_enabled_managers()
        
        # Проверяем что включены только менеджеры с True в конфиге
        assert 'logger' in enabled
        assert 'stats' in enabled
        assert 'error' not in enabled  # Должен быть выключен
    
    def test_call_manager_nonexistent(self):
        """Тест вызова несуществующего менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass()
        
        # Пытаемся вызвать несуществующий менеджер
        result = obj._call_manager('nonexistent', 'info', 'test')
        
        # Должен вернуться None
        assert result is None
    
    def test_call_manager_exception_handling(self):
        """Тест обработки исключений при вызове метода менеджера."""
        class TestClass(ObservableMixin):
            pass
        
        # Создаем "сломанный" менеджер, который бросает исключение
        broken_manager = Mock()
        broken_manager.info.side_effect = Exception("Test error")
        
        obj = TestClass(managers={'logger': broken_manager}, config={'logger': True})
        
        # Вызываем метод, который вызовет исключение
        result = obj._call_manager('logger', 'info', 'test')
        
        # Ошибка должна быть обработана и возвращен None
        assert result is None
    
    def test_track_error_fallback(self):
        """Тест fallback механизма при отсутствии метода track_error."""
        class TestClass(ObservableMixin):
            pass
        
        # Создаем менеджер без метода track_error, но с record_error
        error_manager = Mock()
        error_manager.track_error = None  # Метод отсутствует
        error_manager.record_error = Mock()
        
        obj = TestClass(managers={'error': error_manager}, config={'error': True})
        error = Exception("Test error")
        
        # Вызываем track_error, должен сработать fallback на record_error
        obj._track_error(error)
        
        # Проверяем что был вызван fallback метод
        error_manager.record_error.assert_called_once_with(error, {})
    
    def test_record_metric_fallback(self):
        """Тест fallback механизма при отсутствии метода record_metric."""
        class TestClass(ObservableMixin):
            pass
        
        # Создаем менеджер без метода record_metric, но с increment
        stats_manager = Mock()
        stats_manager.record_metric = None  # Метод отсутствует
        stats_manager.increment = Mock()
        
        obj = TestClass(managers={'statistics': stats_manager}, config={'statistics': True})
        
        # Вызываем record_metric, должен сработать fallback на increment
        obj._record_metric('test.metric')
        
        # Проверяем что был вызван fallback метод
        stats_manager.increment.assert_called_once_with('test.metric', {})
    
    def test_record_timing(self, stats_manager):
        """Тест записи времени выполнения через record_timing."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'statistics': stats_manager}, config={'statistics': True})
        
        # Записываем время выполнения
        obj._record_timing('test.timing', duration=1.5, tags={'env': 'test'})
        
        # Проверяем вызов
        stats_manager.record_timing.assert_called_once_with('test.timing', 1.5, {'env': 'test'})
    
    def test_record_timing_fallback(self):
        """Тест fallback механизма при отсутствии метода record_timing."""
        class TestClass(ObservableMixin):
            pass
        
        # Создаем менеджер без метода record_timing, но с timing
        stats_manager = Mock()
        stats_manager.record_timing = None  # Метод отсутствует
        stats_manager.timing = Mock()
        
        obj = TestClass(managers={'statistics': stats_manager}, config={'statistics': True})
        
        # Вызываем record_timing, должен сработать fallback на timing
        obj._record_timing('test.timing', duration=1.5)
        
        # Проверяем что был вызван fallback метод
        stats_manager.timing.assert_called_once_with('test.timing', 1.5, {})
    
    def test_logged_decorator(self, logger_manager):
        """Тест декоратора logged для автоматического логирования вызовов."""
        class TestClass(ObservableMixin):
            def __init__(self, logger):
                # Инициализируем миксин
                ObservableMixin.__init__(self, managers={'logger': logger}, config={'logger': True})
                # Применяем декоратор к методу
                self.test_method = self.logged(level='info')(self._test_method_impl)
            
            def _test_method_impl(self, x, y):
                return x + y
        
        obj = TestClass(logger_manager)
        # Вызываем декорированный метод
        result = obj.test_method(2, 3)
        
        # Проверяем результат выполнения
        assert result == 5
        # Проверяем что логгер был вызван (хотя бы один раз)
        assert logger_manager.info.call_count >= 1
    
    def test_logged_decorator_with_args(self, logger_manager):
        """Тест декоратора logged с логированием аргументов и результата."""
        class TestClass(ObservableMixin):
            def __init__(self, logger):
                ObservableMixin.__init__(self, managers={'logger': logger}, config={'logger': True})
                # Применяем декоратор с логированием аргументов и результата
                self.test_method = self.logged(level='info', log_args=True, log_result=True)(self._test_method_impl)
            
            def _test_method_impl(self, x, y):
                return x + y
        
        obj = TestClass(logger_manager)
        result = obj.test_method(2, 3)
        
        assert result == 5
        # Должно быть минимум 2 вызова логгера: для входа и выхода
        assert logger_manager.info.call_count >= 2
    
    def test_logged_decorator_error_handling(self, logger_manager, error_manager):
        """Тест декоратора logged при возникновении исключения."""
        class TestClass(ObservableMixin):
            def __init__(self, logger, error):
                ObservableMixin.__init__(self, managers={'logger': logger, 'error': error}, 
                                        config={'logger': True, 'error': True})
                # Применяем декоратор
                self.test_method = self.logged(level='info')(self._test_method_impl)
            
            def _test_method_impl(self):
                raise ValueError("Test error")
        
        obj = TestClass(logger_manager, error_manager)
        
        # Ожидаем исключение
        with pytest.raises(ValueError):
            obj.test_method()
        
        # Проверяем что ошибка была залогирована и отслежена
        assert logger_manager.error.called is True
        assert error_manager.track_error.called is True
    
    def test_timed_decorator(self, stats_manager):
        """Тест декоратора timed для измерения времени выполнения."""
        class TestClass(ObservableMixin):
            def __init__(self, stats):
                ObservableMixin.__init__(self, managers={'statistics': stats}, config={'statistics': True})
                # Применяем декоратор timed
                self.test_method = self.timed(metric_name='test.operation')(self._test_method_impl)
            
            def _test_method_impl(self):
                import time
                time.sleep(0.01)  # Искусственная задержка
                return "result"
        
        obj = TestClass(stats_manager)
        result = obj.test_method()
        
        # Проверяем результат
        assert result == "result"
        # Проверяем что статистика была записана
        assert stats_manager.record_timing.called is True
    
    def test_timed_decorator_error(self, stats_manager):
        """Тест декоратора timed при возникновении исключения."""
        class TestClass(ObservableMixin):
            def __init__(self, stats):
                ObservableMixin.__init__(self, managers={'statistics': stats}, config={'statistics': True})
                self.test_method = self.timed(metric_name='test.operation')(self._test_method_impl)
            
            def _test_method_impl(self):
                raise ValueError("Test error")
        
        obj = TestClass(stats_manager)
        
        # Ожидаем исключение
        with pytest.raises(ValueError):
            obj.test_method()
        
        # Проверяем что статистика ошибки была записана
        calls = [str(call) for call in stats_manager.record_timing.call_args_list]
        assert any('error' in str(call) for call in calls)
    
    def test_monitored_decorator(self, logger_manager, stats_manager):
        """Тест комбинированного декоратора monitored (логирование + статистика)."""
        class TestClass(ObservableMixin):
            def __init__(self, logger, stats):
                ObservableMixin.__init__(self, managers={'logger': logger, 'statistics': stats}, 
                                        config={'logger': True, 'statistics': True})
                # Применяем декоратор monitored
                self.test_method = self.monitored(level='info', metric_name='test.operation')(self._test_method_impl)
            
            def _test_method_impl(self):
                return "result"
        
        obj = TestClass(logger_manager, stats_manager)
        result = obj.test_method()
        
        # Проверяем результат
        assert result == "result"
        # Проверяем что были выполнены все виды мониторинга
        assert logger_manager.info.called is True
        assert stats_manager.record_metric.called is True
        assert stats_manager.record_timing.called is True
    
    def test_update_config(self, logger_manager):
        """Тест обновления конфигурации менеджеров."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': True})
        
        # Обновляем конфигурацию: выключаем логгер
        obj.update_config({'logger': False})
        assert obj.is_enabled('logger') is False
        
        # Включаем обратно
        obj.update_config({'logger': True})
        assert obj.is_enabled('logger') is True
    
    def test_update_config_with_dict(self, logger_manager):
        """Тест обновления конфигурации с помощью сложного словаря."""
        class TestClass(ObservableMixin):
            pass
        
        obj = TestClass(managers={'logger': logger_manager}, config={'logger': True})
        
        # Обновляем конфигурацию с помощью словаря с полем enabled
        obj.update_config({'logger': {'enabled': False}})
        assert obj.is_enabled('logger') is False
    
    def test_get_config(self):
        """Тест получения текущей конфигурации."""
        class TestClass(ObservableMixin):
            pass
        
        # Создаем тестовую конфигурацию
        config = {'logger': True, 'error': False}
        obj = TestClass(config=config)
        
        # Получаем конфигурацию
        retrieved_config = obj.get_config()
        
        # Проверяем что конфигурация правильная
        assert retrieved_config == config
        # Проверяем что возвращается копия, а не оригинал
        assert retrieved_config is not config
    
    def test_get_state(self, logger_manager, error_manager):
        """Тест получения полного состояния ObservableMixin."""
        class TestClass(ObservableMixin):
            pass
        
        managers = {'logger': logger_manager, 'error': error_manager}
        config = {'logger': True, 'error': False}
        obj = TestClass(managers=managers, config=config)
        
        # Получаем состояние
        state = obj.get_state()
        
        # Проверяем структуру состояния
        assert 'config' in state
        assert 'enabled' in state
        assert 'managers' in state
        assert 'enabled_managers' in state
        
        # Проверяем содержимое
        assert state['config'] == config
        assert set(state['managers']) == {'logger', 'error'}
        assert 'logger' in state['enabled_managers']
        assert 'error' not in state['enabled_managers']  # Должен быть выключен


class TestObservableMixinIntegration:
    """Интеграционные тесты ObservableMixin с реальными сценариями."""
    
    def test_real_world_scenario(self):
        """Тест реального сценария использования ObservableMixin."""
        # Создаем моки для реальных менеджеров
        logger = Mock()
        logger.info = Mock()
        stats = Mock()
        stats.record_metric = Mock()
        stats.record_timing = Mock()
        
        # Класс бизнес-логики с ObservableMixin
        class BusinessLogic(ObservableMixin):
            def __init__(self, logger=None, stats=None):
                managers = {}
                config = {}
                if logger:
                    managers['logger'] = logger
                    config['logger'] = True
                if stats:
                    managers['statistics'] = stats
                    config['statistics'] = True
                
                ObservableMixin.__init__(self, managers=managers, config=config)
                # Декорируем метод для мониторинга
                self.process_data = self.monitored(level='info', metric_name='business.process')(self._process_data_impl)
            
            def _process_data_impl(self, data):
                self._log_info(f"Processing data: {data}")
                result = data * 2
                self._record_metric('business.operations')
                return result
        
        # Создаем экземпляр с менеджерами
        logic = BusinessLogic(logger=logger, stats=stats)
        
        # Вызываем метод
        result = logic.process_data(5)
        
        # Проверяем результат и вызовы менеджеров
        assert result == 10
        assert logger.info.called is True
        assert stats.record_metric.called is True
        assert stats.record_timing.called is True
    
    def test_conditional_logging(self):
        """Тест условного логирования через контекст."""
        logger = Mock()
        logger.info = Mock()
        
        # Сервис с ObservableMixin
        class Service(ObservableMixin):
            def __init__(self, logger):
                ObservableMixin.__init__(self, managers={'logger': logger}, config={'logger': True})
            
            def sensitive_operation(self):
                # Временно отключаем логирование для конфиденциальной операции
                with self.context('logger', enabled=False):
                    return "secret"
        
        service = Service(logger)
        result = service.sensitive_operation()
        
        # Проверяем что результат возвращен
        assert result == "secret"
        # Проверяем что логгер не был вызван (операция была в контексте с отключенным логированием)
        assert logger.info.called is False
    
    def test_call_manager_method_caching(self, logger_manager):
        """Тест кэширования методов менеджеров для оптимизации производительности."""
        class TestClass(ObservableMixin):
            def __init__(self):
                ObservableMixin.__init__(self, managers={'logger': logger_manager}, config={'logger': True})
        
        obj = TestClass()
        
        # Первый вызов - метод должен быть получен через getattr и закэширован
        result1 = obj._call_manager('logger', 'info', 'message1')
        
        # Проверяем что метод был вызван
        logger_manager.info.assert_called_with('message1')
        
        # Второй вызов - должен использовать кэш
        result2 = obj._call_manager('logger', 'info', 'message2')
        
        # Проверяем что метод был вызван с новым сообщением
        assert logger_manager.info.call_count == 2
        logger_manager.info.assert_any_call('message2')
        
        # Проверяем что метод закэширован
        assert ('logger', 'info') in obj._method_cache
    
    def test_call_manager_cache_invalidation_on_error(self, logger_manager):
        """Тест очистки кэша при ошибке вызова метода."""
        class TestClass(ObservableMixin):
            def __init__(self):
                ObservableMixin.__init__(self, managers={'logger': logger_manager}, config={'logger': True})
        
        obj = TestClass()
        
        # Первый вызов - кэшируем метод (успешный вызов)
        obj._call_manager('logger', 'info', 'message1')
        
        # Проверяем что метод в кэше и он callable
        assert ('logger', 'info') in obj._method_cache
        cached_method = obj._method_cache[('logger', 'info')]
        assert cached_method is not None
        assert callable(cached_method)
        
        # Симулируем ошибку при вызове метода - заменяем метод на новый который бросает исключение
        # Но нужно сделать это так, чтобы кэшированный метод все еще вызывался, но бросал ошибку
        original_info = logger_manager.info
        
        def failing_info(*args, **kwargs):
            raise Exception("Method error")
        
        # Заменяем метод в менеджере
        logger_manager.info = Mock(side_effect=failing_info)
        
        # Очищаем кэш вручную, чтобы метод был получен заново
        obj._method_cache.pop(('logger', 'info'), None)
        
        # Вызов должен обработать ошибку и очистить кэш
        result = obj._call_manager('logger', 'info', 'message2')
        
        assert result is None
        # Кэш должен быть очищен для этого метода после ошибки
        assert ('logger', 'info') not in obj._method_cache
    
    def test_call_manager_cache_cleared_on_unregister(self, logger_manager):
        """Тест очистки кэша при удалении менеджера."""
        class TestClass(ObservableMixin):
            def __init__(self):
                ObservableMixin.__init__(self, managers={'logger': logger_manager}, config={'logger': True})
        
        obj = TestClass()
        
        # Вызываем метод несколько раз для кэширования
        obj._call_manager('logger', 'info', 'message1')
        obj._call_manager('logger', 'debug', 'message2')
        
        # Проверяем что методы закэшированы
        assert ('logger', 'info') in obj._method_cache
        assert ('logger', 'debug') in obj._method_cache
        
        # Удаляем менеджер
        obj.unregister_manager('logger')
        
        # Кэш для этого менеджера должен быть очищен
        assert ('logger', 'info') not in obj._method_cache
        assert ('logger', 'debug') not in obj._method_cache
    
    def test_call_manager_cache_cleared_on_register_new(self, logger_manager):
        """Тест очистки кэша при регистрации нового менеджера с тем же именем."""
        class TestClass(ObservableMixin):
            def __init__(self):
                ObservableMixin.__init__(self, managers={'logger': logger_manager}, config={'logger': True})
        
        obj = TestClass()
        
        # Вызываем метод для кэширования
        obj._call_manager('logger', 'info', 'message1')
        
        # Проверяем что метод закэширован
        assert ('logger', 'info') in obj._method_cache
        
        # Регистрируем новый менеджер с тем же именем
        new_logger = Mock()
        new_logger.info = Mock()
        obj.register_manager('logger', new_logger)
        
        # Кэш для старого менеджера должен быть очищен
        assert ('logger', 'info') not in obj._method_cache or obj._method_cache.get(('logger', 'info')) != logger_manager.info