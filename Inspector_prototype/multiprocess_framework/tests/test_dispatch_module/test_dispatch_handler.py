"""
Тесты для модуля диспетчеризации сообщений.

Проверяем корректность работы Dispatcher, DispatchStrategy, HandlerInfo и Scenario.
"""
import pytest

from multiprocess_framework.modules.Dispatch_module import (
    Dispatcher,
    BaseDispatcher,
    DispatchStrategy,
    HandlerInfo,
    Scenario
)


class TestHandlerInfo:
    """Тесты для класса HandlerInfo."""
    
    def test_handler_info_creation(self):
        """Проверяем создание HandlerInfo с параметрами по умолчанию."""
        def test_handler(data):
            return data
            
        handler_info = HandlerInfo(
            key="test_handler",
            handler=test_handler
        )
        
        assert handler_info.key == "test_handler"
        assert handler_info.handler == test_handler
        assert handler_info.expects_full_message is False
        assert handler_info.metadata == {}
        assert handler_info.efficiency == 0
        assert handler_info.tags == set()
        assert handler_info.stage == 0
    
    def test_handler_info_with_custom_params(self):
        """Проверяем создание HandlerInfo с кастомными параметрами."""
        def test_handler(data):
            return data
            
        handler_info = HandlerInfo(
            key="test_handler",
            handler=test_handler,
            expects_full_message=True,
            metadata={"category": "vision", "version": 1},
            efficiency=10,
            tags={"processing", "high_priority"},
            stage=2
        )
        
        assert handler_info.key == "test_handler"
        assert handler_info.handler == test_handler
        assert handler_info.expects_full_message is True
        assert handler_info.metadata == {"category": "vision", "version": 1}
        assert handler_info.efficiency == 10
        assert handler_info.tags == {"processing", "high_priority"}
        assert handler_info.stage == 2


class TestScenario:
    """Тесты для класса Scenario."""
    
    def test_scenario_creation(self):
        """Проверяем создание сценария."""
        scenario = Scenario(
            name="test_scenario",
            description="Тестовый сценарий",
            metadata={"type": "processing"}
        )
        
        assert scenario.name == "test_scenario"
        assert scenario.description == "Тестовый сценарий"
        assert scenario.metadata == {"type": "processing"}
        assert scenario.handlers == []
    
    def test_scenario_add_handler(self):
        """Проверяем добавление обработчика в сценарий."""
        scenario = Scenario(name="test_scenario")
        
        def handler1(data):
            return data
        
        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=2)
        result = scenario.add_handler(handler_info, stage=2)
        
        assert result is True
        assert len(scenario.handlers) == 1
        assert scenario.handlers[0].key == "handler1"
        assert scenario.handlers[0].stage == 2
    
    def test_scenario_handlers_ordering(self):
        """Проверяем автоматическую сортировку обработчиков по stage."""
        scenario = Scenario(name="test_scenario")
        
        def handler1(data):
            return data
        def handler2(data):
            return data
        def handler3(data):
            return data
        
        h1 = HandlerInfo(key="h1", handler=handler1)
        h2 = HandlerInfo(key="h2", handler=handler2)
        h3 = HandlerInfo(key="h3", handler=handler3)
        
        scenario.add_handler(h3, stage=3)
        scenario.add_handler(h1, stage=1)
        scenario.add_handler(h2, stage=2)
        
        assert len(scenario.handlers) == 3
        assert scenario.handlers[0].key == "h1"
        assert scenario.handlers[1].key == "h2"
        assert scenario.handlers[2].key == "h3"
    
    def test_scenario_remove_handler(self):
        """Проверяем удаление обработчика из сценария."""
        scenario = Scenario(name="test_scenario")
        
        def handler1(data):
            return data
        
        handler_info = HandlerInfo(key="handler1", handler=handler1)
        scenario.add_handler(handler_info, stage=1)
        
        result = scenario.remove_handler("handler1")
        assert result is True
        assert len(scenario.handlers) == 0
    
    def test_scenario_reorder_handler(self):
        """Проверяем изменение порядка обработчика."""
        scenario = Scenario(name="test_scenario")
        
        def handler1(data):
            return data
        
        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=1)
        scenario.add_handler(handler_info, stage=1)
        
        result = scenario.reorder_handler("handler1", new_stage=5)
        assert result is True
        assert scenario.handlers[0].stage == 5
    
    def test_scenario_get_info(self):
        """Проверяем получение информации о сценарии."""
        scenario = Scenario(
            name="test_scenario",
            description="Описание",
            metadata={"type": "test"}
        )
        
        def handler1(data):
            return data
        
        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=1)
        scenario.add_handler(handler_info, stage=1)
        
        info = scenario.get_info()
        
        assert info["name"] == "test_scenario"
        assert info["description"] == "Описание"
        assert info["metadata"] == {"type": "test"}
        assert info["handlers_count"] == 1
        assert len(info["handlers"]) == 1
        assert info["handlers"][0]["key"] == "handler1"


