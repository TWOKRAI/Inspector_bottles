"""
Комплексные тесты для BaseAdapter.

Тесты покрывают все аспекты работы базового адаптера:
- Инициализация и конфигурация
- Жизненный цикл (setup, инициализация)
- Работа с менеджером и процессом
- Логирование (через процесс и fallback)
- Статистика и строковое представление
- Интеграционные сценарии
"""
import pytest
from unittest.mock import Mock, patch
from multiprocess_framework.modules.Base_manager_module.base_adapter import BaseAdapter


class ConcreteAdapter(BaseAdapter):
    """Конкретная реализация BaseAdapter для тестирования."""
    
    def __init__(self, manager, process=None, adapter_name=None, setup_result=True, logging_enabled=True):
        """
        Инициализация тестового адаптера.
        
        Args:
            manager: Менеджер для адаптера
            process: Процесс (опционально)
            adapter_name: Имя адаптера (опционально)
            setup_result: Результат вызова setup() для тестирования успеха/неудачи
            logging_enabled: Включено ли логирование
        """
        super().__init__(manager, process, adapter_name, logging_enabled=logging_enabled)
        self._setup_result = setup_result
        self._setup_called = False
    
    def setup(self) -> bool:
        """Реализация абстрактного метода setup()."""
        self._setup_called = True
        self._initialized = self._setup_result
        return self._setup_result


@pytest.fixture
def manager_mock():
    """Фикстура для создания мока менеджера с атрибутом manager_name."""
    manager = Mock()
    manager.manager_name = "TestManager"
    # Убеждаемся что менеджер НЕ имеет ObservableMixin атрибутов
    # чтобы логика логирования перешла к logger_manager процесса
    if hasattr(manager, '_managers'):
        delattr(manager, '_managers')
    if hasattr(manager, '_call_manager'):
        delattr(manager, '_call_manager')
    return manager


@pytest.fixture
def process_mock():
    """Фикстура для создания мока процесса с атрибутом name."""
    process = Mock()
    process.name = "TestProcess"
    return process


