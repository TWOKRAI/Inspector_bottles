"""
Тесты для платформо-зависимых адаптеров.

Проверяют работу Windows и Linux адаптеров.
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from multiprocessing import Process

from multiprocess_framework.modules.Process_manager_module.platforms import get_platform_adapter
from multiprocess_framework.modules.Process_manager_module.platforms.windows import WindowsPlatform
from multiprocess_framework.modules.Process_manager_module.platforms.linux import LinuxPlatform
from multiprocess_framework.modules.Process_manager_module.platforms.base import PlatformAdapter


class TestPlatformAdapterFactory:
    """Тесты для фабрики адаптеров платформ"""
    
    def test_get_platform_adapter_windows(self):
        """Тест получения Windows адаптера"""
        if sys.platform == "win32":
            adapter = get_platform_adapter()
            assert isinstance(adapter, WindowsPlatform)
    
    def test_get_platform_adapter_linux(self):
        """Тест получения Linux адаптера"""
        if sys.platform.startswith("linux"):
            adapter = get_platform_adapter()
            assert isinstance(adapter, LinuxPlatform)
    
    def test_get_platform_adapter_default(self):
        """Тест получения адаптера по умолчанию"""
        # На macOS и других Unix-системах должен возвращаться Linux адаптер
        if sys.platform not in ("win32", "linux"):
            adapter = get_platform_adapter()
            assert isinstance(adapter, LinuxPlatform)


class TestWindowsPlatform:
    """Тесты для WindowsPlatform"""
    
    @pytest.fixture
    def windows_platform(self):
        """Фикстура для WindowsPlatform"""
        return WindowsPlatform()
    
    def test_windows_platform_initialization(self, windows_platform):
        """Тест инициализации Windows платформы"""
        assert windows_platform._multiprocessing_setup is False
    
    def test_setup_multiprocessing(self, windows_platform):
        """Тест настройки multiprocessing для Windows"""
        if sys.platform == "win32":
            windows_platform.setup_multiprocessing()
            assert windows_platform._multiprocessing_setup is True
    
    def test_setup_multiprocessing_idempotent(self, windows_platform):
        """Тест идемпотентности setup_multiprocessing"""
        if sys.platform == "win32":
            windows_platform.setup_multiprocessing()
            first_call = windows_platform._multiprocessing_setup
            
            windows_platform.setup_multiprocessing()
            second_call = windows_platform._multiprocessing_setup
            
            assert first_call == second_call == True
    
    def test_get_priority_map(self, windows_platform):
        """Тест получения маппинга приоритетов для Windows"""
        priority_map = windows_platform.get_priority_map()
        
        assert isinstance(priority_map, dict)
        assert 'high' in priority_map
        assert 'normal' in priority_map
        assert 'low' in priority_map
        assert 'below_normal' in priority_map
        assert 'above_normal' in priority_map
    
    def test_apply_priority(self, windows_platform):
        """Тест применения приоритета к процессу"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        # Мокаем psutil.Process
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = windows_platform.apply_priority(mock_process, 'normal')
            
            assert result is True
            mock_psutil_instance.nice.assert_called_once()
    
    def test_apply_priority_access_denied(self, windows_platform):
        """Тест обработки AccessDenied при применении приоритета"""
        import psutil
        
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_instance.nice.side_effect = psutil.AccessDenied()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = windows_platform.apply_priority(mock_process, 'high')
            
            assert result is False
    
    def test_apply_priority_invalid_name(self, windows_platform):
        """Тест применения несуществующего приоритета"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_process.return_value = mock_psutil_instance
            
            # Используем несуществующий приоритет
            result = windows_platform.apply_priority(mock_process, 'invalid_priority')
            
            # Должен использоваться нормальный приоритет по умолчанию
            assert result is True
            mock_psutil_instance.nice.assert_called_once()


class TestLinuxPlatform:
    """Тесты для LinuxPlatform"""
    
    @pytest.fixture
    def linux_platform(self):
        """Фикстура для LinuxPlatform"""
        return LinuxPlatform()
    
    def test_setup_multiprocessing(self, linux_platform):
        """Тест настройки multiprocessing для Linux"""
        # На Linux ничего не делается, просто проверяем что метод существует
        linux_platform.setup_multiprocessing()
        # Метод не должен вызывать ошибку
    
    def test_get_priority_map(self, linux_platform):
        """Тест получения маппинга приоритетов для Linux"""
        priority_map = linux_platform.get_priority_map()
        
        assert isinstance(priority_map, dict)
        assert 'high' in priority_map
        assert 'normal' in priority_map
        assert 'low' in priority_map
        assert 'below_normal' in priority_map
        assert 'above_normal' in priority_map
        
        # Проверяем что значения - это nice values
        assert priority_map['high'] == -10
        assert priority_map['normal'] == 0
        assert priority_map['low'] == 10
    
    def test_apply_priority(self, linux_platform):
        """Тест применения приоритета к процессу на Linux"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = linux_platform.apply_priority(mock_process, 'normal')
            
            assert result is True
            mock_psutil_instance.nice.assert_called_once_with(0)
    
    def test_apply_priority_high(self, linux_platform):
        """Тест применения высокого приоритета на Linux"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = linux_platform.apply_priority(mock_process, 'high')
            
            assert result is True
            mock_psutil_instance.nice.assert_called_once_with(-10)
    
    def test_apply_priority_access_denied(self, linux_platform):
        """Тест обработки AccessDenied при применении приоритета"""
        import psutil
        
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_instance.nice.side_effect = psutil.AccessDenied()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = linux_platform.apply_priority(mock_process, 'high')
            
            assert result is False
    
    def test_apply_priority_permission_error(self, linux_platform):
        """Тест обработки PermissionError при применении приоритета"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_instance.nice.side_effect = PermissionError()
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = linux_platform.apply_priority(mock_process, 'high')
            
            assert result is False
    
    def test_apply_priority_generic_exception(self, linux_platform):
        """Тест обработки общего исключения при применении приоритета"""
        mock_process = Mock(spec=Process)
        mock_process.pid = 12345
        
        with patch('psutil.Process') as mock_psutil_process:
            mock_psutil_instance = Mock()
            mock_psutil_instance.nice.side_effect = Exception("Generic error")
            mock_psutil_process.return_value = mock_psutil_instance
            
            result = linux_platform.apply_priority(mock_process, 'normal')
            
            assert result is False