class TestDispatcherInitialization:
    """Тесты инициализации Dispatcher."""
    
    def test_dispatcher_creation_default(self):
        """Проверяем создание диспетчера с параметрами по умолчанию."""
        dispatcher = Dispatcher("test_dispatcher")
        
        assert dispatcher.name == "test_dispatcher"
        assert dispatcher.strategy == DispatchStrategy.EXACT_MATCH
        assert dispatcher.handlers == {}
    
    def test_dispatcher_creation_custom_strategy(self):
        """Проверяем создание диспетчера с кастомной стратегией."""
        dispatcher = Dispatcher("test_dispatcher", DispatchStrategy.FALLBACK_MATCH)
        
        assert dispatcher.name == "test_dispatcher"
        assert dispatcher.strategy == DispatchStrategy.FALLBACK_MATCH
        assert dispatcher.handlers == {}
    
    def test_advanced_dispatcher_creation(self):
        """Проверяем создание диспетчера с CHAIN_MATCH стратегией."""
        dispatcher = Dispatcher("test_dispatcher", DispatchStrategy.CHAIN_MATCH)
        
        assert dispatcher.name == "test_dispatcher"
        assert dispatcher.strategy == DispatchStrategy.CHAIN_MATCH
        # Проверяем, что сценарии доступны через метод
        assert dispatcher.get_all_scenarios() == []


class TestDispatcherRegistration:
    """Тесты регистрации обработчиков."""
    
    def test_register_handler_basic(self):
        """Проверяем регистрацию простого обработчика."""
        dispatcher = Dispatcher("test")
        
        def test_handler(data):
            return {"result": data}
        
        result = dispatcher.register_handler("process_data", test_handler)
        
        assert result is True
        assert "process_data" in dispatcher.handlers
        handler_info = dispatcher.handlers["process_data"]
        assert handler_info.key == "process_data"
        assert handler_info.handler == test_handler
    
    def test_register_handler_with_metadata(self):
        """Проверяем регистрацию обработчика с метаданными."""
        dispatcher = Dispatcher("test")
        
        def test_handler(data):
            return data
        
        result = dispatcher.register_handler(
            "analyze_image",
            test_handler,
            metadata={"type": "vision", "complexity": "high"},
            efficiency=5,
            tags=["image_processing", "ai"]
        )
        
        assert result is True
        handler_info = dispatcher.handlers["analyze_image"]
        assert handler_info.metadata == {"type": "vision", "complexity": "high"}
        assert handler_info.efficiency == 5
        assert handler_info.tags == {"image_processing", "ai"}
    
    def test_register_duplicate_handler(self):
        """Проверяем регистрацию дублирующего обработчика."""
        dispatcher = Dispatcher("test")
        
        def handler1(data):
            return data
        
        def handler2(data):
            return data
        
        # Первая регистрация должна быть успешной
        result1 = dispatcher.register_handler("test_command", handler1)
        assert result1 is True
        
        # Вторая регистрация с тем же ключом должна вернуть False
        result2 = dispatcher.register_handler("test_command", handler2)
        assert result2 is False
    
    def test_overwrite_handler(self):
        """Проверяем принудительную перезапись обработчика."""
        dispatcher = Dispatcher("test")
        
        def handler1(data):
            return {"version": 1}
        
        def handler2(data):
            return {"version": 2}
        
        # Регистрируем первый обработчик
        result1 = dispatcher.register_handler("test_command", handler1)
        assert result1 is True
        
        # Перезаписываем обработчик
        result2 = dispatcher.overwrite_handler("test_command", handler2)
        assert result2 is True
        
        # Проверяем, что теперь используется новый обработчик
        message = {"command": "test_command", "data": {}}
        result = dispatcher.dispatch(message)
        assert result == {"version": 2}
    
    def test_overwrite_nonexistent_handler(self):
        """Проверяем перезапись несуществующего обработчика."""
        dispatcher = Dispatcher("test")
        
        def handler(data):
            return data
        
        # Перезапись несуществующего обработчика должна создать новый
        result = dispatcher.overwrite_handler("new_command", handler)
        assert result is True
        assert "new_command" in dispatcher.handlers


