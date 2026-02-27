"""
Интеграционные тесты для шаблонного приложения.

Этот модуль содержит базовые тесты шаблонного приложения (TemplateApplication).
Тесты проверяют основные сценарии использования и демонстрируют как работать
с шаблонным приложением.

Проверяемые аспекты:
- Инициализация приложения
- Межпроцессное взаимодействие
- Управление воркерами
- Работа с конфигурациями
- Маршрутизация сообщений
- Жизненный цикл процессов
- Статистика приложения

Использование:
    pytest src/multiprocess_framework/refactored/tests/integration/test_template_application.py -v

Документация:
    См. README.md и TEMPLATE_FRAMEWORK_GUIDE.md для подробного руководства
"""

import pytest
import time
from multiprocess_framework.refactored.tests.integration.template_app import (
    TemplateApplication,
    AppConfigManager,
    AppConfig
)
from multiprocess_framework.refactored.modules.message_module import Message


class TestTemplateApplication:
    """Тесты шаблонного приложения."""
    
    def test_app_initialization(self):
        """Тест инициализации приложения."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=True,
            db_process_enabled=True,
            ui_process_enabled=False,  # Отключаем UI для тестов
            vision_workers_count=1,
            ai_workers_count=1,
            db_workers_count=1
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        
        # Инициализация должна пройти успешно
        assert app.initialize() is True
        
        # Проверяем что менеджеры созданы
        assert app.shared_resources is not None
        assert app.config_manager is not None
        assert app.process_manager is not None
        
        # Проверяем что процессы созданы через ProcessManagerCore
        assert len(app.process_names) > 0
        assert 'vision_process' in app.process_names
        assert 'ai_process' in app.process_names
        assert 'db_process' in app.process_names
        
        # Очистка
        app.stop()
    
    def test_process_communication(self):
        """Тест межпроцессного взаимодействия."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=True,
            db_process_enabled=True,
            ui_process_enabled=False,
            vision_workers_count=1,
            ai_workers_count=1,
            db_workers_count=1
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        app.start()
        
        try:
            # Даем время процессам запуститься
            time.sleep(0.5)
            
            # Отправляем тестовое сообщение
            app.send_test_message()
            
            # Ждем обработки
            time.sleep(1)
            
            # Проверяем что сообщение было обработано
            # (в реальном приложении можно проверить результаты)
            
        finally:
            app.stop()
    
    def test_worker_management(self):
        """Тест управления воркерами."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=False,
            db_process_enabled=False,
            ui_process_enabled=False,
            vision_workers_count=2
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        app.start()
        
        try:
            time.sleep(0.5)
            
            # Проверяем что воркеры созданы
            vision_workers = app.vision_process.worker_manager.get_all_workers_status()
            assert len(vision_workers) == 2
            
            # Проверяем статус воркеров
            for worker_name, status in vision_workers.items():
                assert status is not None
            
        finally:
            app.stop()
    
    def test_config_management(self):
        """Тест работы с конфигурациями."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=False,
            db_process_enabled=False,
            ui_process_enabled=False
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        
        try:
            # Проверяем что конфигурация сохранена
            app_config = app.config_manager.get_config('app')
            assert app_config is not None
            assert app_config.get('vision_process_enabled') is True
            
            # Изменяем конфигурацию
            # ConfigManager работает через get_config и set на объекте конфигурации
            app_config = app.config_manager.get_config('app')
            if app_config:
                app_config.set('vision_process_enabled', False)
            updated_config = app.config_manager.get_config('app')
            assert updated_config.get('vision_process_enabled') is False
            
        finally:
            app.stop()
    
    def test_message_routing(self):
        """Тест маршрутизации сообщений."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=True,
            db_process_enabled=True,
            ui_process_enabled=False,
            vision_workers_count=1,
            ai_workers_count=1,
            db_workers_count=1
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        app.start()
        
        try:
            time.sleep(0.5)
            
            # Создаем сообщение для Vision Process
            message = Message.create(
                type='data',
                sender='test',
                targets=['vision_process'],
                data={
                    'type': 'image',
                    'image_data': b'test_data',
                    'image_id': 'test_001'
                }
            )
            
            # Отправляем через RouterManager
            if app.vision_process.router_manager:
                result = app.vision_process.router_manager.send_message(message)
                assert result is not None
            
        finally:
            app.stop()
    
    def test_process_lifecycle(self):
        """Тест жизненного цикла процессов."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=False,
            db_process_enabled=False,
            ui_process_enabled=False
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        
        # Инициализация
        assert app.initialize() is True
        assert app.vision_process.is_initialized is True
        
        # Запуск
        app.start()
        assert app.is_running is True
        
        time.sleep(0.5)
        
        # Остановка
        app.stop()
        assert app.is_running is False
    
    def test_app_stats(self):
        """Тест получения статистики приложения."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=True,
            db_process_enabled=True,
            ui_process_enabled=False,
            vision_workers_count=1,
            ai_workers_count=1,
            db_workers_count=1
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        app.start()
        
        try:
            time.sleep(0.5)
            
            stats = app.get_stats()
            
            assert stats['is_running'] is True
            assert 'processes' in stats
            assert 'vision' in stats['processes']
            assert 'ai' in stats['processes']
            assert 'db' in stats['processes']
            
        finally:
            app.stop()


class TestProcessIntegration:
    """Тесты интеграции процессов."""
    
    def test_vision_to_ai_communication(self):
        """Тест коммуникации Vision -> AI."""
        # Этот тест демонстрирует как Vision Process отправляет данные в AI Process
        pass  # Реализация зависит от конкретной логики
    
    def test_ai_to_db_communication(self):
        """Тест коммуникации AI -> DB."""
        # Этот тест демонстрирует как AI Process отправляет результаты в DB Process
        pass  # Реализация зависит от конкретной логики
    
    def test_all_modules_usage(self):
        """Тест использования всех модулей фреймворка."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=True,
            db_process_enabled=True,
            ui_process_enabled=False
        )
        
        app = TemplateApplication(config=config, test_mode=True)
        app.initialize()
        
        try:
            # Проверяем что все модули используются:
            # - ProcessModule (базовый класс процессов)
            # - WorkerManager (управление потоками)
            # - RouterManager (маршрутизация сообщений)
            # - ConfigManager (работа с конфигурациями)
            # - CommandManager (обработка команд)
            # - LoggerManager (логирование)
            
            vision = app.vision_process
            assert vision.worker_manager is not None
            assert vision.router_manager is not None
            assert vision.command_manager is not None
            assert vision.logger_manager is not None
            
        finally:
            app.stop()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

