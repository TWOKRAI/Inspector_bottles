"""
Менеджер разделяемой памяти для изображений и данных (Refactored).

Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
Инкапсулирует логику работы с multiprocessing.shared_memory.
Ссылки на блоки памяти хранятся в ProcessData.custom через data_schema.
"""

import numpy as np
import struct
from multiprocessing import shared_memory
from typing import List, Dict, Optional, Any

from ...base_manager import BaseManager, ObservableMixin


class MemoryManager(BaseManager, ObservableMixin):
    """
    Менеджер разделяемой памяти для изображений и данных (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Инкапсулирует логику работы с multiprocessing.shared_memory.
    Ссылки на блоки памяти хранятся в ProcessData.custom через data_schema.
    
    Attributes:
        manager_name: Имя менеджера
        process_state_registry: ProcessStateRegistry для интеграции с ProcessData
        _local_memories: Локальное хранилище (для обратной совместимости)
    """
    
    def __init__(
        self,
        manager_name: str = "MemoryManager",
        process: Optional[Any] = None,
        process_state_registry=None,
        logger=None,
        **kwargs
    ):
        """
        Инициализация менеджера памяти.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс (опционально)
            process_state_registry: ProcessStateRegistry для интеграции с ProcessData
            logger: Логгер (опционально, используется через ObservableMixin)
            **kwargs: Дополнительные параметры для ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin
        managers = kwargs.get('managers', {})
        if logger and 'logger' not in managers:
            managers['logger'] = logger
        
        config = kwargs.get('config', {})
        auto_proxy = kwargs.get('auto_proxy', True)
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=auto_proxy
        )
        
        # ProcessStateRegistry для интеграции с ProcessData
        self.process_state_registry = process_state_registry
        
        # Временное хранилище для локального использования (для обратной совместимости)
        # В идеале все должно храниться в ProcessData.custom через data_schema
        self._local_memories: Dict[str, List[shared_memory.SharedMemory]] = {}
        self._local_memory_params: Dict[str, tuple] = {}
        self._local_index_usage: Dict[str, List[int]] = {}
        self._local_coll_memories: Dict[str, int] = {}
        
        # Статистика
        self._stats = {
            'created': 0,
            'written': 0,
            'read': 0,
            'errors': 0
        }
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация менеджера памяти.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            self.is_initialized = True
            self._log_info(f"MemoryManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize MemoryManager: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы менеджера памяти.
        
        Закрывает все блоки разделенной памяти.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Закрываем все блоки памяти
            self._close_all_memories()
            
            # Очищаем локальное хранилище
            self._local_memories.clear()
            self._local_memory_params.clear()
            self._local_index_usage.clear()
            self._local_coll_memories.clear()
            
            self.is_initialized = False
            self._log_info("MemoryManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during MemoryManager shutdown: {e}")
            return False
    
    def _close_all_memories(self):
        """Закрыть все блоки разделенной памяти."""
        # Закрываем локальные блоки
        for memories in self._local_memories.values():
            for shm in memories:
                try:
                    if shm:
                        shm.close()
                        if shm.name:
                            try:
                                shm.unlink()
                            except FileNotFoundError:
                                pass
                except Exception as e:
                    self._log_error(f"Error closing memory block: {e}")
        
        # Закрываем блоки из ProcessData (если есть)
        if self.process_state_registry:
            for process_name in self.process_state_registry.get_process_names():
                process_data = self.process_state_registry.get_process_data(process_name)
                if process_data and 'memory_blocks' in process_data.custom:
                    for memories in process_data.custom['memory_blocks'].values():
                        for shm in memories:
                            try:
                                if shm:
                                    shm.close()
                                    if shm.name:
                                        try:
                                            shm.unlink()
                                        except FileNotFoundError:
                                            pass
                            except Exception as e:
                                self._log_error(f"Error closing memory block: {e}")
    
    # ========================================================================
    # ОСНОВНОЙ API - СОЗДАНИЕ ПАМЯТИ
    # ========================================================================
    
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
            
            # Инициализируем структуру для хранения памяти в ProcessData.custom (через data_schema)
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
                    self._log_warning(f"Failed to create memory for {name}")
                    continue
                
                # Сохраняем ссылки в ProcessData.custom (данные хранятся через data_schema)
                process_data.custom['memory_blocks'][name] = shm_list
                process_data.custom['memory_params'][name] = params
                process_data.custom['memory_index_usage'][name] = [0] * coll
                process_data.custom['memory_coll'][name] = coll
                self._stats['created'] += 1
            
            self._log_info(f"Created {len(memory_names)} memory blocks for process '{process_name}'")
            return True
            
        except Exception as e:
            self._log_error(f"Failed to create memory dict for {process_name}: {e}")
            self._stats['errors'] += 1
            return False
    
    def _create_memory_dict_local(self, memory_names: Dict[str, tuple], coll: int) -> bool:
        """Локальное создание памяти (для обратной совместимости)."""
        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = self._calculate_memory_size(num_images, image_shape, dtype)
            
            shm_list = self.create_memory(name, size, coll)
            
            if not shm_list:
                self._log_warning(f"Failed to create memory for {name}")
                continue
            
            self._local_memories[name] = shm_list
            self._local_memory_params[name] = params
            self._local_index_usage[name] = [0] * coll
            self._local_coll_memories[name] = coll
            self._stats['created'] += 1
        
        return True
    
    def create_memory(self, shm_name_orig: str, size: int, coll: int = 1) -> Optional[List[shared_memory.SharedMemory]]:
        """
        Создает блоки разделенной памяти.
        
        Args:
            shm_name_orig: Базовое имя блока памяти
            size: Размер блока в байтах
            coll: Количество блоков
        
        Returns:
            Список блоков SharedMemory или None при ошибке
        """
        shm_list = []
        for i in range(coll):
            shm_name = f"{shm_name_orig}_{i}"
            try:
                shm = shared_memory.SharedMemory(name=shm_name, create=True, size=size)
                shm_list.append(shm)
            except Exception as e:
                self._log_error(f"Error creating memory '{shm_name}': {e}")
                # Закрываем уже созданные блоки
                for created_shm in shm_list:
                    try:
                        created_shm.close()
                        created_shm.unlink()
                    except Exception:
                        pass
                return None
        
        return shm_list
    
    def _calculate_memory_size(self, num_images: int, image_shape: tuple, dtype: type) -> int:
        """
        Вычисляет размер памяти для изображений.
        
        Формат: 4 байта (количество изображений) + для каждого изображения:
        - 12 байт (h, w, c) + 1 байт (dtype) + данные изображения
        
        Args:
            num_images: Количество изображений
            image_shape: Форма изображения (height, width, channels)
            dtype: Тип данных numpy
        
        Returns:
            Размер в байтах
        """
        h, w, c = image_shape
        itemsize = np.dtype(dtype).itemsize
        # 4 байта для количества изображений + для каждого изображения:
        # 12 байт (h, w, c) + 1 байт (dtype) + данные
        return 4 + num_images * (12 + 1 + h * w * c * itemsize)
    
    # ========================================================================
    # ОСНОВНОЙ API - РАБОТА С ПАМЯТЬЮ
    # ========================================================================
    
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
            self._log_warning(f"Memory '{shm_name}' not initialized for process '{process_name}'")
            return False
        
        memories = memory_data['memories']
        coll = memory_data['coll']
        
        if shm_name not in memories:
            self._log_warning(f"Memory '{shm_name}' not found")
            return False
        
        if shm_name not in coll or index >= coll[shm_name]:
            self._log_warning(f"Invalid index {index} for '{shm_name}'")
            return False
        
        if index >= len(memories[shm_name]) or memories[shm_name][index] is None:
            self._log_warning(f"Memory block {index} for '{shm_name}' is corrupted")
            return False
        
        return True
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику менеджера памяти.
        
        Интегрируется со статистикой BaseManager и ObservableMixin.
        """
        stats = super().get_stats() if hasattr(super(), 'get_stats') else {}
        
        memory_stats = {
            'created': self._stats['created'],
            'written': self._stats['written'],
            'read': self._stats['read'],
            'errors': self._stats['errors'],
            'local_memories_count': len(self._local_memories)
        }
        
        if isinstance(stats, dict):
            stats['memory'] = memory_stats
        else:
            stats = {'memory': memory_stats}
        
        return stats
    
    # ========================================================================
    # ОСНОВНОЙ API - РАБОТА С ИЗОБРАЖЕНИЯМИ
    # ========================================================================
    
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
        
        # Проверяем возможность записи
        if not self._validate_write_operation(process_name, shm_name, index, len(images)):
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
            
            self._stats['written'] += 1
            return shm.name
        
        except Exception as e:
            self._log_error(f"Write error: {e}")
            self._stats['errors'] += 1
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
            
            if n != -1:
                num_images = min(n, num_images)
            
            for _ in range(num_images):
                # Читаем реальные размеры
                h, w, c = struct.unpack('III', buffer[offset:offset+12])
                offset += 12
                
                # Читаем тип данных
                dtype_char = chr(buffer[offset])
                dtype = np.dtype(dtype_char)
                offset += 1
                
                # Читаем данные
                arr = np.frombuffer(buffer, dtype=dtype, count=h*w*c, offset=offset)
                img = arr.reshape((h, w, c)).copy()
                
                # Пропускаем выравнивание
                offset += max_h * max_w * max_c * itemsize
                
                images.append(img)
            
            self._stats['read'] += 1
            return images
        
        except Exception as e:
            self._log_error(f"Read error: {e}")
            self._stats['errors'] += 1
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
                            if shm:
                                shm.close()
                                if shm.name:
                                    try:
                                        shm.unlink()
                                    except FileNotFoundError:
                                        pass
                        except Exception as e:
                            self._log_error(f"Error closing memory {shm_name}: {e}")
                    process_data.custom['memory_blocks'].pop(shm_name, None)
                    process_data.custom['memory_params'].pop(shm_name, None)
                    process_data.custom['memory_index_usage'].pop(shm_name, None)
                    process_data.custom['memory_coll'].pop(shm_name, None)
        else:
            # Локальный режим
            if shm_name in self._local_memories:
                for shm in self._local_memories[shm_name]:
                    try:
                        if shm:
                            shm.close()
                            if shm.name:
                                try:
                                    shm.unlink()
                                except FileNotFoundError:
                                    pass
                    except Exception as e:
                        self._log_error(f"Error closing memory {shm_name}: {e}")
                del self._local_memories[shm_name]
                self._local_memory_params.pop(shm_name, None)
                self._local_index_usage.pop(shm_name, None)
                self._local_coll_memories.pop(shm_name, None)
    
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
                            if shm:
                                shm.close()
                                if shm.name:
                                    try:
                                        shm.unlink()
                                    except FileNotFoundError:
                                        pass
                        except Exception as e:
                            self._log_error(f"Error closing memory {name}: {e}")
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
                        if shm:
                            shm.close()
                            if shm.name:
                                try:
                                    shm.unlink()
                                except FileNotFoundError:
                                    pass
                    except Exception as e:
                        self._log_error(f"Error closing memory {name}: {e}")
                del self._local_memories[name]
                self._local_memory_params.pop(name, None)
                self._local_index_usage.pop(name, None)
                self._local_coll_memories.pop(name, None)
    
    # ========================================================================
    # ВАЛИДАЦИЯ И ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def _validate_write_operation(
        self,
        process_name: str,
        shm_name: str,
        index: int,
        num_images: int
    ) -> bool:
        """
        Проверяет возможность записи.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока
            num_images: Количество изображений для записи
        
        Returns:
            bool: True если запись возможна
        """
        memory_data = self._get_memory_data(process_name, shm_name)
        if not memory_data:
            return False
        
        coll = memory_data['coll']
        params = memory_data['params']
        
        if shm_name not in coll or index >= coll[shm_name]:
            self._log_warning(f"Invalid index {index}!")
            return False
        
        max_images = params[shm_name][0]
        if num_images > max_images:
            self._log_warning(f"Too many images ({num_images} > {max_images})!")
            return False
        
        return True
    
    def _validate_read_operation(self, process_name: str, shm_name: str, index: int) -> bool:
        """
        Проверяет возможность чтения.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока
        
        Returns:
            bool: True если чтение возможно
        """
        return self._validate_memory_access(process_name, shm_name, index)
    
    def _clear_memory(self, process_name: str, shm_name: str, index: int):
        """
        Безопасная очистка памяти.
        
        Args:
            process_name: Имя процесса
            shm_name: Имя блока памяти
            index: Индекс блока
        """
        if self._validate_memory_access(process_name, shm_name, index):
            memory_data = self._get_memory_data(process_name, shm_name)
            if memory_data:
                shm = memory_data['memories'][shm_name][index]
                try:
                    shm.buf[:] = b'\x00' * shm.size
                except Exception as e:
                    self._log_error(f"Clear error: {e}")

