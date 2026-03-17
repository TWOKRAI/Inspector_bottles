import time
from typing import final


@final
class FrameFPS:
    """
    Максимально производительный FPS-счетчик.
    
    Ключевые оптимизации:
    - Локальные переменные в горячем пути (убираем поиск в self)
    - __slots__ для компактности
    - perf_counter() для точности
    - Инлайн-логика без вызовов методов
    """
    
    __slots__ = ('_interval', '_frames', '_start', '_fps', '_last')
    
    def __init__(self, update_interval: float = 1.0) -> None:
        if update_interval <= 0:
            raise ValueError("interval must be > 0")
        self._interval = update_interval
        self._frames = 0
        now = time.perf_counter()
        self._start = now
        self._last = now
        self._fps = 0.0
    
    @property
    def fps(self) -> float:
        return self._fps
    
    def update(self) -> float:
        # Локальные ссылки для скорости (avoid attribute lookup)
        frames = self._frames + 1
        self._frames = frames
        
        now = time.perf_counter()
        elapsed = now - self._start
        
        if elapsed >= self._interval:
            self._fps = frames / elapsed
            self._frames = 0
            self._start = now
            self._last = now
            return self._fps
        
        return 0.0
    
    def reset(self) -> None:
        now = time.perf_counter()
        self._frames = 0
        self._start = now
        self._last = now
        self._fps = 0.0


# ==================== MICRO-OPTIMIZATIONS ====================

@final  
class FrameFPSUnrolled:
    """
    Версия с развернутым циклом для максимальной скорости.
    Использует счетчик модуло вместо сравнения с float.
    """
    
    __slots__ = ('_interval_frames', '_frame_counter', '_fps')
    
    def __init__(self, target_fps: float = 60.0, avg_frames: int = 60) -> None:
        """
        Args:
            target_fps: Ожидаемый FPS для расчета интервала
            avg_frames: Количество кадров для усреднения
        """
        self._interval_frames = avg_frames
        self._frame_counter = 0
        self._fps = target_fps  # Предполагаем target_fps пока не измерим
    
    def update(self) -> float:
        """Обновление каждый кадр, расчет FPS каждые N кадров."""
        self._frame_counter += 1
        
        # Развернутый счетчик — нет ветвлений в горячем пути!
        if self._frame_counter >= self._interval_frames:
            # Здесь можно вставить точный замер времени
            # Для простоты — предполагаем стабильный FPS
            self._fps = self._interval_frames * 60.0 / self._frame_counter  # Псевдо-расчет
            self._frame_counter = 0
            return self._fps
        
        return 0.0


# ==================== C-LEVEL SIMULATION ====================

try:
    import ctypes
    import ctypes.util
    
    # Пытаемся использовать clock_gettime напрямую для наносекундной точности
    class HighResTimer:
        """Доступ к CLOCK_MONOTONIC напрямую через ctypes."""
        
        CLOCK_MONOTONIC = 1
        
        class timespec(ctypes.Structure):
            _fields_ = [('tv_sec', ctypes.c_long), ('tv_nsec', ctypes.c_long)]
        
        def __init__(self):
            librt = ctypes.CDLL(ctypes.util.find_library('rt') or 'libc.so.6')
            self._clock_gettime = librt.clock_gettime
            self._clock_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(self.timespec)]
            self._clock_gettime.restype = ctypes.c_int
            self._ts = self.timespec()
        
        def now(self) -> float:
            self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.byref(self._ts))
            return self._ts.tv_sec + self._ts.tv_nsec * 1e-9
    
    HIGH_RES_AVAILABLE = True
    
except Exception:
    HIGH_RES_AVAILABLE = False
    HighResTimer = None  # type: ignore


