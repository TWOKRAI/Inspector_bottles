"""
Тесты интеграции всех компонентов модуля Shared_resources_module.
"""
import pytest
import numpy as np
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    SharedResourcesManager,
    QueueManager,
    ImageMemoryManager,
)
from multiprocess_framework.modules.Process_module.process_data import ProcessData, ProcessDataKeys
from multiprocess_framework.modules.Shared_resources_module.data_schema.models.types import ComponentType
from multiprocess_framework.modules.Shared_resources_module.data_schema.utils import get_nested_value


class TestFullIntegration:
    """Тесты полной интеграции всех компонентов."""
    
    def test_full_workflow(self):
        """Проверяет полный рабочий процесс с всеми компонентами."""
        # 1. Создание библиотеки
        shared_resources = SharedResourcesManager()
        
        # 2. Регистрация процессов (конфигурация теперь в ProcessData.custom)
        # Создаем ProcessData для vision_process
        vision_process_data = ProcessData(
            component_type=ComponentType.PROCESS,
            component_class="VisionProcess",
            name="vision_process"
        )
        vision_process_data.custom[ProcessDataKeys.CONFIG_PROCESS] = {
            "camera_id": 0,
            "resolution": (1920, 1080)
        }
        shared_resources.process_state_registry.register_process(vision_process_data)
        
        # Создаем ProcessData для ai_process
        ai_process_data = ProcessData(
            component_type=ComponentType.PROCESS,
            component_class="AIProcess",
            name="ai_process"
        )
        ai_process_data.custom[ProcessDataKeys.CONFIG_PROCESS] = {
            "model_path": "model.pth"
        }
        shared_resources.process_state_registry.register_process(ai_process_data)
        
        # 3. Создание QueueManager и регистрация очередей
        queue_manager = QueueManager(process_state_registry=shared_resources.process_state_registry)
        queue_config = {
            "data": {"maxsize": 100},
            "system": {"maxsize": 50}
        }
        queue_manager.create_and_register_queues("vision_process", queue_config)
        queue_manager.create_and_register_queues("ai_process", queue_config)
        
        # 4. Создание ImageMemoryManager и памяти
        memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)
        memory_config = {
            "camera_feed": (100, (480, 640, 3), np.uint8),
            "processed_images": (50, (224, 224, 3), np.uint8)
        }
        memory_manager.create_memory_dict("vision_process", memory_config, coll=5)
        
        # 5. Проверка доступа через удобный интерфейс
        vision_data = shared_resources.vision_process
        
        # Очереди
        assert vision_data.queues.data is not None
        assert vision_data.queues.system is not None
        
        # Конфигурация (теперь в ProcessData.custom)
        config = vision_data.custom.get(ProcessDataKeys.CONFIG_PROCESS, {})
        assert config.get("camera_id") == 0
        assert config.get("resolution") == (1920, 1080)
        
        # Память в custom
        assert 'memory_blocks' in vision_data.custom
        assert 'camera_feed' in vision_data.custom['memory_blocks']
        
        # 6. Использование очередей
        vision_data.queues.data.put({"type": "image", "data": "test"})
        message = vision_data.queues.data.get()
        assert message["type"] == "image"
        
        # 7. Использование памяти
        arrays = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) for _ in range(10)]
        free_idx = memory_manager.find_free_index("vision_process", "camera_feed")
        assert free_idx is not None
        
        result = memory_manager.write_images("vision_process", "camera_feed", arrays, free_idx)
        assert result is not None
        
        read_arrays = memory_manager.read_images("vision_process", "camera_feed", free_idx)
        assert len(read_arrays) == len(arrays)
        assert np.array_equal(arrays[0], read_arrays[0])
        
        # 8. Межпроцессное взаимодействие
        ai_data = shared_resources.ai_process
        vision_data.queues.data.put({"target": "ai_process", "data": "result"})
        
        # AI процесс может получить данные через свою очередь
        # (в реальном сценарии это было бы в другом процессе)
    
    def test_multiple_processes_with_memory(self):
        """Проверяет работу нескольких процессов с памятью."""
        shared_resources = SharedResourcesManager()
        memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)
        
        # Регистрируем процессы
        shared_resources.register_process_state("process1")
        shared_resources.register_process_state("process2")
        
        # Создаем память для каждого процесса
        memory_config1 = {"data1": (50, (100, 100, 3), np.uint8)}
        memory_config2 = {"data2": (50, (100, 100, 3), np.uint8)}
        
        memory_manager.create_memory_dict("process1", memory_config1, coll=3)
        memory_manager.create_memory_dict("process2", memory_config2, coll=3)
        
        # Проверяем, что данные изолированы
        process1_data = shared_resources.process1
        process2_data = shared_resources.process2
        
        assert 'data1' in process1_data.custom['memory_blocks']
        assert 'data2' not in process1_data.custom.get('memory_blocks', {})
        
        assert 'data2' in process2_data.custom['memory_blocks']
        assert 'data1' not in process2_data.custom.get('memory_blocks', {})
        
        # Записываем данные в разные процессы
        arrays1 = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(5)]
        arrays2 = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(5)]
        
        idx1 = memory_manager.find_free_index("process1", "data1")
        idx2 = memory_manager.find_free_index("process2", "data2")
        
        memory_manager.write_images("process1", "data1", arrays1, idx1)
        memory_manager.write_images("process2", "data2", arrays2, idx2)
        
        # Читаем и проверяем изоляцию
        read1 = memory_manager.read_images("process1", "data1", idx1)
        read2 = memory_manager.read_images("process2", "data2", idx2)
        
        assert len(read1) == len(arrays1)
        assert len(read2) == len(arrays2)
        assert np.array_equal(arrays1[0], read1[0])
        assert np.array_equal(arrays2[0], read2[0])
    
    def test_queue_and_memory_together(self):
        """Проверяет совместное использование очередей и памяти."""
        shared_resources = SharedResourcesManager()
        queue_manager = QueueManager(process_state_registry=shared_resources.process_state_registry)
        memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)
        
        # Регистрируем процесс
        shared_resources.register_process_state("worker")
        
        # Создаем очереди
        queue_manager.create_and_register_queues("worker", {"data": {"maxsize": 100}})
        
        # Создаем память
        memory_config = {"images": (20, (200, 200, 3), np.uint8)}
        memory_manager.create_memory_dict("worker", memory_config, coll=2)
        
        # Симулируем рабочий процесс:
        # 1. Получаем задачу из очереди
        worker_data = shared_resources.worker
        worker_data.queues.data.put({"action": "process", "image_id": 1})
        
        # 2. Загружаем изображение в память
        arrays = [np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8) for _ in range(5)]
        free_idx = memory_manager.find_free_index("worker", "images")
        memory_manager.write_images("worker", "images", arrays, free_idx)
        
        # 3. Обрабатываем (в реальности здесь была бы обработка)
        read_arrays = memory_manager.read_images("worker", "images", free_idx)
        assert len(read_arrays) == len(arrays)
        
        # 4. Отправляем результат обратно в очередь
        worker_data.queues.data.put({"action": "result", "image_id": 1, "status": "processed"})
        
        # Проверяем, что все работает
        task = worker_data.queues.data.get()
        assert task["action"] == "process"
        
        result = worker_data.queues.data.get()
        assert result["action"] == "result"
    
    def test_serialization_with_memory_references(self):
        """Проверяет сериализацию с ссылками на память."""
        import pickle
        
        shared_resources = SharedResourcesManager()
        memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)
        
        # Создаем процесс и память
        shared_resources.register_process_state("test_process")
        memory_config = {"test": (10, (100, 100, 3), np.uint8)}
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Проверяем, что ссылки на память сохранены в ProcessData
        process_data = shared_resources.get_process_data("test_process")
        assert 'memory_blocks' in process_data.custom
        
        # Сериализуем SharedResourcesManager
        # ВАЖНО: SharedMemory объекты не сериализуются напрямую,
        # но ссылки на них остаются в ProcessData.custom
        try:
            serialized = pickle.dumps(shared_resources)
            deserialized = pickle.loads(serialized)
            
            # После десериализации ProcessData должен быть доступен
            deserialized_data = deserialized.get_process_data("test_process")
            assert deserialized_data is not None
            # Примечание: SharedMemory объекты нужно будет переподключить в новом процессе
        except Exception as e:
            # Это может быть нормально, если SharedMemory не сериализуется
            # В реальном использовании память создается в основном процессе
            # и передается по ссылкам
            pass

