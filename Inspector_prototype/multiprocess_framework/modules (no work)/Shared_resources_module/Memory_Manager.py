"""
Менеджер разделяемой памяти для изображений и данных.

Набор методов для работы с разделяемой памятью.
Ссылки на блоки памяти хранятся в ProcessData.custom для интеграции с общей архитектурой.

ВАЖНО: Данные памяти хранятся в ProcessData.custom, этот класс предоставляет только методы.
"""

import numpy as np
import struct
from multiprocessing import shared_memory
from typing import List, Dict, Optional

from ..Process_module.process_state_registry import ProcessStateRegistry


class ImageMemoryManager:
    """
    Менеджер разделяемой памяти для изображений и данных.
    
    Набор методов для работы с разделяемой памятью.
    Ссылки на блоки памяти хранятся в ProcessData.custom для интеграции с общей архитектурой.
    
    ВАЖНО: Данные памяти хранятся в ProcessData.custom, этот класс предоставляет только методы.
    
    Пример использования:
        memory_manager = ImageMemoryManager(process_state_registry)
        memory_manager.create_memory_dict("process_1", memory_config, coll=5)
        memory_manager.write_images("process_1", "camera_feed", images, index=0)
    """
    def __init__(self, process_state_registry: Optional[ProcessStateRegistry] = None):
        """
        Инициализация менеджера памяти.
        
        Args:
            process_state_registry: ProcessStateRegistry для интеграции с ProcessData (опционально)
        """
        self.process_state_registry = process_state_registry
        
        # Временное хранилище для локального использования (если не используется ProcessStateRegistry)
        # В идеале все должно храниться в ProcessData.custom
        self._local_memories: Dict[str, List[shared_memory.SharedMemory]] = {}
        self._local_memory_params: Dict[str, tuple] = {}
        self._local_index_usage: Dict[str, List[int]] = {}
        self._local_coll_memories: Dict[str, int] = {}


    def create_memory_dict(
        self, 
        process_name: str, 
        memory_names: Dict[str, tuple], 
        coll: int
    ) -> bool:
        """
        Создает память с проверкой ошибок и сохраняет ссылки в ProcessData.
        
        Args:
            process_name: Имя процесса для сохранения ссылок в ProcessData
            memory_names: Словарь конфигураций памяти {name: (num_images, image_shape, dtype)}
            coll: Количество блоков памяти для каждого типа
            
        Returns:
            bool: True если успешно
        """
        if not self.process_state_registry:
            # Локальный режим (для обратной совместимости)
            return self._create_memory_dict_local(memory_names, coll)
        
        try:
            process_data = self.process_state_registry.get_process_data(process_name)
            if not process_data:
                # Автоматически регистрируем процесс если не зарегистрирован
                self.process_state_registry.register_process(process_name)
                process_data = self.process_state_registry.get_process_data(process_name)
            
            # Инициализируем структуру для хранения памяти в ProcessData.custom
            if 'memory_blocks' not in process_data.custom:
                process_data.custom['memory_blocks'] = {}
            if 'memory_params' not in process_data.custom:
                process_data.custom['memory_params'] = {}
            if 'memory_index_usage' not in process_data.custom:
                process_data.custom['memory_index_usage'] = {}
            if 'memory_coll' not in process_data.custom:
                process_data.custom['memory_coll'] = {}
            
            for name, params in memory_names.items():
                num_images, image_shape, dtype = params
                size = self._calculate_memory_size(num_images, image_shape, dtype)
                
                shm_list = self.create_memory(name, size, coll)
                
                if not shm_list:
                    print(f"⚠️ Failed to create memory for {name}")
                    continue
                
                # Сохраняем ссылки в ProcessData.custom
                process_data.custom['memory_blocks'][name] = shm_list
                process_data.custom['memory_params'][name] = params
                process_data.custom['memory_index_usage'][name] = [0] * coll
                process_data.custom['memory_coll'][name] = coll
            
            print(f"ImageMemoryManager: Created {len(memory_names)} memory blocks for process '{process_name}'")
            return True
            
        except Exception as e:
            print(f"ImageMemoryManager: Failed to create memory dict for {process_name}: {e}")
            return False
    
    def _create_memory_dict_local(self, memory_names: Dict[str, tuple], coll: int) -> bool:
        """Локальное создание памяти (для обратной совместимости)"""
        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = self._calculate_memory_size(num_images, image_shape, dtype)
            
            shm_list = self.create_memory(name, size, coll)
            
            if not shm_list:
                print(f"⚠️ Failed to create memory for {name}")
                continue
            
            self._local_memories[name] = shm_list
            self._local_memory_params[name] = params
            self._local_index_usage[name] = [0] * coll
            self._local_coll_memories[name] = coll
        
        return True


    def _get_memory_data(self, process_name: str, shm_name: str) -> Optional[Dict]:
        """
        Получает данные памяти из ProcessData или локального хранилища.
        
        Returns:
            Словарь с данными памяти или None
        """
        if self.process_state_registry:
            process_data = self.process_state_registry.get_process_data(process_name)
            if process_data and 'memory_blocks' in process_data.custom:
                return {
                    'memories': process_data.custom['memory_blocks'],
                    'params': process_data.custom.get('memory_params', {}),
                    'index_usage': process_data.custom.get('memory_index_usage', {}),
                    'coll': process_data.custom.get('memory_coll', {})
                }
        else:
            # Локальный режим
            if shm_name in self._local_memories:
                return {
                    'memories': self._local_memories,
                    'params': self._local_memory_params,
                    'index_usage': self._local_index_usage,
                    'coll': self._local_coll_memories
                }
        return None
    
    def _validate_memory_access(self, process_name: str, shm_name: str, index: int) -> bool:
        """
        Проверяет доступ к памяти перед операциями.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока
            
        Returns:
            bool: True если доступ валиден
        """
        memory_data = self._get_memory_data(process_name, shm_name)
        if not memory_data:
            print(f"Memory '{shm_name}' not initialized for process '{process_name}'!")
            return False
        
        memories = memory_data['memories']
        coll = memory_data['coll']
        
        if shm_name not in memories:
            print(f"Memory '{shm_name}' not found!")
            return False
            
        if shm_name not in coll or index >= coll[shm_name]:
            print(f"Invalid index {index} for '{shm_name}'")
            return False
            
        if index >= len(memories[shm_name]) or memories[shm_name][index] is None:
            print(f"Memory block {index} for '{shm_name}' is corrupted!")
            return False
            
        return True
    
    def create_memory(self, shm_name_orig: str, size: int, coll: int = 1) -> Optional[List[shared_memory.SharedMemory]]:
        shm_list = []
        for i in range(coll):
            shm_name = f"{shm_name_orig}_{i}"
            try:
                shm = shared_memory.SharedMemory(name=shm_name, create=True, size=size)
                shm_list.append(shm)
                #print(f"Created memory '{shm_name}' ({size} bytes)")
            except Exception as e:
                print(f"Error creating memory: {e}")
                for shm in shm_list:
                    shm.close()
                    shm.unlink()
                return None
            
        return shm_list

    def _calculate_memory_size(self, num_images: int, image_shape: tuple, dtype: type) -> int:
        h, w, c = image_shape
        itemsize = np.dtype(dtype).itemsize
        return 4 + num_images * (12 + 1 + h * w * c * itemsize)

        
    def find_free_index(self, process_name: str, shm_name: str) -> Optional[int]:
        """
        Находит первый свободный индекс для блока памяти.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            
        Returns:
            int: Свободный индекс или None
        """
        memory_data = self._get_memory_data(process_name, shm_name)
        if not memory_data:
            return None
        
        index_usage = memory_data['index_usage']
        if shm_name not in index_usage:
            return None
        
        usage_list = index_usage[shm_name]
        for i in range(len(usage_list)):
            if usage_list[i] == 0:
                return i
        
        return None
    
    
    def write_images(
        self, 
        process_name: str,
        shm_name: str, 
        images: List[np.ndarray], 
        index: int
    ) -> Optional[str]:
        """
        Записывает изображения в разделяемую память.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            images: Список изображений для записи
            index: Индекс блока памяти
            
        Returns:
            str: Имя блока памяти или None при ошибке
        """
        if not self._validate_memory_access(process_name, shm_name, index):
            return None

        try:
            memory_data = self._get_memory_data(process_name, shm_name)
            if not memory_data:
                return None
            
            shm = memory_data['memories'][shm_name][index]
            buffer = shm.buf
            max_images, max_shape, expected_dtype = memory_data['params'][shm_name]
            max_h, max_w, max_c = max_shape

            # Записываем количество изображений
            buffer[0:4] = struct.pack('I', len(images))
            offset = 4

            for img in images:
                # Проверяем размеры и тип
                if img.dtype != expected_dtype:
                    raise ValueError(f"Неверный тип данных: {img.dtype} вместо {expected_dtype}")
                
                h, w = img.shape[:2]
                c = 1 if img.ndim == 2 else img.shape[2]
                
                # Проверка на максимальные размеры
                if h > max_h or w > max_w or c > max_c:
                    raise ValueError(
                        f"Размеры изображения ({h}x{w}x{c}) "
                        f"превышают максимальные ({max_h}x{max_w}x{max_c})"
                    )

                # Записываем реальные размеры
                buffer[offset:offset+12] = struct.pack('III', h, w, c)
                offset += 12
                
                # Записываем тип данных
                buffer[offset] = ord(img.dtype.char)
                offset += 1

                # Записываем данные (автоматическое выравнивание)
                img_bytes = img.tobytes()
                buffer[offset:offset+len(img_bytes)] = img_bytes
                offset += len(img_bytes)

                # Заполняем оставшееся пространство нулями (если нужно)
                expected_size = max_h * max_w * max_c * img.dtype.itemsize
                padding = expected_size - len(img_bytes)
                if padding > 0:
                    buffer[offset:offset+padding] = b'\x00' * padding
                    offset += padding

            #self.index_usage[index] = 1

            #print(f'сохранил в {shm.name}')
            return shm.name

        except Exception as e:
            print(f"Write error: {e}")
            self._clear_memory(process_name, shm_name, index)
            return None

    def read_images(
        self, 
        process_name: str,
        shm_name: str, 
        index: int, 
        n: int = -1
    ) -> Optional[List[np.ndarray]]:
        """
        Читает изображения из разделяемой памяти.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока памяти
            n: Количество изображений для чтения (-1 для всех)
            
        Returns:
            List[np.ndarray]: Список изображений или None при ошибке
        """
        if not self._validate_read_operation(process_name, shm_name, index):
            print(f'НЕ прошел валидацию чтения {shm_name}')
            return None
        
        try:
            memory_data = self._get_memory_data(process_name, shm_name)
            if not memory_data:
                return None
            
            shm = memory_data['memories'][shm_name][index]
            buffer = shm.buf
            _, max_shape, expected_dtype = memory_data['params'][shm_name]
            max_h, max_w, max_c = max_shape
            itemsize = np.dtype(expected_dtype).itemsize

            images = []
            num_images = struct.unpack('I', buffer[0:4])[0]
            offset = 4

            if num_images == 0:
                return []

            if n == -1:
                num_images
            else:
                num_images = n

            for _ in range(num_images):
                # Читаем реальные размеры
                h, w, c = struct.unpack('III', buffer[offset:offset+12])
                offset += 12
                
                # Читаем тип данных
                dtype_char = chr(buffer[offset])
                dtype = np.dtype(dtype_char)
                offset += 1

                # Читаем данные
                data_size = h * w * c * dtype.itemsize
                arr = np.frombuffer(buffer, dtype=dtype, 
                                count=h*w*c, offset=offset)
                img = arr.reshape((h, w, c)).copy()
                
                # Пропускаем выравнивание
                offset += max_h * max_w * max_c * itemsize
                
                images.append(img)

            #print(f'считал из {shm.name}')

            return images

        except Exception as e:
            print(f"Read error: {e}")
            return None

    def release_memory(self, process_name: str, shm_name: str, index: int) -> None:
        """
        Освобождает память с гарантированным закрытием.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока памяти
        """
        memory_data = self._get_memory_data(process_name, shm_name)
        if not memory_data:
            return
        
        index_usage = memory_data['index_usage']
        if shm_name in index_usage and 0 <= index < len(index_usage[shm_name]):
            self._clear_memory(process_name, shm_name, index)
            # Помечаем индекс как свободный
            if self.process_state_registry:
                process_data = self.process_state_registry.get_process_data(process_name)
                if process_data and 'memory_index_usage' in process_data.custom:
                    if shm_name in process_data.custom['memory_index_usage']:
                        process_data.custom['memory_index_usage'][shm_name][index] = 0
            else:
                # Локальный режим
                if shm_name in self._local_index_usage:
                    self._local_index_usage[shm_name][index] = 0
                

    def _validate_write_operation(
        self, 
        process_name: str, 
        shm_name: str, 
        index: int, 
        num_images: int
    ) -> bool:
        """Проверяет возможность записи"""
        memory_data = self._get_memory_data(process_name, shm_name)
        if not memory_data:
            return False
        
        coll = memory_data['coll']
        params = memory_data['params']
        
        if shm_name not in coll or index >= coll[shm_name]:
            print(f"Invalid index {index}!")
            return False
        
        max_images = params[shm_name][0]
        if num_images > max_images:
            print(f"Too many images ({num_images} > {max_images})!")
            return False
        
        return True

    def _validate_read_operation(self, process_name: str, shm_name: str, index: int) -> bool:
        """Проверяет возможность чтения"""
        return self._validate_memory_access(process_name, shm_name, index)

    def _clear_memory(self, process_name: str, shm_name: str, index: int):
        """Безопасная очистка памяти"""
        if self._validate_memory_access(process_name, shm_name, index):
            memory_data = self._get_memory_data(process_name, shm_name)
            if memory_data:
                shm = memory_data['memories'][shm_name][index]
                try:
                    shm.buf[:] = b'\x00' * shm.size
                except Exception as e:
                    print(f"Clear error: {e}")


    def close_all(self, process_name: Optional[str] = None):
        """
        Гарантированное закрытие ресурсов.
        
        Args:
            process_name: Имя процесса (если None, закрывает все локальные ресурсы)
        """
        if process_name and self.process_state_registry:
            # Закрываем память для конкретного процесса
            process_data = self.process_state_registry.get_process_data(process_name)
            if process_data and 'memory_blocks' in process_data.custom:
                for name, shm_list in process_data.custom['memory_blocks'].items():
                    for shm in shm_list:
                        try:
                            shm.close()
                            shm.unlink()
                        except Exception as e:
                            print(f"Error closing memory {name}: {e}")
                # Очищаем данные
                process_data.custom.pop('memory_blocks', None)
                process_data.custom.pop('memory_params', None)
                process_data.custom.pop('memory_index_usage', None)
                process_data.custom.pop('memory_coll', None)
        else:
            # Закрываем локальные ресурсы
            for name in list(self._local_memories.keys()):
                for shm in self._local_memories[name]:
                    try:
                        shm.close()
                        shm.unlink()
                    except Exception as e:
                        print(f"Error closing memory {name}: {e}")
                del self._local_memories[name]
                self._local_memory_params.pop(name, None)
                self._local_index_usage.pop(name, None)
                self._local_coll_memories.pop(name, None)

    def close_memory(self, process_name: str, shm_name: str) -> None:
        """
        Закрывает и очищает ресурсы для конкретной памяти.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
        """
        if self.process_state_registry:
            process_data = self.process_state_registry.get_process_data(process_name)
            if process_data and 'memory_blocks' in process_data.custom:
                if shm_name in process_data.custom['memory_blocks']:
                    for shm in process_data.custom['memory_blocks'][shm_name]:
                        try:
                            shm.close()
                            shm.unlink()
                        except Exception as e:
                            print(f"Error closing memory {shm_name}: {e}")
                    process_data.custom['memory_blocks'].pop(shm_name, None)
                    process_data.custom['memory_params'].pop(shm_name, None)
                    process_data.custom['memory_index_usage'].pop(shm_name, None)
                    process_data.custom['memory_coll'].pop(shm_name, None)
        else:
            # Локальный режим
            if shm_name in self._local_memories:
                for shm in self._local_memories[shm_name]:
                    try:
                        shm.close()
                        shm.unlink()
                    except Exception as e:
                        print(f"Error closing memory {shm_name}: {e}")
                del self._local_memories[shm_name]
                self._local_memory_params.pop(shm_name, None)
                self._local_index_usage.pop(shm_name, None)
                self._local_coll_memories.pop(shm_name, None)


    def __del__(self):
        self.close_all()