class TestDispatcherDispatching:
    """Тесты диспетчеризации сообщений."""
    
    def test_dispatch_exact_match(self):
        """Проверяем диспетчеризацию с точным совпадением."""
        dispatcher = Dispatcher("test")
        
        def process_command(data):
            return {"processed": True, "data": data}
        
        dispatcher.register_handler("process", process_command)
        
        message = {"command": "process", "data": {"image": "test.jpg"}}
        result = dispatcher.dispatch(message)
        
        assert result == {"processed": True, "data": {"image": "test.jpg"}}
    
    def test_dispatch_fallback_match(self):
        """Проверяем диспетчеризацию с fallback стратегией."""
        dispatcher = Dispatcher("test", DispatchStrategy.FALLBACK_MATCH)
        
        results = []
        
        def low_efficiency_handler(data):
            results.append("low")
            return {"efficiency": "low"}
        
        def high_efficiency_handler(data):
            results.append("high")
            return {"efficiency": "high"}
        
        # Регистрируем обработчики с разной эффективностью
        dispatcher.register_handler("process", low_efficiency_handler, efficiency=1)
        dispatcher.register_handler("process", high_efficiency_handler, efficiency=10)
        
        message = {"command": "process", "data": {}}
        result = dispatcher.dispatch(message)
        
        # Должен быть вызван обработчик с высшей эффективностью
        assert result == {"efficiency": "high"}
        assert "high" in results
        assert "low" not in results  # Низкоэффективный не должен вызываться
    
    def test_dispatch_full_message(self):
        """Проверяем диспетчеризацию с полным сообщением."""
        dispatcher = Dispatcher("test")
        
        def full_message_handler(message):
            return {"received_full": True, "command": message.get("command")}
        
        dispatcher.register_handler(
            "full_test",
            full_message_handler,
            expects_full_message=True
        )
        
        message = {"command": "full_test", "data": {"test": "value"}, "meta": "info"}
        result = dispatcher.dispatch(message)
        
        assert result == {"received_full": True, "command": "full_test"}
    
    def test_dispatch_missing_key(self):
        """Проверяем обработку сообщения без ключевого поля."""
        dispatcher = Dispatcher("test")
        
        message = {"data": {"test": "value"}}  # Нет поля 'command'
        result = dispatcher.dispatch(message)
        
        assert result == {"status": "error", "reason": "Key field 'command' not found"}
    
    def test_dispatch_no_handler(self):
        """Проверяем обработку сообщения без подходящего обработчика."""
        dispatcher = Dispatcher("test")
        
        message = {"command": "unknown_command", "data": {}}
        result = dispatcher.dispatch(message)
        
        assert result == {"status": "error", "reason": "No handler for key 'unknown_command'"}
    
    def test_dispatch_custom_key_fields(self):
        """Проверяем диспетчеризацию с кастомными именами полей."""
        dispatcher = Dispatcher("test")
        
        def custom_handler(data):
            return {"handled": True, "data": data}
        
        dispatcher.register_handler("custom_action", custom_handler)
        
        message = {"action": "custom_action", "payload": {"test": "value"}}
        result = dispatcher.dispatch(message, key_field="action", data_field="payload")
        
        assert result == {"handled": True, "data": {"test": "value"}}
    
    def test_dispatch_handler_exception(self):
        """Проверяем обработку исключений в обработчике."""
        dispatcher = Dispatcher("test")
        
        def failing_handler(data):
            raise ValueError("Test error in handler")
        
        dispatcher.register_handler("failing_command", failing_handler)
        
        message = {"command": "failing_command", "data": {}}
        result = dispatcher.dispatch(message)
        
        assert result == {"status": "error", "reason": "Dispatch failed: Test error in handler"}