class TestBaseAdapter:
    """Тесты для базовой функциональности BaseAdapter."""
    
    def test_initialization_with_manager_only(self, manager_mock):
        """Тест инициализации адаптера только с менеджером (без процесса)."""
        adapter = ConcreteAdapter(manager_mock)
        
        # Проверяем что менеджер сохранен
        assert adapter.manager == manager_mock
        # Процесс должен быть None
        assert adapter.process is None
        # Имя адаптера должно быть по умолчанию (имя класса)
        assert adapter.adapter_name == "ConcreteAdapter"
        # Адаптер должен быть неинициализирован после создания
        assert adapter._initialized is False
    
    def test_initialization_with_process(self, manager_mock, process_mock):
        """Тест инициализации адаптера с менеджером и процессом."""
        adapter = ConcreteAdapter(manager_mock, process=process_mock)
        
        # Проверяем что менеджер и процесс сохранены
        assert adapter.manager == manager_mock
        assert adapter.process == process_mock
    
    def test_initialization_with_custom_name(self, manager_mock):
        """Тест инициализации адаптера с кастомным именем."""
        adapter = ConcreteAdapter(manager_mock, adapter_name="CustomAdapter")
        
        # Проверяем что кастомное имя сохранено
        assert adapter.adapter_name == "CustomAdapter"
    
    def test_base_adapter_is_abstract(self, manager_mock):
        """Тест что BaseAdapter является абстрактным классом (нельзя инстанцировать)."""
        with pytest.raises(TypeError):
            BaseAdapter(manager_mock)  # Должен вызывать TypeError из-за абстрактного метода setup()
    
    def test_setup_method(self, manager_mock):
        """Тест успешного выполнения метода setup()."""
        adapter = ConcreteAdapter(manager_mock, setup_result=True)
        
        # Перед setup адаптер не инициализирован
        assert adapter.is_initialized() is False
        
        # Вызываем setup
        result = adapter.setup()
        
        # Проверяем результат
        assert result is True
        # Адаптер должен быть инициализирован
        assert adapter.is_initialized() is True
        # Флаг вызова setup должен быть установлен
        assert adapter._setup_called is True
    
    def test_setup_method_failure(self, manager_mock):
        """Тест неудачного выполнения метода setup()."""
        adapter = ConcreteAdapter(manager_mock, setup_result=False)
        
        # Вызываем setup, который должен вернуть False
        result = adapter.setup()
        
        # Проверяем что setup вернул False
        assert result is False
        # Адаптер не должен быть инициализирован после неудачного setup
        assert adapter.is_initialized() is False
    
    def test_is_initialized(self, manager_mock):
        """Тест метода is_initialized() в разных состояниях."""
        adapter = ConcreteAdapter(manager_mock)
        
        # По умолчанию адаптер не инициализирован
        assert adapter.is_initialized() is False
        
        # Устанавливаем флаг инициализации напрямую
        adapter._initialized = True
        
        # Теперь адаптер должен быть инициализирован
        assert adapter.is_initialized() is True
    
    def test_get_manager(self, manager_mock):
        """Тест получения менеджера через метод get_manager()."""
        adapter = ConcreteAdapter(manager_mock)
        
        # Получаем менеджер через метод
        manager = adapter.get_manager()
        
        # Проверяем что вернулся тот же менеджер
        assert manager == manager_mock
    
    def test_get_stats_with_manager_name(self, manager_mock):
        """Тест получения статистики когда менеджер имеет атрибут manager_name."""
        adapter = ConcreteAdapter(manager_mock)
        adapter._initialized = True  # Устанавливаем флаг инициализации
        
        # Получаем статистику
        stats = adapter.get_stats()
        
        # Проверяем содержимое статистики
        assert stats["adapter_name"] == "ConcreteAdapter"
        assert stats["initialized"] is True
        assert stats["manager"] == "TestManager"  # manager_name из мока
    
    def test_get_stats_without_manager_name(self):
        """Тест получения статистики когда менеджер не имеет атрибута manager_name."""
        # Используем обычный объект без атрибутов
        manager_no_name = object()
        adapter = ConcreteAdapter(manager_no_name)
        
        # Получаем статистику
        stats = adapter.get_stats()
        
        # Менеджер должен быть помечен как "unknown"
        assert stats["manager"] == "unknown"
    
    def test_log_with_process_logger(self, manager_mock):
        """Тест логирования через логгер процесса (успешный сценарий)."""
        # Создаем мок процесса с логгер-менеджером
        process = Mock()
        logger_manager = Mock()
        logger_manager.info = Mock()
        process.logger_manager = logger_manager
        
        # Создаем адаптер с процессом
        adapter = ConcreteAdapter(manager_mock, process=process)
        
        # Вызываем логирование
        adapter._log("info", "Test message", "test_context")
        
        # Проверяем что логгер был вызван с правильными аргументами
        logger_manager.info.assert_called_once_with("Test message", "test_context")
    
    def test_log_with_process_logger_different_levels(self, manager_mock):
        """Тест логирования разных уровней через логгер процесса."""
        process = Mock()
        logger_manager = Mock()
        # Мокаем методы разных уровней логирования
        logger_manager.debug = Mock()
        logger_manager.warning = Mock()
        logger_manager.error = Mock()
        process.logger_manager = logger_manager
        
        adapter = ConcreteAdapter(manager_mock, process=process)
        
        # Тестируем разные уровни логирования
        adapter._log("debug", "Debug message")
        adapter._log("warning", "Warning message")
        adapter._log("error", "Error message")
        
        # Проверяем вызовы с правильными аргументами
        # Контекст по умолчанию - имя адаптера
        logger_manager.debug.assert_called_once_with("Debug message", "ConcreteAdapter")
        logger_manager.warning.assert_called_once_with("Warning message", "ConcreteAdapter")
        logger_manager.error.assert_called_once_with("Error message", "ConcreteAdapter")
    
    def test_log_with_process_logger_exception(self, manager_mock):
        """Тест обработки исключения при логировании через логгер процесса."""
        process = Mock()
        logger_manager = Mock()
        # Логгер бросает исключение при вызове
        logger_manager.info = Mock(side_effect=Exception("Logger error"))
        process.logger_manager = logger_manager
        
        adapter = ConcreteAdapter(manager_mock, process=process)
        
        # Используем patch для перехвата вызова print (fallback)
        with patch('builtins.print') as mock_print:
            adapter._log("info", "Test message")
            # Должен быть вызван print при ошибке в логгере
            mock_print.assert_called_once()
    
    def test_log_without_process(self, manager_mock):
        """Тест логирования без процесса (fallback на print)."""
        adapter = ConcreteAdapter(manager_mock)
        
        # Перехватываем вызов print
        with patch('builtins.print') as mock_print:
            adapter._log("info", "Test message", "context")
            
            # Проверяем что print был вызван
            mock_print.assert_called_once()
            
            # Проверяем содержимое вызова print
            call_args = str(mock_print.call_args)
            assert "INFO" in call_args  # Уровень логирования
            assert "ConcreteAdapter" in call_args  # Имя адаптера
            assert "Test message" in call_args  # Сообщение
    
    def test_log_without_logger_manager(self, manager_mock):
        """Тест логирования когда процесс есть, но нет logger_manager."""
        process = Mock()
        # Удаляем атрибут logger_manager у процесса
        del process.logger_manager
        
        adapter = ConcreteAdapter(manager_mock, process=process)
        
        # Должен использоваться fallback на print
        with patch('builtins.print') as mock_print:
            adapter._log("info", "Test message")
            mock_print.assert_called_once()
    
    def test_str_representation(self, manager_mock):
        """Тест строкового представления неинициализированного адаптера."""
        adapter = ConcreteAdapter(manager_mock)
        
        # Получаем строковое представление
        str_repr = str(adapter)
        
        # Проверяем содержимое
        assert "ConcreteAdapter" in str_repr  # Имя класса
        assert "initialized" in str_repr.lower()  # Флаг инициализации
        assert "False" in str_repr  # Не инициализирован
    
    def test_str_representation_initialized(self, manager_mock):
        """Тест строкового представления инициализированного адаптера."""
        adapter = ConcreteAdapter(manager_mock)
        adapter._initialized = True  # Инициализируем адаптер
        
        str_repr = str(adapter)
        
        # Должен показывать True для инициализации
        assert "ConcreteAdapter" in str_repr
        assert "True" in str_repr
    
    def test_lifecycle_sequence(self, manager_mock):
        """Тест полного жизненного цикла адаптера."""
        adapter = ConcreteAdapter(manager_mock)
        
        # Перед setup адаптер не инициализирован
        assert adapter.is_initialized() is False
        
        # Вызываем setup
        result = adapter.setup()
        
        # Проверяем успешную инициализацию
        assert result is True
        assert adapter.is_initialized() is True
    
    def test_adapter_with_manager_without_manager_name(self):
        """Тест адаптера с менеджером без атрибута manager_name."""
        # Создаем простой объект без атрибутов
        manager = object()
        adapter = ConcreteAdapter(manager)
        
        # Получаем статистику
        stats = adapter.get_stats()
        
        # Менеджер должен быть помечен как "unknown"
        assert stats["manager"] == "unknown"


