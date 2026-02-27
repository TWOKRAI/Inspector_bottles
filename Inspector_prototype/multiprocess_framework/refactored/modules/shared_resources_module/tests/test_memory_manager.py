"""
Юнит-тесты для MemoryManager.
"""

import pytest
import numpy as np

from ..memory.memory_manager import MemoryManager


class TestMemoryManager:
    """Тесты для MemoryManager."""
    
    def test_initialization(self):
        """Тест инициализации менеджера памяти."""
        manager = MemoryManager()
        assert manager is not None
        assert manager.manager_name == "MemoryManager"
    
    def test_initialize(self):
        """Тест инициализации."""
        manager = MemoryManager()
        assert manager.initialize() is True
        assert manager.is_initialized is True
    
    def test_create_memory(self):
        """Тест создания блока памяти."""
        manager = MemoryManager()
        manager.initialize()
        
        size = 1024  # 1KB
        shm_list = manager.create_memory("test_memory", size, coll=2)
        
        assert shm_list is not None
        assert len(shm_list) == 2
        
        # Очистка
        for shm in shm_list:
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass
    
    def test_calculate_memory_size(self):
        """Тест расчета размера памяти."""
        manager = MemoryManager()
        
        # 10 изображений 100x100x3 uint8
        size = manager._calculate_memory_size(10, (100, 100, 3), np.uint8)
        
        # 4 байта (количество) + 10 * (12 + 1 + 100*100*3*1) = 4 + 10 * 30013 = 300134
        expected = 4 + 10 * (12 + 1 + 100 * 100 * 3 * 1)
        assert size == expected
    
    def test_create_memory_dict_local(self):
        """Тест создания словаря памяти в локальном режиме."""
        manager = MemoryManager()
        manager.initialize()
        
        memory_config = {
            "test_memory": (10, (100, 100, 3), np.uint8)
        }
        
        result = manager._create_memory_dict_local(memory_config, coll=2)
        assert result is True
        assert "test_memory" in manager._local_memories
        
        # Очистка
        manager.close_all()
    
    def test_find_free_index(self):
        """Тест поиска свободного индекса."""
        manager = MemoryManager()
        manager.initialize()
        
        memory_config = {
            "test_memory": (10, (100, 100, 3), np.uint8)
        }
        
        manager._create_memory_dict_local(memory_config, coll=3)
        
        free_idx = manager.find_free_index("test_memory", "test_memory")
        assert free_idx == 0
        
        # Очистка
        manager.close_all()
    
    def test_write_read_images(self):
        """Тест записи и чтения изображений."""
        manager = MemoryManager()
        manager.initialize()
        
        memory_config = {
            "test_memory": (10, (100, 100, 3), np.uint8)
        }
        
        manager._create_memory_dict_local(memory_config, coll=1)
        
        # Создаем тестовые изображения
        images = [
            np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            for _ in range(5)
        ]
        
        # Запись
        result = manager.write_images("test_memory", "test_memory", images, index=0)
        assert result is not None
        
        # Чтение
        read_images = manager.read_images("test_memory", "test_memory", index=0)
        assert read_images is not None
        assert len(read_images) == 5
        
        # Проверка данных
        for i, (original, read) in enumerate(zip(images, read_images)):
            assert np.array_equal(original, read), f"Image {i} mismatch"
        
        # Очистка
        manager.close_all()