class TestDispatcherInfoMethods:
    """Тесты методов получения информации об обработчиках."""
    
    def test_get_handler_info(self):
        """Проверяем получение информации о конкретном обработчике."""
        dispatcher = Dispatcher("test")
        
        def handler(data):
            return data
        
        dispatcher.register_handler("test_handler", handler, efficiency=5, tags=["test"])
        
        info = dispatcher.get_handler_info("test_handler")
        
        assert info is not None
        assert info["key"] == "test_handler"
        assert info["efficiency"] == 5
        assert "test" in info["tags"]
    
    def test_get_all_handlers(self):
        """Проверяем получение информации обо всех обработчиках."""
        dispatcher = Dispatcher("test")
        
        def handler1(data):
            return data
        def handler2(data):
            return data
        
        dispatcher.register_handler("handler1", handler1, efficiency=5)
        dispatcher.register_handler("handler2", handler2, efficiency=10)
        
        all_handlers = dispatcher.get_all_handlers()
        
        assert len(all_handlers) == 2
        keys = [h["key"] for h in all_handlers]
        assert "handler1" in keys
        assert "handler2" in keys
    
    def test_get_handlers_by_tag(self):
        """Проверяем получение обработчиков по тегу."""
        dispatcher = Dispatcher("test")
        
        def handler1(data):
            return data
        def handler2(data):
            return data
        
        dispatcher.register_handler("handler1", handler1, tags=["vision"])
        dispatcher.register_handler("handler2", handler2, tags=["audio"])
        
        vision_handlers = dispatcher.get_handlers_by_tag("vision")
        
        assert len(vision_handlers) == 1
        assert vision_handlers[0]["key"] == "handler1"


