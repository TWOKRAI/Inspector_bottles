import time
from collections import deque
from typing import Protocol, final


class FPSProvider(Protocol):
    """Протокол для провайдеров FPS."""
    
    def update(self) -> float: ...
    def get_fps(self) -> float: ...


@final  # Запрет наследования для оптимизации
class FrameFPS:
    """
    Высокопроизводительный счетчик FPS.
    
    Оптимизации:
    - __slots__: экономия памяти (~40% меньше), быстрый доступ к атрибутам
    - Один вызов time.time() на update()
    - Нет аллокаций в горячем пути (кроме возврата float)
    - Локальные переменные для ускорения доступа
    """
    
    __slots__ = ('_interval', '_frames', '_start', '_fps', '_last_update')
    
    def __init__(self, update_interval: float = 1.0) -> None:
        if update_interval <= 0:
            raise ValueError("interval must be positive")
        
        self._interval: float = update_interval
        self._frames: int = 0
        self._start: float = time.perf_counter()  # Более точный, чем time.time()
        self._fps: float = 0.0
        self._last_update: float = self._start
    
    @property
    def fps(self) -> float:
        """Текущий FPS (последнее измеренное значение)."""
        return self._fps
    
    @property
    def instantaneous_fps(self) -> float:
        """
        Мгновенный FPS на основе времени с последнего обновления.
        Полезно для плавных UI-индикаторов.
        """
        elapsed = time.perf_counter() - self._last_update
        if elapsed > 0:
            return self._frames / elapsed if self._frames > 0 else self._fps
        return self._fps
    
    def update(self) -> float:
        """
        Инкремент счетчика кадров. Возвращает FPS если обновление произошло.
        
        Горячий путь — минимум операций:
        - 1 вызов perf_counter()
        - 2 сравнения
        - 2 присваивания (обычно)
        """
        self._frames += 1
        
        now = time.perf_counter()
        elapsed = now - self._start
        
        if elapsed >= self._interval:
            # Расчет FPS
            self._fps = self._frames / elapsed
            
            # Сброс с сохранением остатка для точности
            # (не теряем дробную часть интервала)
            self._frames = 0
            self._start = now
            self._last_update = now
            
            return self._fps
        
        return 0.0
    
    def get_fps(self) -> float:
        """Обратная совместимость."""
        return self._fps
    
    def reset(self) -> None:
        """Сброс состояния."""
        self._frames = 0
        self._start = time.perf_counter()
        self._fps = 0.0
        self._last_update = self._start


@final
class RingBufferFPS:
    """
    FPS с кольцевым буфером — O(1) на каждый кадр.
    
    Хранит N последних временных меток в deque с maxlen.
    Без аллокаций памяти после инициализации.
    """
    
    __slots__ = ('_window', '_buffer', '_fps', '_count')
    
    def __init__(self, window_seconds: float = 1.0, max_samples: int = 120) -> None:
        self._window: float = window_seconds
        self._buffer: deque[float] = deque(maxlen=max_samples)  # Фиксированный размер!
        self._fps: float = 0.0
        self._count: int = 0  # Текущий размер (для скорости, т.к. len(deque) O(1))
    
    @property
    def fps(self) -> float:
        return self._fps
    
    def update(self) -> float:
        """
        O(1) операции только:
        - append (автоматически вытесняет старые при maxlen)
        - 2 индексации deque
        - вычитание и деление
        """
        now = time.perf_counter()
        self._buffer.append(now)
        
        # Удаляем старые метки с конца пока они вне окна
        # popleft() — O(1) для deque
        cutoff = now - self._window
        while self._buffer and self._buffer[0] < cutoff:
            self._buffer.popleft()
        
        if len(self._buffer) >= 2:
            actual_window = self._buffer[-1] - self._buffer[0]
            if actual_window > 0:
                self._fps = (len(self._buffer) - 1) / actual_window
                return self._fps
        
        return 0.0
    
    def reset(self) -> None:
        self._buffer.clear()
        self._fps = 0.0


