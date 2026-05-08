# Software Stack — Софт на каждом уровне

## Уровень 1: Jetson Orin NX 16GB

### ОС и базовый слой
| Компонент | Версия / вариант | Примечание |
|-----------|-----------------|-----------|
| JetPack | 6.x (L4T 36.x) | NVIDIA официальный SDK |
| Ubuntu | 22.04 (aarch64) | Встроена в JetPack |
| CUDA | 12.x | Включён в JetPack |
| cuDNN | 8.x | Ускорение нейросетей |
| TensorRT | 8.x / 10.x | Оптимизация inference |
| ROS2 | Humble / Jazzy | Коммуникация |

### AI / ML
| Задача | Софт | Модель | RAM |
|--------|------|--------|-----|
| LLM | llama.cpp / TensorRT-LLM | LLaMA-3 13B / Qwen-2 14B (Q4_K_M) | 8-10 GB |
| STT | faster-whisper (CTranslate2) | whisper-large-v3 | 1-1.5 GB |
| TTS | Piper / Coqui TTS | ru_RU модель | 0.3-0.5 GB |
| Сенсорный фьюжн | Custom (Python/C++) | — | 0.5-1 GB |
| Планировщик | BehaviorTree.CPP / SMACH | — | 0.2 GB |

### Ключевые библиотеки
- `torch` (PyTorch 2.x, CUDA)
- `transformers` / `llama-cpp-python`
- `numpy`, `opencv`
- `rclpy` (ROS2 Python API)

---

## Уровень 2: Jetson Orin Nano 8GB (STEMBLOCK)

### ОС и базовый слой
| Компонент | Версия / вариант | Примечание |
|-----------|-----------------|-----------|
| JetPack | 6.x (L4T 36.x) | Та же версия что Orin NX — единая экосистема |
| Ubuntu | 22.04 (aarch64) | Встроена в JetPack |
| CUDA | 12.x | Полная совместимость с Orin NX |
| cuDNN | 8.x | Ускорение нейросетей |
| TensorRT | 8.x / 10.x | Оптимизация inference |
| ROS2 | Humble / Jazzy | Из apt — без source build! |

### Навигация и SLAM
| Задача | Софт | Примечание |
|--------|------|-----------|
| 2D SLAM | slam_toolbox / Cartographer | Из RPLIDAR LaserScan |
| 3D SLAM | RTAB-Map | Из RealSense D435i |
| Навигация | Nav2 (Navigation2) | Полный стек планирования |
| Локальный планировщик | DWB / TEB | Обход препятствий |
| Obstacle avoidance | costmap_2d + depth | Из point cloud D435i |

### Драйверы сенсоров
| Сенсор | ROS2 пакет | Интерфейс |
|--------|-----------|-----------|
| RPLIDAR A2 | `rplidar_ros` | USB → UART |
| RealSense D435i | `realsense2_camera` | USB 3.0 |
| IMU (D435i) | встроен в realsense | — |

### Ключевые библиотеки
- `librealsense2`
- `pcl` (Point Cloud Library)
- `tf2` (coordinate transforms)
- `nav2_*` пакеты

---

## Уровень 3: RPi 5 + AI HAT+

### ОС и базовый слой
| Компонент | Версия / вариант | Примечание |
|-----------|-----------------|-----------|
| Raspberry Pi OS | Bookworm (64-bit) | Debian 12 base |
| Hailo Runtime | hailort 4.x | Для AI HAT+ |
| Hailo TAPPAS | — | Pipeline примеры |
| ROS2 | Humble (apt или source) | — |

### Компьютерное зрение
| Задача | Софт | Модель | NPU/CPU |
|--------|------|--------|---------|
| Детекция объектов | Hailo Model Zoo | YOLOv8n / YOLOv9t (.hef) | NPU 26 TOPS |
| Детекция лиц | Hailo Model Zoo | SCRFD / RetinaFace (.hef) | NPU |
| Распознавание лиц | ArcFace | arcface_mobilefacenet (.hef) | NPU |
| Жесты | MediaPipe / custom | hand_landmark (.hef) | NPU |
| Tracking | ByteTrack / DeepSORT | — | CPU |

### Ключевые библиотеки
- `hailo-rpi5-examples`
- `picamera2` (libcamera)
- `opencv-python`
- `rclpy`

---

## Уровень 4: Arduino Mega 2560

### Среда разработки
| Компонент | Примечание |
|-----------|-----------|
| PlatformIO или Arduino IDE | Компиляция и загрузка |
| micro-ROS (предпочт.) | ROS2-совместимый агент на MCU |
| Или rosserial | Классический, проще настроить |

### Библиотеки
| Библиотека | Назначение |
|-----------|-----------|
| `micro_ros_arduino` | ROS2 коммуникация |
| `Servo.h` | Управление сервомоторами |
| `Encoder.h` | Чтение энкодеров через прерывания |
| `PID_v1` | PID-регулятор для моторов |
| `Watchdog` | Аппаратный watchdog для safety |

### Прошивка
- Приём `cmd_vel` (Twist) → пересчёт в ШИМ для 4 моторов (дифференциальный привод)
- Публикация `encoders` → для одометрии на Nano
- Hardware E-stop: прерывание → отключение всех моторов < 1 мс

---

## Сводная таблица софта

| Слой | Orin NX (YAHBOOM) | Orin Nano (STEMBLOCK) | RPi 5 + AI HAT+ | MCU (TBD) |
|------|-------------------|----------------------|-----------------|-----------|
| ОС | Ubuntu 22.04 | Ubuntu 22.04 | RPi OS Bookworm | Bare metal |
| JetPack | 6.x | 6.x | — | — |
| CUDA | 12.x | 12.x | — | — |
| ROS2 | Humble | Humble | Humble | micro-ROS |
| AI framework | TensorRT, llama.cpp | TensorRT | Hailo RT | — |
| Язык | Python + C++ | Python + C++ | Python + C++ | C/C++ |
| Основная задача | LLM, голос, фьюжн | SLAM, навигация | Зрение, ROS broker | Моторы, safety |