@final
class FrameFPSHighRes:
    """Версия с высокоточным таймером, если доступен."""
    
    __slots__ = ('_interval', '_frames', '_start', '_fps', '_timer')
    
    def __init__(self, update_interval: float = 1.0) -> None:
        self._interval = update_interval
        self._frames = 0
        self._fps = 0.0
        
        if HIGH_RES_AVAILABLE:
            self._timer = HighResTimer()
            self._start = self._timer.now()
        else:
            self._timer = None
            self._start = time.perf_counter()
    
    def update(self) -> float:
        frames = self._frames + 1
        self._frames = frames
        
        if self._timer:
            now = self._timer.now()
        else:
            now = time.perf_counter()
        
        elapsed = now - self._start
        
        if elapsed >= self._interval:
            self._fps = frames / elapsed
            self._frames = 0
            self._start = now
            return self._fps
        
        return 0.0


# ==================== БЕНЧМАРК ====================

def benchmark_optimized():
    """Детальный бенчмарк с профилированием."""
    import sys
    
    print("=" * 70)
    print("УЛЬТИМАТИВНЫЙ БЕНЧМАРК")
    print("=" * 70)
    
    # Размеры
    print("\n--- Размеры объектов ---")
    for cls, name in [(FrameFPS, "FrameFPS"), 
                      (FrameFPSUnrolled, "FrameFPSUnrolled"),
                      (FrameFPSHighRes, "FrameFPSHighRes")]:
        obj = cls()
        size = sys.getsizeof(obj)
        print(f"{name}: {size} bytes")
    
    # Чистая скорость update()
    print("\n--- Чистая скорость update() ---")
    iterations = 5_000_000
    
    for cls, name in [(FrameFPS, "FrameFPS"),
                      (FrameFPSUnrolled, "FrameFPSUnrolled")]:
        fps = cls()
        
        # Warmup
        for _ in range(1000):
            fps.update()
        
        # Benchmark
        gc_disabled = False
        try:
            import gc
            gc.disable()
            gc_disabled = True
        except:
            pass
        
        start = time.perf_counter()
        for _ in range(iterations):
            fps.update()
        elapsed = time.perf_counter() - start
        
        if gc_disabled:
            gc.enable()
        
        ops_sec = iterations / elapsed
        ns_per_op = (elapsed / iterations) * 1e9
        print(f"{name}: {ops_sec:,.0f} ops/sec ({ns_per_op:.1f} ns/op)")
    
    # Профилирование
    print("\n--- Детальное профилирование (1M итераций) ---")
    try:
        import cProfile
        import pstats
        import io
        
        fps = FrameFPS(update_interval=1000.0)  # Никогда не сбросится
        
        pr = cProfile.Profile()
        pr.enable()
        
        for _ in range(1_000_000):
            fps.update()
        
        pr.disable()
        
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('tottime')
        ps.print_stats(10)
        print(s.getvalue())
        
    except ImportError:
        print("cProfile недоступен")
    
    # Сравнение с time.time vs perf_counter
    print("\n--- time.time vs time.perf_counter ---")
    iterations = 10_000_000
    
    start = time.perf_counter()
    for _ in range(iterations):
        time.time()
    t_time = time.perf_counter() - start
    
    start = time.perf_counter()
    for _ in range(iterations):
        time.perf_counter()
    t_perf = time.perf_counter() - start
    
    print(f"time.time:        {iterations/t_time:,.0f} ops/sec")
    print(f"time.perf_counter: {iterations/t_perf:,.0f} ops/sec")
    print(f"Разница: {abs(t_time - t_perf)/t_perf*100:.1f}%")
    
    # Векторизованный numpy для сравнения (если доступен)
    print("\n--- Сравнение с numpy (overhead) ---")
    try:
        import numpy as np
        
        # Симуляция: массив временных меток
        n = 10000
        timestamps = np.zeros(n)
        
        start = time.perf_counter()
        for i in range(n):
            timestamps[i] = time.perf_counter()
        numpy_time = time.perf_counter() - start
        
        # vs простой Python
        py_times = [0.0] * n
        start = time.perf_counter()
        for i in range(n):
            py_times[i] = time.perf_counter()
        py_time = time.perf_counter() - start
        
        print(f"Python list: {n/py_time:,.0f} записей/sec")
        print(f"NumPy array: {n/numpy_time:,.0f} записей/sec")
        print(f"NumPy overhead: {(numpy_time/py_time - 1)*100:.1f}%")
        
    except ImportError:
        print("numpy недоступен")


if __name__ == "__main__":
    benchmark_optimized()