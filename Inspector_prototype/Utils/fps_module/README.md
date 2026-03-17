# fps_module — счётчик кадров

Лаконичный, производительный модуль для измерения FPS. Не thread-safe — использовать из одного потока.

## API

```python
from Utils.fps_module import FrameFPS, RingBufferFPS, AverageFPS
```

| Класс | Назначение |
|-------|------------|
| **FrameFPS** | Максимальная скорость. Обновление каждые interval сек. |
| **RingBufferFPS** | Плавный FPS, скользящее окно по времени. |
| **AverageFPS** | FPS + среднее за последние N измерений. |

## Примеры

```python
# Базовый (камера, рендер)
fps = FrameFPS(interval=1.0)
while running:
    render_frame()
    fps.update()
    print(fps.fps)

# Плавный UI
fps = RingBufferFPS(window_seconds=1.0)
fps.update()
label.setText(f"{fps.fps:.1f}")

# Среднее за 10 измерений (≈10 сек при interval=1)
fps = AverageFPS(interval=1.0, average_samples=10)
fps.update()
print(f"Средний: {fps.average_fps:.1f}")
```

