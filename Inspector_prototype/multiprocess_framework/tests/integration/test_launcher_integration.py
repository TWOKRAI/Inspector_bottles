"""
Тесты интеграции SystemLauncher с ProcessManagerBootstrap.

Проверяют взаимодействие между Launcher и ProcessManagerBootstrap.
"""

import pytest
from unittest.mock import Mock
from multiprocess_framework.modules.Process_manager_module import SystemLauncher
from multiprocess_framework.modules.Process_manager_module import ProcessManagerBootstrap


class TestLauncherIntegration:
    """Тесты интеграции SystemLauncher"""
    
    def test_launcher_creation_default(self):
        """Тест создания Launcher с дефолтным ProcessManagerBootstrap"""
        launcher = SystemLauncher()
        
        assert launcher.bootstrap is not None
        assert isinstance(launcher.bootstrap, ProcessManagerBootstrap)
    
    def test_launcher_creation_custom(self):
        """Тест создания Launcher с кастомным ProcessManagerBootstrap"""
        bootstrap = ProcessManagerBootstrap()
        launcher = SystemLauncher(bootstrap=bootstrap)
        
        assert launcher.bootstrap is bootstrap
    
    def test_launcher_get_status(self):
        """Тест получения статуса через Launcher"""
        launcher = SystemLauncher()
        
        status = launcher.get_status()
        assert isinstance(status, dict)
        assert 'bootstrap_running' in status
    
    def test_launcher_get_stats(self):
        """Тест получения статистики через Launcher"""
        launcher = SystemLauncher()
        
        stats = launcher.get_stats()
        assert isinstance(stats, dict)
        assert 'bootstrap' in stats
    
    def test_launcher_bootstrap_access(self):
        """Тест доступа к ProcessManagerBootstrap через Launcher"""
        launcher = SystemLauncher()
        
        # Проверяем что можем использовать методы ProcessManagerBootstrap
        assert hasattr(launcher.bootstrap, 'start')
        assert hasattr(launcher.bootstrap, 'stop')
        assert hasattr(launcher.bootstrap, 'wait')
        assert hasattr(launcher.bootstrap, 'is_running')