class TestBaseAdapterIntegration:
    """Интеграционные тесты BaseAdapter с другими компонентами."""
    
    def test_adapter_with_base_manager(self):
        """Тест адаптера с реальным BaseManager (интеграция)."""
        from multiprocess_framework.modules.Base_manager_module.base_manager import BaseManager
        
        # Создаем конкретную реализацию BaseManager для теста
        class TestManager(BaseManager):
            def initialize(self):
                self.is_initialized = True
                return True
            
            def shutdown(self):
                self.is_initialized = False
                return True
        
        # Создаем менеджер и адаптер
        manager = TestManager("TestManager")
        adapter = ConcreteAdapter(manager)
        
        # Проверяем что адаптер получает правильного менеджера
        assert adapter.get_manager() == manager
        
        # Проверяем статистику
        stats = adapter.get_stats()
        assert stats["manager"] == "TestManager"  # manager_name из BaseManager
    
    def test_adapter_logging_integration(self, manager_mock):
        """Тест интеграции логирования адаптера с логгер-менеджером."""
        process = Mock()
        logger_manager = Mock()
        logger_manager.info = Mock()
        logger_manager.error = Mock()
        process.logger_manager = logger_manager
        
        adapter = ConcreteAdapter(manager_mock, process=process)
        
        # Тестируем логирование разных сообщений
        adapter._log("info", "Info message", "test")
        adapter._log("error", "Error message")
        
        # Проверяем вызовы с правильными контекстами
        logger_manager.info.assert_called_once_with("Info message", "test")
        logger_manager.error.assert_called_once_with("Error message", "ConcreteAdapter")
    
    def test_multiple_adapters_independence(self):
        """Тест независимости нескольких адаптеров (изоляция состояния)."""
        # Создаем два разных менеджера
        manager1 = Mock()
        manager1.manager_name = "Manager1"
        manager2 = Mock()
        manager2.manager_name = "Manager2"
        
        # Создаем два адаптера с разными менеджерами и именами
        adapter1 = ConcreteAdapter(manager1, adapter_name="Adapter1")
        adapter2 = ConcreteAdapter(manager2, adapter_name="Adapter2")
        
        # Инициализируем только первый адаптер
        adapter1.setup()
        
        # Проверяем что состояния адаптеров независимы
        assert adapter1.is_initialized() is True  # Первый инициализирован
        assert adapter2.is_initialized() is False  # Второй не инициализирован
        
        # Проверяем что адаптеры ссылаются на правильных менеджеров
        assert adapter1.get_manager() == manager1
        assert adapter2.get_manager() == manager2
    
    def test_logging_enabled_disabled(self, manager_mock):
        """Тест включения/выключения логирования."""
        adapter = ConcreteAdapter(manager_mock, logging_enabled=True)
        
        assert adapter.is_logging_enabled() is True
        
        adapter.enable_logging(False)
        assert adapter.is_logging_enabled() is False
        
        adapter.enable_logging(True)
        assert adapter.is_logging_enabled() is True
    
    def test_log_with_logging_disabled(self, manager_mock):
        """Тест что логирование не выполняется когда отключено."""
        adapter = ConcreteAdapter(manager_mock, logging_enabled=False)
        
        # Логирование должно быть отключено
        with patch('builtins.print') as mock_print:
            adapter._log("info", "Test message")
            # print не должен быть вызван
            mock_print.assert_not_called()
    
    def test_log_with_observable_mixin_call_manager(self, manager_mock):
        """Тест логирования через _call_manager ObservableMixin менеджера."""
        # Создаем менеджер с ObservableMixin
        from multiprocess_framework.modules.Base_manager_module.observable_mixin import ObservableMixin
        
        # Создаем logger_manager до создания менеджера
        logger_manager = Mock()
        logger_manager.info = Mock()
        
        class ManagerWithObservable(ObservableMixin):
            def __init__(self, logger):
                ObservableMixin.__init__(self, managers={'logger': logger}, config={'logger': True})
        
        observable_manager = ManagerWithObservable(logger_manager)
        adapter = ConcreteAdapter(observable_manager)
        
        # Вызываем логирование
        adapter._log("info", "Test message", "test_context")
        
        # Должен быть вызван logger через _call_manager
        # Проверяем что logger_manager.info был вызван
        assert logger_manager.info.called