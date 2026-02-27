"""
Тесты для ImageMemoryManager с интеграцией ProcessData.
"""
import pytest
import numpy as np
from multiprocessing import shared_memory

from multiprocess_framework.modules.Shared_resources_module import (
    ImageMemoryManager,
    ProcessStateRegistry,
    SharedResourcesManager
)


class TestImageMemoryManager:
    """Тесты для ImageMemoryManager."""
    
    @pytest.fixture
    def registry(self):
        """Создает ProcessStateRegistry для тестов."""
        return ProcessStateRegistry()
    
    @pytest.fixture
    def memory_manager(self, registry):
        """Создает ImageMemoryManager с ProcessStateRegistry."""
        return ImageMemoryManager(process_state_registry=registry)
    
    @pytest.fixture
    def memory_config(self):
        """Конфигурация памяти для тестов."""
        return {
            "test_memory": (10, (100, 100, 3), np.uint8),  # 10 массивов 100x100x3
            "small_memory": (5, (50, 50, 1), np.float32)   # 5 массивов 50x50x1
        }
    
    def test_initialization_with_registry(self, registry):
        """Проверяет инициализацию с ProcessStateRegistry."""
        manager = ImageMemoryManager(process_state_registry=registry)
        assert manager.process_state_registry is registry
    
    def test_initialization_without_registry(self):
        """Проверяет инициализацию без ProcessStateRegistry (локальный режим)."""
        manager = ImageMemoryManager(process_state_registry=None)
        assert manager.process_state_registry is None
    
    def test_create_memory_dict(self, memory_manager, registry, memory_config):
        """Проверяет создание памяти и сохранение в ProcessData."""
        result = memory_manager.create_memory_dict("test_process", memory_config, coll=3)
        
        assert result is True
        
        # Проверяем, что данные сохранены в ProcessData
        process_data = registry.get_process_data("test_process")
        assert process_data is not None
        assert 'memory_blocks' in process_data.custom
        assert 'memory_params' in process_data.custom
        assert 'memory_index_usage' in process_data.custom
        assert 'memory_coll' in process_data.custom
        
        # Проверяем структуру данных
        assert 'test_memory' in process_data.custom['memory_blocks']
        assert 'small_memory' in process_data.custom['memory_blocks']
        assert len(process_data.custom['memory_blocks']['test_memory']) == 3
        assert len(process_data.custom['memory_blocks']['small_memory']) == 3
    
    def test_create_memory_dict_auto_register_process(self, memory_manager, registry, memory_config):
        """Проверяет автоматическую регистрацию процесса при создании памяти."""
        # Процесс не зарегистрирован
        assert registry.get_process_data("new_process") is None
        
        # Создаем память - процесс должен зарегистрироваться автоматически
        memory_manager.create_memory_dict("new_process", memory_config, coll=2)
        
        # Проверяем, что процесс зарегистрирован
        process_data = registry.get_process_data("new_process")
        assert process_data is not None
        assert 'memory_blocks' in process_data.custom
    
    def test_find_free_index(self, memory_manager, memory_config):
        """Проверяет поиск свободного индекса."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=3)
        
        # Находим свободный индекс
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        assert free_idx is not None
        assert free_idx == 0  # Первый индекс должен быть свободен
        
        # Используем индекс (записываем данные)
        arrays = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(5)]
        memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
        
        # Ищем следующий свободный индекс
        next_free_idx = memory_manager.find_free_index("test_process", "test_memory")
        assert next_free_idx is not None
        assert next_free_idx == 1  # Следующий свободный индекс
    
    def test_write_and_read_arrays(self, memory_manager, memory_config):
        """Проверяет запись и чтение numpy массивов."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Создаем тестовые массивы
        original_arrays = [
            np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            for _ in range(5)
        ]
        
        # Записываем массивы
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        result = memory_manager.write_images("test_process", "test_memory", original_arrays, free_idx)
        
        assert result is not None
        
        # Читаем массивы
        read_arrays = memory_manager.read_images("test_process", "test_memory", free_idx)
        
        assert read_arrays is not None
        assert len(read_arrays) == len(original_arrays)
        
        # Проверяем, что массивы идентичны
        for orig, read in zip(original_arrays, read_arrays):
            assert np.array_equal(orig, read)
            assert orig.shape == read.shape
            assert orig.dtype == read.dtype
    
    def test_write_different_shapes(self, memory_manager, memory_config):
        """Проверяет запись массивов разных размеров в пределах максимума."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Создаем массивы разных размеров (в пределах максимума 100x100x3)
        arrays = [
            np.random.randint(0, 256, (80, 90, 3), dtype=np.uint8),
            np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8),
            np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8),
        ]
        
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        result = memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
        
        assert result is not None
        
        # Читаем и проверяем
        read_arrays = memory_manager.read_images("test_process", "test_memory", free_idx)
        assert len(read_arrays) == len(arrays)
        for orig, read in zip(arrays, read_arrays):
            assert np.array_equal(orig, read)
    
    def test_write_float32_arrays(self, memory_manager, memory_config):
        """Проверяет запись массивов float32."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Создаем float32 массивы
        arrays = [
            np.random.rand(50, 50, 1).astype(np.float32)
            for _ in range(3)
        ]
        
        free_idx = memory_manager.find_free_index("test_process", "small_memory")
        result = memory_manager.write_images("test_process", "small_memory", arrays, free_idx)
        
        assert result is not None
        
        # Читаем и проверяем
        read_arrays = memory_manager.read_images("test_process", "small_memory", free_idx)
        assert len(read_arrays) == len(arrays)
        for orig, read in zip(arrays, read_arrays):
            assert np.allclose(orig, read)  # Используем allclose для float
            assert orig.dtype == read.dtype
    
    def test_write_invalid_dtype(self, memory_manager, memory_config):
        """Проверяет обработку неверного типа данных."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Создаем массивы с неверным типом
        arrays = [
            np.random.randint(0, 256, (100, 100, 3), dtype=np.float32)  # Должен быть uint8
        ]
        
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        
        with pytest.raises(ValueError):
            memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
    
    def test_write_too_large_shape(self, memory_manager, memory_config):
        """Проверяет обработку слишком больших размеров."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Создаем массив больше максимального размера
        arrays = [
            np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)  # Больше 100x100x3
        ]
        
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        
        with pytest.raises(ValueError):
            memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
    
    def test_read_partial(self, memory_manager, memory_config):
        """Проверяет чтение части массивов."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Записываем 5 массивов
        arrays = [
            np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            for _ in range(5)
        ]
        
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
        
        # Читаем только 3 первых массива
        read_arrays = memory_manager.read_images("test_process", "test_memory", free_idx, n=3)
        
        assert len(read_arrays) == 3
        for orig, read in zip(arrays[:3], read_arrays):
            assert np.array_equal(orig, read)
    
    def test_release_memory(self, memory_manager, memory_config):
        """Проверяет освобождение памяти."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=3)
        
        # Записываем данные
        arrays = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(3)]
        free_idx = memory_manager.find_free_index("test_process", "test_memory")
        memory_manager.write_images("test_process", "test_memory", arrays, free_idx)
        
        # Освобождаем память
        memory_manager.release_memory("test_process", "test_memory", free_idx)
        
        # Индекс должен стать свободным
        new_free_idx = memory_manager.find_free_index("test_process", "test_memory")
        assert new_free_idx == free_idx
    
    def test_close_memory(self, memory_manager, memory_config):
        """Проверяет закрытие конкретной памяти."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        process_data = memory_manager.process_state_registry.get_process_data("test_process")
        assert 'test_memory' in process_data.custom['memory_blocks']
        
        # Закрываем память
        memory_manager.close_memory("test_process", "test_memory")
        
        # Проверяем, что память удалена из ProcessData
        process_data = memory_manager.process_state_registry.get_process_data("test_process")
        assert 'test_memory' not in process_data.custom.get('memory_blocks', {})
    
    def test_close_all(self, memory_manager, memory_config):
        """Проверяет закрытие всей памяти процесса."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        process_data = memory_manager.process_state_registry.get_process_data("test_process")
        assert 'memory_blocks' in process_data.custom
        
        # Закрываем всю память
        memory_manager.close_all(process_name="test_process")
        
        # Проверяем, что данные удалены
        process_data = memory_manager.process_state_registry.get_process_data("test_process")
        assert 'memory_blocks' not in process_data.custom
        assert 'memory_params' not in process_data.custom
    
    def test_multiple_processes(self, memory_manager, memory_config):
        """Проверяет работу с несколькими процессами."""
        # Создаем память для разных процессов
        memory_manager.create_memory_dict("process1", memory_config, coll=2)
        memory_manager.create_memory_dict("process2", memory_config, coll=2)
        
        # Записываем данные в разные процессы
        arrays1 = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(3)]
        arrays2 = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8) for _ in range(3)]
        
        idx1 = memory_manager.find_free_index("process1", "test_memory")
        idx2 = memory_manager.find_free_index("process2", "test_memory")
        
        memory_manager.write_images("process1", "test_memory", arrays1, idx1)
        memory_manager.write_images("process2", "test_memory", arrays2, idx2)
        
        # Читаем данные из разных процессов
        read1 = memory_manager.read_images("process1", "test_memory", idx1)
        read2 = memory_manager.read_images("process2", "test_memory", idx2)
        
        assert len(read1) == len(arrays1)
        assert len(read2) == len(arrays2)
        assert np.array_equal(arrays1[0], read1[0])
        assert np.array_equal(arrays2[0], read2[0])
    
    def test_local_mode(self, memory_config):
        """Проверяет локальный режим без ProcessStateRegistry."""
        manager = ImageMemoryManager(process_state_registry=None)
        
        # Создаем память в локальном режиме
        result = manager._create_memory_dict_local(memory_config, coll=2)
        assert result is True
        
        # Проверяем, что память создана локально
        assert 'test_memory' in manager._local_memories
        assert len(manager._local_memories['test_memory']) == 2
    
    def test_invalid_process_name(self, memory_manager, memory_config):
        """Проверяет обработку несуществующего процесса."""
        # Пытаемся работать с несуществующим процессом
        free_idx = memory_manager.find_free_index("nonexistent", "test_memory")
        assert free_idx is None
        
        arrays = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)]
        result = memory_manager.write_images("nonexistent", "test_memory", arrays, 0)
        assert result is None
    
    def test_invalid_memory_name(self, memory_manager, memory_config):
        """Проверяет обработку несуществующего блока памяти."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        # Пытаемся работать с несуществующим блоком памяти
        free_idx = memory_manager.find_free_index("test_process", "nonexistent")
        assert free_idx is None
        
        arrays = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)]
        result = memory_manager.write_images("test_process", "nonexistent", arrays, 0)
        assert result is None
    
    def test_invalid_index(self, memory_manager, memory_config):
        """Проверяет обработку неверного индекса."""
        memory_manager.create_memory_dict("test_process", memory_config, coll=2)
        
        arrays = [np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)]
        
        # Пытаемся использовать неверный индекс
        result = memory_manager.write_images("test_process", "test_memory", arrays, 10)
        assert result is None
        
        result = memory_manager.read_images("test_process", "test_memory", 10)
        assert result is None