class TestPlatformAdapterProtocol:
    """Тесты соответствия адаптеров протоколу PlatformAdapter"""
    
    def test_windows_platform_protocol(self):
        """Тест соответствия WindowsPlatform протоколу"""
        adapter = WindowsPlatform()
        
        # Проверяем наличие всех методов протокола
        assert hasattr(adapter, 'setup_multiprocessing')
        assert hasattr(adapter, 'get_priority_map')
        assert hasattr(adapter, 'apply_priority')
        
        # Проверяем что методы вызываются без ошибок
        adapter.setup_multiprocessing()
        priority_map = adapter.get_priority_map()
        assert isinstance(priority_map, dict)
    
    def test_linux_platform_protocol(self):
        """Тест соответствия LinuxPlatform протоколу"""
        adapter = LinuxPlatform()
        
        # Проверяем наличие всех методов протокола
        assert hasattr(adapter, 'setup_multiprocessing')
        assert hasattr(adapter, 'get_priority_map')
        assert hasattr(adapter, 'apply_priority')
        
        # Проверяем что методы вызываются без ошибок
        adapter.setup_multiprocessing()
        priority_map = adapter.get_priority_map()
        assert isinstance(priority_map, dict)


class TestPlatformIntegration:
    """Интеграционные тесты платформенных адаптеров"""
    
    def test_platform_adapter_with_process_manager(self):
        """Тест использования адаптера в ProcessManager"""
        from multiprocess_framework.modules.Process_manager_module import ProcessManager
        
        adapter = get_platform_adapter()
        manager = ProcessManager(platform_adapter=adapter)
        
        assert manager.platform is adapter
        
        # Проверяем что адаптер настроен
        adapter.setup_multiprocessing()
        
        # Проверяем что можем получить приоритеты
        priority_map = adapter.get_priority_map()
        assert isinstance(priority_map, dict)
    
    def test_platform_adapter_priority_consistency(self):
        """Тест согласованности приоритетов между платформами"""
        windows_adapter = WindowsPlatform()
        linux_adapter = LinuxPlatform()
        
        windows_priorities = windows_adapter.get_priority_map()
        linux_priorities = linux_adapter.get_priority_map()
        
        # Проверяем что все ключи одинаковые
        assert set(windows_priorities.keys()) == set(linux_priorities.keys())
        
        # Значения могут отличаться (Windows использует классы приоритетов,
        # Linux использует nice values), но ключи должны совпадать