if __name__ == "__main__":
    # Пример использования
    manager = ImageMemoryManager()
    
    # Конфигурация памяти
    memory_config = {
        "camera_feed": (100, (480, 640, 3), np.uint8),  # 100 изображений 480x640x3
        "sensor_data": (500, (100, 100, 1), np.float32)   # 500 изображений 100x100x1
    }
    
    try:
        # Создаем память с 5 блоками для каждой категории
        manager.create_memory_dict(memory_config, coll=5)
        
        # Запись данных
        images = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) 
                for _ in range(50)]
        
        images2 = [np.random.randint(0, 256, (450, 640, 3), dtype=np.uint8) 
                for _ in range(10)]
        
        # Находим свободный индекс
        free_idx = manager.find_free_index("camera_feed")

        if free_idx is not None:
            print(f"Writing to index {free_idx}")
            manager.write_images(images, "camera_feed", free_idx)
            
            read_data = manager.read_images("camera_feed", free_idx)

            print(f"Read {len(read_data)} images")

            #manager.release_memory("camera_feed", free_idx)

        free_idx = manager.find_free_index("camera_feed")

        if free_idx is not None:
            print(f"Writing to index {free_idx}")
            manager.write_images(images2, "camera_feed", free_idx)

            read_data = manager.read_images("camera_feed", free_idx)

            print(f"Read {len(read_data)} images")

            manager.release_memory("camera_feed", 0)

        free_idx = manager.find_free_index("camera_feed")

        if free_idx is not None:
            print(f"Writing to index {free_idx}")
            manager.write_images(images2, "camera_feed", free_idx)

            read_data = manager.read_images("camera_feed", free_idx)

            print(f"Read {len(read_data)} images")

            #manager.release_memory("camera_feed", 0)
    finally:
        manager.close_all()