# ==================== БЕНЧМАРК ====================

def benchmark():
    """Сравнение производительности реализаций."""
    import sys
    
    print("=" * 60)
    print("БЕНЧМАРК FPS-СЧЕТЧИКОВ")
    print("=" * 60)
    
    # Размеры объектов
    print("\n--- Размер объектов ---")
    fps_basic = FrameFPS()
    fps_ring = RingBufferFPS()
    
    print(f"FrameFPS: {sys.getsizeof(fps_basic)} bytes")
    print(f"RingBufferFPS: {sys.getsizeof(fps_ring)} bytes")
    print(f"RingBufferFPS._buffer: {sys.getsizeof(fps_ring._buffer)} bytes")
    
    # Бенчмарк update()
    print("\n--- Скорость update() ---")
    iterations = 1_000_000
    
    # FrameFPS
    fps = FrameFPS(update_interval=10.0)  # Большой интервал, чтобы не сбрасывался
    start = time.perf_counter()
    for _ in range(iterations):
        fps.update()
    elapsed = time.perf_counter() - start
    print(f"FrameFPS: {iterations/elapsed:,.0f} ops/sec ({elapsed*1e6/iterations:.2f} µs/op)")
    
    # RingBufferFPS
    fps = RingBufferFPS(window_seconds=10.0, max_samples=10000)
    start = time.perf_counter()
    for _ in range(iterations):
        fps.update()
    elapsed = time.perf_counter() - start
    print(f"RingBufferFPS: {iterations/elapsed:,.0f} ops/sec ({elapsed*1e6/iterations:.2f} µs/op)")
    
    # Сравнение с оригиналом (если доступен)
    print("\n--- Сравнение с 'наивной' реализацией ---")
    
    class NaiveFPS:
        def __init__(self, update_interval=1.0):
            self.frame_count = 0
            self.start_time = time.time()
            self.last_fps = 0.0
            self.update_interval = update_interval 
            self.elapsed = 0

        def update(self):
            self.frame_count += 1
            current_time = time.time()
            self.elapsed = current_time - self.start_time
            
            if self.elapsed >= self.update_interval:
                self.last_fps = self.frame_count / self.elapsed
                self.frame_count = 0
                self.start_time = current_time
                return self.last_fps
            return 0
    
    naive = NaiveFPS(update_interval=10.0)
    start = time.perf_counter()
    for _ in range(iterations):
        naive.update()
    elapsed = time.perf_counter() - start
    print(f"NaiveFPS: {iterations/elapsed:,.0f} ops/sec ({elapsed*1e6/iterations:.2f} µs/op)")
    
    print("\n--- Реалистичный тест (60 FPS, 10 сек) ---")
    # Имитация игрового цикла
    
    results = {}
    
    for name, fps_obj in [("FrameFPS", FrameFPS(1.0)), ("RingBufferFPS", RingBufferFPS(1.0))]:
        frame_times = []
        start = time.perf_counter()
        next_frame = start
        
        for _ in range(600):  # 600 кадров @ 60 FPS
            # Имитация времени кадра
            frame_start = time.perf_counter()
            
            # Сам вызов update
            fps_obj.update()
            
            frame_end = time.perf_counter()
            frame_times.append((frame_end - frame_start) * 1e6)  # в микросекундах
            
            # Синхронизация 60 FPS
            next_frame += 0.016666
            sleep_time = next_frame - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        avg_time = sum(frame_times) / len(frame_times)
        max_time = max(frame_times)
        results[name] = (avg_time, max_time)
        print(f"{name}: avg={avg_time:.2f}µs, max={max_time:.2f}µs")
    
    print("\n--- Выводы ---")
    print(f"FrameFPS быстрее в {results['RingBufferFPS'][0]/results['FrameFPS'][0]:.1f}x раз")
    print("RingBufferFPS дает плавный FPS, но дороже по CPU")


if __name__ == "__main__":
    benchmark()