class TestAdvancedDispatcherScenarios:
    """Тесты для работы со сценариями в Dispatcher с CHAIN_MATCH стратегией."""
    
    def test_create_scenario(self):
        """Проверяем создание сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        result = dispatcher.create_scenario(
            "test_scenario",
            description="Тестовый сценарий",
            metadata={"type": "test"}
        )
        
        assert result is True
        assert "test_scenario" in dispatcher.scenarios
    
    def test_create_duplicate_scenario(self):
        """Проверяем создание дублирующего сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        result = dispatcher.create_scenario("test_scenario")
        
        assert result is False
    
    def test_delete_scenario(self):
        """Проверяем удаление сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        result = dispatcher.delete_scenario("test_scenario")
        
        assert result is True
        assert "test_scenario" not in dispatcher.scenarios
    
    def test_get_scenario_info(self):
        """Проверяем получение информации о сценарии."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario", description="Описание")
        info = dispatcher.get_scenario_info("test_scenario")
        
        assert info is not None
        assert info["name"] == "test_scenario"
        assert info["description"] == "Описание"
    
    def test_add_handler_to_scenario(self):
        """Проверяем добавление обработчика в сценарий."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def handler1(data):
            return {"processed": True, "data": data}
        
        result = dispatcher.add_handler_to_scenario(
            "test_scenario",
            "handler1",
            handler1,
            stage=1
        )
        
        assert result is True
        scenario = dispatcher.scenarios["test_scenario"]
        assert len(scenario.handlers) == 1
        assert scenario.handlers[0].key == "handler1"
        assert scenario.handlers[0].stage == 1
    
    def test_remove_handler_from_scenario(self):
        """Проверяем удаление обработчика из сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def handler1(data):
            return data
        
        dispatcher.add_handler_to_scenario("test_scenario", "handler1", handler1, stage=1)
        result = dispatcher.remove_handler_from_scenario("test_scenario", "handler1")
        
        assert result is True
        scenario = dispatcher.scenarios["test_scenario"]
        assert len(scenario.handlers) == 0
    
    def test_reorder_handler_in_scenario(self):
        """Проверяем изменение порядка обработчика в сценарии."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def handler1(data):
            return data
        
        dispatcher.add_handler_to_scenario("test_scenario", "handler1", handler1, stage=1)
        result = dispatcher.reorder_handler_in_scenario("test_scenario", "handler1", new_stage=5)
        
        assert result is True
        scenario = dispatcher.scenarios["test_scenario"]
        assert scenario.handlers[0].stage == 5
    
    def test_dispatch_scenario(self):
        """Проверяем выполнение сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def handler1(data):
            return {"stage1": "done", "data": data}
        
        def handler2(data):
            return {"stage2": "done", "data": data.get("data", {})}
        
        dispatcher.add_handler_to_scenario("test_scenario", "handler1", handler1, stage=1)
        dispatcher.add_handler_to_scenario("test_scenario", "handler2", handler2, stage=2)
        
        message = {"data": {"test": "value"}}
        result = dispatcher.dispatch_scenario("test_scenario", message)
        
        assert result["status"] == "success"
        assert result["scenario"] == "test_scenario"
        assert len(result["stages"]) == 2
        assert result["stages"][0]["handler_key"] == "handler1"
        assert result["stages"][1]["handler_key"] == "handler2"
    
    def test_dispatch_scenario_via_dispatch(self):
        """Проверяем выполнение сценария через метод dispatch."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def handler1(data):
            return {"processed": True}
        
        dispatcher.add_handler_to_scenario("test_scenario", "handler1", handler1, stage=1)
        
        message = {"command": "test_scenario", "data": {}}
        result = dispatcher.dispatch(message)
        
        assert result["status"] == "success"
        assert result["scenario"] == "test_scenario"
    
    def test_dispatch_scenario_stop_on_error(self):
        """Проверяем остановку сценария при ошибке."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario")
        
        def failing_handler(data):
            raise ValueError("Test error")
        
        def handler2(data):
            return {"should_not_run": True}
        
        dispatcher.add_handler_to_scenario("test_scenario", "handler1", failing_handler, stage=1)
        dispatcher.add_handler_to_scenario("test_scenario", "handler2", handler2, stage=2)
        
        message = {"data": {}}
        result = dispatcher.dispatch_scenario("test_scenario", message, stop_on_error=True)
        
        assert result["status"] == "error"
        assert len(result["stages"]) == 1
        assert result["stages"][0]["status"] == "error"
    
    def test_update_scenario_metadata(self):
        """Проверяем обновление метаданных сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario", metadata={"version": 1})
        result = dispatcher.update_scenario_metadata("test_scenario", {"version": 2})
        
        assert result is True
        assert dispatcher.scenarios["test_scenario"].metadata == {"version": 2}
    
    def test_update_scenario_description(self):
        """Проверяем обновление описания сценария."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("test_scenario", description="Old description")
        result = dispatcher.update_scenario_description("test_scenario", "New description")
        
        assert result is True
        assert dispatcher.scenarios["test_scenario"].description == "New description"
    
    def test_get_all_scenarios(self):
        """Проверяем получение информации обо всех сценариях."""
        dispatcher = Dispatcher("test", DispatchStrategy.CHAIN_MATCH)
        
        dispatcher.create_scenario("scenario1")
        dispatcher.create_scenario("scenario2")
        
        all_scenarios = dispatcher.get_all_scenarios()
        
        assert len(all_scenarios) == 2
        names = [s["name"] for s in all_scenarios]
        assert "scenario1" in names
        assert "scenario2" in names
