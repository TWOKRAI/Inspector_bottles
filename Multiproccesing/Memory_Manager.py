import numpy as np
import struct
from multiprocessing import shared_memory
from typing import List, Dict, Optional

class ImageMemoryManager:
    def __init__(self):
        self.memories = {}
        self.memory_params = {}
        self.index_usage = []
        self.coll_memories = {}


    def create_memory_dict(self, memory_names, coll):
        """Создает память с проверкой ошибок"""
        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = self._calculate_memory_size(num_images, image_shape, dtype)
            
            shm_list = self.create_memory(name, size, coll)

            if not shm_list:  # Если создание не удалось
                print(f"⚠️ Failed to create memory for {name}")
                continue  # Пропускаем эту память
            
            self.memories[name] = shm_list
            self.memory_params[name] = params
            self.index_usage = [0] * coll
            self.coll_memories[name] = coll


    def _validate_memory_access(self, shm_name, index):
        """Проверяет доступ к памяти перед операциями"""
        if shm_name not in self.memories:
            print(f"Memory '{shm_name}' not initialized!")
            return False
            
        if index >= len(self.memories[shm_name]):
            print(f"Invalid index {index} for '{shm_name}'")
            return False
            
        if self.memories[shm_name][index] is None:
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

        
    def find_free_index(self, shm_name: str) -> Optional[int]:
        """Находит первый свободный индекс, проверяя все элементы с начала"""
        # if shm_name not in self.index_usage:
        #     print(f"Memory {shm_name} not found!")
        #     return None
        
        # Явный обход списка для отладки
        # print(f"Index status for {shm_name}: {self.index_usage[shm_name]}")
       
        print(self.index_usage)
        for i in range(len(self.index_usage)):
            if self.index_usage[i] == 0:
                print(f"Found free index: {i}")
                return i
        
        print(f"No free slots")
        return None
    
    
    def write_images(self, images: List[np.ndarray], shm_name: str, index: int) -> Optional[str]:
        if not self._validate_memory_access(shm_name, index):
            return None

        try:
            shm = self.memories[shm_name][index]
            buffer = shm.buf
            max_images, max_shape, expected_dtype = self.memory_params[shm_name]
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
            self._clear_memory(shm_name, index)
            return None

    def read_images(self, shm_name: str, index: int, n: int = -1) -> Optional[List[np.ndarray]]:
        if not self._validate_read_operation(shm_name, index):
            print(f'НЕ прошел валидацию чтения {shm_name}')
            return None
        
        try:
            shm = self.memories[shm_name][index]
            buffer = shm.buf
            _, max_shape, _ = self.memory_params[shm_name]
            max_h, max_w, max_c = max_shape
            itemsize = np.dtype(self.memory_params[shm_name][2]).itemsize

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

    def release_memory(self, shm_name: str, index: int) -> None:
        """Освобождает память с гарантированным закрытием"""
        if 0 <= index < len(self.index_usage):
            # Явное удаление ссылок перед очисткой
            if shm_name in self.memories:
                self._clear_memory(shm_name, index)
                
                #print('DELETE NAME', shm_name, 'index', index)

            # self.index_usage[index] = 0

            # print(self.index_usage)
            

    def _validate_write_operation(self, shm_name: str, index: int, num_images: int) -> bool:
        """Проверяет возможность записи"""
        if shm_name not in self.memories:
            print(f"Memory {shm_name} not found!")
            return False

        if index >= self.coll_memories[shm_name]:
            print(f"Invalid index {index}!")
            return False

        # if self.index_usage[shm_name][index] != 0:
        #     print(f"Index {index} is already in use!")
        #     return False

        max_images = self.memory_params[shm_name][0]
        if num_images > max_images:
            print(f"Too many images ({num_images} > {max_images})!")
            return False

        return True

    def _validate_read_operation(self, shm_name: str, index: int) -> bool:
        """Проверяет возможность чтения"""
        if shm_name not in self.memories:
            print(f"Memory {shm_name} not found!")
            return False

        if index >= self.coll_memories[shm_name]:
            print(f"Invalid index {index}!")
            return False

        # if self.index_usage[shm_name][index] != 1:
        #     print(f"Index {index} is not in use!")
        #     return False

        return True

    def _clear_memory(self, shm_name, index):
        """Безопасная очистка памяти"""
        if self._validate_memory_access(shm_name, index):
            shm = self.memories[shm_name][index]
            try:
                shm.buf[:] = b'\x00' * shm.size
            except Exception as e:
                print(f"Clear error: {e}")


    def close_all(self):
        """Гарантированное закрытие ресурсов"""
        for name in list(self.memories.keys()):
            for i in range(len(self.memories[name])):
                if self.memories[name][i]:
                    self.memories[name][i].close()
                    self.memories[name][i].unlink()
            del self.memories[name]
        
        #print('Память освобождена')


    def close_memory(self, shm_name: str) -> None:
        """Закрывает и очищает ресурсы для конкретной памяти"""
        if shm_name in self.memories:
            for shm in self.memories[shm_name]:
                shm.close()
                shm.unlink()
            del self.memories[shm_name]
            del self.memory_params[shm_name]
            #del self.index_usage[shm_name]
            del self.coll_memories[shm_name]


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